"""Central operational gates used by Telegram and administrative workflows."""

from asgiref.sync import sync_to_async

from game.models import BotControl, Player


class BettingPaused(RuntimeError):
    """Raised when an operator has temporarily disabled new wagers."""


def get_bot_control() -> BotControl:
    control, _ = BotControl.objects.get_or_create(pk=1)
    return control


async def get_bot_control_async() -> BotControl:
    return await sync_to_async(get_bot_control, thread_sensitive=True)()


def ensure_betting_open() -> None:
    if get_bot_control().betting_paused:
        raise BettingPaused("New bets are temporarily paused by an operator.")


async def ensure_betting_open_async() -> None:
    await sync_to_async(ensure_betting_open, thread_sensitive=True)()


def is_player_admin(player_id: int) -> bool:
    return Player.objects.filter(pk=player_id, admin=True, is_frozen=False).exists()


async def is_player_admin_async(player_id: int) -> bool:
    return await sync_to_async(is_player_admin, thread_sensitive=True)(player_id)
