"""Localized player navigation, preferences, and account history handlers."""

from asgiref.sync import sync_to_async
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from game.i18n import SUPPORTED_LANGUAGES, translate
from game.models import ChipTransaction, Player, UserSettings
from game.services.language import (
    GROUP_CHAT_TYPES, language_for_update, set_group_language,
)


async def _settings_for(user_id: int) -> UserSettings | None:
    try:
        player = await sync_to_async(Player.objects.get)(pk=user_id)
    except Player.DoesNotExist:
        return None
    settings, _ = await sync_to_async(UserSettings.objects.get_or_create)(player=player)
    return settings


def _play_keyboard(language: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(translate("hub.games", language), callback_data="play:games"),
                InlineKeyboardButton(translate("hub.rewards", language), callback_data="play:rewards"),
            ],
            [
                InlineKeyboardButton(translate("hub.profile", language), callback_data="play:profile"),
                InlineKeyboardButton(translate("hub.social", language), callback_data="play:social"),
            ],
            [
                InlineKeyboardButton(translate("hub.settings", language), callback_data="play:settings"),
                InlineKeyboardButton(translate("hub.help", language), callback_data="play:help"),
            ],
        ]
    )


def play_home_keyboard(language: str) -> InlineKeyboardMarkup:
    return _play_keyboard(language)


def _back_keyboard(language: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(translate("play.back", language), callback_data="play:main")]]
    )


def _home_button(language: str):
    return [InlineKeyboardButton(translate("hub.home", language), callback_data="play:main")]


def _section_keyboard(page: str, language: str, compact_mode: bool = False):
    if page == "games":
        rows = [
            [InlineKeyboardButton(translate("play.blackjack", language), callback_data="play:blackjack")],
            [InlineKeyboardButton(translate("play.poker", language), callback_data="play:poker")],
            [InlineKeyboardButton(translate("play.minigames", language), callback_data="play:minigames")],
            [InlineKeyboardButton(translate("play.horses", language), callback_data="play:horses")],
        ]
    elif page == "rewards":
        rows = [
            [InlineKeyboardButton(translate("hub.daily", language), callback_data="menu:quests")],
            [InlineKeyboardButton(translate("hub.weekly", language), callback_data="play:weekly")],
            [InlineKeyboardButton(translate("hub.achievements", language), callback_data="profile:achievements")],
            [InlineKeyboardButton(translate("menu.items", language), callback_data="menu:items")],
        ]
    elif page == "profile":
        rows = [
            [InlineKeyboardButton(translate("hub.profile", language), callback_data="play:profile_summary")],
            [InlineKeyboardButton(translate("hub.history", language), callback_data="play:history")],
            [InlineKeyboardButton(translate("hub.achievements", language), callback_data="profile:achievements")],
            [InlineKeyboardButton(translate("menu.leaderboards", language), callback_data="menu:leaderboards")],
        ]
    elif page == "social":
        rows = [
            [InlineKeyboardButton(translate("hub.market", language), callback_data="play:market")],
            [InlineKeyboardButton(translate("hub.challenge", language), callback_data="play:challenge")],
            [InlineKeyboardButton(translate("menu.social", language), callback_data="menu:social")],
        ]
    elif page == "settings":
        state = "✅" if compact_mode else "❌"
        rows = [
            [InlineKeyboardButton(translate("hub.language", language), callback_data="play:language")],
            [InlineKeyboardButton(translate("hub.notifications", language), callback_data="play:notifications")],
            [InlineKeyboardButton(f"{state} {translate('hub.compact', language)}", callback_data="play:compact")],
        ]
    else:
        rows = []
    rows.append(_home_button(language))
    return InlineKeyboardMarkup(rows)


async def play_command(update, context) -> None:
    settings = await _settings_for(update.effective_user.id)
    language = await language_for_update(update)
    await update.effective_message.reply_text(
        translate("play.title", language),
        reply_markup=_play_keyboard(language),
    )


