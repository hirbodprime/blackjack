"""Season 1 comeback broadcast. An admin previews it, then sends it themselves.

/comeback          → preview to yourself, with counts
/comeback players  → DM every player once (re-runs skip anyone already reached)
/comeback groups   → post once in every group the bot knows
"""

import asyncio
import logging

from asgiref.sync import sync_to_async
from django.db import IntegrityError
from telegram import InlineKeyboardButton as Btn, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.error import Forbidden, RetryAfter, TelegramError

from game.economy_config import SEASON_STARTING_CHIPS, TOURNAMENT_PRIZE_POOL
from game.models import BroadcastDelivery, Group, Player, UserSettings
from game.services.operations import get_bot_control_async, is_player_admin_async


logger = logging.getLogger(__name__)
CAMPAIGN = "season1-comeback"
SEND_INTERVAL = 0.06  # ~16 messages/second, under Telegram's 30/s

PLAYER_TEXT = {
    "en": (
        "<b>🎰 BIG PAPA CASINO IS BACK</b>\n"
        "<b>Season 1 · The Comeback</b>\n"
        "━━━━━━━━━━━━━━━\n"
        "Everyone starts fresh with <b>{chips:,} chips</b>. Same bankroll, fair race to the top.\n"
        "Played before? Play one game and your permanent 🎖 <b>Veteran</b> badge is yours.\n\n"
        "<b>What's new</b>\n"
        "🐎 A <b>free horse</b> for you: name it and pick a powerup\n"
        "⚔️ <b>Tournaments every evening</b>, {pool:,} chips in prizes\n"
        "📈 <b>Weekly leaderboard</b> and 🌟 <b>season rewards</b>\n"
        "📆 Daily challenges with 🔥 streak bonuses\n"
        "🕹 <b>Arcade</b>: Crash, Mines and Hi-Lo\n"
        "♠️ Rebuilt <b>poker</b>, played right in the group\n"
        "🛍 New shop: boosts, streak freezes and titles\n🏅 50+ badges to collect, with rarity\n\n"
        "Your seat is waiting 👇"
    ),
    "fa": (
        "<b>🎰 کازینو بیگ پاپا برگشت!</b>\n"
        "<b>فصل ۱ · بازگشت</b>\n"
        "━━━━━━━━━━━━━━━\n"
        "همه با <b>{chips:,} چیپ</b> از نو شروع می‌کنند. شروع برابر، رقابت عادلانه.\n"
        "قبلاً بازی کرده‌ای؟ یک بازی کن تا نشان دائمی 🎖 <b>کهنه‌کار</b> مال تو شود.\n\n"
        "<b>چه چیزهایی جدید است</b>\n"
        "🐎 یک <b>اسب رایگان</b>: اسمش را بگذار و پاورآپ انتخاب کن\n"
        "⚔️ <b>تورنمنت هر شب</b> با {pool:,} چیپ جایزه\n"
        "📈 <b>جدول هفتگی</b> و 🌟 <b>جوایز فصل</b>\n"
        "📆 چالش‌های روزانه با جایزه 🔥 زنجیره\n"
        "🕹 <b>آرکید</b>: کرش، ماین و های-لو\n"
        "♠️ <b>پوکر</b> کاملاً جدید، داخل خود گروه\n"
        "🛍 فروشگاه جدید: بوست، محافظ زنجیره و لقب\n🏅 بیش از ۵۰ نشان کمیاب برای جمع کردن\n\n"
        "جایت خالی است 👇"
    ),
}
GROUP_TEXT = (
    "<b>🎰 BIG PAPA CASINO IS BACK · Season 1</b>\n"
    "━━━━━━━━━━━━━━━\n"
    "Fresh start: everyone has {chips:,} chips. Nightly tournaments, weekly prizes, "
    "free horses, rebuilt poker and a new arcade.\n\n"
    "🃏 /startblackjack · ♠️ /poker · 🏇 /horserace\n"
    "Open the bot privately to claim your free horse 👇"
)


def _player_keyboard(lang: str):
    fa = lang == "fa"
    return InlineKeyboardMarkup([
        [Btn("🎁 اسب رایگانت را بگیر" if fa else "🎁 Claim your free horse", callback_data="hub:claim")],
        [Btn("🎮 ورود به کازینو" if fa else "🎮 Open the casino", callback_data="hub:home")],
    ])


