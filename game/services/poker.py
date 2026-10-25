"""Transactional no-limit Texas Hold'em cash-table engine."""

from __future__ import annotations

import random
import uuid
from dataclasses import dataclass
from itertools import combinations

from asgiref.sync import sync_to_async
from django.db import transaction
from django.utils import timezone

from game.models import ChipTransaction, Dealer, Player, PokerHand, PokerSeat, PokerTable
from game.services.economy import InsufficientChips, adjust_balance
from game.services.operations import ensure_betting_open
from game.services.table_games import ensure_poker_can_open


RANKS = "23456789TJQKA"
SUITS = "♠♥♦♣"
PHASES = (PokerHand.Phase.PREFLOP, PokerHand.Phase.FLOP, PokerHand.Phase.TURN, PokerHand.Phase.RIVER)


class PokerError(ValueError):
    pass


class TableExists(PokerError):
    pass


class TableFull(PokerError):
    pass


class InvalidAction(PokerError):
    pass


class NotYourTurn(PokerError):
    pass


@dataclass(frozen=True)
class ActionResult:
    table_id: int
    hand_id: int
    hand_complete: bool
    next_player_id: int | None
    summary: str = ""


def new_deck() -> list[str]:
    deck = [rank + suit for rank in RANKS for suit in SUITS]
    random.SystemRandom().shuffle(deck)
    return deck


def _five_card_rank(cards: tuple[str, ...]):
    values = sorted((RANKS.index(card[0]) + 2 for card in cards), reverse=True)
    counts = {value: values.count(value) for value in set(values)}
    groups = sorted(((count, value) for value, count in counts.items()), reverse=True)
    flush = len({card[1] for card in cards}) == 1
    distinct = sorted(set(values), reverse=True)
    if distinct == [14, 5, 4, 3, 2]:
        straight_high = 5
    else:
        straight_high = distinct[0] if len(distinct) == 5 and distinct[0] - distinct[-1] == 4 else 0
    if flush and straight_high:
        return (8, straight_high)
    if groups[0][0] == 4:
        return (7, groups[0][1], groups[1][1])
    if groups[0][0] == 3 and groups[1][0] == 2:
        return (6, groups[0][1], groups[1][1])
    if flush:
        return (5, *values)
    if straight_high:
        return (4, straight_high)
    if groups[0][0] == 3:
        kickers = sorted((value for value in values if value != groups[0][1]), reverse=True)
        return (3, groups[0][1], *kickers)
    pairs = sorted((value for count, value in groups if count == 2), reverse=True)
    if len(pairs) == 2:
        kicker = next(value for value in values if value not in pairs)
        return (2, *pairs, kicker)
    if len(pairs) == 1:
        kickers = sorted((value for value in values if value != pairs[0]), reverse=True)
        return (1, pairs[0], *kickers)
    return (0, *values)


def evaluate_hand(cards: list[str]):
    if len(cards) < 5:
        raise ValueError("At least five cards are required")
    return max(_five_card_rank(combo) for combo in combinations(cards, 5))


HAND_NAMES = {
    8: "straight flush", 7: "four of a kind", 6: "full house", 5: "flush",
    4: "straight", 3: "three of a kind", 2: "two pair", 1: "pair", 0: "high card",
}


def _ordered(seats, after: int):
    seats = sorted(seats, key=lambda seat: seat.seat_number)
    return [seat for seat in seats if seat.seat_number > after] + [seat for seat in seats if seat.seat_number <= after]


def seat_name(seat: PokerSeat) -> str:
    return seat.bot_name if seat.is_bot else seat.player.name


def _next_actionable(seats, after: int):
    return next((seat for seat in _ordered(seats, after) if not seat.folded and not seat.all_in and seat.stack > 0), None)


def _post(seat: PokerSeat, amount: int) -> int:
    paid = min(seat.stack, amount)
    seat.stack -= paid
    seat.committed_round += paid
    seat.committed_hand += paid
    seat.all_in = seat.stack == 0
    seat.save(update_fields=("stack", "committed_round", "committed_hand", "all_in"))
    return paid


