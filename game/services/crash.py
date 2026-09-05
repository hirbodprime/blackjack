"""Transactional lifecycle for crash minigames."""

from dataclasses import dataclass

from asgiref.sync import sync_to_async
from django.db import transaction

from game.models import ChipTransaction, CrashGame, Player
from game.services.economy import BalanceChange, InsufficientChips, adjust_balance
from game.services.operations import BettingPaused, ensure_betting_open


class ActiveCrashGame(ValueError):
    """Raised when a player already has an unsettled crash game."""


class NoActiveCrashGame(ValueError):
    """Raised when no cash-out eligible crash game exists."""


@dataclass(frozen=True)
class CrashSettlement:
    game_id: int
    multiplier: float
    winnings: int
    balance_change: BalanceChange


@transaction.atomic
def start_crash_game(player_id: int, bet: int) -> CrashGame:
    ensure_betting_open()
    player = Player.objects.select_for_update().get(pk=player_id)
    if CrashGame.objects.filter(
        user_id=player_id,
        crashed=False,
        cashed_out=False,
    ).exists():
        raise ActiveCrashGame

    game = CrashGame.objects.create(user_id=player_id, bet=bet)
    adjust_balance(
        player,
        -bet,
        category=ChipTransaction.Category.BET,
        description="Crash game bet",
        reference_type="crash_game",
        reference_id=game.pk,
        idempotency_key=f"crash:{game.pk}:bet",
    )
    return game


async def start_crash_game_async(player_id: int, bet: int) -> CrashGame:
    return await sync_to_async(start_crash_game, thread_sensitive=True)(player_id, bet)


@transaction.atomic
def cash_out_crash_game(player_id: int) -> CrashSettlement:
    game = (
        CrashGame.objects.select_for_update()
        .filter(user_id=player_id, crashed=False, cashed_out=False)
        .first()
    )
    if game is None:
        raise NoActiveCrashGame

    game.cashed_out = True
    game.save(update_fields=("cashed_out",))
    winnings = int(game.bet * game.multiplier)
    change = adjust_balance(
        player_id,
        winnings,
        category=ChipTransaction.Category.MINIGAME_PAYOUT,
        description=f"Crash cash-out at {game.multiplier}x",
        reference_type="crash_game",
        reference_id=game.pk,
        idempotency_key=f"crash:{game.pk}:cashout",
        metadata={"bet": game.bet, "multiplier": game.multiplier},
    )
    settlement = CrashSettlement(game.pk, game.multiplier, winnings, change)
    game.delete()
    return settlement


async def cash_out_crash_game_async(player_id: int) -> CrashSettlement:
    return await sync_to_async(cash_out_crash_game, thread_sensitive=True)(player_id)


@transaction.atomic
def mark_crash_game_crashed(game_id: int) -> bool:
    game = CrashGame.objects.select_for_update().filter(pk=game_id).first()
    if game is None or game.cashed_out:
        return False
    game.crashed = True
    game.save(update_fields=("crashed",))
    return True


async def mark_crash_game_crashed_async(game_id: int) -> bool:
    return await sync_to_async(mark_crash_game_crashed, thread_sensitive=True)(game_id)


__all__ = [
    "ActiveCrashGame",
    "BettingPaused",
    "InsufficientChips",
    "NoActiveCrashGame",
    "cash_out_crash_game_async",
    "mark_crash_game_crashed_async",
    "start_crash_game_async",
]
