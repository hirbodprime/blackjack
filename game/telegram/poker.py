"""Texas Hold'em played on one live table message in the group.

Everything happens on that message: the player to act uses its buttons, cards
are peeked through a private pop-up, hands deal themselves, and players can sit
down or leave at any time.
"""

from __future__ import annotations

import asyncio
import random
from collections import deque
from html import escape

from asgiref.sync import sync_to_async
from telegram import InlineKeyboardButton as Btn, InlineKeyboardMarkup
from telegram.constants import ChatType, ParseMode
from telegram.error import BadRequest, TelegramError

from game.models import Player, PokerHand, PokerSeat, PokerTable
from game.services.achievements import grant_on_play_async
from game.services.language import group_language, language_for_update
from game.services.operations import BettingPaused
from game.services.poker import (
    HAND_NAMES, InvalidAction, NotYourTurn, PokerError, TableExists, TableFull,
    act_async, act_bot_async, add_bot_async, close_table_async, create_table_async,
    describe_visible_hand, estimate_bot_equity, evaluate_hand, join_table_async,
    leave_table_async, normalize_bot_names_async, remove_bot_async, start_hand_async,
    timeout_action_async,
)
from game.services.table_games import GroupTableBusy


TURN_SECONDS = 40
FIRST_DEAL_SECONDS = 12
NEXT_DEAL_SECONDS = 9
LOG_SIZE = 4
STAKES = ((500, 5), (2_000, 20), (10_000, 100), (50_000, 500))

_log: dict[int, deque] = {}
_deal_tasks: dict[int, asyncio.Task] = {}
_turn_tasks: dict[int, asyncio.Task] = {}
_pings: dict[int, int] = {}

TEXT = {
    "title": {"en": "♠️ TEXAS HOLD'EM", "fa": "♠️ پوکر تگزاس هولدم"},
    "blinds": {"en": "Table #{id} · Blinds {sb:,}/{bb:,} · Buy-in {buy:,}", "fa": "میز #{id} · بلایند {sb:,}/{bb:,} · ورودی {buy:,}"},
    "board": {"en": "Board", "fa": "میز"},
    "pot": {"en": "💰 Pot <b>{pot:,}</b>", "fa": "💰 پات <b>{pot:,}</b>"},
    "to_call": {"en": " · to call {owed:,}", "fa": " · کال {owed:,}"},
    "waiting": {"en": "Waiting for players — need 2 to deal.", "fa": "منتظر بازیکنان — برای شروع ۲ نفر لازم است."},
    "next_hand": {"en": "⏳ Next hand in a few seconds…", "fa": "⏳ دست بعدی تا چند ثانیه دیگر…"},
    "first_hand": {"en": "⏳ Dealing in a few seconds… sit down now!", "fa": "⏳ چند ثانیه تا پخش کارت… الان بنشین!"},
    "turn": {"en": "⏱ {name} to act ({secs}s)", "fa": "⏱ نوبت {name} ({secs} ثانیه)"},
    "folded": {"en": "folded", "fa": "فولد"},
    "allin": {"en": "ALL-IN", "fa": "آل‌این"},
    "sitting_out": {"en": "next hand", "fa": "دست بعد"},
    "leaving": {"en": "leaving", "fa": "در حال خروج"},
    "sit": {"en": "🪑 Sit ({buy:,})", "fa": "🪑 نشستن ({buy:,})"},
    "leave": {"en": "🚪 Leave", "fa": "🚪 خروج"},
    "cards": {"en": "👀 My cards", "fa": "👀 کارت‌های من"},
    "deal": {"en": "▶️ Deal now", "fa": "▶️ پخش کارت"},
    "add_bot": {"en": "🤖 Add bot", "fa": "🤖 افزودن ربات"},
    "rm_bot": {"en": "➖ Bot", "fa": "➖ ربات"},
    "close": {"en": "✖️ Close table", "fa": "✖️ بستن میز"},
    "fold": {"en": "✖ Fold", "fa": "✖ فولد"},
    "check": {"en": "✔ Check", "fa": "✔ چک"},
    "call": {"en": "📞 Call {n:,}", "fa": "📞 کال {n:,}"},
    "raise": {"en": "⬆ {n:,}", "fa": "⬆ {n:,}"},
    "pot_btn": {"en": "⬆ Pot {n:,}", "fa": "⬆ پات {n:,}"},
    "allin_btn": {"en": "💥 All-in", "fa": "💥 آل‌این"},
    "your_turn": {"en": "🔔 {mention}, your turn! You have {secs}s.", "fa": "🔔 {mention}، نوبت توست! {secs} ثانیه وقت داری."},
    "not_seated": {"en": "You're not at this table.", "fa": "شما پشت این میز نیستید."},
    "no_cards": {"en": "You have no cards this hand — wait for the next deal.", "fa": "در این دست کارتی ندارید — منتظر دست بعد باشید."},
    "pick_stakes": {"en": "♠️ Open a Hold'em table — choose the stakes:", "fa": "♠️ ساخت میز هولدم — مبلغ را انتخاب کنید:"},
    "private": {"en": "Poker is played in groups. Add me to a group and send /poker there.", "fa": "پوکر در گروه بازی می‌شود. من را به گروه اضافه کن و آنجا /poker بفرست."},
    "busy": {"en": "A blackjack game is open in this group. Finish it first.", "fa": "یک بازی بلک‌جک در این گروه باز است. ابتدا آن را تمام کنید."},
    "left_now": {"en": "You left with {n:,} chips.", "fa": "با {n:,} چیپ خارج شدید."},
    "left_later": {"en": "You'll be cashed out when this hand ends.", "fa": "پایان این دست تسویه می‌شوید."},
    "seated": {"en": "Seated! Good luck.", "fa": "نشستید! موفق باشید."},
    "result": {"en": "🏆 RESULT", "fa": "🏆 نتیجه"},
    "showdown": {"en": "Showdown", "fa": "رو کردن کارت‌ها"},
    "closed": {"en": "Table closed — all stacks returned.", "fa": "میز بسته شد — همه موجودی‌ها برگشت."},
}

