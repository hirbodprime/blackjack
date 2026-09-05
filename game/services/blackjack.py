"""Transactional persistence operations for blackjack games."""

from asgiref.sync import sync_to_async
from django.db import transaction

from game.models import ChipTransaction, Game, JoinGame, Player
from game.services.economy import InsufficientChips, adjust_balance
from game.services.operations import BettingPaused, ensure_betting_open


class AlreadyJoined(ValueError):
    """Raised when a player is already active in the requested game."""


class ActiveInAnotherGame(ValueError):
    """Raised when a player is already active at another blackjack table."""


@transaction.atomic
def join_game_with_chips(player_id: int, game_id: int) -> JoinGame:
    """Atomically debit a blackjack bet and create the active participation."""
    ensure_betting_open()
    game = Game.objects.select_for_update().get(pk=game_id)
    player = Player.objects.select_for_update().get(pk=player_id)

    active_join = JoinGame.objects.filter(player=player, is_active=True).first()
    if active_join:
        if active_join.game_id == game.pk:
            raise AlreadyJoined(f"Player {player_id} already joined game {game_id}")
        raise ActiveInAnotherGame(
            f"Player {player_id} is already active in game {active_join.game_id}"
        )

    adjust_balance(
        player,
        -game.bet_amount,
        category=ChipTransaction.Category.BET,
        description="Blackjack entry bet",
        reference_type="blackjack_game",
        reference_id=game.pk,
    )
    return JoinGame.objects.create(player=player, game=game, is_active=True)


async def join_game_with_chips_async(player_id: int, game_id: int) -> JoinGame:
    return await sync_to_async(join_game_with_chips, thread_sensitive=True)(
        player_id,
        game_id,
    )


@transaction.atomic
def refund_joined_player(join_id: int, *, description: str) -> bool:
    """Refund and remove one chip-game participant exactly once."""
    joined = (
        JoinGame.objects.select_for_update()
        .select_related("player", "game")
        .filter(pk=join_id)
        .first()
    )
    if joined is None:
        return False

    adjust_balance(
        joined.player,
        joined.game.bet_amount,
        category=ChipTransaction.Category.REFUND,
        description=description,
        reference_type="blackjack_game",
        reference_id=joined.game_id,
        idempotency_key=f"blackjack:{joined.game_id}:join:{joined.pk}:refund",
    )
    joined.delete()
    return True


async def refund_joined_player_async(join_id: int, *, description: str) -> bool:
    return await sync_to_async(refund_joined_player, thread_sensitive=True)(
        join_id,
        description=description,
    )


__all__ = [
    "AlreadyJoined",
    "ActiveInAnotherGame",
    "BettingPaused",
    "InsufficientChips",
    "join_game_with_chips_async",
    "refund_joined_player_async",
]
