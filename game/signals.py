from django.db.models.signals import pre_save,post_save
from django.dispatch import receiver
from .models import DailyQuest, PlayerDailyQuestProgress, QuestHistory,GameParameter, UserSettings, Player

from django.conf import settings
import asyncio
from telegram import Bot

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




@receiver(post_save, sender=GameParameter)
def notify_game_parameter_events(sender, instance, created, **kwargs):
    if created:
        return  # Don't notify on initial creation

    # Avoid circular import

    messages = []
    if instance.new_quests:
        messages.append(f"🎲 New quests: Check /start --> quests and rewards to see the current quests available.")
    if instance.join_bonus:
        messages.append(f"🎁 Bonus Event: Players joining Blackjack games receive {instance.join_bonus_amount} chips!")

    if instance.buyhorse_event:
        messages.append(f"🐎 Buy Horse Event: All horses are now priced at {instance.todays_horse_price:,} chips!")

    if instance.rename_horse_event:
        messages.append("🏷️ Rename Event: You can rename your horses for only 1 chip!")

    if instance.double_chance_event:
        messages.append(f"🎲 Double Chance Event: Your odds just got better! 🎯 Chance to Double Your chips is now `{instance.double_chance}`.")



    if instance.horse_move_event:
        messages.append("🐴 Fast Horse Event: Dealer horses move slower! Win races more easily!")

    if instance.crash_event:
        messages.append("📈 Crash Win Event: Easier wins in crash mode! multipliers increased!")

    if not messages:
        return  # Nothing to announce

    # Send notifications asynchronously
    asyncio.run(send_event_notifications(messages))


async def send_event_notifications(messages):
    bot = Bot(token=settings.TELEGRAM_BOT_TOKEN)
    full_message = "\n\n".join(messages)

    users = await asyncio.to_thread(
        lambda: list(UserSettings.objects.filter(notify_new_events=True).select_related("player"))
    )

    for user_setting in users:
        try:
            await bot.send_message(
                chat_id=user_setting.player.id,
                text=f"📣 New Event Update!\n\n{full_message}"
            )
        except Exception as e:
            print(f"[Event Notify Error] Could not notify {user_setting.player.id}: {e}")
