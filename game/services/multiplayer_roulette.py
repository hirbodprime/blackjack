"""Server-authoritative multiplayer European roulette tables."""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import timedelta

from asgiref.sync import sync_to_async
from django.db import transaction
from django.utils import timezone

from game.models import (
    ChipTransaction, Dealer, Player, RouletteTable, RouletteTableBet,
)
from game.services.economy import InsufficientChips, adjust_balance
from game.services.operations import ensure_betting_open
from game.services.table_games import ensure_roulette_can_open


RED_NUMBERS = {1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36}
BETTING_SECONDS = 40
MIN_BET = 10
MAX_BET = 5_000


class RouletteTableError(ValueError):
    pass


@dataclass(frozen=True)
class Settlement:
    table_id: int
    number: int
    winners: tuple[tuple[int, str, int], ...]
    seed: str


def _multiplier(kind: str) -> int:
    return 36 if kind == RouletteTableBet.Kind.STRAIGHT else 3 if kind in {
        RouletteTableBet.Kind.DOZEN, RouletteTableBet.Kind.COLUMN,
    } else 2


def bet_wins(kind: str, selection: str, number: int) -> bool:
    if kind == RouletteTableBet.Kind.STRAIGHT:
        return number == int(selection)
    if number == 0:
        return False
    if kind == RouletteTableBet.Kind.RED:
        return number in RED_NUMBERS
    if kind == RouletteTableBet.Kind.BLACK:
        return number not in RED_NUMBERS
    if kind == RouletteTableBet.Kind.ODD:
        return number % 2 == 1
    if kind == RouletteTableBet.Kind.EVEN:
        return number % 2 == 0
    if kind == RouletteTableBet.Kind.LOW:
        return 1 <= number <= 18
    if kind == RouletteTableBet.Kind.HIGH:
        return 19 <= number <= 36
    if kind == RouletteTableBet.Kind.DOZEN:
        dozen = int(selection)
        return (dozen - 1) * 12 < number <= dozen * 12
    if kind == RouletteTableBet.Kind.COLUMN:
        return ((number - 1) % 3) + 1 == int(selection)
    return False


def validate_bet(kind: str, selection: str, amount: int) -> None:
    valid_kinds = {choice for choice, _ in RouletteTableBet.Kind.choices}
    if kind not in valid_kinds:
        raise RouletteTableError("Unknown bet type.")
    if not MIN_BET <= amount <= MAX_BET:
        raise RouletteTableError(f"Each bet must be between {MIN_BET:,} and {MAX_BET:,} chips.")
    if kind == RouletteTableBet.Kind.STRAIGHT and (not selection.isdigit() or not 0 <= int(selection) <= 36):
        raise RouletteTableError("Exact number must be from 0 to 36.")
    if kind in {RouletteTableBet.Kind.DOZEN, RouletteTableBet.Kind.COLUMN} and selection not in {"1", "2", "3"}:
        raise RouletteTableError("Dozen and column must be 1, 2, or 3.")
    fixed = {"red": "red", "black": "black", "odd": "odd", "even": "even", "low": "low", "high": "high"}
    if kind in fixed and selection != fixed[kind]:
        raise RouletteTableError("Invalid selection.")


def _table_max_liability(bets) -> int:
    return max(
        (sum(bet.amount * _multiplier(bet.kind) for bet in bets if bet_wins(bet.kind, bet.selection, number)) for number in range(37)),
        default=0,
    )


@transaction.atomic
def create_roulette_table(chat_id: int, player_id: int) -> RouletteTable:
    ensure_betting_open()
    ensure_roulette_can_open(chat_id)
    existing = RouletteTable.objects.select_for_update().filter(
        chat_id=chat_id, status__in=(RouletteTable.Status.BETTING, RouletteTable.Status.SPINNING)
    ).first()
    if existing:
        return existing
    seed = secrets.token_hex(32)
    table = RouletteTable.objects.create(
        chat_id=chat_id,
        created_by_id=player_id,
        closes_at=timezone.now() + timedelta(seconds=BETTING_SECONDS),
        seed_hash=hashlib.sha256(seed.encode()).hexdigest(),
        seed_reveal=seed,  # protected API never exposes this before settlement
        access_token=secrets.token_urlsafe(18)[:32],
    )
    return table


