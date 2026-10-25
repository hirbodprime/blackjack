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
        "en": "♠️ Texas Hold'em\n\nPlayed right in the group on one live table:\n• Send /poker in a group and pick the stakes\n• Tap 🪑 Sit to join — even mid-hand (you play from the next deal)\n• Hands deal automatically; act with the buttons when it's your turn\n• 👀 My cards shows your hand privately — only you can see it\n• 🚪 Leave any time — you're cashed out at once or when the hand ends\n• /pokerraise <amount> for an exact raise",
        "fa": "♠️ پوکر تگزاس هولدم\n\nمستقیم داخل گروه روی یک میز زنده:\n• در گروه /poker بفرست و مبلغ را انتخاب کن\n• برای ورود 🪑 نشستن را بزن — حتی وسط دست (از دست بعد بازی می‌کنی)\n• کارت‌ها خودکار پخش می‌شوند؛ در نوبتت با دکمه‌ها بازی کن\n• 👀 کارت‌های من دستت را خصوصی نشان می‌دهد — فقط خودت می‌بینی\n• 🚪 هر وقت خواستی خارج شو — فوراً یا آخر دست تسویه می‌شوی\n• /pokerraise <مبلغ> برای ریز دقیق",
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
        "en": "🐎 A new horse race is open!\nTap 🐎 Place a bet, then 🏁 Start race when everyone is in.",
        "fa": "🐎 یک مسابقه اسب‌دوانی جدید باز شد!\n🐎 شرط ببند را بزن و وقتی همه آمدند 🏁 شروع مسابقه.",
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
    # ── Season 1 hub ───────────────────────────────────────────────────────
    "s1.brand": {"en": "🎰 BIG PAPA CASINO", "fa": "🎰 کازینو بیگ پاپا"},
    "s1.season": {"en": "Season {number} · {name} · {days}d left", "fa": "فصل {number} · {name} · {days} روز مانده"},
    "s1.no_season": {"en": "Off-season", "fa": "خارج از فصل"},
    "s1.chips": {"en": "💰 {chips} chips", "fa": "💰 {chips} چیپ"},
    "s1.streak": {"en": "🔥 Streak {streak}d · 📆 Daily {done}/{total}", "fa": "🔥 پشت‌سرهم {streak} روز · 📆 روزانه {done}/{total}"},
    "s1.season_pos": {"en": "🏁 Season rank #{rank} · {points} pts", "fa": "🏁 رتبه فصل #{rank} · {points} امتیاز"},
    "s1.live": {"en": "🔴 LIVE: {title} · ends in {left}", "fa": "🔴 زنده: {title} · پایان تا {left}"},
    "s1.next": {"en": "⏳ Next: {title} · in {left}", "fa": "⏳ بعدی: {title} · تا {left}"},
    "s1.btn_claim_horse": {"en": "🎁 Claim your FREE horse!", "fa": "🎁 اسب رایگانت را بگیر!"},
    "s1.btn_play": {"en": "🎮 Play", "fa": "🎮 بازی"},
    "s1.btn_daily": {"en": "📆 Daily", "fa": "📆 روزانه"},
    "s1.btn_compete": {"en": "🏆 Compete", "fa": "🏆 رقابت"},
    "s1.btn_stable": {"en": "🐎 Stable", "fa": "🐎 اصطبل"},
    "s1.btn_shop": {"en": "🛍 Shop", "fa": "🛍 فروشگاه"},
    "s1.btn_bag": {"en": "🎒 Bag", "fa": "🎒 کوله"},
    "s1.btn_profile": {"en": "👤 Profile", "fa": "👤 پروفایل"},
    "s1.btn_friends": {"en": "🤝 Friends", "fa": "🤝 دوستان"},
    "s1.btn_settings": {"en": "⚙️ Settings", "fa": "⚙️ تنظیمات"},
    "s1.btn_help": {"en": "❓ Help", "fa": "❓ راهنما"},
    "s1.btn_home": {"en": "🏠 Home", "fa": "🏠 خانه"},
    "s1.btn_season": {"en": "🌟 Season", "fa": "🌟 فصل"},
    "s1.btn_weekly": {"en": "📈 This week", "fa": "📈 این هفته"},
    "s1.btn_tournament": {"en": "⚔️ Tournament", "fa": "⚔️ تورنمنت"},
    "s1.btn_achievements": {"en": "🏅 Achievements", "fa": "🏅 دستاوردها"},
    "s1.btn_history": {"en": "💰 Chip history", "fa": "💰 تاریخچه چیپ"},
    "s1.btn_bonus": {"en": "💎 Daily bonus", "fa": "💎 جایزه روزانه"},
    "s1.btn_missions": {"en": "🗓 Weekly missions", "fa": "🗓 مأموریت هفتگی"},
    "s1.btn_add_group": {"en": "➕ Add me to a group", "fa": "➕ افزودن من به گروه"},
    "s1.play_title": {
        "en": "🎮 PLAY\n━━━━━━━━━━━━━━━\nTable games run in groups — add me to yours or join the main group.\nQuick games work anywhere.",
        "fa": "🎮 بازی\n━━━━━━━━━━━━━━━\nبازی‌های میزی در گروه اجرا می‌شوند — من را به گروهت اضافه کن یا به گروه اصلی بیا.\nبازی‌های سریع همه‌جا کار می‌کنند.",
    },
    "s1.daily_title": {"en": "📆 DAILY CHALLENGES\n━━━━━━━━━━━━━━━", "fa": "📆 چالش‌های روزانه\n━━━━━━━━━━━━━━━"},
    "s1.daily_footer": {
        "en": "Clear all three to grow your 🔥 streak (current: {streak}d, best: {best}d).\nNew challenges every day at 00:00 UTC.",
        "fa": "هر سه را کامل کن تا 🔥 زنجیره‌ات بیشتر شود (فعلی: {streak} روز، بهترین: {best} روز).\nچالش‌های جدید هر روز ساعت ۰۰:۰۰ UTC.",
    },
    "s1.compete_title": {
        "en": "🏆 COMPETE\n━━━━━━━━━━━━━━━\n🌟 Season — earn XP, climb the season ladder, top 10 win big.\n📈 Weekly — best net winnings Mon→Sun, top 5 paid.\n⚔️ Tournaments — every evening 17:00 UTC (20:30 Tehran), 2 hours, top 3 split {pool} chips.",
        "fa": "🏆 رقابت\n━━━━━━━━━━━━━━━\n🌟 فصل — XP بگیر، در جدول فصل بالا برو، ۱۰ نفر اول جایزه می‌گیرند.\n📈 هفتگی — بیشترین سود خالص دوشنبه تا یکشنبه، ۵ نفر اول جایزه.\n⚔️ تورنمنت — هر شب ساعت ۲۰:۳۰ تهران، ۲ ساعت، ۳ نفر اول {pool} چیپ را تقسیم می‌کنند.",
    },
    "s1.empty_board": {"en": "No scores yet — be the first!", "fa": "هنوز امتیازی ثبت نشده — اولین نفر باش!"},
    "s1.you": {"en": "You", "fa": "شما"},
    "s1.claim_intro": {
        "en": "🐴 YOUR FREE HORSE\n━━━━━━━━━━━━━━━\nEvery player gets one horse for Season 1 — free, forever yours.\n\nStep 1: reply with a name for your horse (max 20 characters).",
        "fa": "🐴 اسب رایگان تو\n━━━━━━━━━━━━━━━\nهر بازیکن در فصل ۱ یک اسب رایگان می‌گیرد — برای همیشه مال خودت.\n\nمرحله ۱: یک اسم برای اسبت بفرست (حداکثر ۲۰ کاراکتر).",
    },
    "s1.claim_pick": {
        "en": "🐴 {name}\n━━━━━━━━━━━━━━━\nStep 2: pick a starter powerup ({uses} races):",
        "fa": "🐴 {name}\n━━━━━━━━━━━━━━━\nمرحله ۲: یک پاورآپ شروع انتخاب کن ({uses} مسابقه):",
    },
    "s1.claim_done": {
        "en": "🎉 Welcome to the stable, {name}!\n\nHorse #{number} is yours with {powerup}.\nRace it in any group: start a race and tap 🐎 Place a bet.",
        "fa": "🎉 {name} به اصطبل خوش آمد!\n\nاسب شماره {number} با {powerup} مال توست.\nدر هر گروه مسابقه بساز و 🐎 شرط ببند را بزن.",
    },
    "s1.claim_have": {"en": "You already claimed your starter horse.", "fa": "اسب شروع خود را قبلاً گرفته‌ای."},
}


def translate(key: str, language: str = DEFAULT_LANGUAGE, **values) -> str:
    catalog = MESSAGES.get(key)
    if catalog is None:
        return key
    selected = language if language in SUPPORTED_LANGUAGES else DEFAULT_LANGUAGE
    template = catalog.get(selected) or catalog[DEFAULT_LANGUAGE]
    return template.format(**values)
