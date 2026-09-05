"""Telegram interface for persistent Texas Hold'em cash tables."""

from __future__ import annotations

import asyncio
import random

from asgiref.sync import sync_to_async
from telegram import ForceReply, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ChatType

from game.models import Player, PokerHand, PokerSeat, PokerTable
from game.services.language import group_language, language_for_update
from game.services.poker import (
    InvalidAction, NotYourTurn, PokerError, TableExists, TableFull,
    act_async, act_bot_async, add_bot_async, cash_out_async, close_table_async,
    create_table_async, describe_visible_hand, estimate_bot_equity, join_table_async,
    normalize_bot_names_async, remove_bot_async,
    start_hand_async, timeout_action_async,
)
from game.services.operations import BettingPaused
from game.services.table_games import GroupTableBusy


TEXT = {
    "private": {"en": "Poker tables can only be created inside a group.", "fa": "میز پوکر فقط داخل گروه ساخته می‌شود."},
    "usage": {"en": "Usage: /poker <buy-in> [small blind]\nExample: /poker 1000 10", "fa": "روش استفاده: /poker <ورودی> [اسمال بلایند]\nمثال: /poker 1000 10"},
    "created": {"en": "🃏 Texas Hold'em cash table", "fa": "🃏 میز نقدی تگزاس هولدم"},
    "dm_required": {"en": "Open the bot privately and press Start before joining; your cards are sent there.", "fa": "پیش از ورود، ربات را خصوصی باز کنید و Start بزنید؛ کارت‌ها آنجا فرستاده می‌شوند."},
    "cards": {"en": "🃏 Your cards at table #{table}: {cards}\nKeep them secret.", "fa": "🃏 کارت‌های شما در میز #{table}: {cards}\nآنها را مخفی نگه دارید."},
    "turn": {"en": "Your turn — pot {pot:,}, current bet {bet:,}, you have committed {committed:,}.\nYou have 60 seconds.", "fa": "نوبت شماست — پات {pot:,}، شرط فعلی {bet:,}، پرداخت شما {committed:,}.\n۶۰ ثانیه فرصت دارید."},
}


def _t(key, language, **values):
    return TEXT[key].get(language, TEXT[key]["en"]).format(**values)


HAND_FA = {
    "straight flush": "استریت فلاش", "four of a kind": "کاره", "full house": "فول هاوس",
    "flush": "فلاش", "straight": "استریت", "three of a kind": "سه‌تایی",
    "two pair": "دو جفت", "one pair": "یک جفت", "pair": "یک جفت", "high card": "کارت بالا",
}


async def _player_insight(hand_id: int, player_id: int, language: str) -> str:
    def calculate():
        hand = PokerHand.objects.select_related("table").get(pk=hand_id)
        seats = list(PokerSeat.objects.filter(table=hand.table).select_related("player"))
        seat = next(item for item in seats if item.player_id == player_id)
        label = describe_visible_hand(seat.hole_cards, hand.community_cards)
        equity = estimate_bot_equity(seat, hand, seats, samples=180)
        return seat.hole_cards, hand.community_cards, label, equity
    hole, board, label, equity = await sync_to_async(calculate, thread_sensitive=True)()
    shown_label = HAND_FA.get(label, label) if language == "fa" else label
    board_text = "   ".join(f"[ {card} ]" for card in board) or ("هنوز کارتی نیست" if language == "fa" else "No community cards yet")
    if language == "fa":
        return f"🃏 کارت‌های شما: {' '.join(hole)}\nمیز: {board_text}\nدست فعلی: {shown_label}\nشانس تقریبی برد در شودان: {equity * 100:.0f}%\nاین فقط تخمین است، نه تضمین."
    return f"🃏 Your cards: {' '.join(hole)}\nBoard: {board_text}\nCurrent hand: {shown_label}\nEstimated showdown chance: {equity * 100:.0f}%\nThis is a rough estimate, not a guarantee."


