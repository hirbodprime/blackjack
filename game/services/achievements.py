"""Achievement catalog and the single unlock path every game uses."""

from asgiref.sync import sync_to_async
from django.db import transaction

from game.models import Achievement, ChipTransaction, Player, PlayerAchievement
from game.services.economy import adjust_balance
from game.services.progression import award_xp


C = Achievement.Category

# (condition, icon, name, description, category, reward_chips, reward_xp, hidden)
# Conditions already emitted by the games keep their original spelling.
CATALOG = (
    # Blackjack
    ("first_natrual_blackjack", "🂡", "Natural", "Get a natural blackjack", C.BLACKJACK, 1_000, 50, False),
    ("21_black_jacks", "🃏", "Twenty-One Club", "Hit 21 blackjacks", C.BLACKJACK, 5_000, 150, False),
    ("100_black_jacks", "🎰", "Card Shark", "Hit 100 blackjacks", C.BLACKJACK, 25_000, 500, False),
    ("100_games", "🎲", "Regular", "Play 100 blackjack games", C.BLACKJACK, 5_000, 150, False),
    ("500_games", "🏛", "Pit Boss", "Play 500 blackjack games", C.BLACKJACK, 25_000, 500, False),
    ("5000_game_join", "🗿", "Furniture", "Join 5,000 blackjack games", C.BLACKJACK, 100_000, 2_000, True),
    ("100_wins", "🏆", "Winner Winner", "Win 100 rounds", C.BLACKJACK, 10_000, 300, False),
    ("100_loses", "🫠", "Thick Skin", "Lose 100 rounds and keep playing", C.BLACKJACK, 3_000, 100, True),
    ("win_5_rounds", "🔥", "Hot Hand", "Win 5 rounds in one game", C.BLACKJACK, 2_000, 80, False),
    ("win_with_10", "🔟", "Low Roller", "Win a round holding only 10", C.BLACKJACK, 1_500, 60, True),
    ("all_in", "💥", "All In", "Bet everything you have", C.BLACKJACK, 0, 50, True),
    ("paid_back_tie", "🤝", "Push It", "Get your bet back on a tie", C.BLACKJACK, 500, 30, False),
    ("5_or_more_player", "👥", "Full Table", "Play at a table with 5+ players", C.BLACKJACK, 1_000, 50, False),
    ("30_or_more_deck", "🧱", "Bust Spectacular", "Reach 30+ in one hand", C.BLACKJACK, 500, 30, True),
    ("thriple_6_in_one_deck", "😈", "Devil's Hand", "Hold three 6s in one hand", C.BLACKJACK, 6_666, 66, True),
    # Horses
    ("starter_horse", "🐴", "Saddle Up", "Claim your first horse", C.HORSES, 0, 50, False),
    ("first_race_win", "🏇", "First Past the Post", "Win a horse race bet", C.HORSES, 1_000, 50, False),
    ("own_horse_win", "🥕", "Proud Owner", "Win a race on your own horse", C.HORSES, 3_000, 100, False),
    ("race_regular", "🏟", "Track Regular", "Join 50 horse races", C.HORSES, 5_000, 200, False),
    # Minigames
    ("slot_jackpot", "🎰", "Jackpot!", "Hit a slot jackpot", C.MINIGAMES, 5_000, 150, False),
    ("crash_5x", "🚀", "To the Moon", "Cash out crash at 5x or more", C.MINIGAMES, 5_000, 150, False),
    ("minigame_100", "🕹", "Arcade Rat", "Play 100 minigames", C.MINIGAMES, 5_000, 200, False),
    # Progress
    ("rank_silver", "🥈", "Silver Rank", "Reach Silver rank", C.PROGRESS, 2_000, 0, False),
    ("rank_gold", "🥇", "Gold Rank", "Reach Gold rank", C.PROGRESS, 5_000, 0, False),
    ("rank_platinum", "💠", "Platinum Rank", "Reach Platinum rank", C.PROGRESS, 10_000, 0, False),
    ("rank_diamond", "💎", "Diamond Rank", "Reach Diamond rank", C.PROGRESS, 25_000, 0, False),
    ("rank_master", "👑", "Master Rank", "Reach Master rank", C.PROGRESS, 50_000, 0, False),
    ("rank_legend", "🌟", "Legend", "Reach Legend rank", C.PROGRESS, 100_000, 0, False),
    ("streak_3", "📅", "Habit", "Complete every daily challenge 3 days in a row", C.PROGRESS, 2_000, 100, False),
    ("streak_7", "🗓", "Committed", "7-day daily challenge streak", C.PROGRESS, 7_000, 300, False),
    ("streak_30", "🏅", "Unstoppable", "30-day daily challenge streak", C.PROGRESS, 50_000, 1_500, False),
    ("weekly_warrior", "⚔️", "Weekly Warrior", "Complete a weekly mission", C.PROGRESS, 1_000, 50, False),
    # Competitions
    ("tournament_podium", "🥉", "On the Podium", "Finish top 3 in a tournament", C.COMPETITION, 0, 200, False),
    ("tournament_champion", "🏆", "Champion", "Win a tournament", C.COMPETITION, 0, 500, False),
    ("weekly_top5", "📈", "Weekly Elite", "Finish top 5 on the weekly leaderboard", C.COMPETITION, 0, 300, False),
    ("weekly_first", "👑", "King of the Week", "Finish 1st on the weekly leaderboard", C.COMPETITION, 0, 600, False),
    ("season_top10", "🎖", "Season Finalist", "Finish a season in the top 10", C.COMPETITION, 0, 1_000, False),
    ("season_champion", "🌟", "Season Champion", "Finish a season in 1st place", C.COMPETITION, 0, 3_000, False),
    # Social
    ("first_market_sale", "💸", "Merchant", "Sell an item on the marketplace", C.SOCIAL, 500, 30, False),
    ("first_market_purchase", "🛒", "Shopper", "Buy an item on the marketplace", C.SOCIAL, 500, 30, False),
    ("first_challenge_win", "⚔️", "Duelist", "Win a friend challenge", C.SOCIAL, 1_000, 50, False),
    ("first_referral", "🤝", "Recruiter", "Invite a friend who joins", C.SOCIAL, 2_000, 100, False),
    # Play milestones (checked from the ledger after each game)
    ("plays_10", "🎲", "Getting Started", "Place 10 bets in any game", C.PROGRESS, 500, 30, False),
    ("plays_100", "🎯", "Regular", "Place 100 bets", C.PROGRESS, 3_000, 150, False),
    ("plays_1000", "🏛", "Institution", "Place 1,000 bets", C.PROGRESS, 25_000, 1_000, False),
    ("all_rounder", "🎪", "All-Rounder", "Play 4 different kinds of game", C.PROGRESS, 3_000, 150, False),
    ("night_owl", "🦉", "Night Owl", "Play between midnight and 5am (Tehran)", C.PROGRESS, 1_000, 50, True),
    ("big_win_10k", "💰", "Big Win", "Collect a single payout of 10,000+", C.PROGRESS, 0, 200, False),
    ("big_win_100k", "💸", "Monster Win", "Collect a single payout of 100,000+", C.PROGRESS, 0, 1_000, False),
    ("rich_100k", "🏦", "Six Figures", "Hold 100,000 chips", C.PROGRESS, 0, 300, False),
    ("rich_1m", "💎", "Millionaire", "Hold 1,000,000 chips", C.PROGRESS, 0, 2_000, False),
    ("arcade_50", "🕹", "Arcade Regular", "Play 50 arcade rounds", C.MINIGAMES, 3_000, 150, False),
    ("poker_10", "♠️", "Card Room Regular", "Sit down at 10 poker tables", C.MINIGAMES, 3_000, 150, False),
    ("season1_pioneer", "🚀", "Season 1 Pioneer", "Played in the first week of Season 1", C.LEGACY, 1_000, 100, False),
    # Legacy
    ("season0_veteran", "🎖", "Veteran", "Played before the Season 1 relaunch", C.LEGACY, 0, 0, False),
    ("season0_founder", "🏛", "Founder", "A top-10 player of the original casino", C.LEGACY, 0, 0, False),
)

