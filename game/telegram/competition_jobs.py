"""Background job that runs the automatic competitions and tells players about them."""

import asyncio
import logging
from datetime import timedelta
from html import escape

from asgiref.sync import sync_to_async
from django.utils import timezone
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.error import Forbidden, RetryAfter, TelegramError

from game.models import ChipTransaction, CompetitionPayout, UserSettings
from game.services.achievements import sync_catalog
from game.services.challenges import ensure_daily_challenges
from game.services.competitions import tick_async, tournament_prizes
from game.services.operations import get_bot_control_async


logger = logging.getLogger(__name__)
TICK_SECONDS = 300
ACTIVE_WINDOW = timedelta(days=21)
VIEW_BUTTON = InlineKeyboardMarkup([[InlineKeyboardButton("🏆 Open Compete", callback_data="hub:compete")]])


async def _dm(bot, chat_id: int, text: str, markup=VIEW_BUTTON) -> bool:
    for _ in range(3):
        try:
            await bot.send_message(chat_id, text, parse_mode=ParseMode.HTML, reply_markup=markup)
            return True
        except RetryAfter as exc:
            await asyncio.sleep(exc.retry_after + 1)
        except Forbidden:
            return False
        except TelegramError:
            logger.exception("Competition DM to %s failed", chat_id)
            return False
    return False


def _recently_active_opted_in() -> list[int]:
    since = timezone.now() - ACTIVE_WINDOW
    active = set(
        ChipTransaction.objects.filter(created_at__gte=since)
        .values_list("player_id", flat=True).distinct()
    )
    return list(
        UserSettings.objects.filter(player_id__in=active, notify_tournaments=True)
        .values_list("player_id", flat=True)
    )


def _payout_lines(payouts: list[CompetitionPayout]) -> str:
    medals = ("🥇", "🥈", "🥉")
    lines = []
    for p in payouts:
        icon = medals[p.rank - 1] if p.rank <= 3 else f"{p.rank}."
        lines.append(f"{icon} {escape(p.player.name)} — +{p.prize_chips:,}")
    return "\n".join(lines)


def _with_players(payouts):
    return list(CompetitionPayout.objects.filter(pk__in=[p.pk for p in payouts]).select_related("player"))


async def _announce(bot, report) -> None:
    muted = (await get_bot_control_async()).broadcasts_muted
    if report.started and not muted:
        recipients = await sync_to_async(_recently_active_opted_in, thread_sensitive=True)()
        for tournament in report.started:
            prizes = " / ".join(f"{p:,}" for p in tournament_prizes(tournament.prize_pool))
            text = (
                f"<b>🔴 {escape(tournament.title)} is LIVE!</b>\n\n"
                f"2 hours · net winnings count · top 3 win {prizes} chips.\n"
                "Jump into a game now 👇"
            )
            for chat_id in recipients:
                await _dm(bot, chat_id, text)
                await asyncio.sleep(0.05)

    for tournament, payouts in report.settled:
        payouts = await sync_to_async(_with_players, thread_sensitive=True)(payouts)
        for p in payouts:
            await _dm(bot, p.player_id, (
                f"<b>🏆 {escape(tournament.title)} — you finished #{p.rank}!</b>\n"
                f"🎁 +{p.prize_chips:,} chips have been added to your balance."
            ))

    if report.weekly:
        payouts = await sync_to_async(_with_players, thread_sensitive=True)(report.weekly)
        board = _payout_lines(payouts)
        for p in payouts:
            await _dm(bot, p.player_id, (
                f"<b>📈 Weekly leaderboard — you placed #{p.rank}!</b>\n"
                f"🎁 +{p.prize_chips:,} chips\n\n{board}"
            ))

    if report.season:
        payouts = await sync_to_async(_with_players, thread_sensitive=True)(report.season)
        board = _payout_lines(payouts)
        for p in payouts:
            await _dm(bot, p.player_id, (
                f"<b>🌟 The season is over — you finished #{p.rank}!</b>\n"
                f"🎁 +{p.prize_chips:,} chips\n\n{board}"
            ))


async def competition_tick(context) -> None:
    try:
        await sync_to_async(ensure_daily_challenges, thread_sensitive=True)()
        report = await tick_async()
        await _announce(context.bot, report)
    except Exception:
        logger.exception("Competition tick failed")


async def start_competition_jobs(application) -> None:
    await sync_to_async(sync_catalog, thread_sensitive=True)()
    application.job_queue.run_repeating(
        competition_tick, interval=TICK_SECONDS, first=20, name="competition_tick"
    )
