"""Telegram lifecycle for the multiplayer roulette Mini App."""

from __future__ import annotations

import asyncio
from collections import defaultdict

from asgiref.sync import sync_to_async
from django.conf import settings
from django.utils import timezone
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ChatType

from game.models import RouletteTable
from game.services.language import group_language
from game.services.multiplayer_roulette import (
    RouletteTableError, create_roulette_table_async, settle_table_async,
)
from game.services.table_games import GroupTableBusy


def _launch_url(bot_username: str, table: RouletteTable) -> str:
    payload = f"rt_{table.pk}_{table.access_token}"
    return f"https://t.me/{bot_username}/{settings.TELEGRAM_CASINO_APP_NAME}?startapp={payload}"


def _open_text(table, language):
    seconds = max(0, int((table.closes_at - timezone.now()).total_seconds()))
    if language == "fa":
        return (
            f"🎡 رولِت چندنفره • میز #{table.pk}\n\n"
            f"شرط‌بندی تا {seconds} ثانیه باز است.\n"
            "حداقل شرط: ۱۰ • حداکثر هر شرط: ۵٬۰۰۰\n"
            f"اثبات شفافیت: {table.seed_hash[:16]}…"
        )
    return (
        f"🎡 Multiplayer Roulette • Table #{table.pk}\n\n"
        f"Betting is open for {seconds} seconds.\n"
        "Minimum bet: 10 • Maximum per bet: 5,000\n"
        f"Fairness commitment: {table.seed_hash[:16]}…"
    )


async def roulette_table_command(update, context):
    if update.effective_chat.type == ChatType.PRIVATE:
        await update.effective_message.reply_text("Open multiplayer roulette inside a group.")
        return
    language = await sync_to_async(group_language)(update.effective_chat.id)
    try:
        table = await create_roulette_table_async(update.effective_chat.id, update.effective_user.id)
    except (RouletteTableError, GroupTableBusy, ValueError) as exc:
        await update.effective_message.reply_text(str(exc))
        return
    username = context.bot.username or (await context.bot.get_me()).username
    button = InlineKeyboardMarkup([[
        InlineKeyboardButton(
            "🎮 Open roulette table" if language == "en" else "🎮 باز کردن میز رولِت",
            url=_launch_url(username, table),
        )
    ]])
    message = await update.effective_message.reply_text(_open_text(table, language), reply_markup=button)
    table.message_id = message.message_id
    await sync_to_async(table.save)(update_fields=("message_id",))
    asyncio.create_task(_settle_after_deadline(context.bot, table.pk))


async def _settle_after_deadline(bot, table_id: int):
    table = await sync_to_async(RouletteTable.objects.get)(pk=table_id)
    delay = max(0, (table.closes_at - timezone.now()).total_seconds())
    await asyncio.sleep(delay)
    try:
        settlement = await settle_table_async(table_id)
    except RouletteTableError:
        return
    table = await sync_to_async(RouletteTable.objects.get)(pk=table_id)
    language = await sync_to_async(group_language)(table.chat_id)
    color = "green" if settlement.number == 0 else "red" if settlement.number in {1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36} else "black"
    totals = defaultdict(lambda: ["", 0])
    for player_id, name, payout in settlement.winners:
        totals[player_id][0] = name
        totals[player_id][1] += payout
    if language == "fa":
        rows = [f"🎯 شماره برنده: {settlement.number} ({color})"]
        rows += (["\n🏆 برندگان:"] + [f"• {name}: {amount:,} چیپ" for name, amount in totals.values()]) if totals else ["\nاین دور برنده‌ای نداشت."]
        rows.append(f"\nSeed: {settlement.seed}")
    else:
        rows = [f"🎯 Winning number: {settlement.number} ({color})"]
        rows += (["\n🏆 Winners:"] + [f"• {name}: {amount:,} chips" for name, amount in totals.values()]) if totals else ["\nNo winning bets this round."]
        rows.append(f"\nFairness seed: {settlement.seed}")
    await bot.send_message(table.chat_id, "\n".join(rows))
    if table.message_id:
        try:
            await bot.edit_message_text(
                chat_id=table.chat_id, message_id=table.message_id,
                text=_open_text(table, language) + f"\n\n✅ Result: {settlement.number}",
            )
        except Exception:
            pass


async def resume_roulette_tables(context):
    tables = await sync_to_async(list)(
        RouletteTable.objects.filter(status__in=(RouletteTable.Status.BETTING, RouletteTable.Status.SPINNING))
    )
    for table in tables:
        asyncio.create_task(_settle_after_deadline(context.bot, table.pk))