async def play_menu_callback(update, context) -> None:
    query = update.callback_query
    await query.answer()
    settings = await _settings_for(update.effective_user.id)
    language = await language_for_update(update)
    if settings is None:
        await query.edit_message_text("Please start the bot in private with /start.")
        return
    page = query.data.split(":", 1)[1]

    if page == "main":
        text = translate("play.title", language)
        keyboard = _play_keyboard(language)
    elif page in {"games", "rewards", "profile", "social", "settings"}:
        text = translate(f"hub.{page}_title", language)
        keyboard = _section_keyboard(page, language, settings.compact_mode if settings else False)
    elif page == "language":
        text = translate("hub.language", language)
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🇬🇧 English", callback_data="play:set_language:en")],
            [InlineKeyboardButton("🇮🇷 فارسی", callback_data="play:set_language:fa")],
            _home_button(language),
        ])
    elif page.startswith("set_language:"):
        selected = page.rsplit(":", 1)[1]
        if query.message.chat.type in GROUP_CHAT_TYPES:
            member = await context.bot.get_chat_member(query.message.chat.id, query.from_user.id)
            if member.status not in {"administrator", "creator", "owner"}:
                await query.answer(
                    "فقط مدیران گروه می‌توانند زبان را تغییر دهند." if language == "fa"
                    else "Only group administrators can change the language.",
                    show_alert=True,
                )
                return
            await set_group_language(
                query.message.chat.id,
                getattr(query.message.chat, "title", None),
                selected,
            )
        else:
            settings.language = selected
            await sync_to_async(settings.save)(update_fields=("language",))
        language = selected
        text = translate("language.changed", language)
        keyboard = _play_keyboard(language)
    elif page == "compact":
        settings.compact_mode = not settings.compact_mode
        await sync_to_async(settings.save)(update_fields=("compact_mode",))
        text = translate("hub.settings_title", language)
        keyboard = _section_keyboard("settings", language, settings.compact_mode)
    elif page == "notifications":
        from game.telegram.retention import _notifications_keyboard
        text = translate("hub.notifications", language)
        keyboard = _notifications_keyboard(settings, language)
    elif page == "weekly":
        from game.telegram.retention import build_weekly_text
        text = await build_weekly_text(query.from_user.id, language)
        keyboard = _section_keyboard("rewards", language)
    elif page == "profile_summary":
        from game.telegram.retention import build_profile_text
        text = await build_profile_text(query.from_user.id, language)
        keyboard = _section_keyboard("profile", language)
    elif page == "history":
        text = await build_history_text(query.from_user.id, language)
        keyboard = _section_keyboard("profile", language)
    elif page == "market":
        from game.telegram.retention import build_marketplace_view
        text, keyboard = await build_marketplace_view(query.from_user.id, language)
    elif page == "challenge":
        text = translate("hub.social_title", language) + "\n\n" + (
            "Reply to a friend's message with:\n/challenge dice 100\n/challenge rps 100\n/challenge blackjack 100"
            if language == "en" else
            "روی پیام دوستتان Reply بزنید و یکی از این دستورها را بفرستید:\n/challenge dice 100\n/challenge rps 100\n/challenge blackjack 100"
        )
        keyboard = _section_keyboard("social", language)
    elif page == "help":
        text = help_text(language)
        keyboard = _back_keyboard(language)
    elif page == "poker":
        text = translate("play.poker_help", language)
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("Buy-in 500 • Blinds 10/20" if language == "en" else "ورودی ۵۰۰ • بلایند ۱۰/۲۰", callback_data="poker:create:500:10")],
            [InlineKeyboardButton("Buy-in 1,000 • Blinds 20/40" if language == "en" else "ورودی ۱٬۰۰۰ • بلایند ۲۰/۴۰", callback_data="poker:create:1000:20")],
            [InlineKeyboardButton("Buy-in 5,000 • Blinds 100/200" if language == "en" else "ورودی ۵٬۰۰۰ • بلایند ۱۰۰/۲۰۰", callback_data="poker:create:5000:100")],
            _home_button(language),
        ])
    else:
        text = translate(f"play.{page}_help", language)
        keyboard = _back_keyboard(language)
    await query.edit_message_text(text=text, reply_markup=keyboard)


