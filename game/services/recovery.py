"""Deterministic recovery for game state that cannot survive a process restart."""

from dataclasses import asdict, dataclass

from asgiref.sync import sync_to_async
from django.db import transaction
from django.utils import timezone

from game.models import (
    ChipTransaction,
    CrashGame,
    Dealer,
    Game,
    Group,
    HorseBet,
    HorseRace,
    JoinGame,
    OperationalEvent,
    Player,
    PokerHand,
    PokerSeat,
    PokerTable,
    RouletteTable,
)
from game.services.economy import adjust_balance


@dataclass
class RecoveryReport:
    crash_games: int = 0
    races: int = 0
    blackjack_games: int = 0
    player_refunds: int = 0


@transaction.atomic
def cancel_crash_game(game_id: int, *, reason: str = "Cancelled by operator") -> int:
    crash = CrashGame.objects.select_for_update().filter(
        pk=game_id, crashed=False, cashed_out=False
    ).first()
    if crash is None:
        return 0
    adjust_balance(
        crash.user_id,
        crash.bet,
        category=ChipTransaction.Category.REFUND,
        description=reason,
        reference_type="crash_game",
        reference_id=crash.pk,
        idempotency_key=f"cancel:crash:{crash.pk}:refund",
    )
    crash.delete()
    OperationalEvent.objects.create(
        severity=OperationalEvent.Severity.WARNING,
        category="operator_cancel",
        message=reason,
        player_id=str(crash.user_id),
        game_id=str(game_id),
        context={"game_type": "crash", "refunds": 1},
    )
    return 1


@transaction.atomic
def cancel_race(race_id: int, *, reason: str = "Cancelled by operator") -> int:
    race = HorseRace.objects.select_for_update().filter(pk=race_id).first()
    if race is None:
        return 0
    bets = list(HorseBet.objects.select_for_update().filter(race=race))
    for bet in bets:
        adjust_balance(
            bet.user_id,
            bet.bet_amount,
            category=ChipTransaction.Category.REFUND,
            description=reason,
            reference_type="horse_race",
            reference_id=race.pk,
            idempotency_key=f"cancel:race:{race.pk}:bet:{bet.pk}:refund",
        )
    chat_id = race.chat_id
    race.delete()
    OperationalEvent.objects.create(
        severity=OperationalEvent.Severity.WARNING,
        category="operator_cancel",
        message=reason,
        chat_id=str(chat_id),
        game_id=str(race_id),
        context={"game_type": "horse_race", "refunds": len(bets)},
    )
    return len(bets)


@transaction.atomic
def cancel_blackjack_game(
    game_id: int, *, reason: str = "Cancelled by operator"
) -> int:
    game = Game.objects.select_for_update().filter(pk=game_id, ended=False).first()
    if game is None:
        return 0
    group = Group.objects.filter(group_chat_id=game.chat_id).first()
    real_money = bool(group and group.vip and group.real_money)
    joined_players = list(
        JoinGame.objects.select_for_update().filter(game=game, is_active=True)
    )
    for joined in joined_players:
        if real_money:
            player = Player.objects.select_for_update().get(pk=joined.player_id)
            player.real_tokens += game.bet_amount
            player.save(update_fields=("real_tokens",))
        else:
            adjust_balance(
                joined.player_id,
                game.bet_amount,
                category=ChipTransaction.Category.REFUND,
                description=reason,
                reference_type="blackjack_game",
                reference_id=game.pk,
                idempotency_key=f"cancel:blackjack:{game.pk}:join:{joined.pk}:refund",
            )

    if game.started:
        dealer = Dealer.objects.select_for_update().first()
        if dealer is not None:
            if real_money:
                dealer.real_tokens += game.bet_amount
                dealer.save(update_fields=("real_tokens",))
            else:
                dealer.chips += game.bet_amount
                dealer.save(update_fields=("chips",))

    chat_id = game.chat_id
    game.delete()
    OperationalEvent.objects.create(
        severity=OperationalEvent.Severity.WARNING,
        category="operator_cancel",
        message=reason,
        chat_id=str(chat_id),
        game_id=str(game_id),
        context={"game_type": "blackjack", "refunds": len(joined_players)},
    )
    return len(joined_players)