RANK_ACHIEVEMENTS = {
    "silver": "rank_silver",
    "gold": "rank_gold",
    "platinum": "rank_platinum",
    "diamond": "rank_diamond",
    "master": "rank_master",
    "legend": "rank_legend",
}


def sync_catalog() -> int:
    """Create or refresh every catalog entry; returns how many were created."""
    created = 0
    for condition, icon, name, description, category, chips, xp, hidden in CATALOG:
        _, was_created = Achievement.objects.update_or_create(
            condition=condition,
            defaults={
                "icon": icon, "name": name, "description": description,
                "category": category, "reward_chips": chips, "reward_xp": xp,
                "hidden": hidden,
            },
        )
        created += was_created
    return created


@transaction.atomic
def unlock(player: Player | int, condition: str) -> Achievement | None:
    """Grant an achievement and its rewards once; returns it only on first unlock."""
    achievement = Achievement.objects.filter(condition=condition).first()
    if achievement is None:
        return None
    player_id = player.pk if isinstance(player, Player) else player
    _, created = PlayerAchievement.objects.get_or_create(
        player_id=player_id, achievement=achievement
    )
    if not created:
        return None
    if achievement.reward_xp:
        award_xp(player_id, achievement.reward_xp)
    if achievement.reward_chips:
        adjust_balance(
            player_id,
            achievement.reward_chips,
            category=ChipTransaction.Category.ACHIEVEMENT_REWARD,
            description=f"Achievement: {achievement.name}",
            reference_type="achievement",
            reference_id=achievement.pk,
            idempotency_key=f"achievement:{achievement.pk}:player:{player_id}",
        )
    if isinstance(player, Player):
        player.refresh_from_db(fields=("chips", "xp", "level"))
    return achievement


