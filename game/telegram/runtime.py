"""Telegram application lifecycle and global error reporting."""

import logging

from asgiref.sync import sync_to_async

from game.models import OperationalEvent


logger = logging.getLogger("blackjack.telegram")


async def telegram_error_handler(update, context) -> None:
    error = context.error
    effective_chat = getattr(update, "effective_chat", None)
    effective_user = getattr(update, "effective_user", None)
    game_id = None
    chat_id = getattr(effective_chat, "id", None)

    logger.exception(
        "Unhandled Telegram update error",
        exc_info=(type(error), error, error.__traceback__) if error else None,
        extra={"chat_id": chat_id, "player_id": getattr(effective_user, "id", None)},
    )

    try:
        await sync_to_async(OperationalEvent.objects.create, thread_sensitive=True)(
            severity=OperationalEvent.Severity.ERROR,
            category="telegram_update",
            message=str(error)[:4000] if error else "Unknown Telegram update error",
            chat_id=chat_id,
            player_id=getattr(effective_user, "id", None),
            game_id=game_id,
            context={
                "update_id": getattr(update, "update_id", None),
                "exception_type": type(error).__name__ if error else None,
            },
        )
    except Exception:
        logger.exception("Failed to persist Telegram operational event")


async def telegram_shutdown(application) -> None:
    logger.info("Telegram application shutdown completed")


async def record_telegram_failure(
    error: Exception,
    *,
    player_id: int | None = None,
    chat_id: int | None = None,
    message_type: str = "message",
    game_id: int | None = None,
) -> None:
    """Persist a caught send failure so it remains visible to operators."""
    logger.warning(
        "Telegram send failed",
        exc_info=(type(error), error, error.__traceback__),
        extra={"player_id": player_id, "chat_id": chat_id, "game_id": game_id},
    )
    try:
        await sync_to_async(OperationalEvent.objects.create, thread_sensitive=True)(
            severity=OperationalEvent.Severity.WARNING,
            category="telegram_send_failure",
            message=str(error)[:4000],
            player_id=player_id,
            chat_id=chat_id,
            game_id=game_id,
            context={"message_type": message_type},
        )
    except Exception:
        logger.exception("Failed to persist caught Telegram send failure")
