from django.db.models.signals import pre_save
from django.dispatch import receiver
from .models import DailyQuest, PlayerDailyQuestProgress, QuestHistory

@receiver(pre_save, sender=DailyQuest)
def handle_quest_change(sender, instance, **kwargs):
    if not instance.pk:
        return  # Skip creation

    old = DailyQuest.objects.get(pk=instance.pk)

    if instance.available == False or instance.date_assigned != old.date_assigned:
        # Fetch progress entries
        progresses = PlayerDailyQuestProgress.objects.filter(quest=instance)

        for progress in progresses:
            if progress.completed:
                # Move to QuestHistory
                QuestHistory.objects.create(
                    player=progress.player,
                    quest_type=instance.quest_type,
                    subtype=instance.subtype,
                    description=instance.description,
                    target=instance.target,
                    reward_xp=instance.reward_xp,
                    reward_chips=instance.reward_chips,
                    progress=progress.progress,
                    date_assigned=instance.date_assigned
                )
            # Delete the progress
            progress.delete()