ACTION_TEXT = {
    "en": {"fold": "folds", "check": "checks", "call": "calls", "raise": "raises to", "allin": "is ALL-IN", "timeout": "⏱"},
    "fa": {"fold": "فولد کرد", "check": "چک کرد", "call": "کال کرد", "raise": "ریز تا", "allin": "آل‌این کرد", "timeout": "⏱"},
}
HAND_FA = {
    "straight flush": "استریت فلاش", "four of a kind": "کاره", "full house": "فول هاوس",
    "flush": "فلاش", "straight": "استریت", "three of a kind": "سه‌تایی",
    "two pair": "دو جفت", "one pair": "یک جفت", "pair": "یک جفت", "high card": "کارت بالا",
}


def _t(key, lang, **values):
    entry = TEXT[key]
    return entry.get(lang, entry["en"]).format(**values)


def _card(card: str) -> str:
    rank = "10" if card[0] == "T" else card[0]
    return f"{rank}{card[1]}"


def _cards(cards) -> str:
    return " ".join(_card(c) for c in cards)


def _hand_name(name: str, lang: str) -> str:
    return HAND_FA.get(name, name) if lang == "fa" else name.title()


def _name(seat: PokerSeat) -> str:
    return seat.bot_name if seat.is_bot else seat.player.name


def _push_log(table_id: int, line: str) -> None:
    _log.setdefault(table_id, deque(maxlen=LOG_SIZE)).append(line)


def _cancel(tasks: dict, table_id: int) -> None:
    task = tasks.pop(table_id, None)
    if task and task is not asyncio.current_task():
        task.cancel()


# ── Rendering ───────────────────────────────────────────────────────────────

async def _state(table_id: int):
    def load():
        table = PokerTable.objects.get(pk=table_id)
        seats = list(table.seats.select_related("player").order_by("seat_number"))
        hand = table.hands.order_by("-number").first()
        return table, seats, hand
    return await sync_to_async(load, thread_sensitive=True)()