async def _announce_result(bot, result, language):
    if not result.hand_complete or not result.summary:
        return
    heading = "🏆 Hand finished — winner" if language == "en" else "🏆 پایان دست — برنده"
    summary = result.summary
    if language == "fa":
        for english, persian in HAND_FA.items():
            summary = summary.replace(english, persian)
        summary = summary.replace("chips", "چیپ").replace("wins", "برنده شد:").replace("(everyone folded)", "(همه فولد کردند)")
    try:
        await bot.send_message(
            chat_id=(await sync_to_async(PokerTable.objects.only("chat_id").get)(pk=result.table_id)).chat_id,
            text=f"{heading}\n\n{summary}",
        )
    except Exception:
        pass


async def _notify_new_street(bot, hand_id, previous_phase, language):
    def load():
        hand = PokerHand.objects.select_related("table").get(pk=hand_id)
        player_ids = list(PokerSeat.objects.filter(table=hand.table, is_bot=False, folded=False).values_list("player_id", flat=True))
        return hand.phase, player_ids
    phase, player_ids = await sync_to_async(load, thread_sensitive=True)()
    if phase == previous_phase or phase == PokerHand.Phase.COMPLETE:
        return
    for player_id in player_ids:
        try:
            await bot.send_message(player_id, await _player_insight(hand_id, player_id, language))
        except Exception:
            pass


async def _table_state(table_id: int):
    def load():
        table = PokerTable.objects.get(pk=table_id)
        seats = list(table.seats.select_related("player").order_by("seat_number"))
        hand = table.hands.order_by("-number").first()
        return table, seats, hand
    return await sync_to_async(load, thread_sensitive=True)()


def _lobby_keyboard(table: PokerTable, language: str):
    join = "➕ Join table" if language == "en" else "➕ ورود به میز"
    start = "▶️ Deal hand" if language == "en" else "▶️ پخش کارت"
    cash = "💰 Cash out" if language == "en" else "💰 برداشت"
    add_bot = "🤖 Add bot" if language == "en" else "🤖 افزودن ربات"
    remove_bot = "➖ Remove bot" if language == "en" else "➖ حذف ربات"
    close = "❌ Close table" if language == "en" else "❌ بستن میز"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(join, callback_data=f"poker:join:{table.pk}")],
        [InlineKeyboardButton(add_bot, callback_data=f"poker:addbot:{table.pk}"), InlineKeyboardButton(remove_bot, callback_data=f"poker:removebot:{table.pk}")],
        [InlineKeyboardButton(start, callback_data=f"poker:start:{table.pk}"), InlineKeyboardButton(cash, callback_data=f"poker:cashout:{table.pk}")],
        [InlineKeyboardButton(close, callback_data=f"poker:close:{table.pk}")],
    ])