@transaction.atomic
def create_table(chat_id: int, host_id: int, buy_in: int, small_blind: int, max_players: int = 8):
    ensure_betting_open()
    ensure_poker_can_open(chat_id)
    if buy_in < 20 or small_blind < 1 or buy_in < small_blind * 10:
        raise PokerError("Buy-in must be at least 20 chips and 10 small blinds.")
    if not 2 <= max_players <= 8:
        raise PokerError("Poker tables support 2 to 8 players.")
    if PokerTable.objects.select_for_update().filter(chat_id=chat_id).exclude(status=PokerTable.Status.CLOSED).exists():
        raise TableExists("This group already has an open poker table.")
    player = Player.objects.select_for_update().get(pk=host_id)
    table = PokerTable.objects.create(
        chat_id=chat_id, host=player, buy_in=buy_in, small_blind=small_blind, max_players=max_players
    )
    seat = PokerSeat.objects.create(table=table, player=player, seat_number=1, stack=0)
    change = adjust_balance(
        player, -buy_in, category=ChipTransaction.Category.POKER_BUY_IN,
        description=f"Poker table #{table.pk} buy-in", reference_type="poker_table",
        reference_id=table.pk, idempotency_key=f"poker:{table.pk}:seat:{seat.pk}:buyin",
    )
    seat.stack = buy_in
    seat.save(update_fields=("stack",))
    return table, change.balance


@transaction.atomic
def join_table(table_id: int, player_id: int):
    ensure_betting_open()
    table = PokerTable.objects.select_for_update().get(pk=table_id)
    if table.status == PokerTable.Status.CLOSED:
        raise PokerError("This table is closed.")
    if table.seats.filter(player_id=player_id).exists():
        raise PokerError("You are already seated.")
    if table.seats.count() >= table.max_players:
        raise TableFull("The table is full.")
    player = Player.objects.select_for_update().get(pk=player_id)
    used = set(table.seats.values_list("seat_number", flat=True))
    seat_number = next(number for number in range(1, table.max_players + 1) if number not in used)
    # Mid-hand arrivals sit out (folded, already acted) until the next deal.
    waiting = table.status == PokerTable.Status.PLAYING
    seat = PokerSeat.objects.create(
        table=table, player=player, seat_number=seat_number, stack=0,
        folded=waiting, acted=waiting,
    )
    change = adjust_balance(
        player, -table.buy_in, category=ChipTransaction.Category.POKER_BUY_IN,
        description=f"Poker table #{table.pk} buy-in", reference_type="poker_table",
        reference_id=table.pk, idempotency_key=f"poker:{table.pk}:seat:{seat.pk}:buyin",
    )
    seat.stack = table.buy_in
    seat.save(update_fields=("stack",))
    return seat, change.balance


@transaction.atomic
def leave_table(table_id: int, player_id: int) -> int | None:
    """Cash out now, or after the running hand. Returns the amount, or None when deferred."""
    table = PokerTable.objects.select_for_update().get(pk=table_id)
    if table.status != PokerTable.Status.PLAYING:
        return cash_out(table_id, player_id)
    seat = PokerSeat.objects.select_for_update().get(table=table, player_id=player_id)
    seat.leave_after_hand = True
    seat.save(update_fields=("leave_after_hand",))
    return None


BOT_NAMES = (
    "Maverick", "River", "Ace", "Nova", "Bluffy", "Chip", "Raven", "Atlas",
    "Luna", "Joker", "Sage", "Phoenix", "Onyx", "Vega", "Bandit", "Clover",
    "Diesel", "Ivy", "Knuckles", "Lucky", "Marble", "Orion", "Pixel", "Queen",
)
BOT_STYLES = ("cautious", "balanced", "aggressive", "wild")


@transaction.atomic
def add_bot(table_id: int, actor_id: int) -> PokerSeat:
    table = PokerTable.objects.select_for_update().get(pk=table_id)
    if table.host_id != actor_id:
        raise PokerError("Only the table host can add bots.")
    if table.status not in {PokerTable.Status.LOBBY, PokerTable.Status.BETWEEN_HANDS}:
        raise PokerError("Bots can only be added between hands.")
    if table.seats.count() >= table.max_players:
        raise TableFull("The table is full.")
    dealer = Dealer.objects.select_for_update().first()
    if dealer is None or dealer.chips < table.buy_in:
        raise PokerError("The casino bankroll cannot fund another poker bot.")
    used = set(table.seats.values_list("seat_number", flat=True))
    seat_number = next(number for number in range(1, table.max_players + 1) if number not in used)
    existing_names = set(table.seats.filter(is_bot=True).values_list("bot_name", flat=True))
    available = [name for name in BOT_NAMES if f"🤖 {name}" not in existing_names]
    rng = random.SystemRandom()
    base = rng.choice(available) if available else f"Bot {seat_number}-{rng.randrange(100, 999)}"
    style = rng.choice(BOT_STYLES)
    dealer.chips -= table.buy_in
    dealer.save(update_fields=("chips",))
    return PokerSeat.objects.create(
        table=table, seat_number=seat_number, stack=table.buy_in,
        is_bot=True, bot_name=f"🤖 {base}", bot_style=style,
    )