def render(table: PokerTable, seats, hand: PokerHand | None, lang: str) -> str:
    lines = [
        f"<b>{_t('title', lang)}</b>",
        _t("blinds", lang, id=table.pk, sb=table.small_blind, bb=table.small_blind * 2, buy=table.buy_in),
        "━━━━━━━━━━━━━━━",
    ]
    playing = hand is not None and hand.phase != PokerHand.Phase.COMPLETE and table.status == PokerTable.Status.PLAYING
    if hand is not None and (playing or table.status == PokerTable.Status.BETWEEN_HANDS):
        board = [_card(c) for c in hand.community_cards] + ["▢"] * (5 - len(hand.community_cards))
        lines.append(f"🂠 {_t('board', lang)}:  <b>{'  '.join(board)}</b>")
        pot_line = _t("pot", lang, pot=hand.pot)
        current = next((s for s in seats if playing and s.seat_number == hand.current_seat), None)
        if current is not None:
            owed = max(0, hand.current_bet - current.committed_round)
            if owed:
                pot_line += _t("to_call", lang, owed=min(owed, current.stack))
        lines.append(pot_line)
        lines.append("━━━━━━━━━━━━━━━")

    showdown = (
        hand is not None and hand.phase == PokerHand.Phase.COMPLETE
        and len([s for s in seats if s.hole_cards and not s.folded]) > 1
    )
    for seat in seats:
        marker = "▶️" if playing and seat.seat_number == hand.current_seat else "▫️"
        dealer = " Ⓓ" if seat.seat_number == table.dealer_seat and hand is not None else ""
        tags = []
        if playing and seat.committed_round:
            tags.append(f"bet {seat.committed_round:,}")
        if seat.all_in and seat.hole_cards:
            tags.append(f"<b>{_t('allin', lang)}</b>")
        elif seat.folded and playing:
            tags.append(_t("sitting_out", lang) if not seat.hole_cards else _t("folded", lang))
        if seat.leave_after_hand:
            tags.append(_t("leaving", lang))
        if showdown and seat.hole_cards and not seat.folded:
            best = HAND_NAMES[evaluate_hand(seat.hole_cards + hand.community_cards)[0]]
            tags.append(f"{_cards(seat.hole_cards)} · {_hand_name(best, lang)}")
        tag_text = f" · {' · '.join(tags)}" if tags else ""
        lines.append(f"{marker}{dealer} {escape(_name(seat))} — {seat.stack:,}{tag_text}")
    if not seats:
        lines.append(_t("waiting", lang))

    if _log.get(table.pk):
        lines.append("━━━━━━━━━━━━━━━")
        lines.extend(f"<i>{line}</i>" for line in _log[table.pk])

    if hand is not None and hand.phase == PokerHand.Phase.COMPLETE and hand.summary:
        lines += ["━━━━━━━━━━━━━━━", f"<b>{_t('result', lang)}</b>", escape(_localize_summary(hand.summary, lang))]
    if playing:
        current = next((s for s in seats if s.seat_number == hand.current_seat), None)
        if current is not None:
            lines.append(f"\n{_t('turn', lang, name=escape(_name(current)), secs=TURN_SECONDS)}")
    elif table.status != PokerTable.Status.CLOSED:
        funded = [s for s in seats if s.stack > 0]
        if len(funded) >= 2:
            lines.append("\n" + _t("next_hand" if hand else "first_hand", lang))
        else:
            lines.append("\n" + _t("waiting", lang))
    else:
        lines.append("\n" + _t("closed", lang))
    return "\n".join(lines)


def _localize_summary(summary: str, lang: str) -> str:
    if lang != "fa":
        return summary
    for english, persian in HAND_FA.items():
        summary = summary.replace(english, persian)
    return summary.replace("chips", "چیپ").replace("wins", "برد").replace("(everyone folded)", "(همه فولد کردند)").replace(" with ", " با ")