@transaction.atomic
def cancel_poker_table(table_id: int, *, reason: str = "Cancelled by operator") -> int:
    table = PokerTable.objects.select_for_update().filter(pk=table_id).exclude(
        status=PokerTable.Status.CLOSED
    ).first()
    if table is None:
        return 0
    seats = list(PokerSeat.objects.select_for_update().filter(table=table))
    refunded = 0
    dealer_refund = 0
    for seat in seats:
        amount = seat.stack + seat.committed_hand
        if seat.is_bot:
            dealer_refund += amount
            continue
        if amount:
            adjust_balance(
                seat.player_id, amount,
                category=ChipTransaction.Category.REFUND,
                description=reason,
                reference_type="poker_table",
                reference_id=table.pk,
                idempotency_key=f"cancel:poker:{table.pk}:seat:{seat.pk}:refund",
            )
            refunded += 1
    if dealer_refund:
        dealer = Dealer.objects.select_for_update().first()
        if dealer:
            dealer.chips += dealer_refund
            dealer.save(update_fields=("chips",))
    PokerHand.objects.filter(table=table).exclude(phase=PokerHand.Phase.COMPLETE).update(
        phase=PokerHand.Phase.COMPLETE,
        current_seat=None,
        completed_at=timezone.now(),
        summary=reason,
    )
    table.status = PokerTable.Status.CLOSED
    table.save(update_fields=("status", "updated_at"))
    table.seats.all().delete()
    OperationalEvent.objects.create(
        severity=OperationalEvent.Severity.WARNING,
        category="operator_cancel",
        message=reason,
        chat_id=table.chat_id,
        game_id=table.pk,
        context={"game_type": "poker", "refunds": refunded},
    )
    return refunded


@transaction.atomic
def cancel_roulette_table(table_id: int, *, reason: str = "Cancelled by operator") -> int:
    table = RouletteTable.objects.select_for_update().filter(
        pk=table_id, status__in=(RouletteTable.Status.BETTING, RouletteTable.Status.SPINNING)
    ).first()
    if table is None:
        return 0
    bets = list(table.bets.select_for_update().all())
    dealer = Dealer.objects.select_for_update().first()
    total = 0
    for bet in bets:
        adjust_balance(
            bet.player_id, bet.amount,
            category=ChipTransaction.Category.REFUND,
            description=reason,
            reference_type="roulette_table", reference_id=table.pk,
            idempotency_key=f"cancel:roulette:{table.pk}:bet:{bet.pk}:refund",
        )
        total += bet.amount
    if dealer and total:
        dealer.chips -= total
        dealer.save(update_fields=("chips",))
    table.status = RouletteTable.Status.CANCELLED
    table.completed_at = timezone.now()
    table.save(update_fields=("status", "completed_at"))
    OperationalEvent.objects.create(
        severity=OperationalEvent.Severity.WARNING,
        category="operator_cancel", message=reason,
        chat_id=str(table.chat_id), game_id=str(table.pk),
        context={"game_type": "roulette", "refunds": len(bets)},
    )
    return len(bets)


@transaction.atomic
def recover_interrupted_games() -> RecoveryReport:
    report = RecoveryReport()

    for crash in CrashGame.objects.select_for_update().filter(
        crashed=False,
        cashed_out=False,
    ):
        adjust_balance(
            crash.user_id,
            crash.bet,
            category=ChipTransaction.Category.REFUND,
            description="Crash game refunded after bot restart",
            reference_type="crash_game",
            reference_id=crash.pk,
            idempotency_key=f"recovery:crash:{crash.pk}:refund",
        )
        report.crash_games += 1
        report.player_refunds += 1
        crash.delete()

    for race in HorseRace.objects.select_for_update().filter(
        race_started=True, completed=False
    ):
        bets = list(HorseBet.objects.select_for_update().filter(race=race))
        for bet in bets:
            adjust_balance(
                bet.user_id,
                bet.bet_amount,
                category=ChipTransaction.Category.REFUND,
                description="Horse race refunded after bot restart",
                reference_type="horse_race",
                reference_id=race.pk,
                idempotency_key=f"recovery:race:{race.pk}:bet:{bet.pk}:refund",
            )
            report.player_refunds += 1
        report.races += 1
        race.delete()

    for game in Game.objects.select_for_update().filter(started=True, ended=False):
        group = Group.objects.filter(group_chat_id=game.chat_id).first()
        real_money = bool(group and group.vip and group.real_money)
        joined_players = list(
            JoinGame.objects.select_for_update().filter(game=game, is_active=True)
        )
        for joined in joined_players:
            if real_money:
                player = Player.objects.select_for_update().get(pk=joined.player_id)
                player.real_tokens += game.bet_amount
                player.save(update_fields=("real_tokens",))
            else:
                adjust_balance(
                    joined.player_id,
                    game.bet_amount,
                    category=ChipTransaction.Category.REFUND,
                    description="Blackjack bet refunded after bot restart",
                    reference_type="blackjack_game",
                    reference_id=game.pk,
                    idempotency_key=f"recovery:blackjack:{game.pk}:join:{joined.pk}:refund",
                )
            report.player_refunds += 1

        dealer = Dealer.objects.select_for_update().first()
        if dealer is not None:
            if real_money:
                dealer.real_tokens += game.bet_amount
                dealer.save(update_fields=("real_tokens",))
            else:
                dealer.chips += game.bet_amount
                dealer.save(update_fields=("chips",))
        report.blackjack_games += 1
        game.delete()

    if report.crash_games or report.races or report.blackjack_games:
        OperationalEvent.objects.create(
            severity=OperationalEvent.Severity.WARNING,
            category="startup_recovery",
            message="Interrupted games were refunded during startup recovery.",
            context=asdict(report),
        )
    return report


async def recover_interrupted_games_async() -> RecoveryReport:
    return await sync_to_async(recover_interrupted_games, thread_sensitive=True)()