@transaction.atomic
def remove_bot(table_id: int, actor_id: int) -> int:
    table = PokerTable.objects.select_for_update().get(pk=table_id)
    if table.host_id != actor_id:
        raise PokerError("Only the table host can remove bots.")
    if table.status not in {PokerTable.Status.LOBBY, PokerTable.Status.BETWEEN_HANDS}:
        raise PokerError("Bots can only be removed between hands.")
    seat = table.seats.select_for_update().filter(is_bot=True).order_by("-seat_number").first()
    if seat is None:
        raise PokerError("There are no bots at this table.")
    dealer = Dealer.objects.select_for_update().first()
    if dealer:
        dealer.chips += seat.stack
        dealer.save(update_fields=("chips",))
    amount = seat.stack
    seat.delete()
    return amount


@transaction.atomic
def close_table(table_id: int, actor_id: int) -> int:
    """Host-close an idle cash table and return every remaining stack."""
    table = PokerTable.objects.select_for_update().get(pk=table_id)
    if table.host_id != actor_id:
        raise PokerError("Only the table host can close the table.")
    if table.status == PokerTable.Status.PLAYING:
        raise PokerError("Finish the current hand before closing the table.")
    seats = list(table.seats.select_for_update())
    dealer_amount = 0
    human_refunds = 0
    for seat in seats:
        if seat.is_bot:
            dealer_amount += seat.stack
        elif seat.stack:
            adjust_balance(
                seat.player_id, seat.stack,
                category=ChipTransaction.Category.POKER_CASH_OUT,
                description=f"Poker table #{table.pk} closed by host",
                reference_type="poker_table", reference_id=table.pk,
                idempotency_key=f"poker:{table.pk}:seat:{seat.pk}:host-close",
            )
            human_refunds += 1
    if dealer_amount:
        dealer = Dealer.objects.select_for_update().first()
        if dealer:
            dealer.chips += dealer_amount
            dealer.save(update_fields=("chips",))
    table.seats.all().delete()
    table.status = PokerTable.Status.CLOSED
    table.save(update_fields=("status", "updated_at"))
    return human_refunds


@transaction.atomic
def cash_out(table_id: int, player_id: int) -> int:
    table = PokerTable.objects.select_for_update().get(pk=table_id)
    if table.status == PokerTable.Status.PLAYING:
        raise PokerError("You cannot cash out during a hand.")
    seat = PokerSeat.objects.select_for_update().get(table=table, player_id=player_id)
    amount = seat.stack
    if amount:
        adjust_balance(
            player_id, amount, category=ChipTransaction.Category.POKER_CASH_OUT,
            description=f"Poker table #{table.pk} cash-out", reference_type="poker_table",
            reference_id=table.pk, idempotency_key=f"poker:{table.pk}:seat:{seat.pk}:cashout",
        )
    seat.delete()
    if not table.seats.filter(is_bot=False).exists():
        bots = list(table.seats.select_for_update().filter(is_bot=True))
        dealer = Dealer.objects.select_for_update().first()
        if dealer:
            dealer.chips += sum(bot.stack for bot in bots)
            dealer.save(update_fields=("chips",))
        table.seats.filter(is_bot=True).delete()
        table.status = PokerTable.Status.CLOSED
        table.save(update_fields=("status", "updated_at"))
    elif table.host_id == player_id:
        table.host_id = table.seats.order_by("seat_number").values_list("player_id", flat=True).first()
        table.save(update_fields=("host", "updated_at"))
    return amount


