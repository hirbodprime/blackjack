"""Small, typed translation catalog used by new and migrated bot surfaces."""

from collections.abc import Mapping


DEFAULT_LANGUAGE = "en"
SUPPORTED_LANGUAGES = {"en", "fa"}

MESSAGES: Mapping[str, Mapping[str, str]] = {
    "start.welcome": {
        "en": "🃏 Blackjack Bot\n\nWelcome back. Choose a section to explore:\n• View your profile and statistics\n• Play games and open boxes\n• Complete quests and earn rewards\n\nLet the cards decide your fate.",
        "fa": "🃏 ربات بلک‌جک\n\nخوش آمدید. یک بخش را انتخاب کنید:\n• مشاهده پروفایل و آمار\n• بازی‌ها و جعبه‌های جایزه\n• انجام مأموریت‌ها و دریافت پاداش\n\nبگذارید کارت‌ها سرنوشت را تعیین کنند.",
    },
    "menu.profile": {"en": "Profile", "fa": "پروفایل"},
    "menu.leaderboards": {"en": "Leaderboards", "fa": "رتبه‌بندی"},
    "menu.shop": {"en": "Shop", "fa": "فروشگاه"},
    "menu.social": {"en": "Social", "fa": "اجتماعی"},
    "menu.events": {"en": "Events", "fa": "رویدادها"},
    "menu.items": {"en": "Items", "fa": "آیتم‌ها"},
    "menu.quests": {"en": "Quests & rewards", "fa": "مأموریت‌ها و پاداش‌ها"},
    "menu.how_to_play": {"en": "How to play", "fa": "راهنمای بازی"},
    "menu.minigames": {"en": "Minigames", "fa": "مینی‌گیم‌ها"},
    "menu.settings": {"en": "Settings", "fa": "تنظیمات"},
    "menu.support": {"en": "Support", "fa": "پشتیبانی"},
    "play.title": {
        "en": "🎮 Main menu\n\nEverything you need is here. What would you like to do?",
        "fa": "🎮 منوی اصلی\n\nهمه‌چیز از اینجا در دسترس است. چه کاری می‌خواهید انجام دهید؟",
    },
    "hub.games": {"en": "🎮 Play games", "fa": "🎮 بازی‌ها"},
    "hub.rewards": {"en": "🎁 Rewards", "fa": "🎁 پاداش‌ها"},
    "hub.profile": {"en": "👤 My profile", "fa": "👤 پروفایل من"},
    "hub.social": {"en": "🤝 Social & market", "fa": "🤝 اجتماعی و بازار"},
    "hub.settings": {"en": "⚙️ Settings", "fa": "⚙️ تنظیمات"},
    "hub.help": {"en": "❓ Help", "fa": "❓ راهنما"},
    "hub.home": {"en": "🏠 Main menu", "fa": "🏠 منوی اصلی"},
    "hub.games_title": {"en": "🎮 Games\n\nChoose a game category:", "fa": "🎮 بازی‌ها\n\nیک دسته را انتخاب کنید:"},
    "hub.rewards_title": {"en": "🎁 Rewards\n\nClaim rewards and follow your missions:", "fa": "🎁 پاداش‌ها\n\nپاداش‌ها را بگیرید و مأموریت‌ها را دنبال کنید:"},
    "hub.profile_title": {"en": "👤 Profile\n\nView your progress and account activity:", "fa": "👤 پروفایل\n\nپیشرفت و فعالیت حساب خود را ببینید:"},
    "hub.social_title": {"en": "🤝 Social & marketplace\n\nPlay with friends and trade items safely:", "fa": "🤝 اجتماعی و بازار\n\nبا دوستان بازی کنید و آیتم‌ها را امن معامله کنید:"},
    "hub.settings_title": {"en": "⚙️ Settings\n\nChoose your language, notifications, and message style:", "fa": "⚙️ تنظیمات\n\nزبان، اعلان‌ها و نوع نمایش پیام را انتخاب کنید:"},
    "hub.help_title": {"en": "❓ Quick help\n\nUse the buttons to explore. Commands still work as shortcuts. In a group, start with /startblackjack, then players use /join. During your turn use /hit or /stand.", "fa": "❓ راهنمای سریع\n\nاز دکمه‌ها برای جابه‌جایی استفاده کنید. دستورها همچنان میانبر هستند. در گروه با /startblackjack شروع کنید، سپس بازیکنان /join بزنند. در نوبت خود از /hit یا /stand استفاده کنید."},
    "hub.language": {"en": "🌐 Language", "fa": "🌐 زبان"},
    "hub.notifications": {"en": "🔔 Notifications", "fa": "🔔 اعلان‌ها"},
    "hub.compact": {"en": "📝 Compact messages", "fa": "📝 پیام‌های خلاصه"},
    "hub.daily": {"en": "📆 Daily missions", "fa": "📆 مأموریت‌های روزانه"},
    "hub.weekly": {"en": "🗓 Weekly missions", "fa": "🗓 مأموریت‌های هفتگی"},
    "hub.achievements": {"en": "🏅 Achievements", "fa": "🏅 دستاوردها"},
    "hub.history": {"en": "💰 Chip history", "fa": "💰 تاریخچه چیپ"},
    "hub.market": {"en": "🛒 Marketplace", "fa": "🛒 بازار"},
    "hub.challenge": {"en": "⚔️ Friend challenges", "fa": "⚔️ رقابت دوستانه"},
    "onboarding.language": {"en": "Welcome! First, choose your language.\n\nخوش آمدید! ابتدا زبان خود را انتخاب کنید.", "fa": "خوش آمدید! ابتدا زبان خود را انتخاب کنید.\n\nWelcome! First, choose your language."},
    "onboarding.one": {"en": "👋 Welcome to Blackjack Bot!\n\nYou received starter chips. You can play blackjack in groups, try quick minigames, complete missions, and collect items.", "fa": "👋 به ربات بلک‌جک خوش آمدید!\n\nچیپ شروع دریافت کردید. می‌توانید در گروه بلک‌جک بازی کنید، مینی‌گیم‌ها را امتحان کنید، مأموریت انجام دهید و آیتم جمع کنید."},
    "onboarding.two": {"en": "🛡 A quick safety note\n\nChips are in-game currency only. Start with small bets, use /profile to review activity, and take breaks when you want.", "fa": "🛡 یک نکته مهم\n\nچیپ‌ها فقط پول داخل بازی هستند. با شرط کم شروع کنید، فعالیت خود را در /profile ببینید و هر زمان خواستید استراحت کنید."},
    "onboarding.ready": {"en": "✅ You're ready. Open the main menu and choose your first activity.", "fa": "✅ آماده‌اید. منوی اصلی را باز کنید و اولین فعالیت خود را انتخاب کنید."},
    "onboarding.next": {"en": "Next ➡️", "fa": "بعدی ➡️"},
    "onboarding.start": {"en": "Open main menu 🎮", "fa": "باز کردن منوی اصلی 🎮"},
    "play.blackjack": {"en": "🃏 Blackjack", "fa": "🃏 بلک‌جک"},
    "play.poker": {"en": "🃏 Texas Hold'em Poker", "fa": "🃏 پوکر تگزاس هولدم"},
    "play.minigames": {"en": "🎲 Minigames", "fa": "🎲 مینی‌گیم‌ها"},
    "play.horses": {"en": "🐎 Horses", "fa": "🐎 اسب‌ها"},
    "play.profile": {"en": "👤 Profile & history", "fa": "👤 پروفایل و تاریخچه"},
    "play.back": {"en": "◀️ Back", "fa": "◀️ بازگشت"},
    "play.blackjack_help": {
        "en": "🃏 Blackjack\n\n/startblackjack — open normal betting\n/highroller — high-stakes table\n/join — join the open table\n/hit — draw a card\n/stand — keep your hand\n/flee — leave before the game starts",
        "fa": "🃏 بلک‌جک\n\n/startblackjack — شروع شرط‌بندی عادی\n/highroller — میز شرط بالا\n/join — ورود به بازی\n/hit — دریافت کارت\n/stand — توقف\n/flee — خروج پیش از شروع بازی",
    },
    "play.poker_help": {
        "en": "🃏 Texas Hold'em cash poker\n\nChoose a buy-in / small blind below, or create a custom table with /poker <buy-in> [small blind]. Account chips become your table stack and return when you cash out. Cards and actions are sent privately.",
        "fa": "🃏 پوکر نقدی تگزاس هولدم\n\nورودی / اسمال بلایند را انتخاب کنید یا با /poker <ورودی> [اسمال بلایند] میز دلخواه بسازید. چیپ حساب به موجودی میز تبدیل می‌شود و هنگام برداشت برمی‌گردد. کارت‌ها و اکشن‌ها خصوصی ارسال می‌شوند.",
    },
    "play.minigames_help": {
        "en": "🎲 Minigames\n\n/slot <bet>\n/coin <heads|tails> <bet>\n/draw <bet>\n/rps <rock|paper|scissors> <bet>\n/dice <bet>\n/double <bet>\n/crash <bet> then /cashout\n/roulette <red|black|0-36> <bet>",
        "fa": "🎲 مینی‌گیم‌ها\n\n/slot <شرط>\n/coin <heads|tails> <شرط>\n/draw <شرط>\n/rps <rock|paper|scissors> <شرط>\n/dice <شرط>\n/double <شرط>\n/crash <شرط> سپس /cashout\n/roulette <red|black|0-36> <شرط>",
    },
    "play.horses_help": {
        "en": "🐎 Horse racing\n\n/horse — horse menu\n/horserace — create a race\n/joinrace <horse> <bet> — enter\n/startrace — begin the race",
        "fa": "🐎 مسابقه اسب‌دوانی\n\n/horse — منوی اسب\n/horserace — ساخت مسابقه\n/joinrace <اسب> <شرط> — ورود\n/startrace — شروع مسابقه",
    },
    "play.profile_help": {
        "en": "👤 Player tools\n\n/start — profile menu\n/stats — blackjack statistics\n/history — recent chip activity\n/leaderboard — rankings\n/language <en|fa> — language\n/compact <on|off> — compact output",
        "fa": "👤 ابزار بازیکن\n\n/start — منوی پروفایل\n/stats — آمار بلک‌جک\n/history — گردش اخیر چیپ‌ها\n/leaderboard — رتبه‌بندی\n/language <en|fa> — زبان\n/compact <on|off> — نمایش خلاصه",
    },
    "language.usage": {
        "en": "Usage: /language en or /language fa",
        "fa": "روش استفاده: /language en یا /language fa",
    },
    "language.changed": {
        "en": "Language changed to English.",
        "fa": "زبان به فارسی تغییر کرد.",
    },
    "language.group_admin_only": {
        "en": "Only group administrators can change this group's language.",
        "fa": "فقط مدیران گروه می‌توانند زبان این گروه را تغییر دهند.",
    },
    "group.blackjack_started": {
        "en": "A new Blackjack game has started in {group_name}!",
        "fa": "یک بازی جدید بلک‌جک در {group_name} شروع شده است!",
    },
    "group.blackjack_set_bet": {
        "en": "🃏 Set the bet amount for the Blackjack game to start.",
        "fa": "🃏 مبلغ شرط را برای شروع بازی بلک‌جک تعیین کنید.",
    },
    "group.blackjack_betting_started": {
        "en": "🃏 Betting has started!",
        "fa": "🃏 مرحله شرط‌بندی شروع شد!",
    },
    "group.highroller_set_bet": {
        "en": "🃏 Set your high-roller bet amount to start.",
        "fa": "🃏 مبلغ شرط سنگین را برای شروع تعیین کنید.",
    },
    "group.highroller_betting_started": {
        "en": "🃏 High-roller betting has started!",
        "fa": "🃏 شرط‌بندی سنگین شروع شد!",
    },
    "group.race_started_notice": {
        "en": "A new horse race has started in {group_name}!",
        "fa": "یک مسابقه اسب‌دوانی جدید در {group_name} شروع شده است!",
    },
    "group.race_started": {
        "en": "🐎 A new horse race has started!\nJoin with /joinrace <horse_number> <bet_amount> (no bets on Horse 1!)",
        "fa": "🐎 یک مسابقه اسب‌دوانی جدید شروع شد!\nبا /joinrace <شماره اسب> <مبلغ شرط> وارد شوید (شرط روی اسب ۱ مجاز نیست).",
    },
    "compact.usage": {
        "en": "Usage: /compact on or /compact off",
        "fa": "روش استفاده: /compact on یا /compact off",
    },
    "compact.changed": {
        "en": "Compact mode is now {state}.",
        "fa": "حالت خلاصه {state} شد.",
    },
    "history.empty": {
        "en": "No chip activity has been recorded yet.",
        "fa": "هنوز گردش چیپی ثبت نشده است.",
    },
    "history.title": {
        "en": "💰 Recent chip activity",
        "fa": "💰 گردش اخیر چیپ‌ها",
    },
    "history.row": {
        "en": "{amount} — {label} — balance {balance}",
        "fa": "{amount} — {label} — موجودی {balance}",
    },
}


def translate(key: str, language: str = DEFAULT_LANGUAGE, **values) -> str:
    catalog = MESSAGES.get(key)
    if catalog is None:
        return key
    selected = language if language in SUPPORTED_LANGUAGES else DEFAULT_LANGUAGE
    template = catalog.get(selected) or catalog[DEFAULT_LANGUAGE]
    return template.format(**values)
