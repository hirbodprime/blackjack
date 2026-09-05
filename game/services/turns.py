"""Persistent blackjack turn tokens and timeout decisions."""

from dataclasses import dataclass
from uuid import uuid4

from asgiref.sync import sync_to_async
from django.db import transaction

from game.models import Game, JoinGame, OperationalEvent


@dataclass(frozen=True)
class TurnTimeoutResult:
    applied: bool
    removed: bool = False
    timeout_count: int = 0
    player_id: int | None = None


@transaction.atomic
def begin_player_turn(game_id: int, player_id: int) -> str:
    game = Game.objects.select_for_update().get(pk=game_id, started=True, ended=False)
    if not game.turn_order or game.turn_order[0] != player_id:
        raise ValueError("Player is not the current turn")
    joined = JoinGame.objects.select_for_update().get(
        game=game, player_id=player_id, is_active=True
    )
    token = str(uuid4())
    joined.turn_token = token
    joined.save(update_fields=("turn_token",))
    return token


async def begin_player_turn_async(*args, **kwargs) -> str:
    return await sync_to_async(begin_player_turn, thread_sensitive=True)(*args, **kwargs)


@transaction.atomic
def record_player_action(game_id: int, player_id: int) -> None:
    joined = JoinGame.objects.select_for_update().get(
        game_id=game_id, player_id=player_id, is_active=True
    )
    joined.consecutive_timeouts = 0
    joined.turn_token = ""
    joined.save(update_fields=("consecutive_timeouts", "turn_token"))


async def record_player_action_async(*args, **kwargs) -> None:
    await sync_to_async(record_player_action, thread_sensitive=True)(*args, **kwargs)


@transaction.atomic
def apply_player_timeout(game_id: int, player_id: int, token: str) -> TurnTimeoutResult:
    game = Game.objects.select_for_update().filter(
        pk=game_id, started=True, ended=False
    ).first()
    if game is None or not game.turn_order or game.turn_order[0] != player_id:
        return TurnTimeoutResult(False)
    joined = JoinGame.objects.select_for_update().filter(
        game=game, player_id=player_id, is_active=True
    ).first()
    if joined is None or joined.turn_token != token:
        return TurnTimeoutResult(False)

    joined.consecutive_timeouts += 1
    joined.turn_token = ""
    joined.has_stood = True
    removed = joined.consecutive_timeouts >= 2
    if removed:
        joined.is_active = False
    joined.save(update_fields=(
        "consecutive_timeouts", "turn_token", "has_stood", "is_active"
    ))
    if removed:
        OperationalEvent.objects.create(
            severity=OperationalEvent.Severity.INFO,
            category="player_inactivity",
            message="Player removed after two consecutive blackjack turn timeouts.",
            chat_id=game.chat_id,
            player_id=joined.player_id,
            game_id=game.pk,
            context={"consecutive_timeouts": joined.consecutive_timeouts},
        )
    return TurnTimeoutResult(
        True, removed, joined.consecutive_timeouts, joined.player_id
    )


async def apply_player_timeout_async(*args, **kwargs) -> TurnTimeoutResult:
    return await sync_to_async(apply_player_timeout, thread_sensitive=True)(
        *args, **kwargs
    )
