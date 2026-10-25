"""Automatic daily challenges (easy / medium / hard) and the completion streak."""

import random
from dataclasses import dataclass
from datetime import date, timedelta

from asgiref.sync import sync_to_async
from django.db import transaction
from django.utils import timezone

from game.economy_config import DAILY_STREAK_BONUS, DAILY_STREAK_BONUS_CAP
from game.models import ChipTransaction, DailyQuest, Player, PlayerDailyQuestProgress
from game.services.economy import adjust_balance
from game.services.shop import consume_streak_freeze


# (quest_type, subtype, description, target, xp, chips) — subtypes are the
# events the games already report through update_daily_quest_progress.
TEMPLATES = {
    "easy": (
        ("blackjack", "join", "Play {n} blackjack games", 3, 60, 600),
        ("minigames", "dice", "Roll the dice {n} times", 5, 50, 500),
        ("minigames", "coin", "Flip a coin {n} times", 5, 50, 500),
        ("minigames", "slot", "Spin the slots {n} times", 5, 50, 500),
        ("minigames", "dart", "Throw {n} darts", 3, 50, 500),
        ("race", "joinhorse", "Join {n} horse races", 2, 60, 600),
    ),
    "medium": (
        ("blackjack", "join", "Play {n} blackjack games", 8, 120, 1_500),
        ("blackjack", "15", "Stand on exactly 15, {n} times", 2, 120, 1_500),
        ("minigames", "1.4", "Cash out crash at 1.4x+ {n} times", 3, 120, 1_500),
        ("race", "joinhorse", "Join {n} horse races", 5, 120, 1_500),
        ("minigames", "slot", "Spin the slots {n} times", 15, 120, 1_500),
    ),
    "hard": (
        ("blackjack", "hitblackjack", "Hit {n} blackjacks", 2, 250, 3_500),
        ("blackjack", "natural", "Get a natural blackjack", 1, 250, 3_500),
        ("race", "win", "Win {n} horse races", 2, 250, 3_500),
        ("minigames", "1.8", "Cash out crash at 1.8x+ {n} times", 2, 250, 3_500),
        ("blackjack", "join", "Play {n} blackjack games", 20, 250, 3_500),
    ),
}
DIFFICULTY_ICON = {"easy": "🟢", "medium": "🟡", "hard": "🔴"}


def ensure_daily_challenges(day: date | None = None) -> list[DailyQuest]:
    """Create today's three challenges once and retire earlier generated ones."""
    day = day or timezone.localdate()
    existing = list(DailyQuest.objects.filter(auto_generated=True, date_assigned=day).order_by("pk"))
    if existing:
        return existing
    DailyQuest.objects.filter(auto_generated=True, available=True).exclude(
        date_assigned=day
    ).update(available=False)
    picker = random.Random(day.toordinal())
    created = []
    used = set()
    for difficulty in ("easy", "medium", "hard"):
        options = [t for t in TEMPLATES[difficulty] if (t[0], t[1]) not in used]
        quest_type, subtype, text, target, xp, chips = picker.choice(options)
        used.add((quest_type, subtype))
        created.append(DailyQuest.objects.create(
            quest_type=quest_type, subtype=subtype, description=text.format(n=target),
            target=target, reward_xp=xp, reward_chips=chips, date_assigned=day,
            available=True, difficulty=difficulty, auto_generated=True,
        ))
    return created


@dataclass(frozen=True)
class StreakResult:
    streak: int
    bonus: int


@transaction.atomic
def record_daily_completion(player_id: int, day: date | None = None) -> StreakResult | None:
    """Extend the streak when the player has cleared every challenge of ``day``."""
    day = day or timezone.localdate()
    challenge_ids = list(
        DailyQuest.objects.filter(auto_generated=True, date_assigned=day).values_list("pk", flat=True)
    )
    if not challenge_ids:
        return None
    done = PlayerDailyQuestProgress.objects.filter(
        player_id=player_id, quest_id__in=challenge_ids, completed=True
    ).count()
    if done < len(challenge_ids):
        return None
    player = Player.objects.select_for_update().get(pk=player_id)
    if player.last_streak_date == day:
        return None
    if player.last_streak_date == day - timedelta(days=1):
        player.daily_streak += 1
    elif (
        player.last_streak_date == day - timedelta(days=2)
        and player.daily_streak
        and consume_streak_freeze(player.pk)
    ):
        player.daily_streak += 1
    else:
        player.daily_streak = 1
    player.best_daily_streak = max(player.best_daily_streak, player.daily_streak)
    player.last_streak_date = day
    player.save(update_fields=("daily_streak", "best_daily_streak", "last_streak_date"))
    bonus = min(DAILY_STREAK_BONUS * player.daily_streak, DAILY_STREAK_BONUS_CAP)
    adjust_balance(
        player, bonus,
        category=ChipTransaction.Category.QUEST_REWARD,
        description=f"Daily streak day {player.daily_streak}",
        reference_type="daily_streak", reference_id=day.isoformat(),
        idempotency_key=f"streak:{player.pk}:{day.isoformat()}",
    )
    from game.services.achievements import unlock

    for length in (3, 7, 30):
        if player.daily_streak >= length:
            unlock(player.pk, f"streak_{length}")
    return StreakResult(player.daily_streak, bonus)


def todays_board(player_id: int, day: date | None = None) -> list[tuple[DailyQuest, int, bool]]:
    quests = ensure_daily_challenges(day)
    progress = {
        p.quest_id: p
        for p in PlayerDailyQuestProgress.objects.filter(player_id=player_id, quest__in=quests)
    }
    return [
        (q, progress[q.pk].progress if q.pk in progress else 0,
         progress[q.pk].completed if q.pk in progress else False)
        for q in quests
    ]


ensure_daily_challenges_async = sync_to_async(ensure_daily_challenges, thread_sensitive=True)
record_daily_completion_async = sync_to_async(record_daily_completion, thread_sensitive=True)
todays_board_async = sync_to_async(todays_board, thread_sensitive=True)


FA_TEMPLATES = {
    ("blackjack", "join"): "{n} بازی بلک‌جک انجام بده",
    ("blackjack", "15"): "{n} بار روی دقیقاً ۱۵ بایست",
    ("blackjack", "hitblackjack"): "{n} بار بلک‌جک بگیر",
    ("blackjack", "natural"): "یک بلک‌جک طبیعی بگیر",
    ("minigames", "dice"): "{n} بار تاس بریز",
    ("minigames", "coin"): "{n} بار سکه بینداز",
    ("minigames", "slot"): "{n} بار اسلات بچرخان",
    ("minigames", "dart"): "{n} بار دارت پرتاب کن",
    ("minigames", "1.4"): "{n} بار در کرش با ۱.۴x+ برداشت کن",
    ("minigames", "1.8"): "{n} بار در کرش با ۱.۸x+ برداشت کن",
    ("race", "joinhorse"): "در {n} مسابقه اسب شرکت کن",
    ("race", "win"): "{n} مسابقه اسب ببر",
}


def quest_text(quest: DailyQuest, language: str) -> str:
    if language == "fa" and quest.auto_generated:
        template = FA_TEMPLATES.get((quest.quest_type, quest.subtype))
        if template:
            return template.format(n=quest.target)
    return quest.description