unlock_async = sync_to_async(unlock, thread_sensitive=True)


def unlock_message(achievement: Achievement) -> str:
    rewards = []
    if achievement.reward_chips:
        rewards.append(f"+{achievement.reward_chips:,} chips")
    if achievement.reward_xp:
        rewards.append(f"+{achievement.reward_xp:,} XP")
    suffix = f"\n🎁 {' · '.join(rewards)}" if rewards else ""
    return (
        f"🏅 Achievement unlocked!\n\n{achievement.icon or '🏅'} {achievement.name}\n"
        f"{achievement.description}{suffix}"
    )


# ── Persian names ───────────────────────────────────────────────────────────

FA = {
    "first_natrual_blackjack": ("طبیعی", "یک بلک‌جک طبیعی بگیر"),
    "21_black_jacks": ("باشگاه ۲۱", "۲۱ بار بلک‌جک بگیر"),
    "100_black_jacks": ("کارت‌باز حرفه‌ای", "۱۰۰ بار بلک‌جک بگیر"),
    "100_games": ("پای ثابت", "۱۰۰ بازی بلک‌جک انجام بده"),
    "500_games": ("رئیس سالن", "۵۰۰ بازی بلک‌جک انجام بده"),
    "5000_game_join": ("جزو اثاثیه", "۵۰۰۰ بار وارد بلک‌جک شو"),
    "100_wins": ("برنده برنده", "۱۰۰ دست ببر"),
    "100_loses": ("پوست کلفت", "۱۰۰ دست ببازی و ادامه بدهی"),
    "win_5_rounds": ("دست داغ", "۵ دست در یک بازی ببر"),
    "win_with_10": ("کم‌خطر", "با ۱۰ ببر"),
    "all_in": ("همه یا هیچ", "همه چیپ‌هایت را شرط ببند"),
    "paid_back_tie": ("مساوی", "در تساوی شرطت را پس بگیر"),
    "5_or_more_player": ("میز پر", "در میزی با ۵ نفر یا بیشتر بازی کن"),
    "30_or_more_deck": ("سوختن تماشایی", "در یک دست به ۳۰+ برس"),
    "thriple_6_in_one_deck": ("دست شیطان", "سه ۶ در یک دست داشته باش"),
    "starter_horse": ("سوار شو", "اسب اولت را بگیر"),
    "first_race_win": ("اول از خط", "یک شرط مسابقه اسب ببر"),
    "own_horse_win": ("صاحب افتخار", "با اسب خودت ببر"),
    "race_regular": ("پای ثابت پیست", "در ۵۰ مسابقه شرکت کن"),
    "slot_jackpot": ("جک‌پات!", "جک‌پات اسلات بزن"),
    "crash_5x": ("تا ماه", "در کرش با ۵ برابر یا بیشتر برداشت کن"),
    "minigame_100": ("گیمر", "۱۰۰ مینی‌گیم بازی کن"),
    "rank_silver": ("رتبه نقره", "به رتبه نقره برس"),
    "rank_gold": ("رتبه طلا", "به رتبه طلا برس"),
    "rank_platinum": ("رتبه پلاتین", "به رتبه پلاتین برس"),
    "rank_diamond": ("رتبه الماس", "به رتبه الماس برس"),
    "rank_master": ("رتبه استاد", "به رتبه استاد برس"),
    "rank_legend": ("افسانه", "به رتبه افسانه برس"),
    "streak_3": ("عادت", "۳ روز پشت‌سرهم همه چالش‌ها را کامل کن"),
    "streak_7": ("متعهد", "زنجیره ۷ روزه"),
    "streak_30": ("توقف‌ناپذیر", "زنجیره ۳۰ روزه"),
    "weekly_warrior": ("جنگجوی هفته", "یک مأموریت هفتگی را کامل کن"),
    "tournament_podium": ("روی سکو", "در تورنمنت جزو ۳ نفر اول شو"),
    "tournament_champion": ("قهرمان", "یک تورنمنت را ببر"),
    "weekly_top5": ("نخبه هفته", "در جدول هفتگی جزو ۵ نفر اول شو"),
    "weekly_first": ("پادشاه هفته", "در جدول هفتگی اول شو"),
    "season_top10": ("فینالیست فصل", "فصل را جزو ۱۰ نفر اول تمام کن"),
    "season_champion": ("قهرمان فصل", "فصل را اول تمام کن"),
    "first_market_sale": ("تاجر", "یک آیتم در بازار بفروش"),
    "first_market_purchase": ("خریدار", "یک آیتم از بازار بخر"),
    "first_challenge_win": ("دوئل‌باز", "یک رقابت دوستانه را ببر"),
    "first_referral": ("معرف", "دوستی را دعوت کن که عضو شود"),
    "plays_10": ("شروع کار", "۱۰ شرط در هر بازی ببند"),
    "plays_100": ("پای ثابت", "۱۰۰ شرط ببند"),
    "plays_1000": ("نهاد", "۱۰۰۰ شرط ببند"),
    "all_rounder": ("همه‌فن‌حریف", "۴ نوع بازی مختلف انجام بده"),
    "night_owl": ("جغد شب", "بین نیمه‌شب تا ۵ صبح (تهران) بازی کن"),
    "big_win_10k": ("برد بزرگ", "یک برد ۱۰٬۰۰۰+ بگیر"),
    "big_win_100k": ("برد هیولا", "یک برد ۱۰۰٬۰۰۰+ بگیر"),
    "rich_100k": ("شش رقمی", "۱۰۰٬۰۰۰ چیپ داشته باش"),
    "rich_1m": ("میلیونر", "۱٬۰۰۰٬۰۰۰ چیپ داشته باش"),
    "arcade_50": ("پای ثابت آرکید", "۵۰ دور آرکید بازی کن"),
    "poker_10": ("پای ثابت پوکر", "پشت ۱۰ میز پوکر بنشین"),
    "season1_pioneer": ("پیشگام فصل ۱", "در هفته اول فصل ۱ بازی کرد"),
    "season0_veteran": ("کهنه‌کار", "پیش از بازگشایی فصل ۱ بازی کرده"),
    "season0_founder": ("بنیان‌گذار", "از ۱۰ نفر برتر کازینوی قدیمی"),
}


