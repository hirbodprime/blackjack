"""Atomic daily-quest progress and reward settlement."""

from dataclasses import dataclass

from asgiref.sync import sync_to_async
from django.db import transaction

from game.models import (
    ChipTransaction,
    DailyQuest,
    Player,
    PlayerDailyQuestProgress,
)
from game.services.economy import adjust_balance
from game.services.progression import ProgressionResult, award_xp


@dataclass(frozen=True)
class QuestProgressResult:
    progress: int
    completed_now: bool
    progression: ProgressionResult | None = None
    chip_reward: int = 0


@transaction.atomic
def advance_daily_quest(
    player_id: int, quest_id: int, amount: int = 1
) -> QuestProgressResult:
    if amount <= 0:
        raise ValueError("Quest progress amount must be positive")
    player = Player.objects.select_for_update().get(pk=player_id)
    quest = DailyQuest.objects.get(pk=quest_id, available=True)
    progress, _ = PlayerDailyQuestProgress.objects.select_for_update().get_or_create(
        player=player,
        quest=quest,
        defaults={"subtype": quest.subtype, "progress": 0, "completed": False},
    )
    if progress.completed:
        return QuestProgressResult(progress.progress, False)

    progress.progress += amount
    completed_now = progress.progress >= quest.target
    progression = None
    if completed_now:
        progress.completed = True
        progression = award_xp(player, quest.reward_xp)
        if quest.reward_chips:
            adjust_balance(
                player,
                quest.reward_chips,
                category=ChipTransaction.Category.QUEST_REWARD,
                description=f"Completed daily quest: {quest.description}",
                reference_type="daily_quest",
                reference_id=quest.pk,
                idempotency_key=f"quest:{quest.pk}:player:{player.pk}:reward",
            )
    progress.save(update_fields=("progress", "completed"))
    return QuestProgressResult(
        progress.progress,
        completed_now,
        progression,
        quest.reward_chips if completed_now else 0,
    )


async def advance_daily_quest_async(*args, **kwargs) -> QuestProgressResult:
    return await sync_to_async(advance_daily_quest, thread_sensitive=True)(*args, **kwargs)