@transaction.atomic
def start_hand(table_id: int, actor_id: int | None = None) -> PokerHand:
    """Deal the next hand. ``actor_id=None`` is the automatic dealer; any seated player may deal."""
    table = PokerTable.objects.select_for_update().get(pk=table_id)
    if actor_id is not None and not table.seats.filter(player_id=actor_id).exists():
        raise PokerError("Only seated players can deal.")
    if table.status == PokerTable.Status.CLOSED:
        raise PokerError("This table is closed.")
    if table.status == PokerTable.Status.PLAYING:
        raise PokerError("A hand is already running.")
    seats = list(PokerSeat.objects.select_for_update().filter(table=table, stack__gt=0).select_related("player"))
    if len(seats) < 2:
        raise PokerError("At least two players with chips are required.")
    for seat in seats:
        seat.hole_cards, seat.committed_round, seat.committed_hand = [], 0, 0
        seat.folded = seat.all_in = seat.acted = False
    dealer = _ordered(seats, table.dealer_seat)[0]
    table.dealer_seat = dealer.seat_number
    table.hand_number += 1
    table.status = PokerTable.Status.PLAYING
    table.save(update_fields=("dealer_seat", "hand_number", "status", "updated_at"))
    deck = new_deck()
    for _ in range(2):
        for seat in _ordered(seats, dealer.seat_number):
            seat.hole_cards.append(deck.pop())
    PokerSeat.objects.bulk_update(seats, ("hole_cards", "committed_round", "committed_hand", "folded", "all_in", "acted"))
    if len(seats) == 2:
        small, big = dealer, _ordered(seats, dealer.seat_number)[0]
    else:
        small = _ordered(seats, dealer.seat_number)[0]
        big = _ordered(seats, small.seat_number)[0]
    _post(small, table.small_blind)
    _post(big, table.small_blind * 2)
    current = _next_actionable(seats, big.seat_number)
    hand = PokerHand.objects.create(
        table=table, number=table.hand_number, deck=deck,
        pot=sum(seat.committed_hand for seat in seats), current_bet=max(seat.committed_round for seat in seats),
        min_raise=table.small_blind * 2, current_seat=current.seat_number if current else None,
        action_token=str(uuid.uuid4()),
    )
    return hand


def _round_complete(seats, current_bet):
    live = [seat for seat in seats if not seat.folded]
    actionable = [seat for seat in live if not seat.all_in and seat.stack > 0]
    return len(live) <= 1 or all(seat.acted and seat.committed_round == current_bet for seat in actionable)


def _award_pots(hand: PokerHand, seats: list[PokerSeat]) -> str:
    live = [seat for seat in seats if not seat.folded]
    payouts = {seat.pk: 0 for seat in seats}
    if len(live) == 1:
        payouts[live[0].pk] = sum(seat.committed_hand for seat in seats)
        winner_lines = [f"{seat_name(live[0])} wins {payouts[live[0].pk]:,} chips (everyone folded)."]
    else:
        ranks = {seat.pk: evaluate_hand(seat.hole_cards + hand.community_cards) for seat in live}
        levels = sorted({seat.committed_hand for seat in seats if seat.committed_hand})
        previous = 0
        winner_lines = []
        for level in levels:
            contributors = [seat for seat in seats if seat.committed_hand >= level]
            pot = (level - previous) * len(contributors)
            eligible = [seat for seat in live if seat.committed_hand >= level]
            best = max(ranks[seat.pk] for seat in eligible)
            winners = [seat for seat in eligible if ranks[seat.pk] == best]
            share, remainder = divmod(pot, len(winners))
            for index, winner in enumerate(_ordered(winners, hand.table.dealer_seat)):
                payouts[winner.pk] += share + (1 if index < remainder else 0)
            winner_lines.append(
                f"{', '.join(seat_name(w) for w in winners)}: {pot:,} chips with {HAND_NAMES[best[0]]}."
            )
            previous = level
    for seat in seats:
        seat.stack += payouts[seat.pk]
    PokerSeat.objects.bulk_update(seats, ("stack",))
    return "\n".join(winner_lines)