async def onboarding_callback(update, context) -> None:
    query = update.callback_query
    await query.answer()
    settings = await _settings_for(query.from_user.id)
    if settings is None:
        await query.edit_message_text("Please use /start first.")
        return
    parts = query.data.split(":")
    action = parts[1]
    if action == "language":
        settings.language = parts[2]
        await sync_to_async(settings.save)(update_fields=("language",))
        language = settings.language
        await query.edit_message_text(
            translate("onboarding.one", language),
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton(translate("onboarding.next", language), callback_data="onboarding:safety")
            ]]),
        )
    elif action == "safety":
        language = settings.language
        await query.edit_message_text(
            translate("onboarding.two", language),
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton(translate("onboarding.start", language), callback_data="onboarding:finish")
            ]]),
        )
    elif action == "finish":
        settings.onboarding_complete = True
        await sync_to_async(settings.save)(update_fields=("onboarding_complete",))
        await query.edit_message_text(
            translate("onboarding.ready", settings.language),
            reply_markup=_play_keyboard(settings.language),
        )


async def onboarding_command(update, context) -> None:
    settings = await _settings_for(update.effective_user.id)
    if settings is None:
        await update.effective_message.reply_text("Please use /start first.")
        return
    settings.onboarding_complete = False
    await sync_to_async(settings.save)(update_fields=("onboarding_complete",))
    await update.effective_message.reply_text(
        translate("onboarding.language", settings.language),
        reply_markup=onboarding_language_keyboard(),
    )


def onboarding_language_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🇬🇧 English", callback_data="onboarding:language:en")],
        [InlineKeyboardButton("🇮🇷 فارسی", callback_data="onboarding:language:fa")],
    ])


async def language_command(update, context) -> None:
    settings = await _settings_for(update.effective_user.id)
    current = await language_for_update(update)
    if settings is None and update.effective_chat.type not in GROUP_CHAT_TYPES:
        await update.effective_message.reply_text("Start the bot with /start first.")
        return
    if not context.args or context.args[0].lower() not in SUPPORTED_LANGUAGES:
        await update.effective_message.reply_text(translate("language.usage", current))
        return

    selected = context.args[0].lower()
    if update.effective_chat.type in GROUP_CHAT_TYPES:
        member = await context.bot.get_chat_member(
            update.effective_chat.id, update.effective_user.id
        )
        if member.status not in {"administrator", "creator", "owner"}:
            await update.effective_message.reply_text(
                "فقط مدیران گروه می‌توانند زبان را تغییر دهند."
                if current == "fa" else
                "Only group administrators can change the language."
            )
            return
        await set_group_language(
            update.effective_chat.id,
            getattr(update.effective_chat, "title", None),
            selected,
        )
    else:
        settings.language = selected
        await sync_to_async(settings.save)(update_fields=("language",))
    await update.effective_message.reply_text(
        translate("language.changed", selected)
    )


async def compact_command(update, context) -> None:
    settings = await _settings_for(update.effective_user.id)
    language = settings.language if settings else "en"
    if settings is None:
        await update.effective_message.reply_text("Start the bot with /start first.")
        return
    if not context.args or context.args[0].lower() not in {"on", "off"}:
        await update.effective_message.reply_text(translate("compact.usage", language))
        return

    settings.compact_mode = context.args[0].lower() == "on"
    await sync_to_async(settings.save)(update_fields=("compact_mode",))
    if language == "fa":
        state = "فعال" if settings.compact_mode else "غیرفعال"
    else:
        state = "on" if settings.compact_mode else "off"
    await update.effective_message.reply_text(
        translate("compact.changed", language, state=state)
    )


async def history_command(update, context) -> None:
    settings = await _settings_for(update.effective_user.id)
    language = settings.language if settings else "en"
    if settings is None:
        await update.effective_message.reply_text("Start the bot with /start first.")
        return

    limit = 5 if settings.compact_mode else 10
    text = await build_history_text(update.effective_user.id, language, limit)
    await update.effective_message.reply_text(text)


