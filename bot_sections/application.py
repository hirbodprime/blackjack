import asyncio

from django.conf import settings
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    PollAnswerHandler,
    filters,
)

from bot_sections.blackjack_game import (
    flee_game,
    force_start,
    get_dealer_blackjack_stats,
    get_player_chips,
    get_user_id_command,
    give_token,
    handle_poll_response,
    highroller,
    hit,
    join_blackjack,
    nextgame,
    photo_handler,
    poll_answer_handler,
    rules_command,
    stand,
    start_blackjack,
)
from bot_sections.core_and_menus import (
    start,
)
from bot_sections.horse_racing_and_social import (
    catch_all_text,
    horse,
    horserace,
    joinrace,
    myid,
    referral_leaderboard,
    richest,
    startrace,
    teachme,
)
from bot_sections.items_and_callbacks import (
    handle_menu_callback,
)
from bot_sections.minigames_and_economy import (
    admin_help,
    broadcast,
    broadcastgroups,
    cashout,
    claim_daily_tokens,
    coinflip,
    crash,
    double_or_nothing,
    give_chips,
    give_chips2,
    group,
    leaderboard,
    list_groups,
    lucky_draw,
    minigames,
    on_new_chat_members,
    repay_loan,
    request_loan,
    roll_dice,
    rps_game,
    slot_machine,
    sync_group_names,
)
from bot_sections.players_and_progression import (
    achievement_info,
    dart,
    my_achievements,
    stats,
)
from bot_sections.poll_recovery import (
    handle_stale_polls_and_reschedule,
)
from game.telegram.player_experience import (
    compact_command,
    history_command,
    language_command,
    modern_help_command,
    onboarding_callback,
    onboarding_command,
    play_command,
    play_menu_callback,
)
from game.telegram.poker import (
    poker_callback,
    poker_command,
    poker_custom_raise_text,
    poker_raise_command,
)
from game.telegram.retention import (
    buy_item_command,
    cancel_listing_command,
    challenge_command,
    marketplace_command,
    notifications_command,
    profile_command,
    retention_callback,
    sell_item_command,
    weekly_command,
)
from game.telegram.hub import hub_callback, section_command
from game.telegram.roulette_table import roulette_table_command
from game.telegram.runtime import (
    telegram_error_handler,
    telegram_shutdown,
)
from game.telegram.update_guard import (
    TelegramUpdateGuard,
)


def build_application():
    if not settings.TELEGRAM_BOT_TOKEN:
        token_name = "TELEGRAM_TEST_BOT_TOKEN" if settings.DEBUG else "TELEGRAM_BOT_TOKEN"
        raise RuntimeError(f"{token_name} must be set in the environment.")

    app = (
        ApplicationBuilder()
        .token(settings.TELEGRAM_BOT_TOKEN)
        .concurrent_updates(True)
        .post_init(handle_stale_polls_and_reschedule)
        .post_shutdown(telegram_shutdown)
        .build()
    )
    register_handlers(app)
    return app


