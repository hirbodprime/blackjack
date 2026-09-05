"""In-process throttling and duplicate-delivery protection for Telegram updates."""

import time

from asgiref.sync import sync_to_async
from telegram.ext import ApplicationHandlerStop

from game.models import BotControl, OperationalEvent, Player


def telegram_access_allowed(user_id: int, command: str | None = None) -> bool:
    if command in TelegramUpdateGuard.SAFE_COMMANDS:
        return True
    player = Player.objects.filter(pk=user_id).values("admin", "is_frozen").first()
    if player is None:
        return True
    if player["is_frozen"]:
        return False
    control = BotControl.objects.filter(pk=1).first()
    return not (control and control.maintenance_mode and not player["admin"])


class TelegramUpdateGuard:
    SAFE_COMMANDS = {"/start", "/help", "/language", "/myid"}

    def __init__(self, command_cooldown: float = 1.25, callback_ttl: float = 300.0):
        self.command_cooldown = command_cooldown
        self.callback_ttl = callback_ttl
        self._commands: dict[tuple[int, str], float] = {}
        self._callbacks: dict[str, float] = {}

    def allow_command(self, user_id: int, command: str, *, now: float | None = None) -> bool:
        current = time.monotonic() if now is None else now
        key = (user_id, command.lower())
        self._prune(current)
        previous = self._commands.get(key)
        allowed = previous is None or current - previous >= self.command_cooldown
        if allowed:
            self._commands[key] = current
        return allowed

    def allow_callback(self, callback_id: str, *, now: float | None = None) -> bool:
        current = time.monotonic() if now is None else now
        self._prune(current)
        previous = self._callbacks.get(callback_id)
        allowed = previous is None or current - previous >= self.callback_ttl
        if allowed:
            self._callbacks[callback_id] = current
        return allowed

    def _prune(self, now: float) -> None:
        command_cutoff = now - max(self.command_cooldown * 10, 60)
        callback_cutoff = now - self.callback_ttl
        self._commands = {
            key: seen for key, seen in self._commands.items() if seen >= command_cutoff
        }
        self._callbacks = {
            key: seen for key, seen in self._callbacks.items() if seen >= callback_cutoff
        }

    async def handle_command(self, update, context) -> None:
        message = update.effective_message
        user = update.effective_user
        if message is None or user is None or not message.text:
            return
        command = message.text.split(maxsplit=1)[0].split("@", 1)[0]
        if not await self._access_allowed(user.id, command=command):
            player = await sync_to_async(
                Player.objects.filter(pk=user.id).values("is_frozen", "freeze_reason").first,
                thread_sensitive=True,
            )()
            if player and player["is_frozen"]:
                reason = f" Reason: {player['freeze_reason']}" if player["freeze_reason"] else ""
                await message.reply_text(f"Your player account is temporarily frozen.{reason}")
            else:
                control = await sync_to_async(BotControl.objects.filter(pk=1).first)()
                await message.reply_text(
                    control.maintenance_message if control else "The bot is under maintenance."
                )
            raise ApplicationHandlerStop
        if self.allow_command(user.id, command):
            return
        await self._record_rate_limit(user.id, update, "command", command)
        await message.reply_text("Please wait a moment before repeating that command.")
        raise ApplicationHandlerStop

    async def handle_callback(self, update, context) -> None:
        query = update.callback_query
        if query is None:
            return
        if not await self._access_allowed(update.effective_user.id):
            await query.answer("This action is unavailable while the account or bot is paused.", show_alert=True)
            raise ApplicationHandlerStop
        if self.allow_callback(query.id):
            return
        await self._record_rate_limit(
            update.effective_user.id, update, "callback", query.data or ""
        )
        await query.answer("That action was already processed.", show_alert=False)
        raise ApplicationHandlerStop

    async def _access_allowed(self, user_id: int, *, command: str | None = None) -> bool:
        return await sync_to_async(telegram_access_allowed, thread_sensitive=True)(
            user_id, command
        )

    async def _record_rate_limit(self, user_id, update, kind: str, value: str) -> None:
        await sync_to_async(OperationalEvent.objects.create, thread_sensitive=True)(
            severity=OperationalEvent.Severity.INFO,
            category="rate_limit",
            message=f"Blocked repeated Telegram {kind}",
            chat_id=getattr(getattr(update, "effective_chat", None), "id", None),
            player_id=user_id,
            context={"kind": kind, "value": value, "update_id": update.update_id},
        )