def _group_keyboard(bot_username: str):
    return InlineKeyboardMarkup([[Btn("🎁 Claim my free horse", url=f"https://t.me/{bot_username}?start=play")]])


def _audience():
    languages = dict(UserSettings.objects.values_list("player_id", "language"))
    done = set(BroadcastDelivery.objects.filter(campaign=CAMPAIGN).values_list("chat_id", flat=True))
    players = [
        (pid, languages.get(pid, "en"))
        for pid in Player.objects.filter(is_frozen=False).values_list("pk", flat=True)
        if pid not in done
    ]
    groups = [
        int(gid) for gid in Group.objects.values_list("group_chat_id", flat=True)
        if gid and gid.lstrip("-").isdigit() and int(gid) not in done
    ]
    return players, groups


def _claim(chat_id: int) -> bool:
    try:
        BroadcastDelivery.objects.create(campaign=CAMPAIGN, chat_id=chat_id)
        return True
    except IntegrityError:
        return False


def _record(chat_id: int, delivered: bool, error: str = "") -> None:
    BroadcastDelivery.objects.filter(campaign=CAMPAIGN, chat_id=chat_id).update(
        delivered=delivered, error=error[:120]
    )


async def _send(bot, chat_id: int, text: str, markup) -> tuple[bool, str]:
    for _ in range(3):
        try:
            await bot.send_message(chat_id, text, parse_mode=ParseMode.HTML, reply_markup=markup)
            return True, ""
        except RetryAfter as exc:
            await asyncio.sleep(exc.retry_after + 1)
        except Forbidden as exc:
            return False, f"blocked: {exc}"
        except TelegramError as exc:
            return False, str(exc)
    return False, "rate limited"


async def comeback_command(update, context):
    user_id = update.effective_user.id
    if not await is_player_admin_async(user_id):
        await update.effective_message.reply_text("🚫 Admins only.")
        return
    mode = (context.args[0].lower() if context.args else "preview")
    players, groups = await sync_to_async(_audience, thread_sensitive=True)()
    values = {"chips": SEASON_STARTING_CHIPS, "pool": TOURNAMENT_PRIZE_POOL}

    if mode == "preview":
        for lang in ("en", "fa"):
            await update.effective_message.reply_text(
                PLAYER_TEXT[lang].format(**values), parse_mode=ParseMode.HTML, reply_markup=_player_keyboard(lang)
            )
        await update.effective_message.reply_text(
            GROUP_TEXT.format(**values), parse_mode=ParseMode.HTML,
            reply_markup=_group_keyboard(context.bot.username),
        )
        await update.effective_message.reply_text(
            f"👆 Preview only. Still to reach: {len(players)} players, {len(groups)} groups.\n"
            "Run the season launch first, then:\n/comeback players\n/comeback groups"
        )
        return

    if (await get_bot_control_async()).broadcasts_muted:
        await update.effective_message.reply_text("Broadcasts are muted in Bot Control.")
        return
    if mode not in {"players", "groups"}:
        await update.effective_message.reply_text("Usage: /comeback [players|groups]")
        return

    targets = (
        [(pid, PLAYER_TEXT[lang if lang in PLAYER_TEXT else "en"].format(**values), _player_keyboard(lang)) for pid, lang in players]
        if mode == "players" else
        [(gid, GROUP_TEXT.format(**values), _group_keyboard(context.bot.username)) for gid in groups]
    )
    status = await update.effective_message.reply_text(f"📣 Sending to {len(targets)} {mode}…")
    sent = failed = 0
    for chat_id, text, markup in targets:
        if not await sync_to_async(_claim, thread_sensitive=True)(chat_id):
            continue
        ok, error = await _send(context.bot, chat_id, text, markup)
        await sync_to_async(_record, thread_sensitive=True)(chat_id, ok, error)
        sent += ok
        failed += not ok
        await asyncio.sleep(SEND_INTERVAL)
    await status.edit_text(f"✅ Comeback sent to {sent} {mode}. {failed} could not be reached (blocked or left).")