def register_handlers(app):
    """Register handlers in their original order; within a group, the first match wins."""
    update_guard = TelegramUpdateGuard()
    app.add_handler(
        MessageHandler(filters.COMMAND, update_guard.handle_command),
        group=-100,
    )
    app.add_handler(
        CallbackQueryHandler(update_guard.handle_callback),
        group=-100,
    )
    app.add_error_handler(telegram_error_handler)

    app.add_handler(CommandHandler("teachme", teachme))
    app.add_handler(CommandHandler("play", play_command))
    app.add_handler(CommandHandler("history", history_command))
    app.add_handler(CommandHandler("language", language_command))
    app.add_handler(CommandHandler("compact", compact_command))
    app.add_handler(CommandHandler("onboarding", onboarding_command))
    app.add_handler(CallbackQueryHandler(play_menu_callback, pattern=r"^play:"))
    app.add_handler(CallbackQueryHandler(hub_callback, pattern=r"^hub:"))
    for page in ("daily", "compete", "season", "tournament"):
        app.add_handler(CommandHandler(page, section_command(page)))
    app.add_handler(CallbackQueryHandler(onboarding_callback, pattern=r"^onboarding:"))
    app.add_handler(CommandHandler("poker", poker_command))
    app.add_handler(CommandHandler("pokerraise", poker_raise_command))
    app.add_handler(CallbackQueryHandler(poker_callback, pattern=r"^poker:"))
    app.add_handler(MessageHandler(filters.ChatType.PRIVATE & filters.Regex(r"^\s*[0-9][0-9,]*\s*$"), poker_custom_raise_text))
    app.add_handler(CommandHandler("profile", profile_command))
    app.add_handler(CommandHandler("notifications", notifications_command))
    app.add_handler(CommandHandler("weekly", weekly_command))
    app.add_handler(CommandHandler("market", marketplace_command))
    app.add_handler(CommandHandler("sellitem", sell_item_command))
    app.add_handler(CommandHandler("buyitem", buy_item_command))
    app.add_handler(CommandHandler("cancellisting", cancel_listing_command))
    app.add_handler(CommandHandler("challenge", challenge_command))
    app.add_handler(CallbackQueryHandler(retention_callback, pattern=r"^retention:"))


    # Register handlers
    # app.add_handler(CommandHandler("duel", duel_command))
    # app.add_handler(CommandHandler("card", hit_command))
    # app.add_handler(CommandHandler("stop", stand_command))
    # app.add_handler(CallbackQueryHandler(handle_duel_response, pattern=r"duel_response:"))


    app.add_handler(CommandHandler("referral", referral_leaderboard))

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(handle_menu_callback))
    # app.add_handler(CallbackQueryHandler(handle_language_callback, pattern=r"^language:set:"))

    app.add_handler(CommandHandler("double", double_or_nothing))
    app.add_handler(CommandHandler("crash", crash))
    app.add_handler(CommandHandler("cashout", cashout))
    app.add_handler(CommandHandler("richest", richest))

    app.add_handler(CommandHandler("horse", horse))
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, catch_all_text)
    )

    app.add_handler(CommandHandler("myid", myid))

    # THIS line must come *after* the CallbackQueryHandler:
    # app.add_handler(
    #     MessageHandler(filters.TEXT & ~filters.COMMAND, catch_buy_horse_number)
    # )
    # app.add_handler(
    #     MessageHandler(filters.TEXT & ~filters.COMMAND, catch_set_emoji)
    # )
    app.add_handler(CommandHandler("horserace", horserace))
    app.add_handler(CommandHandler("joinrace", joinrace))
    app.add_handler(CommandHandler("startrace", startrace))
    # app.add_handler(CommandHandler("shop", shop))
    # app.add_handler(CommandHandler("buyhorse", buyhorse))
    # app.add_handler(CommandHandler("setemoji", setemoji))
    # app.add_handler(CommandHandler("myhorses", myhorses))
    # app.add_handler(CommandHandler("shopspells", shopupgrades))
    # app.add_handler(CommandHandler("buyspell", buyupgrade))
    # app.add_handler(CommandHandler("applyspell", applyupgrade))
    # app.add_handler(CommandHandler("unapplyspell", unapplyupgrade))

    app.add_handler(CommandHandler("admin", admin_help))
    app.add_handler(CommandHandler("listgroups", list_groups))
    app.add_handler(CommandHandler("broadcastgroup", broadcastgroups))

    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, on_new_chat_members))
    app.add_handler(CommandHandler("roulette", roulette_table_command))
    app.add_handler(CommandHandler("sync_groups", sync_group_names))

    # app.add_handler(CommandHandler("spin", spin))
    app.add_handler(CommandHandler("givechips", give_chips))

    app.add_handler(CommandHandler("broadcast", broadcast))
    app.add_handler(CommandHandler("repay_loan", repay_loan))
    app.add_handler(CommandHandler("loan", request_loan))
    app.add_handler(CommandHandler("minigames", minigames))

    app.add_handler(CommandHandler("dice", roll_dice))
    app.add_handler(CommandHandler("slot", slot_machine))
    app.add_handler(CommandHandler("coin", coinflip))
    app.add_handler(CommandHandler("draw", lucky_draw))
    app.add_handler(CommandHandler("rps", rps_game))
    app.add_handler(CommandHandler("dart", dart))
    app.add_handler(CommandHandler("daily_token", claim_daily_tokens))
    app.add_handler(CommandHandler("leaderboard", leaderboard))
    app.add_handler(CommandHandler("group", group))

    # app.add_handler(CommandHandler("spinrewards", spinrewards))

    app.add_handler(photo_handler)
    app.add_handler(CommandHandler("user_id", get_user_id_command))
    app.add_handler(CommandHandler("give_token", give_token))
    # app.add_handler(CommandHandler("buy_tokens", buy_tokens))
    # app.add_handler(CommandHandler("set_status", set_status))
    app.add_handler(CommandHandler("help", modern_help_command))
    app.add_handler(CommandHandler("rules", rules_command))
    # app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("highroller", highroller, block=False))

    app.add_handler(CommandHandler("startblackjack", start_blackjack, block=False))
    app.add_handler(CommandHandler("join", join_blackjack))
    app.add_handler(CommandHandler("forcestart", force_start))

    app.add_handler(PollAnswerHandler(poll_answer_handler))  # PollAnswerHandler for poll answers
    app.add_handler(PollAnswerHandler(handle_poll_response))

    app.add_handler(CommandHandler("my_tokens", get_player_chips))
    app.add_handler(CommandHandler("stand", stand))
    app.add_handler(CommandHandler("flee", flee_game))
    app.add_handler(CommandHandler("nextgame", nextgame))
    app.add_handler(CommandHandler("hit", hit))
    app.add_handler(CommandHandler("dealer_stats", get_dealer_blackjack_stats))
    app.add_handler(CommandHandler("achievements", my_achievements))
    app.add_handler(CommandHandler("achievements_info", achievement_info))

    app.add_handler(CommandHandler("chips", give_chips2))


def main():
    # Python 3.14 no longer creates an event loop implicitly in the main thread.
    # Application.run_polling() reuses the loop registered here.
    asyncio.set_event_loop(asyncio.new_event_loop())
    build_application().run_polling()


if __name__ == "__main__":
    main()
