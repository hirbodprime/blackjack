"""Buttons for group games, so players tap instead of typing commands.

``cmd:<name>`` runs an existing command handler on behalf of whoever tapped.
The handlers only read the chat, the sender and ``reply_text`` from the
message, so a small adapter around the callback query is all they need.
"""

from html import escape

from asgiref.sync import sync_to_async
from telegram import InlineKeyboardButton as Btn, InlineKeyboardMarkup
from telegram.constants import ChatType, ParseMode
from telegram.error import TelegramError

from game.models import HorseRace, OwnedHorse
from game.i18n import pick
from game.services.language import group_language, language_for_update


RACE_BETS = (100, 500, 1_000, 5_000)


class _TappedMessage:
    """The group message the button sits on, but 'sent' by the person who tapped."""

    def __init__(self, query, text: str = ""):
        self._message = query.message
        self.from_user = query.from_user
        self.chat = query.message.chat
        self.chat_id = query.message.chat.id
        self.message_id = query.message.message_id
        self.text = text

    async def reply_text(self, text, **kwargs):
        kwargs.pop("quote", None)
        return await self._message.get_bot().send_message(self.chat_id, text, **kwargs)

    def __getattr__(self, name):
        return getattr(self._message, name)


class TappedUpdate:
    def __init__(self, update, text: str = ""):
        query = update.callback_query
        self.update_id = update.update_id
        self.callback_query = None
        self.message = self.effective_message = _TappedMessage(query, text)
        self.effective_chat = query.message.chat
        self.effective_user = query.from_user


def _handlers():
    from bot_sections.blackjack_game import (
        flee_game, force_start, highroller, hit, join_blackjack, nextgame, stand, start_blackjack,
    )
    from bot_sections.horse_racing_and_social import horserace, joinrace, startrace
    from game.telegram.roulette_table import roulette_table_command

    return {
        "join": join_blackjack, "hit": hit, "stand": stand, "flee": flee_game,
        "forcestart": force_start, "nextgame": nextgame,
        "startblackjack": start_blackjack, "highroller": highroller,
        "horserace": horserace, "startrace": startrace, "joinrace": joinrace,
        "roulette": roulette_table_command,
    }


async def run_as_command(update, context, name: str, args: list[str] | None = None) -> None:
    handler = _handlers()[name]
    context.args = args or []
    await handler(TappedUpdate(update, f"/{name} {' '.join(args or [])}".strip()), context)


# ── Keyboards attached to game messages ─────────────────────────────────────

async def chat_language(chat_id: int) -> str:
    return await sync_to_async(group_language, thread_sensitive=True)(chat_id)


def blackjack_join_keyboard(lang: str = "en"):
    return InlineKeyboardMarkup([[
        Btn(pick(lang, "🙋 Join", "🙋 ورود"), callback_data="cmd:join"),
        Btn(pick(lang, "▶️ Start now", "▶️ شروع"), callback_data="cmd:forcestart"),
    ]])


def blackjack_turn_keyboard(lang: str = "en"):
    return InlineKeyboardMarkup([[
        Btn(pick(lang, "🎰 Hit", "🎰 کارت"), callback_data="cmd:hit"),
        Btn(pick(lang, "✋ Stand", "✋ بس"), callback_data="cmd:stand"),
    ]])


def race_keyboard(lang: str = "en"):
    return InlineKeyboardMarkup([[
        Btn(pick(lang, "🐎 Place a bet", "🐎 شرط ببند"), callback_data="race:pick"),
        Btn(pick(lang, "🏁 Start race", "🏁 شروع مسابقه"), callback_data="cmd:startrace"),
    ]])


def group_launcher(bot_username: str, lang: str = "en", chat_id: int | None = None):
    from game.telegram.hub import arcade_button

    fa = lang == "fa"
    return InlineKeyboardMarkup([
        *([[arcade_button(False, bot_username, chat_id)]] if chat_id is not None else []),
        [Btn("🃏 بلک‌جک" if fa else "🃏 Blackjack", callback_data="cmd:startblackjack"),
         Btn("💎 شرط بالا" if fa else "💎 High roller", callback_data="cmd:highroller")],
        [Btn("♠️ پوکر" if fa else "♠️ Poker", callback_data="race:poker"),
         Btn("🏇 مسابقه اسب" if fa else "🏇 Horse race", callback_data="cmd:horserace")],
        [Btn("🎡 رولت" if fa else "🎡 Roulette", callback_data="cmd:roulette")],
        [Btn("👤 منوی شخصی من" if fa else "👤 My casino (private)", url=f"https://t.me/{bot_username}?start=play")],
    ])