def _finish_hand(hand: PokerHand, seats: list[PokerSeat]) -> str:
    while len(hand.community_cards) < 5 and len([seat for seat in seats if not seat.folded]) > 1:
        hand.deck.pop()  # burn
        hand.community_cards.append(hand.deck.pop())
    summary = _award_pots(hand, seats)
    hand.phase = PokerHand.Phase.COMPLETE
    hand.current_seat = None
    hand.summary = summary
    hand.completed_at = timezone.now()
    hand.pot = sum(seat.committed_hand for seat in seats)
    hand.save(update_fields=("deck", "community_cards", "phase", "current_seat", "summary", "completed_at", "pot"))
    table = hand.table
    table.status = PokerTable.Status.BETWEEN_HANDS
    table.save(update_fields=("status", "updated_at"))
    removed_ids = []
    returned_to_casino = 0
    for seat in seats:
        if seat.is_bot and seat.stack == 0:
            removed_ids.append(seat.pk)
        elif not seat.is_bot and (seat.leave_after_hand or seat.stack == 0):
            if seat.stack:
                adjust_balance(
                    seat.player_id, seat.stack,
                    category=ChipTransaction.Category.POKER_CASH_OUT,
                    description=f"Poker table #{table.pk} cash-out after leaving",
                    reference_type="poker_table", reference_id=table.pk,
                    idempotency_key=f"poker:{table.pk}:seat:{seat.pk}:timeout-cashout",
                )
            removed_ids.append(seat.pk)
    if removed_ids:
        PokerSeat.objects.filter(pk__in=removed_ids).delete()
        humans = table.seats.filter(is_bot=False).order_by("seat_number")
        if not humans.exists():
            bots = list(table.seats.filter(is_bot=True))
            returned_to_casino = sum(bot.stack for bot in bots)
            table.seats.filter(is_bot=True).delete()
            table.status = PokerTable.Status.CLOSED
        elif table.host_id not in humans.values_list("player_id", flat=True):
            table.host_id = humans.first().player_id
        table.save(update_fields=("status", "host", "updated_at"))
        if returned_to_casino:
            dealer = Dealer.objects.select_for_update().first()
            if dealer:
                dealer.chips += returned_to_casino
                dealer.save(update_fields=("chips",))
    return summary


@transaction.atomic
def act(
    hand_id: int,
    player_id: int | None,
    action: str,
    amount: int | None = None,
    *,
    bot_seat_id: int | None = None,
) -> ActionResult:
    hand = PokerHand.objects.select_for_update().select_related("table").get(pk=hand_id)
    if hand.phase == PokerHand.Phase.COMPLETE:
        raise InvalidAction("This hand is already complete.")
    seats = list(PokerSeat.objects.select_for_update().filter(table=hand.table).select_related("player"))
    if bot_seat_id is not None:
        seat = next((candidate for candidate in seats if candidate.pk == bot_seat_id and candidate.is_bot), None)
    else:
        seat = next((candidate for candidate in seats if candidate.player_id == player_id and not candidate.is_bot), None)
    if seat is None or seat.seat_number != hand.current_seat:
        raise NotYourTurn("It is not your turn.")
    owed = hand.current_bet - seat.committed_round
    if action == "fold":
        seat.folded = True
    elif action == "check":
        if owed:
            raise InvalidAction("You cannot check while facing a bet.")
    elif action == "call":
        if owed <= 0:
            raise InvalidAction("There is nothing to call.")
        _post(seat, owed)
    elif action in {"raise", "allin"}:
        target = seat.committed_round + seat.stack if action == "allin" else int(amount or 0)
        if target <= hand.current_bet and target < seat.committed_round + seat.stack:
            raise InvalidAction("A raise must exceed the current bet.")
        paid = min(seat.stack, target - seat.committed_round)
        if paid <= 0:
            raise InvalidAction("Invalid raise amount.")
        previous_bet = hand.current_bet
        _post(seat, paid)
        if seat.committed_round > previous_bet:
            raise_size = seat.committed_round - previous_bet
            if not seat.all_in and raise_size < hand.min_raise:
                raise InvalidAction(f"Minimum raise is {hand.min_raise:,} chips.")
            if raise_size >= hand.min_raise:
                hand.min_raise = raise_size
            hand.current_bet = seat.committed_round
            for other in seats:
                if other.pk != seat.pk and not other.folded and not other.all_in:
                    other.acted = False
                    other.save(update_fields=("acted",))
    else:
        raise InvalidAction("Unknown poker action.")
    seat.acted = True
    seat.consecutive_timeouts = 0
    seat.save(update_fields=("folded", "acted", "consecutive_timeouts", "stack", "committed_round", "committed_hand", "all_in"))
    hand.pot = sum(candidate.committed_hand for candidate in seats)
    if _round_complete(seats, hand.current_bet):
        if len([candidate for candidate in seats if not candidate.folded]) <= 1:
            summary = _finish_hand(hand, seats)
            return ActionResult(hand.table_id, hand.pk, True, None, summary)
        phase_index = PHASES.index(hand.phase)
        if phase_index == len(PHASES) - 1:
            summary = _finish_hand(hand, seats)
            return ActionResult(hand.table_id, hand.pk, True, None, summary)
        hand.deck.pop()
        deal_count = 3 if hand.phase == PokerHand.Phase.PREFLOP else 1
        hand.community_cards.extend(hand.deck.pop() for _ in range(deal_count))
        hand.phase = PHASES[phase_index + 1]
        hand.current_bet = 0
        hand.min_raise = hand.table.small_blind * 2
        for candidate in seats:
            candidate.committed_round = 0
            candidate.acted = candidate.folded or candidate.all_in
        PokerSeat.objects.bulk_update(seats, ("committed_round", "acted"))
        next_seat = _next_actionable(seats, hand.table.dealer_seat)
        if len([candidate for candidate in seats if not candidate.folded and not candidate.all_in]) < 2:
            summary = _finish_hand(hand, seats)
            return ActionResult(hand.table_id, hand.pk, True, None, summary)
    else:
        next_seat = _next_actionable(seats, seat.seat_number)
    hand.current_seat = next_seat.seat_number if next_seat else None
    hand.action_token = str(uuid.uuid4())
    hand.save(update_fields=("deck", "community_cards", "phase", "pot", "current_bet", "min_raise", "current_seat", "action_token"))
    return ActionResult(hand.table_id, hand.pk, False, next_seat.player_id if next_seat else None)