def keyboard(table: PokerTable, seats, hand: PokerHand | None, lang: str) -> InlineKeyboardMarkup | None:
    if table.status == PokerTable.Status.CLOSED:
        return None
    rows = []
    playing = table.status == PokerTable.Status.PLAYING and hand is not None and hand.phase != PokerHand.Phase.COMPLETE
    if playing:
        seat = next((s for s in seats if s.seat_number == hand.current_seat), None)
        rows.append([Btn(_t("cards", lang), callback_data=f"poker:cards:{table.pk}")])
        if seat is not None and not seat.is_bot:
            owed = max(0, hand.current_bet - seat.committed_round)
            top = seat.committed_round + seat.stack
            first = [Btn(_t("fold", lang), callback_data=f"poker:act:{hand.pk}:fold")]
            first.append(
                Btn(_t("call", lang, n=min(owed, seat.stack)), callback_data=f"poker:act:{hand.pk}:call")
                if owed else Btn(_t("check", lang), callback_data=f"poker:act:{hand.pk}:check")
            )
            rows.append(first)
            if top > hand.current_bet:
                min_target = hand.current_bet + hand.min_raise
                pot_target = hand.current_bet + hand.pot + owed
                raises = []
                if min_target < top:
                    raises.append(Btn(_t("raise", lang, n=min_target), callback_data=f"poker:act:{hand.pk}:raise:{min_target}"))
                if min_target < pot_target < top:
                    raises.append(Btn(_t("pot_btn", lang, n=pot_target), callback_data=f"poker:act:{hand.pk}:raise:{pot_target}"))
                raises.append(Btn(_t("allin_btn", lang), callback_data=f"poker:act:{hand.pk}:allin"))
                rows.append(raises)
        rows.append([
            Btn(_t("sit", lang, buy=table.buy_in), callback_data=f"poker:sit:{table.pk}"),
            Btn(_t("leave", lang), callback_data=f"poker:leave:{table.pk}"),
        ])
        return InlineKeyboardMarkup(rows)

    rows.append([
        Btn(_t("sit", lang, buy=table.buy_in), callback_data=f"poker:sit:{table.pk}"),
        Btn(_t("leave", lang), callback_data=f"poker:leave:{table.pk}"),
    ])
    rows.append([
        Btn(_t("deal", lang), callback_data=f"poker:deal:{table.pk}"),
        Btn(_t("add_bot", lang), callback_data=f"poker:addbot:{table.pk}"),
        Btn(_t("rm_bot", lang), callback_data=f"poker:rmbot:{table.pk}"),
    ])
    rows.append([Btn(_t("close", lang), callback_data=f"poker:close:{table.pk}")])
    return InlineKeyboardMarkup(rows)


async def refresh(bot, table_id: int, lang: str, *, repost: bool = False) -> None:
    table, seats, hand = await _state(table_id)
    text, markup = render(table, seats, hand, lang), keyboard(table, seats, hand, lang)
    if table.message_id and not repost:
        try:
            await bot.edit_message_text(
                chat_id=table.chat_id, message_id=table.message_id, text=text,
                reply_markup=markup, parse_mode=ParseMode.HTML,
            )
            return
        except BadRequest as exc:
            if "not modified" in str(exc).lower():
                return
        except TelegramError:
            pass
    old_id = table.message_id
    message = await bot.send_message(table.chat_id, text, reply_markup=markup, parse_mode=ParseMode.HTML)
    await sync_to_async(PokerTable.objects.filter(pk=table_id).update)(message_id=message.message_id)
    if old_id:
        try:
            await bot.delete_message(table.chat_id, old_id)
        except TelegramError:
            pass


# ── Game flow ───────────────────────────────────────────────────────────────

async def _clear_ping(bot, table: PokerTable) -> None:
    message_id = _pings.pop(table.pk, None)
    if message_id:
        try:
            await bot.delete_message(table.chat_id, message_id)
        except TelegramError:
            pass


async def _after_action(bot, table_id: int, result, lang: str) -> None:
    table, seats, hand = await _state(table_id)
    await _clear_ping(bot, table)
    if result.hand_complete:
        _cancel(_turn_tasks, table_id)
        await refresh(bot, table_id, lang)
        schedule_deal(bot, table_id, lang, NEXT_DEAL_SECONDS)
        return
    await refresh(bot, table_id, lang)
    await _prompt_turn(bot, table_id, lang)


async def _prompt_turn(bot, table_id: int, lang: str) -> None:
    table, seats, hand = await _state(table_id)
    if hand is None or hand.phase == PokerHand.Phase.COMPLETE or hand.current_seat is None:
        return
    seat = next((s for s in seats if s.seat_number == hand.current_seat), None)
    if seat is None:
        return
    _cancel(_turn_tasks, table_id)
    if seat.is_bot:
        _turn_tasks[table_id] = asyncio.create_task(_bot_turn(bot, table_id, hand.pk, seat.pk, lang))
        return
    mention = f'<a href="tg://user?id={seat.player_id}">{escape(seat.player.name)}</a>'
    try:
        ping = await bot.send_message(
            table.chat_id, _t("your_turn", lang, mention=mention, secs=TURN_SECONDS),
            parse_mode=ParseMode.HTML, reply_to_message_id=table.message_id,
        )
        _pings[table_id] = ping.message_id
    except TelegramError:
        pass
    _turn_tasks[table_id] = asyncio.create_task(
        _turn_timeout(bot, table_id, hand.pk, seat.player_id, hand.action_token, lang)
    )