def _action_keyboard(hand: PokerHand, seat: PokerSeat, language: str):
    owed = max(0, hand.current_bet - seat.committed_round)
    rows = []
    if owed:
        rows.append([
            InlineKeyboardButton((f"Call {min(owed, seat.stack):,}" if language == "en" else f"کال {min(owed, seat.stack):,}"), callback_data=f"poker:act:{hand.pk}:call"),
            InlineKeyboardButton("Fold" if language == "en" else "فولد", callback_data=f"poker:act:{hand.pk}:fold"),
        ])
    else:
        rows.append([
            InlineKeyboardButton("Check" if language == "en" else "چک", callback_data=f"poker:act:{hand.pk}:check"),
            InlineKeyboardButton("Fold" if language == "en" else "فولد", callback_data=f"poker:act:{hand.pk}:fold"),
        ])
    min_target = hand.current_bet + hand.min_raise
    if seat.committed_round + seat.stack > hand.current_bet:
        half_pot_target = min(
            seat.committed_round + seat.stack,
            max(min_target, hand.current_bet + max(1, hand.pot // 2)),
        )
        rows.append([
            InlineKeyboardButton((f"Min raise to {min_target:,}" if language == "en" else f"ریز تا {min_target:,}"), callback_data=f"poker:act:{hand.pk}:raise:{min_target}"),
            InlineKeyboardButton((f"½ pot to {half_pot_target:,}" if language == "en" else f"نیم پات تا {half_pot_target:,}"), callback_data=f"poker:act:{hand.pk}:raise:{half_pot_target}"),
        ])
        rows.append([
            InlineKeyboardButton("Custom raise…" if language == "en" else "ریز دلخواه…", callback_data=f"poker:custom:{hand.pk}"),
            InlineKeyboardButton("All-in" if language == "en" else "آل‌این", callback_data=f"poker:act:{hand.pk}:allin"),
        ])
    return InlineKeyboardMarkup(rows)


def _render(table, seats, hand, language):
    title = _t("created", language)
    status_labels = {"lobby": "Lobby", "playing": "Hand in progress", "between": "Hand finished — table remains open", "closed": "Table closed"}
    if language == "fa":
        status_labels = {"lobby": "لابی", "playing": "دست در حال اجرا", "between": "دست تمام شد — میز هنوز باز است", "closed": "میز بسته شد"}
    lines = [title, f"Table #{table.pk} • {status_labels[table.status]}", f"Buy-in: {table.buy_in:,} • Small/Big blind: {table.small_blind:,}/{table.small_blind * 2:,}", ""]
    for seat in seats:
        flags = []
        if seat.seat_number == table.dealer_seat:
            flags.append("D")
        if seat.folded:
            flags.append("fold")
        if seat.all_in:
            flags.append("all-in")
        name = seat.bot_name if seat.is_bot else seat.player.name
        style = f" • {seat.bot_style}" if seat.is_bot else ""
        lines.append(f"{seat.seat_number}. {name}{style} — {seat.stack:,} " + (f"[{'/'.join(flags)}]" if flags else ""))
    if hand and hand.phase != PokerHand.Phase.COMPLETE:
        current_seat = next((seat for seat in seats if seat.seat_number == hand.current_seat), None)
        current = (current_seat.bot_name if current_seat and current_seat.is_bot else current_seat.player.name) if current_seat else "—"
        cards = "   ".join(f"[ {card} ]" for card in hand.community_cards) or "[  ?  ]"
        lines.extend(["", "━━━ COMMUNITY CARDS ━━━", cards, "━━━━━━━━━━━━━━━━━━━━━", f"Pot: {hand.pot:,} • Bet: {hand.current_bet:,}", f"Turn: {current}"])
    elif hand and hand.summary:
        cards = "   ".join(f"[ {card} ]" for card in hand.community_cards)
        lines.extend(["", "━━━ FINAL BOARD ━━━", cards, "━━━━━━━━━━━━━━━", f"Result:\n{hand.summary}"])
    return "\n".join(lines)


async def _refresh_table(bot, table_id: int, language: str):
    table, seats, hand = await _table_state(table_id)
    keyboard = (
        _lobby_keyboard(table, language)
        if table.status in {PokerTable.Status.LOBBY, PokerTable.Status.BETWEEN_HANDS}
        else None
    )
    if table.message_id:
        try:
            await bot.edit_message_text(chat_id=table.chat_id, message_id=table.message_id, text=_render(table, seats, hand, language), reply_markup=keyboard)
            return
        except Exception:
            pass
    message = await bot.send_message(chat_id=table.chat_id, text=_render(table, seats, hand, language), reply_markup=keyboard)
    table.message_id = message.message_id
    await sync_to_async(table.save)(update_fields=("message_id", "updated_at"))


async def _prompt_turn(bot, hand_id: int, language: str):
    def load():
        hand = PokerHand.objects.select_related("table").get(pk=hand_id)
        seat = PokerSeat.objects.select_related("player").get(table=hand.table, seat_number=hand.current_seat)
        return hand, seat
    hand, seat = await sync_to_async(load, thread_sensitive=True)()
    if seat.is_bot:
        asyncio.create_task(_bot_turn(bot, hand.pk, seat.pk, language))
        return
    await bot.send_message(
        chat_id=seat.player_id,
        text=(
            _t("turn", language, pot=hand.pot, bet=hand.current_bet, committed=seat.committed_round)
            + "\n\n" + await _player_insight(hand.pk, seat.player_id, language)
        ),
        reply_markup=_action_keyboard(hand, seat, language),
    )
    asyncio.create_task(_turn_timeout(bot, hand.pk, seat.player_id, hand.action_token, language))


async def _bot_turn(bot, hand_id, seat_id, language):
    await asyncio.sleep(random.SystemRandom().uniform(1.2, 3.2))
    previous_phase = await sync_to_async(PokerHand.objects.values_list("phase", flat=True).get)(pk=hand_id)
    try:
        result, action = await act_bot_async(hand_id, seat_id)
    except (PokerError, PokerSeat.DoesNotExist, PokerHand.DoesNotExist):
        return
    seat = await sync_to_async(PokerSeat.objects.filter(pk=seat_id).first)()
    name = seat.bot_name if seat else ("Poker bot" if language == "en" else "ربات پوکر")
    if language == "fa":
        action = action.replace("raise to", "ریز تا").replace("allin", "آل‌این").replace("call", "کال").replace("check", "چک").replace("fold", "فولد")
    try:
        await bot.send_message(
            chat_id=(await sync_to_async(PokerTable.objects.only("chat_id").get)(pk=result.table_id)).chat_id,
            text=(f"{name}: {action}" if language == "en" else f"{name}: {action}"),
        )
    except Exception:
        pass
    await _refresh_table(bot, result.table_id, language)
    await _announce_result(bot, result, language)
    if not result.hand_complete:
        await _notify_new_street(bot, result.hand_id, previous_phase, language)
        await _prompt_turn(bot, result.hand_id, language)


async def _turn_timeout(bot, hand_id, player_id, token, language):
    await asyncio.sleep(60)
    def state():
        hand = PokerHand.objects.select_related("table").get(pk=hand_id)
        seat = PokerSeat.objects.select_related("player").get(table=hand.table, player_id=player_id)
        move = "fold" if seat.consecutive_timeouts + 1 >= 2 or seat.committed_round != hand.current_bet else "check"
        return hand.table.chat_id, seat.player.name, move, hand.phase
    try:
        chat_id, name, move, previous_phase = await sync_to_async(state, thread_sensitive=True)()
    except (PokerHand.DoesNotExist, PokerSeat.DoesNotExist):
        return
    result = await timeout_action_async(hand_id, player_id, token)
    if result is None:
        return
    timeout_note = " (timed out)" if language == "en" else " (اتمام زمان)"
    try:
        await bot.send_message(chat_id, _human_action_text(name, move, None, language) + timeout_note)
    except Exception:
        pass
    await _refresh_table(bot, result.table_id, language)
    await _announce_result(bot, result, language)
    if not result.hand_complete:
        await _notify_new_street(bot, result.hand_id, previous_phase, language)
        await _prompt_turn(bot, result.hand_id, language)


def _human_action_text(name, move, amount, language):
    labels = {
        "en": {"fold": "folded", "check": "checked", "call": "called", "raise": "raised to", "allin": "went all-in for"},
        "fa": {"fold": "فولد کرد", "check": "چک کرد", "call": "کال کرد", "raise": "ریز کرد تا", "allin": "آل‌این کرد با"},
    }[language if language in {"en", "fa"} else "en"]
    suffix = f" {amount:,}" if amount is not None and move in {"call", "raise", "allin"} else ""
    return f"🃏 {name} {labels[move]}{suffix}."


async def _complete_human_action(bot, hand, user_id, move, amount, language):
    seat = await sync_to_async(
        PokerSeat.objects.select_related("player").get,
        thread_sensitive=True,
    )(table=hand.table, player_id=user_id)
    owed = max(0, hand.current_bet - seat.committed_round)
    shown_amount = amount
    if move == "call":
        shown_amount = min(owed, seat.stack)
    elif move == "allin":
        shown_amount = seat.committed_round + seat.stack
    result = await act_async(hand.pk, user_id, move, amount)
    try:
        await bot.send_message(
            chat_id=hand.table.chat_id,
            text=_human_action_text(seat.player.name, move, shown_amount, language),
        )
    except Exception:
        pass
    await _refresh_table(bot, result.table_id, language)
    await _announce_result(bot, result, language)
    if not result.hand_complete:
        await _notify_new_street(bot, result.hand_id, hand.phase, language)
        await _prompt_turn(bot, result.hand_id, language)
    return result


async def poker_command(update, context):
    language = await language_for_update(update)
    if update.effective_chat.type == ChatType.PRIVATE:
        await update.effective_message.reply_text(_t("private", language))
        return
    if not context.args:
        await update.effective_message.reply_text(_t("usage", language))
        return
    try:
        buy_in = int(context.args[0])
        blind = int(context.args[1]) if len(context.args) > 1 else max(1, buy_in // 50)
        table, _ = await create_table_async(update.effective_chat.id, update.effective_user.id, buy_in, blind)
    except (ValueError, PokerError, TableExists, BettingPaused, GroupTableBusy, Player.DoesNotExist) as exc:
        message = "یک بازی بلک‌جک در این گروه باز است. ابتدا آن را تمام یا لغو کنید." if language == "fa" and isinstance(exc, GroupTableBusy) else str(exc)
        await update.effective_message.reply_text(message)
        return
    message = await update.effective_message.reply_text(_render(table, list(await sync_to_async(list)(table.seats.select_related("player"))), None, language), reply_markup=_lobby_keyboard(table, language))
    table.message_id = message.message_id
    await sync_to_async(table.save)(update_fields=("message_id", "updated_at"))


async def poker_callback(update, context):
    query = update.callback_query
    language = await language_for_update(update)
    parts = query.data.split(":")
    action = parts[1]
    try:
        if action == "create":
            if query.message.chat.type == ChatType.PRIVATE:
                await query.answer(_t("private", language), show_alert=True)
                return
            table, _ = await create_table_async(
                query.message.chat.id, query.from_user.id, int(parts[2]), int(parts[3])
            )
            message = await context.bot.send_message(
                query.message.chat.id,
                _render(table, list(await sync_to_async(list)(table.seats.select_related("player"))), None, language),
                reply_markup=_lobby_keyboard(table, language),
            )
            table.message_id = message.message_id
            await sync_to_async(table.save)(update_fields=("message_id", "updated_at"))
            await query.answer()
        elif action == "join":
            table_id = int(parts[2])
            language = await sync_to_async(group_language)(
                (await sync_to_async(PokerTable.objects.only("chat_id").get)(pk=table_id)).chat_id
            )
            try:
                await context.bot.send_message(query.from_user.id, "🃏 Poker private messages are ready.")
            except Exception:
                await query.answer(_t("dm_required", language), show_alert=True)
                return
            await join_table_async(table_id, query.from_user.id)
            await query.answer("Seated!" if language == "en" else "وارد شدید!")
            await _refresh_table(context.bot, table_id, language)
        elif action == "addbot":
            table_id = int(parts[2])
            table = await sync_to_async(PokerTable.objects.only("chat_id").get)(pk=table_id)
            language = await sync_to_async(group_language)(table.chat_id)
            seat = await add_bot_async(table_id, query.from_user.id)
            await query.answer((f"Added {seat.bot_name}." if language == "en" else f"{seat.bot_name} اضافه شد."), show_alert=True)
            await _refresh_table(context.bot, table_id, language)
        elif action == "removebot":
            table_id = int(parts[2])
            table = await sync_to_async(PokerTable.objects.only("chat_id").get)(pk=table_id)
            language = await sync_to_async(group_language)(table.chat_id)
            amount = await remove_bot_async(table_id, query.from_user.id)
            await query.answer((f"Bot removed; {amount:,} chips returned to the casino." if language == "en" else f"ربات حذف شد؛ {amount:,} چیپ به کازینو برگشت."), show_alert=True)
            await _refresh_table(context.bot, table_id, language)
        elif action == "close":
            table_id = int(parts[2])
            table = await sync_to_async(PokerTable.objects.only("chat_id").get)(pk=table_id)
            language = await sync_to_async(group_language)(table.chat_id)
            refunds = await close_table_async(table_id, query.from_user.id)
            await query.answer((f"Table closed; {refunds} player stack(s) returned." if language == "en" else f"میز بسته شد؛ موجودی {refunds} بازیکن برگشت."), show_alert=True)
            await _refresh_table(context.bot, table_id, language)
        elif action in {"start", "next"}:
            table_id = int(parts[2])
            language = await sync_to_async(group_language)(
                (await sync_to_async(PokerTable.objects.only("chat_id").get)(pk=table_id)).chat_id
            )
            pending_table, pending_seats, _ = await _table_state(table_id)
            if pending_table.host_id != query.from_user.id:
                await query.answer("Only the table host can deal." if language == "en" else "فقط میزبان می‌تواند کارت پخش کند.", show_alert=True)
                return
            if len([seat for seat in pending_seats if seat.stack > 0]) < 2:
                await query.answer("At least two funded players are required." if language == "en" else "حداقل دو بازیکن دارای چیپ لازم است.", show_alert=True)
                return
            for pending_seat in pending_seats:
                if pending_seat.stack <= 0 or pending_seat.is_bot:
                    continue
                try:
                    await context.bot.send_message(
                        pending_seat.player_id,
                        "🃏 A poker hand is about to begin." if language == "en" else "🃏 یک دست پوکر در حال شروع است.",
                    )
                except Exception:
                    await query.answer(
                        (f"{pending_seat.player.name} must open the bot privately first." if language == "en" else f"{pending_seat.player.name} باید ابتدا ربات را خصوصی باز کند."),
                        show_alert=True,
                    )
                    return
            hand = await start_hand_async(table_id, query.from_user.id)
            table, seats, _ = await _table_state(table_id)
            for seat in seats:
                if seat.hole_cards and not seat.is_bot:
                    guide = (
                        "\n\nHand ranking: straight flush > four of a kind > full house > flush > straight > three of a kind > two pair > one pair > high card."
                        if language == "en" else
                        "\n\nرتبه دست‌ها: استریت فلاش > کاره > فول هاوس > فلاش > استریت > سه‌تایی > دو جفت > یک جفت > کارت بالا."
                    )
                    await context.bot.send_message(
                        seat.player_id,
                        await _player_insight(hand.pk, seat.player_id, language) + guide,
                    )
            await query.answer()
            await _refresh_table(context.bot, table_id, language)
            await _prompt_turn(context.bot, hand.pk, language)
        elif action == "cashout":
            table_id = int(parts[2])
            language = await sync_to_async(group_language)(
                (await sync_to_async(PokerTable.objects.only("chat_id").get)(pk=table_id)).chat_id
            )
            amount = await cash_out_async(table_id, query.from_user.id)
            await query.answer((f"Cashed out {amount:,} chips." if language == "en" else f"{amount:,} چیپ برداشت شد."), show_alert=True)
            await _refresh_table(context.bot, table_id, language)
        elif action == "custom":
            hand_id = int(parts[2])
            poker_hand = await sync_to_async(PokerHand.objects.select_related("table").get)(pk=hand_id)
            seat = await sync_to_async(PokerSeat.objects.get)(table=poker_hand.table, player_id=query.from_user.id)
            if poker_hand.current_seat != seat.seat_number:
                raise NotYourTurn("It is not your turn.")
            language = await sync_to_async(group_language)(poker_hand.table.chat_id)
            await query.answer()
            await context.bot.send_message(
                query.from_user.id,
                (f"Reply with your desired total bet for hand #{hand_id}.\nMinimum: {poker_hand.current_bet + poker_hand.min_raise:,}" if language == "en" else f"مبلغ کل شرط دلخواه برای دست #{hand_id} را پاسخ دهید.\nحداقل: {poker_hand.current_bet + poker_hand.min_raise:,}"),
                reply_markup=ForceReply(selective=True, input_field_placeholder="Total bet amount"),
            )
        elif action == "act":
            hand_id, move = int(parts[2]), parts[3]
            poker_hand = await sync_to_async(PokerHand.objects.select_related("table").get)(pk=hand_id)
            language = await sync_to_async(group_language)(poker_hand.table.chat_id)
            amount = int(parts[4]) if len(parts) > 4 else None
            result = await _complete_human_action(context.bot, poker_hand, query.from_user.id, move, amount, language)
            await query.answer()
            try:
                await query.edit_message_reply_markup(reply_markup=None)
            except Exception:
                pass
    except (ValueError, PokerError, InvalidAction, NotYourTurn, TableFull, BettingPaused, GroupTableBusy, Player.DoesNotExist, PokerTable.DoesNotExist, PokerSeat.DoesNotExist) as exc:
        message = "یک بازی بلک‌جک در این گروه باز است. ابتدا آن را تمام یا لغو کنید." if language == "fa" and isinstance(exc, GroupTableBusy) else str(exc)
        await query.answer(message, show_alert=True)


async def poker_raise_command(update, context):
    language = await language_for_update(update)
    if not context.args:
        await update.effective_message.reply_text("Usage: /pokerraise <total bet>")
        return
    def active():
        return PokerHand.objects.select_related("table").filter(
            table__seats__player_id=update.effective_user.id,
            current_seat__isnull=False,
        ).exclude(phase=PokerHand.Phase.COMPLETE).order_by("-created_at").first()
    hand = await sync_to_async(active, thread_sensitive=True)()
    if hand is None:
        await update.effective_message.reply_text("You have no active poker turn.")
        return
    language = await sync_to_async(group_language)(hand.table.chat_id)
    try:
        result = await _complete_human_action(context.bot, hand, update.effective_user.id, "raise", int(context.args[0]), language)
    except (ValueError, PokerError) as exc:
        await update.effective_message.reply_text(str(exc))
        return
    await update.effective_message.reply_text("Raise accepted.")


async def poker_custom_raise_text(update, context):
    reply = update.effective_message.reply_to_message
    if reply is None or not reply.from_user or not reply.from_user.is_bot or "#" not in (reply.text or ""):
        return
    raw = (update.effective_message.text or "").replace(",", "").strip()
    if not raw.isdigit():
        return
    # Load the latest hand and let the transactional action validator perform
    # the authoritative turn check.
    def latest():
        return PokerHand.objects.select_related("table").filter(
            table__seats__player_id=update.effective_user.id,
        ).exclude(phase=PokerHand.Phase.COMPLETE).order_by("-created_at").first()
    hand = await sync_to_async(latest, thread_sensitive=True)()
    if hand is None:
        return
    language = await sync_to_async(group_language)(hand.table.chat_id)
    try:
        await _complete_human_action(context.bot, hand, update.effective_user.id, "raise", int(raw), language)
    except (ValueError, PokerError) as exc:
        await update.effective_message.reply_text(str(exc))
        return
    await update.effective_message.reply_text("Raise accepted." if language == "en" else "ریز ثبت شد.")


async def resume_poker_tables(context):
    """Re-publish persisted active tables and restore the current turn timer."""
    tables = await sync_to_async(list)(
        PokerTable.objects.exclude(status=PokerTable.Status.CLOSED)
    )
    for table in tables:
        await normalize_bot_names_async(table.pk)
        language = await sync_to_async(group_language)(table.chat_id)
        await _refresh_table(context.bot, table.pk, language)
        hand = await sync_to_async(
            table.hands.exclude(phase=PokerHand.Phase.COMPLETE).order_by("-number").first
        )()
        if table.status != PokerTable.Status.PLAYING or hand is None:
            continue
        if hand.current_seat is not None:
            try:
                await _prompt_turn(context.bot, hand.pk, language)
            except Exception:
                # The table remains recoverable; a blocked DM must not abort startup.
                pass