@transaction.atomic
def place_table_bet(
    table_id: int, player_id: int, kind: str, selection: str,
    amount: int, request_id: str,
) -> RouletteTableBet:
    ensure_betting_open()
    validate_bet(kind, selection, amount)
    existing = RouletteTableBet.objects.filter(idempotency_key=request_id).first()
    if existing:
        return existing
    table = RouletteTable.objects.select_for_update().get(pk=table_id)
    if table.status != RouletteTable.Status.BETTING or timezone.now() >= table.closes_at:
        raise RouletteTableError("Betting is closed for this round.")
    player = Player.objects.select_for_update().get(pk=player_id)
    dealer = Dealer.objects.select_for_update().first()
    if dealer is None:
        raise RouletteTableError("Casino bankroll is unavailable.")
    if player.chips < amount:
        raise InsufficientChips("Not enough chips.")
    proposed = RouletteTableBet(
        table=table, player=player, kind=kind, selection=selection,
        amount=amount, idempotency_key=request_id,
    )
    active_tables = RouletteTable.objects.filter(status__in=(RouletteTable.Status.BETTING, RouletteTable.Status.SPINNING))
    total_liability = 0
    for active in active_tables:
        bets = list(active.bets.all())
        if active.pk == table.pk:
            bets.append(proposed)
        total_liability += _table_max_liability(bets)
    if total_liability > dealer.chips + amount:
        raise RouletteTableError("The casino bankroll cannot cover that bet right now.")
    adjust_balance(
        player, -amount, category=ChipTransaction.Category.BET,
        description=f"Roulette table #{table.pk}: {kind} {selection}",
        reference_type="roulette_table", reference_id=table.pk,
        idempotency_key=f"roulette-table:{request_id}:bet",
        metadata={"kind": kind, "selection": selection},
    )
    dealer.chips += amount
    dealer.save(update_fields=("chips",))
    proposed.save()
    return proposed


@transaction.atomic
def settle_table(table_id: int) -> Settlement:
    table = RouletteTable.objects.select_for_update().get(pk=table_id)
    if table.status == RouletteTable.Status.COMPLETE:
        winners = tuple(
            (bet.player_id, bet.player.name, bet.payout)
            for bet in table.bets.filter(won=True).select_related("player")
        )
        return Settlement(table.pk, table.winning_number, winners, table.seed_reveal)
    if timezone.now() < table.closes_at:
        raise RouletteTableError("Betting is still open.")
    table.status = RouletteTable.Status.SPINNING
    table.save(update_fields=("status",))
    digest = hashlib.sha256(f"{table.seed_reveal}:{table.pk}".encode()).digest()
    number = int.from_bytes(digest, "big") % 37
    dealer = Dealer.objects.select_for_update().first()
    if dealer is None:
        raise RouletteTableError("Casino bankroll is unavailable.")
    winners = []
    for bet in table.bets.select_for_update().select_related("player"):
        bet.won = bet_wins(bet.kind, bet.selection, number)
        bet.payout = bet.amount * _multiplier(bet.kind) if bet.won else 0
        bet.settled_at = timezone.now()
        if bet.payout:
            adjust_balance(
                bet.player_id, bet.payout,
                category=ChipTransaction.Category.MINIGAME_PAYOUT,
                description=f"Roulette table #{table.pk} win on {bet.kind} {bet.selection}",
                reference_type="roulette_table", reference_id=table.pk,
                idempotency_key=f"roulette-table:{bet.pk}:payout",
                metadata={"number": number, "kind": bet.kind, "selection": bet.selection},
            )
            dealer.chips -= bet.payout
            winners.append((bet.player_id, bet.player.name, bet.payout))
        bet.save(update_fields=("won", "payout", "settled_at"))
    dealer.save(update_fields=("chips",))
    table.status = RouletteTable.Status.COMPLETE
    table.winning_number = number
    table.completed_at = timezone.now()
    table.save(update_fields=("status", "winning_number", "completed_at"))
    return Settlement(table.pk, number, tuple(winners), table.seed_reveal)


create_roulette_table_async = lambda *a, **kw: sync_to_async(create_roulette_table, thread_sensitive=True)(*a, **kw)
settle_table_async = lambda *a, **kw: sync_to_async(settle_table, thread_sensitive=True)(*a, **kw)