async def _bot_turn(bot, table_id, hand_id, seat_id, lang):
    await asyncio.sleep(random.uniform(1.0, 2.4))
    try:
        result, action = await act_bot_async(hand_id, seat_id)
    except (PokerError, PokerSeat.DoesNotExist, PokerHand.DoesNotExist):
        return
    name = await sync_to_async(PokerSeat.objects.filter(pk=seat_id).values_list("bot_name", flat=True).first)()
    move, _, amount = action.partition(" to ")
    _push_log(table_id, _action_line(name or "🤖", move, int(amount.replace(",", "")) if amount else None, lang))
    await _after_action(bot, table_id, result, lang)


async def _turn_timeout(bot, table_id, hand_id, player_id, token, lang):
    await asyncio.sleep(TURN_SECONDS)
    result = await timeout_action_async(hand_id, player_id, token)
    if result is None:
        return
    name = await sync_to_async(Player.objects.filter(pk=player_id).values_list("name", flat=True).first)()
    _push_log(table_id, f"{ACTION_TEXT[lang if lang in ACTION_TEXT else 'en']['timeout']} {escape(name or '?')}")
    await _after_action(bot, table_id, result, lang)


def _action_line(name: str, move: str, amount: int | None, lang: str) -> str:
    words = ACTION_TEXT.get(lang, ACTION_TEXT["en"])
    suffix = f" {amount:,}" if amount and move in {"raise", "call"} else ""
    return f"{escape(name)} {words.get(move, move)}{suffix}"


def schedule_deal(bot, table_id: int, lang: str, delay: int) -> None:
    _cancel(_deal_tasks, table_id)
    _deal_tasks[table_id] = asyncio.create_task(_deal_later(bot, table_id, lang, delay))


async def _deal_later(bot, table_id: int, lang: str, delay: int) -> None:
    await asyncio.sleep(delay)
    await _deal(bot, table_id, lang, actor_id=None)


async def _deal(bot, table_id: int, lang: str, actor_id: int | None) -> None:
    _cancel(_deal_tasks, table_id)
    table, seats, _ = await _state(table_id)
    if table.status in {PokerTable.Status.CLOSED, PokerTable.Status.PLAYING}:
        return
    if len([s for s in seats if s.stack > 0]) < 2 or not any(not s.is_bot for s in seats):
        await refresh(bot, table_id, lang)
        return
    await start_hand_async(table_id, actor_id)
    _log[table_id] = deque(maxlen=LOG_SIZE)
    await refresh(bot, table_id, lang, repost=True)
    await _prompt_turn(bot, table_id, lang)


# ── Commands & callbacks ────────────────────────────────────────────────────

def _stakes_keyboard():
    return InlineKeyboardMarkup([
        [Btn(f"🪙 {buy:,} · {sb:,}/{sb * 2:,}", callback_data=f"poker:create:{buy}:{sb}")]
        for buy, sb in STAKES
    ])