def estimate_bot_equity(seat: PokerSeat, hand: PokerHand, seats: list[PokerSeat], samples: int = 120) -> float:
    """Monte Carlo strength using only information legitimately visible to this bot."""
    known = set(seat.hole_cards + hand.community_cards)
    unseen = [card for card in (rank + suit for rank in RANKS for suit in SUITS) if card not in known]
    opponents = max(1, len([other for other in seats if other.pk != seat.pk and not other.folded]))
    board_needed = 5 - len(hand.community_cards)
    rng = random.SystemRandom()
    score = 0.0
    for _ in range(samples):
        drawn = rng.sample(unseen, board_needed + opponents * 2)
        board = hand.community_cards + drawn[:board_needed]
        ours = evaluate_hand(seat.hole_cards + board)
        offset = board_needed
        rival_ranks = []
        for _opponent in range(opponents):
            rival_ranks.append(evaluate_hand(drawn[offset:offset + 2] + board))
            offset += 2
        best_rival = max(rival_ranks)
        score += 1 if ours > best_rival else 0.5 if ours == best_rival else 0
    return score / samples


def describe_visible_hand(hole_cards: list[str], community_cards: list[str]) -> str:
    cards = hole_cards + community_cards
    if len(cards) >= 5:
        return HAND_NAMES[evaluate_hand(cards)[0]]
    counts = sorted((sum(card[0] == rank for card in cards) for rank in RANKS), reverse=True)
    if counts[0] == 4:
        return "four of a kind"
    if counts[0] == 3 and len(counts) > 1 and counts[1] >= 2:
        return "full house"
    if counts[0] == 3:
        return "three of a kind"
    pairs = sum(count >= 2 for count in counts)
    if pairs >= 2:
        return "two pair"
    if pairs == 1:
        return "one pair"
    return "high card"


@transaction.atomic
def normalize_bot_names(table_id: int) -> None:
    seats = list(PokerSeat.objects.select_for_update().filter(table_id=table_id, is_bot=True).order_by("seat_number"))
    used = set()
    rng = random.SystemRandom()
    for seat in seats:
        if seat.bot_name and seat.bot_name not in used:
            used.add(seat.bot_name)
            continue
        available = [name for name in BOT_NAMES if f"🤖 {name}" not in used]
        base = rng.choice(available) if available else f"Bot {seat.seat_number}-{rng.randrange(100, 999)}"
        seat.bot_name = f"🤖 {base}"
        seat.save(update_fields=("bot_name",))
        used.add(seat.bot_name)