def localized(achievement: Achievement, language: str) -> tuple[str, str]:
    if language == "fa" and achievement.condition in FA:
        return FA[achievement.condition]
    return achievement.name, achievement.description


# ── Rarity ──────────────────────────────────────────────────────────────────

RARITY = (  # (max share of players, emoji, en, fa)
    (0.01, "🟡", "Legendary", "افسانه‌ای"),
    (0.05, "🟣", "Epic", "حماسی"),
    (0.20, "🔵", "Rare", "کمیاب"),
    (1.01, "⚪", "Common", "معمولی"),
)


def rarity_map() -> dict[int, float]:
    """Achievement id → share of active players who own it."""
    from django.db.models import Count

    players = max(1, PlayerAchievement.objects.values("player_id").distinct().count())
    counts = dict(
        PlayerAchievement.objects.values_list("achievement_id").annotate(n=Count("id"))
    )
    return {aid: counts.get(aid, 0) / players for aid in Achievement.objects.values_list("pk", flat=True)}


def rarity_label(share: float, language: str = "en") -> str:
    for limit, emoji, en, fa in RARITY:
        if share < limit:
            return f"{emoji} {fa if language == 'fa' else en}"
    return ""


def showcase(player_id: int, shares: dict[int, float] | None = None, limit: int = 3) -> str:
    """The player's rarest badge icons, for names on boards and the home screen."""
    shares = shares if shares is not None else rarity_map()
    owned = list(
        PlayerAchievement.objects.filter(player_id=player_id).select_related("achievement")
    )
    owned.sort(key=lambda pa: (shares.get(pa.achievement_id, 1), -pa.pk))
    return "".join(pa.achievement.icon or "🏅" for pa in owned[:limit])


