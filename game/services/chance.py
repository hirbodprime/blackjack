"""Atomic settlement for single-update games of chance."""

from dataclasses import dataclass

from asgiref.sync import sync_to_async
from django.db import transaction

from game.models import ChipTransaction, Player
from game.services.economy import BalanceChange, InsufficientChips, adjust_balance
from game.services.operations import BettingPaused, ensure_betting_open


@dataclass(frozen=True)
class RouletteResult:
    selected_number: int
    result_number: int
    bet: int
    winnings: int
    won: bool
    payout_change: BalanceChange | None
    replayed: bool = False


@dataclass(frozen=True)
class SpinResult:
    label: str
    chips_delta: int
    xp_delta: int
    level_delta: int
    actual_chips_delta: int
    replayed: bool = False


@transaction.atomic
def settle_roulette(
    player_id: int,
    selected_number: int,
    bet: int,
    result_number: int,
    operation_id: str,
) -> RouletteResult:
    bet_key = f"roulette:{operation_id}:bet"
    existing = ChipTransaction.objects.filter(idempotency_key=bet_key).first()
    if existing:
        metadata = existing.metadata
        won = bool(metadata["won"])
        payout = ChipTransaction.objects.filter(
            idempotency_key=f"roulette:{operation_id}:payout"
        ).first()
        return RouletteResult(
            selected_number=int(metadata["selected_number"]),
            result_number=int(metadata["result_number"]),
            bet=abs(existing.amount),
            winnings=int(metadata["winnings"]),
            won=won,
            payout_change=(BalanceChange(payout, False) if payout else None),
            replayed=True,
        )

    ensure_betting_open()
    player = Player.objects.select_for_update().get(pk=player_id)
    won = selected_number == result_number
    winnings = bet * 35 if won else 0
    adjust_balance(
        player,
        -bet,
        category=ChipTransaction.Category.BET,
        description=f"Roulette bet on {selected_number}",
        reference_type="roulette",
        reference_id=operation_id,
        idempotency_key=bet_key,
        metadata={
            "selected_number": selected_number,
            "result_number": result_number,
            "won": won,
            "winnings": winnings,
        },
    )
    payout_change = None
    if won:
        # Return the stake plus 35x winnings, preserving the original net result.
        payout_change = adjust_balance(
            player,
            bet * 36,
            category=ChipTransaction.Category.MINIGAME_PAYOUT,
            description=f"Roulette win on {selected_number}",
            reference_type="roulette",
            reference_id=operation_id,
            idempotency_key=f"roulette:{operation_id}:payout",
            metadata={"result_number": result_number, "net_winnings": winnings},
        )
    return RouletteResult(
        selected_number,
        result_number,
        bet,
        winnings,
        won,
        payout_change,
    )


async def settle_roulette_async(*args, **kwargs) -> RouletteResult:
    return await sync_to_async(settle_roulette, thread_sensitive=True)(*args, **kwargs)


@transaction.atomic
def settle_spin(
    player_id: int,
    tier: str,
    cost: int,
    outcome: tuple[str, int, int, int],
    operation_id: str,
) -> SpinResult:
    bet_key = f"spin:{operation_id}:cost"
    existing = ChipTransaction.objects.filter(idempotency_key=bet_key).first()
    if existing:
        metadata = existing.metadata
        return SpinResult(
            label=metadata["label"],
            chips_delta=int(metadata["chips_delta"]),
            xp_delta=int(metadata["xp_delta"]),
            level_delta=int(metadata["level_delta"]),
            actual_chips_delta=int(metadata["actual_chips_delta"]),
            replayed=True,
        )

    ensure_betting_open()
    player = Player.objects.select_for_update().get(pk=player_id)
    label, chips_delta, xp_delta, level_delta = outcome
    balance_after_cost = player.chips - cost
    if balance_after_cost < 0:
        raise InsufficientChips
    actual_chips_delta = max(chips_delta, -balance_after_cost)
    metadata = {
        "tier": tier,
        "label": label,
        "chips_delta": chips_delta,
        "actual_chips_delta": actual_chips_delta,
        "xp_delta": xp_delta,
        "level_delta": level_delta,
    }
    adjust_balance(
        player,
        -cost,
        category=ChipTransaction.Category.BET,
        description=f"{tier} wheel spin cost",
        reference_type="spin",
        reference_id=operation_id,
        idempotency_key=bet_key,
        metadata=metadata,
    )
    if actual_chips_delta:
        adjust_balance(
            player,
            actual_chips_delta,
            category=ChipTransaction.Category.MINIGAME_PAYOUT,
            description=f"{tier} wheel chip result: {label}",
            reference_type="spin",
            reference_id=operation_id,
            idempotency_key=f"spin:{operation_id}:chips",
            allow_negative=False,
            metadata=metadata,
        )

    player.xp = max(player.xp + xp_delta, 0)
    player.level = max(player.level + level_delta, 1)
    player.save(update_fields=("xp", "level"))
    return SpinResult(
        label,
        chips_delta,
        xp_delta,
        level_delta,
        actual_chips_delta,
    )


async def settle_spin_async(*args, **kwargs) -> SpinResult:
    return await sync_to_async(settle_spin, thread_sensitive=True)(*args, **kwargs)


__all__ = [
    "BettingPaused",
    "InsufficientChips",
    "RouletteResult",
    "settle_roulette_async",
    "SpinResult",
    "settle_spin_async",
]