async def poker_command(update, context):
    lang = await language_for_update(update)
    if update.effective_chat.type == ChatType.PRIVATE:
        await update.effective_message.reply_text(_t("private", lang))
        return
    if context.args:
        try:
            buy_in = int(context.args[0])
            blind = int(context.args[1]) if len(context.args) > 1 else max(1, buy_in // 100)
        except ValueError:
            await update.effective_message.reply_text("/poker <buy-in> [small blind]")
            return
        await _create(context.bot, update.effective_chat.id, update.effective_user.id, buy_in, blind, lang,
                      reply=update.effective_message.reply_text)
        return
    await update.effective_message.reply_text(_t("pick_stakes", lang), reply_markup=_stakes_keyboard())


async def _create(bot, chat_id, user_id, buy_in, blind, lang, *, reply):
    try:
        table, _ = await create_table_async(chat_id, user_id, buy_in, blind)
    except GroupTableBusy:
        await reply(_t("busy", lang))
        return False
    except (PokerError, TableExists, BettingPaused, Player.DoesNotExist) as exc:
        await reply(str(exc) or "Start the bot first with /start.")
        return False
    _log[table.pk] = deque(maxlen=LOG_SIZE)
    await refresh(bot, table.pk, lang, repost=True)
    return True


async def _table_lang(table_id: int) -> str:
    chat_id = await sync_to_async(PokerTable.objects.filter(pk=table_id).values_list("chat_id", flat=True).get)()
    return await sync_to_async(group_language)(chat_id)


async def _peek(query, table_id: int, lang: str) -> None:
    def calculate():
        seat = PokerSeat.objects.filter(table_id=table_id, player_id=query.from_user.id).first()
        if seat is None:
            return None
        hand = PokerHand.objects.filter(table_id=table_id).order_by("-number").first()
        if hand is None or not seat.hole_cards:
            return ""
        seats = list(PokerSeat.objects.filter(table_id=table_id))
        label = describe_visible_hand(seat.hole_cards, hand.community_cards)
        equity = None
        if hand.phase != PokerHand.Phase.COMPLETE and not seat.folded:
            equity = estimate_bot_equity(seat, hand, seats, samples=200)
        return seat.hole_cards, label, equity
    data = await sync_to_async(calculate, thread_sensitive=True)()
    if data is None:
        await query.answer(_t("not_seated", lang), show_alert=True)
        return
    if not data:
        await query.answer(_t("no_cards", lang), show_alert=True)
        return
    cards, label, equity = data
    text = f"🂡 {_cards(cards)}\n{_hand_name(label, lang)}"
    if equity is not None:
        text += f"\n📊 ~{equity * 100:.0f}% " + ("شانس برد" if lang == "fa" else "to win")
    await query.answer(text, show_alert=True)


async def poker_callback(update, context):
    query = update.callback_query
    parts = query.data.split(":")
    action = parts[1]
    lang = await language_for_update(update)
    bot = context.bot
    try:
        if action == "create":
            if query.message.chat.type == ChatType.PRIVATE:
                await query.answer(_t("private", lang), show_alert=True)
                return
            async def reply(text):
                await query.answer(text[:200], show_alert=True)
            created = await _create(
                bot, query.message.chat.id, query.from_user.id, int(parts[2]), int(parts[3]), lang, reply=reply
            )
            if created:
                await query.answer()
                try:
                    await query.message.delete()
                except TelegramError:
                    pass
            return

        if action == "act":
            hand_id, move = int(parts[2]), parts[3]
            amount = int(parts[4]) if len(parts) > 4 else None
            hand = await sync_to_async(PokerHand.objects.select_related("table").get)(pk=hand_id)
            lang = await sync_to_async(group_language)(hand.table.chat_id)
            seat = await sync_to_async(
                PokerSeat.objects.select_related("player").filter(table=hand.table, player_id=query.from_user.id).first
            )()
            shown = amount
            if seat and move == "call":
                shown = min(hand.current_bet - seat.committed_round, seat.stack)
            result = await act_async(hand_id, query.from_user.id, move, amount)
            await query.answer()
            _cancel(_turn_tasks, hand.table_id)
            _push_log(hand.table_id, _action_line(seat.player.name, move, shown, lang))
            await _after_action(bot, hand.table_id, result, lang)
            return

        table_id = int(parts[2])
        lang = await _table_lang(table_id)
        if action == "cards":
            await _peek(query, table_id, lang)
        elif action == "sit":
            await join_table_async(table_id, query.from_user.id)
            await query.answer(_t("seated", lang))
            from bot_sections.players_and_progression import announce_badges

            await announce_badges(query.from_user.id, await grant_on_play_async(query.from_user.id), context)
            name = await sync_to_async(Player.objects.filter(pk=query.from_user.id).values_list("name", flat=True).first)()
            _push_log(table_id, f"🪑 {escape(name or '')}")
            await refresh(bot, table_id, lang)
            await _maybe_autodeal(bot, table_id, lang)
        elif action == "leave":
            amount = await leave_table_async(table_id, query.from_user.id)
            await query.answer(
                _t("left_later", lang) if amount is None else _t("left_now", lang, n=amount), show_alert=True
            )
            await _fold_if_their_turn(bot, table_id, query.from_user.id, lang)
            await refresh(bot, table_id, lang)
        elif action == "deal":
            await query.answer()
            await _deal(bot, table_id, lang, actor_id=query.from_user.id)
        elif action == "addbot":
            seat = await add_bot_async(table_id, query.from_user.id)
            await query.answer(seat.bot_name)
            _push_log(table_id, f"🪑 {escape(seat.bot_name)}")
            await refresh(bot, table_id, lang)
            await _maybe_autodeal(bot, table_id, lang)
        elif action == "rmbot":
            await remove_bot_async(table_id, query.from_user.id)
            await query.answer()
            await refresh(bot, table_id, lang)
        elif action == "close":
            await close_table_async(table_id, query.from_user.id)
            _cancel(_deal_tasks, table_id)
            await query.answer(_t("closed", lang), show_alert=True)
            await refresh(bot, table_id, lang)
        else:
            await query.answer()
    except GroupTableBusy:
        await query.answer(_t("busy", lang), show_alert=True)
    except (ValueError, PokerError, InvalidAction, NotYourTurn, TableFull, BettingPaused,
            Player.DoesNotExist, PokerTable.DoesNotExist, PokerSeat.DoesNotExist, PokerHand.DoesNotExist) as exc:
        message = str(exc) or ("Start the bot first with /start." if isinstance(exc, Player.DoesNotExist) else "⚠️")
        await query.answer(message[:200], show_alert=True)


async def _maybe_autodeal(bot, table_id: int, lang: str) -> None:
    table, seats, hand = await _state(table_id)
    if table.status == PokerTable.Status.PLAYING or table_id in _deal_tasks:
        return
    if len([s for s in seats if s.stack > 0]) >= 2:
        schedule_deal(bot, table_id, lang, FIRST_DEAL_SECONDS if hand is None else NEXT_DEAL_SECONDS)


async def _fold_if_their_turn(bot, table_id: int, player_id: int, lang: str) -> None:
    table, seats, hand = await _state(table_id)
    if hand is None or hand.phase == PokerHand.Phase.COMPLETE:
        return
    seat = next((s for s in seats if s.player_id == player_id), None)
    if seat is None or seat.seat_number != hand.current_seat:
        return
    _cancel(_turn_tasks, table_id)
    result = await act_async(hand.pk, player_id, "fold")
    _push_log(table_id, _action_line(seat.player.name, "fold", None, lang))
    await _after_action(bot, table_id, result, lang)


async def poker_raise_command(update, context):
    """/pokerraise <total> — raise to an exact amount when it's your turn."""
    if not context.args or not context.args[0].replace(",", "").isdigit():
        await update.effective_message.reply_text("Usage: /pokerraise <total bet>")
        return
    def active():
        return PokerHand.objects.select_related("table").filter(
            table__chat_id=update.effective_chat.id, table__seats__player_id=update.effective_user.id,
        ).exclude(phase=PokerHand.Phase.COMPLETE).order_by("-created_at").first()
    hand = await sync_to_async(active, thread_sensitive=True)()
    if hand is None:
        await update.effective_message.reply_text("You have no active poker turn here.")
        return
    lang = await sync_to_async(group_language)(hand.table.chat_id)
    amount = int(context.args[0].replace(",", ""))
    try:
        result = await act_async(hand.pk, update.effective_user.id, "raise", amount)
    except PokerError as exc:
        await update.effective_message.reply_text(str(exc))
        return
    _cancel(_turn_tasks, hand.table_id)
    _push_log(hand.table_id, _action_line(update.effective_user.first_name, "raise", amount, lang))
    try:
        await update.effective_message.delete()
    except TelegramError:
        pass
    await _after_action(context.bot, hand.table_id, result, lang)


async def resume_poker_tables(context):
    """Re-post open tables after a restart and pick the game back up."""
    tables = await sync_to_async(list)(PokerTable.objects.exclude(status=PokerTable.Status.CLOSED))
    for table in tables:
        await normalize_bot_names_async(table.pk)
        lang = await sync_to_async(group_language)(table.chat_id)
        try:
            await refresh(context.bot, table.pk, lang, repost=True)
            if table.status == PokerTable.Status.PLAYING:
                await _prompt_turn(context.bot, table.pk, lang)
            else:
                await _maybe_autodeal(context.bot, table.pk, lang)
        except TelegramError:
            # A group that removed the bot must not abort startup.
            pass