async def build_history_text(user_id: int, language: str | None = None, limit: int | None = None) -> str:
    settings = await _settings_for(user_id)
    language = language or (settings.language if settings else "en")
    limit = limit or (5 if settings and settings.compact_mode else 10)
    entries = await sync_to_async(list)(ChipTransaction.objects.filter(player_id=user_id)[:limit])
    if not entries:
        return translate("history.empty", language)

    rows = [translate("history.title", language)]
    for entry in entries:
        sign = "+" if entry.amount > 0 else ""
        label = entry.get_category_display()
        rows.append(translate(
            "history.row", language, amount=f"{sign}{entry.amount:,}",
            label=label, balance=f"{entry.balance_after:,}"
        ))
    return "\n".join(rows)


def help_text(language: str) -> str:
    if language == "fa":
        return (
            "❓ راهنمای ربات بلک‌جک\n\n"
            "شروع سریع\n"
            "• /play منوی اصلی را باز می‌کند.\n"
            "• در گروه، مدیر بازی /startblackjack را می‌زند.\n"
            "• بازیکنان با /join وارد می‌شوند.\n"
            "• در نوبت خود /hit برای کارت و /stand برای توقف بزنید.\n\n"
            "پوکر تگزاس هولدم\n"
            "از Play Games → Poker یک میز نقدی بسازید. کارت‌ها و دکمه‌های اکشن خصوصی می‌آیند؛ موجودی میز هنگام Cash Out به حساب برمی‌گردد.\n\n"
            "بازی‌های سریع\n"
            "از Play Games وارد شوید. بازی‌ها شامل اسلات، شیر یا خط، تاس، قرعه، "
            "سنگ‌کاغذقیچی، دابل، کرش و رولت هستند. قبل از تأیید، مبلغ شرط را بررسی کنید.\n\n"
            "پیشرفت و پاداش\n"
            "Daily و Weekly Missions، دستاوردها، XP، لِول و جعبه‌های جایزه از بخش Rewards در دسترس‌اند.\n\n"
            "دوستان و بازار\n"
            "در Social & Market می‌توانید آیتم معامله کنید. برای رقابت، روی پیام دوستتان Reply بزنید و "
            "/challenge dice 100 یا rps/blackjack را استفاده کنید. هر دو مبلغ شرط قبل از شروع امن نگه داشته می‌شود.\n\n"
            "حساب و امنیت\n"
            "Profile موجودی، آمار و تاریخچه چیپ را نشان می‌دهد. چیپ‌ها فقط پول داخل بازی هستند. "
            "کوچک شروع کنید، دنبال باخت نروید و هر زمان خواستید استراحت کنید.\n\n"
            "تنظیمات\n"
            "زبان، اعلان‌ها و پیام خلاصه از /play → Settings قابل تغییر است."
        )
    return (
        "❓ Blackjack Bot Guide\n\n"
        "Quick start\n"
        "• /play opens the main menu.\n"
        "• In a group, the host uses /startblackjack.\n"
        "• Players enter with /join.\n"
        "• On your turn, use /hit for another card or /stand to stop.\n\n"
        "Texas Hold'em poker\n"
        "Open Play Games → Poker to create a cash table. Hole cards and action buttons arrive privately; your table stack returns to your account when you cash out.\n\n"
        "Quick games\n"
        "Open Play Games for slots, coin flip, dice, lucky draw, rock-paper-scissors, double, crash, and roulette. "
        "Always check your stake before confirming.\n\n"
        "Progress and rewards\n"
        "Daily and Weekly Missions, achievements, XP, levels, and reward boxes are under Rewards.\n\n"
        "Friends and marketplace\n"
        "Social & Market lets you trade items. To challenge someone, reply to their message with "
        "/challenge dice 100, using rps or blackjack for the other modes. Both stakes are safely held before play.\n\n"
        "Account and safety\n"
        "Profile shows your balance, statistics, and chip history. Chips are in-game currency only. "
        "Start small, never chase losses, and take a break whenever you want.\n\n"
        "Settings\n"
        "Change language, notifications, and compact messages through /play → Settings."
    )


async def modern_help_command(update, context) -> None:
    language = await language_for_update(update)
    await update.effective_message.reply_text(
        help_text(language), reply_markup=_back_keyboard(language)
    )
