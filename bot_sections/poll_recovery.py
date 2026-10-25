import asyncio

from django.utils import (
    timezone,
)
from telegram import (
    BotCommand,
    BotCommandScopeAllGroupChats,
    BotCommandScopeAllPrivateChats,
)

from bot_sections.blackjack_game import (
    remove_game_if_no_poll_answer,
)
from game.models import (
    ActivePoll,
    Game,
)
from game.services.recovery import (
    recover_interrupted_games_async,
)


async def handle_stale_polls_and_reschedule(context, timeout=60):
    from asgiref.sync import sync_to_async

    from game.telegram.poker import resume_poker_tables
    from game.telegram.roulette_table import resume_roulette_tables

    from game.telegram.competition_jobs import start_competition_jobs

    await start_competition_jobs(context)
    await recover_interrupted_games_async()
    await resume_poker_tables(context)
    await resume_roulette_tables(context)

    # Menus do the work; only a few entry points are listed.
    private = {
        "en": [("start", "🏠 Home menu"), ("daily", "📆 Daily challenges"), ("shop", "🛍 Shop"), ("help", "❓ Help")],
        "fa": [("start", "🏠 منوی اصلی"), ("daily", "📆 چالش‌های روزانه"), ("shop", "🛍 فروشگاه"), ("help", "❓ راهنما")],
    }
    groups = {
        "en": [("play", "🎮 Game menu"), ("help", "❓ Help")],
        "fa": [("play", "🎮 منوی بازی"), ("help", "❓ راهنما")],
    }
    for lang, code in (("en", None), ("fa", "fa")):
        await context.bot.set_my_commands(
            [BotCommand(c, d) for c, d in private[lang]], scope=BotCommandScopeAllPrivateChats(), language_code=code
        )
        await context.bot.set_my_commands(
            [BotCommand(c, d) for c, d in groups[lang]], scope=BotCommandScopeAllGroupChats(), language_code=code
        )
        await context.bot.set_my_commands(
            [BotCommand(c, d) for c, d in private[lang]], language_code=code
        )

    polls = await sync_to_async(list)(
        ActivePoll.objects.filter(has_response=False)
    )

    now = timezone.now()

    for poll in polls:
        elapsed = (now - poll.created_at).total_seconds()

        if elapsed >= timeout:
            # Too late — delete immediately
            deleted, _ = await sync_to_async(Game.objects.filter(
                chat_id=poll.chat_id, started=False, ended=False
            ).delete)()
            await sync_to_async(poll.delete)()

            try:
                await context.bot.send_message(poll.chat_id, "⏰ No one responded to the bet poll. Game cancelled.")
            except:
                pass

            print(f"🗑 Cleaned up stale poll {poll.poll_id} (deleted {deleted} games)")

        else:
            # Still valid — reschedule
            remaining = timeout - int(elapsed)
            asyncio.create_task(remove_game_if_no_poll_answer(context, poll.poll_id, timeout=remaining))





# language 



# async def handle_language_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
#     query = update.callback_query
#     await query.answer()
#     data = query.data

#     if data.startswith("language:set:"):
#         lang_code = data.split(":")[-1]
#         chat_id = query.message.chat_id

#         group, _ = await sync_to_async(Group.objects.get_or_create)(group_chat_id=chat_id)
#         settings, _ = await sync_to_async(GroupSettings.objects.get_or_create)(group=group)
#         settings.language = lang_code
#         await sync_to_async(settings.save)()

#         lang_display = "English" if lang_code == "en" else "فارسی"
#         await query.edit_message_text(f"🌍 Language updated to {lang_display}")





# async def get_group_language(chat_id):
#     try:
#         group = await sync_to_async(Group.objects.get)(group_chat_id=chat_id)
#         settings = await sync_to_async(GroupSettings.objects.get)(group=group)
#         return settings.language
#     except GroupSettings.DoesNotExist:
#         return "en"












