async def handle_stale_polls_and_reschedule(context, timeout=60):
    from asgiref.sync import sync_to_async
    from game.telegram.poker import resume_poker_tables
    from game.telegram.roulette_table import resume_roulette_tables

    await recover_interrupted_games_async()
    await resume_poker_tables(context)
    await resume_roulette_tables(context)

    english_commands = [
        BotCommand("play", "Open the main menu"),
        BotCommand("profile", "View your profile and activity"),
        BotCommand("weekly", "View weekly missions"),
        BotCommand("market", "Browse the item marketplace"),
        BotCommand("notifications", "Choose notification preferences"),
        BotCommand("onboarding", "Replay the getting-started guide"),
        BotCommand("language", "Change language: en or fa"),
        BotCommand("help", "Show game help"),
        BotCommand("poker", "Create a Texas Hold'em table"),
        BotCommand("roulette", "Open a multiplayer roulette table"),
    ]
    persian_commands = [
        BotCommand("play", "باز کردن منوی اصلی"),
        BotCommand("profile", "نمایش پروفایل و فعالیت‌ها"),
        BotCommand("weekly", "نمایش مأموریت‌های هفتگی"),
        BotCommand("market", "مشاهده بازار آیتم‌ها"),
        BotCommand("notifications", "تنظیم اعلان‌ها"),
        BotCommand("onboarding", "نمایش دوباره راهنمای شروع"),
        BotCommand("language", "تغییر زبان: en یا fa"),
        BotCommand("help", "راهنمای بازی"),
        BotCommand("poker", "ساخت میز پوکر تگزاس هولدم"),
        BotCommand("roulette", "باز کردن میز رولِت چندنفره"),
    ]
    await context.bot.set_my_commands(english_commands)
    await context.bot.set_my_commands(persian_commands, language_code="fa")

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