def showcase_many(player_ids, limit: int = 1) -> dict[int, str]:
    shares = rarity_map()
    rows = {}
    for pa in PlayerAchievement.objects.filter(player_id__in=list(player_ids)).select_related("achievement"):
        rows.setdefault(pa.player_id, []).append(pa)
    result = {}
    for player_id, owned in rows.items():
        owned.sort(key=lambda pa: shares.get(pa.achievement_id, 1))
        result[player_id] = "".join(pa.achievement.icon or "🏅" for pa in owned[:limit])
    return result


# ── Granting after real play ────────────────────────────────────────────────

GAME_KINDS = {
    "blackjack_game": "blackjack", "horse_race": "horses", "poker_table": "poker",
    "minigame": "minigames", "crash_game": "minigames", "arcade": "arcade",
    "roulette_table": "roulette", "telegram_update": "minigames",
}
_last_check: dict[int, float] = {}
CHECK_INTERVAL = 30.0


def grant_on_play(player_id: int) -> list[Achievement]:
    """Hand over pending badges and check ledger milestones. Call after a real game action."""
    import time
    from datetime import timedelta

    from django.db.models import Max
    from django.utils import timezone

    from game.models import ArcadeRound, ChipTransaction as Tx, PendingAchievement
    from game.services.seasons import active_season

    now = time.monotonic()
    if now - _last_check.get(player_id, 0) < CHECK_INTERVAL:
        return []
    _last_check[player_id] = now

    earned = list(
        PendingAchievement.objects.filter(player_id=player_id).values_list("condition", flat=True)
    )
    PendingAchievement.objects.filter(player_id=player_id).delete()

    bets = Tx.objects.filter(player_id=player_id, category__in=(Tx.Category.BET, Tx.Category.POKER_BUY_IN))
    count = bets.count()
    earned += [f"plays_{n}" for n in (10, 100, 1000) if count >= n]
    kinds = {GAME_KINDS.get(ref) for ref in bets.values_list("reference_type", flat=True).distinct()}
    if len(kinds - {None}) >= 4:
        earned.append("all_rounder")
    biggest = Tx.objects.filter(
        player_id=player_id,
        category__in=(Tx.Category.BLACKJACK_PAYOUT, Tx.Category.RACE_PAYOUT,
                      Tx.Category.MINIGAME_PAYOUT, Tx.Category.POKER_CASH_OUT),
    ).aggregate(m=Max("amount"))["m"] or 0
    earned += [key for key, floor in (("big_win_10k", 10_000), ("big_win_100k", 100_000)) if biggest >= floor]
    chips = Player.objects.filter(pk=player_id).values_list("chips", flat=True).first() or 0
    earned += [key for key, floor in (("rich_100k", 100_000), ("rich_1m", 1_000_000)) if chips >= floor]
    if ArcadeRound.objects.filter(player_id=player_id).count() >= 50:
        earned.append("arcade_50")
    if bets.filter(category=Tx.Category.POKER_BUY_IN).count() >= 10:
        earned.append("poker_10")
    tehran_hour = (timezone.now() + timedelta(hours=3, minutes=30)).hour
    if tehran_hour < 5:
        earned.append("night_owl")
    season = active_season()
    if season and season.number == 1 and timezone.now() < season.starts_at + timedelta(days=7):
        earned.append("season1_pioneer")

    unlocked = []
    for condition in dict.fromkeys(earned):
        achievement = unlock(player_id, condition)
        if achievement:
            unlocked.append(achievement)
    return unlocked


grant_on_play_async = sync_to_async(grant_on_play, thread_sensitive=True)


def unlock_message_for(achievement: Achievement, language: str) -> str:
    name, description = localized(achievement, language)
    rewards = []
    if achievement.reward_chips:
        rewards.append(f"+{achievement.reward_chips:,} " + ("چیپ" if language == "fa" else "chips"))
    if achievement.reward_xp:
        rewards.append(f"+{achievement.reward_xp:,} XP")
    title = "🏅 نشان جدید!" if language == "fa" else "🏅 New badge unlocked!"
    suffix = f"\n🎁 {' · '.join(rewards)}" if rewards else ""
    return f"{title}\n\n{achievement.icon or '🏅'} {name}\n{description}{suffix}"