def choose_bot_action(hand: PokerHand, seat: PokerSeat, seats: list[PokerSeat]):
    equity = estimate_bot_equity(seat, hand, seats)
    owed = max(0, hand.current_bet - seat.committed_round)
    pot_odds = owed / (hand.pot + owed) if owed else 0
    rng = random.SystemRandom()
    style = seat.bot_style or "balanced"
    aggression = {"cautious": 0.74, "balanced": 0.64, "aggressive": 0.55, "wild": 0.48}[style]
    bluff = {"cautious": 0.02, "balanced": 0.06, "aggressive": 0.12, "wild": 0.20}[style]
    # Small noise deliberately keeps the opponents human-like and fallible.
    perceived = max(0.0, min(1.0, equity + rng.uniform(-0.08, 0.08)))
    total_available = seat.committed_round + seat.stack
    if owed and perceived + 0.04 < pot_odds:
        return "fold", None
    if total_available > hand.current_bet and (perceived >= aggression or rng.random() < bluff):
        target = hand.current_bet + hand.min_raise
        if perceived > 0.86 and seat.stack <= max(hand.pot * 2, owed * 3):
            return "allin", None
        target += int(min(seat.stack, max(hand.min_raise, hand.pot // 3)) * rng.uniform(0, 0.7))
        return "raise", min(total_available, max(target, hand.current_bet + hand.min_raise))
    return ("call", None) if owed else ("check", None)


@transaction.atomic
def act_bot(hand_id: int, seat_id: int) -> tuple[ActionResult, str]:
    hand = PokerHand.objects.select_for_update().select_related("table").get(pk=hand_id)
    seats = list(PokerSeat.objects.select_for_update().filter(table=hand.table).select_related("player"))
    seat = next((candidate for candidate in seats if candidate.pk == seat_id and candidate.is_bot), None)
    if seat is None or seat.seat_number != hand.current_seat:
        raise NotYourTurn("The bot turn has already moved on.")
    action, amount = choose_bot_action(hand, seat, seats)
    try:
        result = act(hand_id, None, action, amount, bot_seat_id=seat.pk)
    except InvalidAction:
        # A short all-in can change the legal minimum; calling/checking is always safe.
        action, amount = (("call", None) if hand.current_bet > seat.committed_round else ("check", None))
        result = act(hand_id, None, action, amount, bot_seat_id=seat.pk)
    label = action if amount is None else f"{action} to {amount:,}"
    return result, label


@transaction.atomic
def timeout_action(hand_id: int, player_id: int, token: str) -> ActionResult | None:
    hand = PokerHand.objects.select_for_update().get(pk=hand_id)
    if hand.phase == PokerHand.Phase.COMPLETE or hand.action_token != token:
        return None
    seat = PokerSeat.objects.select_for_update().get(table=hand.table, player_id=player_id)
    if seat.seat_number != hand.current_seat:
        return None
    timeout_count = seat.consecutive_timeouts + 1
    seat.consecutive_timeouts = timeout_count
    seat.leave_after_hand = timeout_count >= 2
    seat.save(update_fields=("consecutive_timeouts", "leave_after_hand"))
    action = "fold" if timeout_count >= 2 else ("check" if seat.committed_round == hand.current_bet else "fold")
    result = act(hand_id, player_id, action)
    # act resets it; preserve the timeout count and sit a repeat offender out after the hand.
    if PokerSeat.objects.filter(pk=seat.pk).exists():
        seat.refresh_from_db()
        seat.consecutive_timeouts = timeout_count
        seat.save(update_fields=("consecutive_timeouts", "leave_after_hand"))
    return result


create_table_async = lambda *a, **kw: sync_to_async(create_table, thread_sensitive=True)(*a, **kw)
join_table_async = lambda *a, **kw: sync_to_async(join_table, thread_sensitive=True)(*a, **kw)
add_bot_async = lambda *a, **kw: sync_to_async(add_bot, thread_sensitive=True)(*a, **kw)
remove_bot_async = lambda *a, **kw: sync_to_async(remove_bot, thread_sensitive=True)(*a, **kw)
close_table_async = lambda *a, **kw: sync_to_async(close_table, thread_sensitive=True)(*a, **kw)
cash_out_async = lambda *a, **kw: sync_to_async(cash_out, thread_sensitive=True)(*a, **kw)
leave_table_async = lambda *a, **kw: sync_to_async(leave_table, thread_sensitive=True)(*a, **kw)
start_hand_async = lambda *a, **kw: sync_to_async(start_hand, thread_sensitive=True)(*a, **kw)
act_async = lambda *a, **kw: sync_to_async(act, thread_sensitive=True)(*a, **kw)
act_bot_async = lambda *a, **kw: sync_to_async(act_bot, thread_sensitive=True)(*a, **kw)
timeout_action_async = lambda *a, **kw: sync_to_async(timeout_action, thread_sensitive=True)(*a, **kw)
normalize_bot_names_async = lambda *a, **kw: sync_to_async(normalize_bot_names, thread_sensitive=True)(*a, **kw)