GROUP_LAUNCHER_TEXT = {
    "en": "<b>🎰 BIG PAPA CASINO</b>\nPick a game to start at this table 👇",
    "fa": "<b>🎰 کازینو بیگ پاپا</b>\nیک بازی را برای این گروه شروع کن 👇",
}


async def show_group_launcher(update, context) -> None:
    lang = await language_for_update(update)
    await update.effective_message.reply_text(
        GROUP_LAUNCHER_TEXT.get(lang, GROUP_LAUNCHER_TEXT["en"]),
        parse_mode=ParseMode.HTML,
        reply_markup=group_launcher(context.bot.username, lang, update.effective_chat.id),
    )


# ── Callbacks ───────────────────────────────────────────────────────────────

async def cmd_callback(update, context) -> None:
    query = update.callback_query
    name = query.data.split(":", 1)[1]
    if name not in _handlers() or query.message.chat.type == ChatType.PRIVATE:
        await query.answer()
        return
    await query.answer()
    await run_as_command(update, context, name)


def _race_horses(chat_id: int, user_id: int) -> list[tuple[int, str]]:
    """Horses a player may back: the house runners plus their own horses."""
    horses = [(2, "Horse 2"), (3, "Horse 3")]
    for horse in OwnedHorse.objects.filter(user_id=user_id).order_by("horse_number"):
        horses.append((horse.horse_number, f"{horse.emoji or '🐎'} {horse.name or f'Horse {horse.horse_number}'}"))
    return horses


async def race_callback(update, context) -> None:
    """race:pick → horse buttons for the tapper; race:h:<uid>:<n> → bet buttons; race:b:… → bet."""
    query = update.callback_query
    parts = query.data.split(":")
    user = query.from_user
    if parts[1] == "poker":
        from game.telegram.poker import STAKES

        await query.answer()
        lang = await chat_language(query.message.chat.id)
        await query.message.reply_text(
            pick(lang, "♠️ Choose the stakes:", "♠️ مبلغ را انتخاب کن:"),
            reply_markup=InlineKeyboardMarkup([
                [Btn(f"🪙 {buy:,} · {sb:,}/{sb * 2:,}", callback_data=f"poker:create:{buy}:{sb}")]
                for buy, sb in STAKES
            ]),
        )
        return
    if parts[1] == "pick":
        open_race = await HorseRace.objects.filter(
            chat_id=query.message.chat.id, race_started=False, completed=False
        ).aexists()
        if not open_race:
            lang = await chat_language(query.message.chat.id)
            await query.answer(pick(lang, "No race is open — start one first.", "مسابقه‌ای باز نیست — اول یکی بساز."), show_alert=True)
            return
        lang = await chat_language(query.message.chat.id)
        horses = await sync_to_async(_race_horses, thread_sensitive=True)(query.message.chat.id, user.id)
        await query.answer()
        rows = [[Btn(label, callback_data=f"race:h:{user.id}:{number}")] for number, label in horses]
        rows.append([Btn(pick(lang, "✖️ Cancel", "✖️ لغو"), callback_data=f"race:x:{user.id}")])
        await query.message.reply_text(
            f"🐎 {escape(user.first_name)}, " + pick(lang, "pick your horse:", "اسبت را انتخاب کن:"),
            reply_markup=InlineKeyboardMarkup(rows), parse_mode=ParseMode.HTML,
        )
        return

    owner = int(parts[2])
    if owner != user.id:
        await query.answer("🙅", show_alert=False)
        return
    if parts[1] == "x":
        await query.answer()
        await _delete(query)
        return
    if parts[1] == "h":
        horse = parts[3]
        await query.answer()
        lang = await chat_language(query.message.chat.id)
        await query.edit_message_text(
            f"🐎 #{horse} — " + pick(lang, "how much?", "چقدر؟"),
            reply_markup=InlineKeyboardMarkup([
                [Btn(f"🪙 {amount:,}", callback_data=f"race:b:{owner}:{horse}:{amount}") for amount in RACE_BETS],
                [Btn(pick(lang, "✖️ Cancel", "✖️ لغو"), callback_data=f"race:x:{owner}")],
            ]),
        )
        return
    if parts[1] == "b":
        await query.answer()
        await _delete(query)
        await run_as_command(update, context, "joinrace", [parts[3], parts[4]])


async def _delete(query) -> None:
    try:
        await query.message.delete()
    except TelegramError:
        pass
