"""Season 1 home screen and its sections: dashboard, play, daily, compete, stable claim."""

from dataclasses import dataclass
from html import escape

from asgiref.sync import sync_to_async
from django.utils import timezone
from django.conf import settings
from telegram import InlineKeyboardButton as Btn, InlineKeyboardMarkup, WebAppInfo
from telegram.constants import ChatType, ParseMode
from telegram.error import BadRequest

from game.economy_config import (
    SEASON_PRIZES, STARTER_HORSE_POWERUP_USES, TOURNAMENT_PRIZE_POOL, WEEKLY_PRIZES,
    tournament_prizes,
)
from game.i18n import pick, translate
from game.services.achievements import localized, rarity_label, rarity_map, showcase, showcase_many
from game.models import Achievement, Player, PlayerAchievement, Season, Tournament, UserSettings
from game.services import arcade, competitions, seasons
from game.services.challenges import DIFFICULTY_ICON, quest_text, todays_board
from game.services.horses import (
    InvalidStarterChoice, StarterAlreadyClaimed, claim_starter_horse_async,
    clean_horse_name, starter_horse_for, starter_powerup_offers_async,
)
from game.services.language import language_for_update
from game.services.ranks import level_line, progress_bar, rank_label


MAIN_GROUP_URL = "https://t.me/+JLQINcmYLZg3NDM0"
MEDALS = ("🥇", "🥈", "🥉")


def _rank_icon(position: int) -> str:
    return MEDALS[position - 1] if position <= len(MEDALS) else f"{position}."


