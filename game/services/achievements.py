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