def _duration(delta) -> str:
    minutes = max(0, int(delta.total_seconds() // 60))
    days, minutes = divmod(minutes, 1440)
    hours, minutes = divmod(minutes, 60)
    if days:
        return f"{days}d {hours}h"
    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


def _fmt(n: int) -> str:
    return f"{n:,}"


# ── Dashboard ───────────────────────────────────────────────────────────────

@dataclass
class Dashboard:
    player: Player
    settings: UserSettings
    daily_done: int
    daily_total: int
    season: Season | None
    season_position: tuple[int, int] | None
    live: Tournament | None
    upcoming: Tournament | None
    has_starter: bool
    badges: str = ""


def load_dashboard(user_id: int) -> Dashboard | None:
    player = Player.objects.filter(pk=user_id).first()
    if player is None:
        return None
    settings, _ = UserSettings.objects.get_or_create(player=player)
    board = todays_board(user_id)
    season = seasons.active_season()
    return Dashboard(
        player=player,
        settings=settings,
        daily_done=sum(1 for _, _, done in board if done),
        daily_total=len(board),
        season=season,
        season_position=seasons.player_position(season, user_id) if season else None,
        live=competitions.live_tournament() if season else None,
        upcoming=competitions.next_tournament() if season else None,
        has_starter=starter_horse_for(user_id) is not None,
        badges=showcase(user_id),
    )


load_dashboard_async = sync_to_async(load_dashboard, thread_sensitive=True)


def render_home(d: Dashboard, lang: str):
    now = timezone.now()
    p = d.player
    lines = [f"<b>{translate('s1.brand', lang)}</b>"]
    if d.season:
        lines.append(translate(
            "s1.season", lang, number=d.season.number, name=escape(d.season.name),
            days=max(0, (d.season.ends_at - now).days),
        ))
    lines.append("━━━━━━━━━━━━━━━")
    title = f" · {escape(p.title)}" if p.title else ""
    badges = f" {d.badges}" if d.badges else ""
    lines.append(f"👤 <b>{escape(p.name)}</b>{badges}{title} · {rank_label(p.level, lang)}")
    lines.append(translate("s1.chips", lang, chips=_fmt(p.chips)))
    lines.append(f"⭐ {level_line(p.level, p.xp, lang)}")
    lines.append(translate("s1.streak", lang, streak=p.daily_streak, done=d.daily_done, total=d.daily_total))
    if d.season_position:
        rank, points = d.season_position
        lines.append(translate("s1.season_pos", lang, rank=rank, points=_fmt(points)))
    if d.live:
        lines.append(translate("s1.live", lang, title=escape(d.live.title), left=_duration(d.live.ends_at - now)))
    elif d.upcoming:
        lines.append(translate("s1.next", lang, title=escape(d.upcoming.title), left=_duration(d.upcoming.starts_at - now)))

    rows = []
    if not d.has_starter:
        rows.append([Btn(translate("s1.btn_claim_horse", lang), callback_data="hub:claim")])
    rows += [
        [Btn(translate("s1.btn_play", lang), callback_data="hub:play"),
         Btn(translate("s1.btn_daily", lang), callback_data="hub:daily")],
        [Btn(translate("s1.btn_compete", lang), callback_data="hub:compete"),
         Btn(translate("s1.btn_stable", lang), callback_data="menu:mainhorse")],
        [Btn(translate("s1.btn_shop", lang), callback_data="store:home"),
         Btn(translate("s1.btn_bag", lang), callback_data="store:bag")],
        [Btn(translate("s1.btn_profile", lang), callback_data="hub:profile"),
         Btn(translate("s1.btn_friends", lang), callback_data="play:social")],
        [Btn(translate("s1.btn_settings", lang), callback_data="play:settings"),
         Btn(translate("s1.btn_help", lang), callback_data="play:help")],
    ]
    return "\n".join(lines), InlineKeyboardMarkup(rows)


def _home_row(lang: str, back: str | None = None):
    row = []
    if back:
        row.append(Btn(translate("play.back", lang), callback_data=back))
    row.append(Btn(translate("s1.btn_home", lang), callback_data="hub:home"))
    return row


# ── Sections ────────────────────────────────────────────────────────────────

def arcade_group_url(bot_username: str, chat_id: int) -> str:
    # Main Mini App link: opens over the group chat and ties play to that group's ranking.
    return f"https://t.me/{bot_username}?startapp={arcade.group_start_param(chat_id)}"


def arcade_button(private: bool, bot_username: str, chat_id: int | None = None) -> Btn:
    """web_app buttons only work in private chats; groups get a Main Mini App link instead."""
    if private:
        return Btn("🕹 Arcade · Crash · Mines · Hi-Lo", web_app=WebAppInfo(f"{settings.CASINO_PUBLIC_URL}/casino/arcade/"))
    return Btn("🕹 Arcade · Crash · Mines · Hi-Lo", url=arcade_group_url(bot_username, chat_id))


def render_play(lang: str, bot_username: str, private: bool = True, chat_id: int | None = None):
    rows = [
        [arcade_button(private, bot_username, chat_id)],
        [Btn(translate("play.blackjack", lang), callback_data="play:blackjack"),
         Btn(pick(lang, "♠️ Poker", "♠️ پوکر"), callback_data="play:poker")],
        [Btn(translate("play.horses", lang), callback_data="play:horses"),
         Btn(translate("play.minigames", lang), callback_data="play:minigames")],
        [Btn(translate("s1.btn_add_group", lang), url=f"https://t.me/{bot_username}?startgroup=play")],
        [Btn(pick(lang, "👥 Main group", "👥 گروه اصلی"), url=MAIN_GROUP_URL)],
        _home_row(lang),
    ]
    return translate("s1.play_title", lang), InlineKeyboardMarkup(rows)


def render_daily(user_id: int, lang: str):
    player = Player.objects.get(pk=user_id)
    lines = [f"<b>{translate('s1.daily_title', lang)}</b>"]
    for quest, progress, done in todays_board(user_id):
        shown = min(progress, quest.target)
        state = "✅" if done else DIFFICULTY_ICON.get(quest.difficulty, "▫️")
        lines.append(
            f"\n{state} <b>{escape(quest_text(quest, lang))}</b>\n"
            f"   {progress_bar(shown, quest.target, 8)} {shown}/{quest.target}\n"
            f"   🎁 {_fmt(quest.reward_chips)} {pick(lang, 'chips', 'چیپ')} · {quest.reward_xp} XP"
        )
    lines.append("\n" + translate(
        "s1.daily_footer", lang, streak=player.daily_streak, best=player.best_daily_streak
    ))
    rows = [
        [Btn(translate("s1.btn_bonus", lang), callback_data="quests:daily_rewards"),
         Btn(translate("s1.btn_missions", lang), callback_data="play:weekly")],
        _home_row(lang),
    ]
    return "\n".join(lines), InlineKeyboardMarkup(rows)


def _board_lines(rows, user_id: int, lang: str, unit: str, prizes=()) -> list[str]:
    if not rows:
        return [translate("s1.empty_board", lang)]
    icons = showcase_many([player_id for player_id, _, _ in rows])
    lines = []
    for position, (player_id, name, score) in enumerate(rows, start=1):
        prize = f" · 🎁 {_fmt(prizes[position - 1])}" if position <= len(prizes) else ""
        me = " ◀️" if player_id == user_id else ""
        badge = f" {icons[player_id]}" if icons.get(player_id) else ""
        lines.append(f"{_rank_icon(position)} {escape(name)}{badge} — <b>{_fmt(score)}</b> {unit}{prize}{me}")
    return lines


def _compete_keyboard(lang: str):
    return InlineKeyboardMarkup([
        [Btn(translate("s1.btn_season", lang), callback_data="hub:season"),
         Btn(translate("s1.btn_weekly", lang), callback_data="hub:weekly")],
        [Btn(translate("s1.btn_tournament", lang), callback_data="hub:tournament"),
         Btn(pick(lang, "🌍 All-time", "🌍 همه‌دوران"), callback_data="menu:leaderboards")],
        _home_row(lang),
    ])


def render_compete(lang: str):
    text = translate("s1.compete_title", lang, pool=_fmt(TOURNAMENT_PRIZE_POOL))
    return f"<b>{text.splitlines()[0]}</b>\n" + "\n".join(text.splitlines()[1:]), _compete_keyboard(lang)


def render_season(user_id: int, lang: str):
    season = seasons.active_season()
    if season is None:
        return translate("s1.no_season", lang), _compete_keyboard(lang)
    rows = [
        (r.player_id, f"{r.player.name} · {r.player.title}" if r.player.title else r.player.name, r.points)
        for r in seasons.standings(season, 10)
    ]
    pts = pick(lang, "pts", "امتیاز")
    lines = [
        pick(lang, f"<b>🌟 SEASON {season.number} · {escape(season.name).upper()}</b>",
             f"<b>🌟 فصل {season.number} · {escape(season.name)}</b>"),
        f"⏳ {_duration(season.ends_at - timezone.now())} {pick(lang, 'left', 'مانده')}",
        "━━━━━━━━━━━━━━━",
        *_board_lines(rows, user_id, lang, pts, SEASON_PRIZES),
    ]
    mine = seasons.player_position(season, user_id)
    if mine and mine[0] > 10:
        lines.append(f"\n{translate('s1.you', lang)}: #{mine[0]} · {_fmt(mine[1])} {pts}")
    lines.append(pick(lang, "\n<i>Season points = XP earned this season.</i>", "\n<i>امتیاز فصل = XP کسب‌شده در این فصل.</i>"))
    return "\n".join(lines), _compete_keyboard(lang)


def render_weekly(user_id: int, lang: str):
    start, end = competitions.week_bounds()
    season = seasons.active_season()
    window_start = max(start, season.starts_at) if season else start
    rows = [(r.player_id, r.name, r.score) for r in competitions.leaderboard(window_start, end, limit=10)]
    mine = competitions.player_score(user_id, window_start, end)
    lines = [
        pick(lang, "<b>📈 THIS WEEK</b>", "<b>📈 این هفته</b>"),
        f"⏳ {pick(lang, 'resets in', 'ریست تا')} {_duration(end - timezone.now())}",
        "━━━━━━━━━━━━━━━",
        *_board_lines(rows, user_id, lang, "", WEEKLY_PRIZES),
        f"\n{translate('s1.you', lang)}: <b>{mine:+,}</b>",
        pick(lang, "\n<i>Score = net winnings across all games.</i>", "\n<i>امتیاز = سود خالص در همه بازی‌ها.</i>"),
    ]
    return "\n".join(lines), _compete_keyboard(lang)


KIND_FA = {"blackjack": "بلک‌جک", "horses": "مسابقه اسب", "minigames": "مینی‌گیم‌ها", "poker": "پوکر", "all": "همه بازی‌ها"}


def _tournament_title(tournament: Tournament, lang: str) -> str:
    if lang != "fa":
        return tournament.title
    return f"{competitions.KIND_EMOJI[tournament.kind]} تورنمنت {KIND_FA[tournament.kind]}"


def render_tournament(user_id: int, lang: str):
    now = timezone.now()
    tournament = competitions.live_tournament(now)
    if tournament is None:
        upcoming = competitions.next_tournament(now)
        if upcoming is None:
            return translate("s1.empty_board", lang), _compete_keyboard(lang)
        prizes = " / ".join(_fmt(p) for p in tournament_prizes(upcoming.prize_pool))
        kind = KIND_FA[upcoming.kind] if lang == "fa" else Tournament.Kind(upcoming.kind).label.lower()
        text = (
            f"<b>⚔️ {escape(_tournament_title(upcoming, lang))}</b>\n"
            f"⏳ {pick(lang, 'starts in', 'شروع تا')} {_duration(upcoming.starts_at - now)} · "
            f"{pick(lang, 'lasts', 'مدت')} {_duration(upcoming.ends_at - upcoming.starts_at)}\n━━━━━━━━━━━━━━━\n"
            f"🎁 {pick(lang, 'Prizes', 'جوایز')}: {prizes}\n\n<i>"
            + pick(lang, f"Just play — your net winnings in {kind} during the window are your score.",
                   f"فقط بازی کن — سود خالص تو در {kind} در این بازه امتیازت است.")
            + "</i>"
        )
        return text, _compete_keyboard(lang)
    prizes = tournament_prizes(tournament.prize_pool)
    rows = [(r.player_id, r.name, r.score) for r in competitions.tournament_standings(tournament, 10)]
    mine = competitions.player_score(user_id, tournament.starts_at, tournament.ends_at, tournament.kind)
    lines = [
        f"<b>🔴 {pick(lang, 'LIVE', 'زنده')} · {escape(_tournament_title(tournament, lang))}</b>",
        f"⏳ {pick(lang, 'ends in', 'پایان تا')} {_duration(tournament.ends_at - now)}",
        "━━━━━━━━━━━━━━━",
        *_board_lines(rows, user_id, lang, "", prizes),
        f"\n{translate('s1.you', lang)}: <b>{mine:+,}</b>",
    ]
    return "\n".join(lines), _compete_keyboard(lang)


def render_profile(user_id: int, lang: str):
    from game.models import Stats

    p = Player.objects.get(pk=user_id)
    stats = Stats.objects.filter(player=p).first()
    shares = rarity_map()
    owned = list(PlayerAchievement.objects.filter(player=p).select_related("achievement"))
    owned.sort(key=lambda pa: shares.get(pa.achievement_id, 1))
    total = Achievement.objects.count()
    horse = starter_horse_for(user_id)
    season = seasons.active_season()
    position = seasons.player_position(season, user_id) if season else None
    lines = [
        f"<b>👤 {escape(p.name)}</b>" + (f" · {escape(p.title)}" if p.title else ""),
        "━━━━━━━━━━━━━━━",
        rank_label(p.level, lang),
        f"⭐ {level_line(p.level, p.xp, lang)}",
        f"💰 {_fmt(p.chips)} {pick(lang, 'chips', 'چیپ')}",
    ]
    if position:
        lines.append(f"🏁 {pick(lang, 'Season', 'فصل')} #{position[0]} · {_fmt(position[1])} {pick(lang, 'pts', 'امتیاز')}")
    lines.append(f"🔥 {pick(lang, 'Streak', 'زنجیره')} {p.daily_streak} ({pick(lang, 'best', 'بهترین')} {p.best_daily_streak})")
    if stats:
        played = stats.wins + stats.loses
        rate = f"{100 * stats.wins // played}%" if played else "—"
        lines.append(f"🃏 {stats.wins}W / {stats.loses}L · {rate} · {stats.how_many_21}× 21")
    if horse:
        lines.append(f"🐎 {escape(horse.name or '')} (#{horse.horse_number})")
    lines.append(f"\n<b>🏅 {pick(lang, 'BADGES', 'نشان‌ها')} {len(owned)}/{total}</b>")
    if owned:
        for pa in owned[:6]:
            name, _ = localized(pa.achievement, lang)
            lines.append(f"{pa.achievement.icon or '🏅'} {escape(name)} · {rarity_label(shares.get(pa.achievement_id, 1), lang)}")
        if len(owned) > 6:
            lines.append(pick(lang, f"…and {len(owned) - 6} more", f"…و {len(owned) - 6} نشان دیگر"))
    else:
        lines.append(pick(lang, "Play any game to start earning badges!", "برای گرفتن نشان، هر بازی‌ای را شروع کن!"))
    rows = [
        [Btn(translate("s1.btn_achievements", lang), callback_data="hub:ach"),
         Btn(translate("s1.btn_history", lang), callback_data="play:history")],
        [Btn(pick(lang, "📊 Stats", "📊 آمار"), callback_data="profile:stats"),
         Btn(pick(lang, "🐎 My races", "🐎 مسابقه‌های من"), callback_data="profile:myraces")],
        _home_row(lang),
    ]
    return "\n".join(lines), InlineKeyboardMarkup(rows)


CATEGORY_FA = {
    "blackjack": "بلک‌جک", "horses": "اسب‌ها", "minigames": "مینی‌گیم", "progress": "پیشرفت",
    "competition": "رقابت", "social": "اجتماعی", "legacy": "افتخارات",
}


def render_achievements(user_id: int, lang: str, category: str | None):
    categories = Achievement.Category
    category = category if category in categories.values else categories.PROGRESS
    shares = rarity_map()
    unlocked = set(PlayerAchievement.objects.filter(player_id=user_id).values_list("achievement_id", flat=True))
    label = CATEGORY_FA[category] if lang == "fa" else categories(category).label.upper()
    lines = [f"<b>🏅 {pick(lang, 'BADGES', 'نشان‌ها')} · {label}</b>", "━━━━━━━━━━━━━━━"]
    for a in Achievement.objects.filter(category=category).order_by("reward_chips", "pk"):
        have = a.pk in unlocked
        if a.hidden and not have:
            lines.append(pick(lang, "❔ <i>Hidden badge</i>", "❔ <i>نشان مخفی</i>"))
            continue
        name, description = localized(a, lang)
        reward = f" · 🎁 {_fmt(a.reward_chips)}" if a.reward_chips else ""
        mark = "✅" if have else "▫️"
        rarity = rarity_label(shares.get(a.pk, 0), lang)
        lines.append(f"{mark} {a.icon or '🏅'} <b>{escape(name)}</b> · {rarity}\n     {escape(description)}{reward}")
    tabs = [
        Btn(("• " if c == category else "") + (CATEGORY_FA[c] if lang == "fa" else categories(c).label),
            callback_data=f"hub:ach:{c}")
        for c in categories.values
    ]
    rows = [tabs[i:i + 3] for i in range(0, len(tabs), 3)] + [_home_row(lang, back="hub:profile")]
    return "\n".join(lines), InlineKeyboardMarkup(rows)


# ── Handlers ────────────────────────────────────────────────────────────────

async def _show(update, text, keyboard, *, edit: bool):
    if edit:
        try:
            await update.callback_query.edit_message_text(
                text, reply_markup=keyboard, parse_mode=ParseMode.HTML, disable_web_page_preview=True
            )
        except BadRequest as exc:
            if "not modified" not in str(exc).lower():
                raise
        return
    await update.effective_message.reply_text(
        text, reply_markup=keyboard, parse_mode=ParseMode.HTML, disable_web_page_preview=True
    )


async def show_home(update, context, *, edit: bool = False) -> bool:
    lang = await language_for_update(update)
    dashboard = await load_dashboard_async(update.effective_user.id)
    if dashboard is None:
        return False
    text, keyboard = render_home(dashboard, lang)
    await _show(update, text, keyboard, edit=edit)
    return True


async def hub_callback(update, context) -> None:
    query = update.callback_query
    user_id = query.from_user.id
    lang = await language_for_update(update)
    page, _, arg = query.data.removeprefix("hub:").partition(":")

    if page == "claim_pick":
        await _finish_claim(update, context, lang, int(arg))
        return
    await query.answer()
    if page == "home":
        if not await show_home(update, context, edit=True):
            await query.edit_message_text("Please start the bot in private with /start.")
        return
    if page == "claim":
        await _start_claim(update, context, lang)
        return

    renderers = {
        "play": lambda: render_play(
            lang, context.bot.username, query.message.chat.type == ChatType.PRIVATE, query.message.chat.id
        ),
        "daily": lambda: render_daily(user_id, lang),
        "compete": lambda: render_compete(lang),
        "season": lambda: render_season(user_id, lang),
        "weekly": lambda: render_weekly(user_id, lang),
        "tournament": lambda: render_tournament(user_id, lang),
        "profile": lambda: render_profile(user_id, lang),
        "ach": lambda: render_achievements(user_id, lang, arg or None),
    }
    render = renderers.get(page)
    if render is None:
        return
    text, keyboard = await sync_to_async(render, thread_sensitive=True)()
    await _show(update, text, keyboard, edit=True)


# ── Starter horse claim ─────────────────────────────────────────────────────

async def _start_claim(update, context, lang):
    query = update.callback_query
    if query.message.chat.type != ChatType.PRIVATE:
        await query.answer("Open me in private to claim your horse.", show_alert=True)
        return
    if await sync_to_async(starter_horse_for, thread_sensitive=True)(query.from_user.id):
        await query.edit_message_text(translate("s1.claim_have", lang), reply_markup=InlineKeyboardMarkup([_home_row(lang)]))
        return
    context.user_data["awaiting_starter_name"] = True
    await query.edit_message_text(translate("s1.claim_intro", lang), reply_markup=InlineKeyboardMarkup([_home_row(lang)]))


async def starter_name_text(update, context) -> bool:
    """Consume the horse name reply; returns True when the message was handled."""
    if not context.user_data.get("awaiting_starter_name"):
        return False
    lang = await language_for_update(update)
    try:
        name = clean_horse_name(update.message.text)
    except InvalidStarterChoice:
        await update.message.reply_text("❌ 1–20 characters, please. Try another name:")
        return True
    context.user_data.pop("awaiting_starter_name", None)
    context.user_data["starter_name"] = name
    offers = await starter_powerup_offers_async(update.effective_user.id)
    rows = [[Btn(f"{u.name}", callback_data=f"hub:claim_pick:{u.pk}")] for u in offers]
    details = "\n".join(f"{u.name} — {escape(u.description)}" for u in offers)
    await update.message.reply_text(
        translate("s1.claim_pick", lang, name=escape(name), uses=STARTER_HORSE_POWERUP_USES) + "\n\n" + details,
        reply_markup=InlineKeyboardMarkup(rows + [_home_row(lang)]),
        parse_mode=ParseMode.HTML,
    )
    return True


async def _finish_claim(update, context, lang, upgrade_id: int):
    query = update.callback_query
    name = context.user_data.get("starter_name")
    if not name:
        await query.answer("Start again from 🎁 Claim your FREE horse.", show_alert=True)
        return
    try:
        horse = await claim_starter_horse_async(
            query.from_user.id, name, upgrade_id, STARTER_HORSE_POWERUP_USES
        )
    except StarterAlreadyClaimed:
        await query.answer(translate("s1.claim_have", lang), show_alert=True)
        return
    except InvalidStarterChoice as exc:
        await query.answer(str(exc), show_alert=True)
        return
    await query.answer("🎉")
    context.user_data.pop("starter_name", None)
    upgrade = await sync_to_async(
        lambda: horse.horseappliedupgrade_set.select_related("upgrade").first().upgrade.name,
        thread_sensitive=True,
    )()
    await query.edit_message_text(
        translate("s1.claim_done", lang, name=escape(horse.name), number=horse.horse_number, powerup=upgrade),
        reply_markup=InlineKeyboardMarkup([
            [Btn(translate("s1.btn_stable", lang), callback_data="menu:mainhorse")],
            _home_row(lang),
        ]),
        parse_mode=ParseMode.HTML,
    )


def section_command(page: str):
    """Build a /command that opens one hub section as a fresh message."""

    async def command(update, context) -> None:
        user_id = update.effective_user.id
        lang = await language_for_update(update)
        if not await Player.objects.filter(pk=user_id).aexists():
            await update.effective_message.reply_text("Start the bot first with /start.")
            return
        renderers = {
            "daily": lambda: render_daily(user_id, lang),
            "compete": lambda: render_compete(lang),
            "season": lambda: render_season(user_id, lang),
            "tournament": lambda: render_tournament(user_id, lang),
        }
        text, keyboard = await sync_to_async(renderers[page], thread_sensitive=True)()
        await _show(update, text, keyboard, edit=False)

    return command
