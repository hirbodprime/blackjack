import random
from telegram import Update, Bot, BotCommand, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode,ChatType
from telegram.ext import ApplicationBuilder, CommandHandler, PollAnswerHandler, ContextTypes, MessageHandler, filters,CallbackQueryHandler, filters
from telegram.helpers import escape_markdown
import asyncio
from telegram.error import TimedOut,RetryAfter,BadRequest


import math

import os
import django

# Set the environment variable to point to your Django settings module
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'blackjack.settings')
from django.db.models import Sum, Avg, Count

# Initialize Django
django.setup()
from dotenv import load_dotenv
import time
import re
from game.models import (Game, Player, JoinGame,Stats,Dealer,RoundWinner,Group,ITEM_TYPE_CHOICES,
                         PlayerItem,PlayerActiveItem,UserSettings,
                         NextGameNotification,Achievement,ReferralEarning,
                         DailyQuest,PlayerDailyQuestProgress,
                         PlayerAchievement,HorseRaceWin,OwnedHorse,
                         GameParameter,QuestHistory,ActivePoll,
                         HorseAppliedUpgrade,HorseSale,CrashGame,
                         PlayerUpgrade,HorseUpgrade,generate_referral_code)
from game.models import ChipTransaction
from game.services.economy import (
    InsufficientDealerChips,
    InsufficientExperience,
    NoOutstandingLoan,
    adjust_balance_async,
    issue_loan_async,
    purchase_item_async,
    repay_loan_async,
    transfer_chips_async,
)
from game.services.blackjack import (
    ActiveInAnotherGame,
    AlreadyJoined,
    BettingPaused,
    InsufficientChips,
    join_game_with_chips_async,
    refund_joined_player_async,
)
from game.services.operations import (
    ensure_betting_open_async,
    get_bot_control_async,
    is_player_admin_async,
)
from game.telegram.update_guard import TelegramUpdateGuard
from game.telegram.runtime import (
    record_telegram_failure,
    telegram_error_handler,
    telegram_shutdown,
)
from game.telegram.player_experience import (
    compact_command,
    history_command,
    modern_help_command,
    language_command,
    onboarding_callback,
    onboarding_command,
    onboarding_language_keyboard,
    play_command,
    play_home_keyboard,
    play_menu_callback,
)
from game.telegram.retention import (
    buy_item_command, cancel_listing_command, challenge_command,
    marketplace_command, notifications_command, profile_command,
    retention_callback, sell_item_command, weekly_command,
)
from game.services.racing import (
    ActiveRaceBet,
    AlreadyBet,
    RaceAlreadyStarted,
    complete_race_async,
    place_race_bet_async,
    repair_recorded_races_async,
)
from game.services.crash import (
    ActiveCrashGame,
    NoActiveCrashGame,
    cash_out_crash_game_async,
    mark_crash_game_crashed_async,
    start_crash_game_async,
)
from game.services.chance import settle_roulette_async, settle_spin_async
from game.services.recovery import recover_interrupted_games_async
from game.services.mystery import open_mystery_box_async
from game.services.horses import (
    HorseNotOwned,
    HorseUnavailable,
    InvalidHorseSale,
    UpgradeAlreadyOwned,
    buy_horse_async,
    buy_horse_for_recipient_async,
    buy_horse_upgrade_async,
    customize_horse_async,
    gift_owned_horse_async,
    purchase_horse_sale_async,
)
from game.services.progression import award_xp_async, deduct_xp_amount_async
from game.services.referrals import award_referral_bonus_async
from game.services.rewards import (
    RewardAlreadyClaimed,
    claim_daily_box_async,
    claim_daily_chips_async,
    claim_daily_xp_async,
)
from game.services.quests import advance_daily_quest_async
from game.services.items import (
    ItemCategoryAlreadyActive,
    ItemUnavailable,
    activate_inventory_item_async,
    consume_xp_booster_async,
)
from game.services.language import group_language
from game.services.table_games import GroupTableBusy, ensure_blackjack_can_open
from game.services.rps_bot import choose_and_record_rps
from game.services.turns import (
    apply_player_timeout_async,
    begin_player_turn_async,
    record_player_action_async,
)
from game.economy_config import (
    MYSTERY_BOX_COOLDOWN_SECONDS,
    SIGNUP_REFERRED_REWARD,
    SIGNUP_REFERRER_REWARD,
    SLOT_JACKPOT_MULTIPLIER,
    SLOT_PAIR_MULTIPLIER,
    apply_potion_multiplier,
    horse_race_payout_pool,
    referral_share,
    standard_win_payout,
)

from django.core.exceptions import ObjectDoesNotExist
from asgiref.sync import sync_to_async
from game.models import HorseRace, HorseBet, Player


from datetime import datetime, timedelta
from django.utils import timezone
from lang import t
load_dotenv()
from asgiref.sync import sync_to_async


async def add_chips(
    player,
    amount,
    context=None,
    reason=None,
    *,
    category=None,
    reference_type="",
    reference_id="",
    idempotency_key=None,
):
    if category is None:
        category = (
            ChipTransaction.Category.QUEST_REWARD
            if reason == "Quest Reward"
            else ChipTransaction.Category.OTHER
        )

    await adjust_balance_async(
        player,
        amount,
        category=category,
        description=reason or "",
        reference_type=reference_type,
        reference_id=reference_id,
        idempotency_key=idempotency_key,
    )

    # if context:
    #     message = f"💰 You've received {amount} chips!"
    #     if reason:
    #         message += f"\n📌 Reason: {reason}"
    #     await context.bot.send_message(chat_id=player.id, text=message)

async def update_daily_quest_progress(player, quest_type, subtype=None, amount=1, context=None):
    from game.services.retention import advance_weekly_missions_async

    quest_notifications = True
    if context:
        user_settings, _ = await sync_to_async(UserSettings.objects.get_or_create)(player=player)
        quest_notifications = user_settings.notify_quests

    matching_quests = await sync_to_async(list)(DailyQuest.objects.filter(
        quest_type=quest_type,
        subtype=subtype,
        # date_assigned=today,
        available=True
    ))

    for quest in matching_quests:
        result = await advance_daily_quest_async(player.id, quest.id, amount)
        if result.completed_now and context and quest_notifications:
            for level, chips_reward in result.progression.level_rewards:
                await context.bot.send_message(
                    chat_id=player.id,
                    text=f"🎉 Congratulations! You've reached level {level}! You've been rewarded with {chips_reward} 💰 chips!",
                )
            await context.bot.send_message(
                chat_id=player.id,
                text=f"✅ Daily Quest Completed: {quest.description}\n🎁 Rewards: {quest.reward_xp} XP, {quest.reward_chips} Chips!"
            )
    weekly_completed = await advance_weekly_missions_async(
        player.id, quest_type, subtype, amount
    )
    if context and quest_notifications:
        for mission in weekly_completed:
            await context.bot.send_message(
                chat_id=player.id,
                text=f"✅ Weekly Mission Completed: {mission.description}\n"
                     f"🎁 Rewards: {mission.reward_xp} XP, {mission.reward_chips} Chips!",
            )



def escape_md(text):
    return re.sub(r'([_*[\]()~`>#+\-=|{}.!])', r'\\\1', text)

async def apply_referral_bonus(
    winner: Player,
    won_amount: int,
    context: ContextTypes.DEFAULT_TYPE
):
    """
    If `winner` was referred by someone, give that referrer 10% of won_amount
    (rounded down). Do NOT deduct from winner. Record the earning, and
    send the referrer a private Telegram message.
    """
    # ── (1) Fetch the referrer safely in a thread (no direct `winner.referrer` access)
    ref = await sync_to_async(lambda: winner.referrer)()
    if ref is None:
        return  # no referrer, no bonus

    bonus = referral_share(won_amount)
    if bonus <= 0:
        return

    change = await award_referral_bonus_async(
        ref.id,
        winner.id,
        bonus,
        description=f"Referral share of player {winner.id} winnings",
    )
    ref.chips = change.balance
    ref.total_referral_bonus += bonus

    # ── (4) Finally, DM the referrer in a safe async call
    try:
        await context.bot.send_message(
            chat_id=ref.id,
            text=(
                f"🎉 Hey {ref.name}! You just earned *{bonus} chips* "
                f"because {winner.name} won {won_amount} chips. Congrats! 🎁"
            ),
            parse_mode="Markdown"
        )
    except Exception:
        # If the bot can’t DM (user didn’t open a private chat), fail silently.
        pass



# NEW MENU





def build_support_menu():
    keyboard = [
        [
            InlineKeyboardButton("👥 Join Main Group", url="https://t.me/+JLQINcmYLZg3NDM0")
        ],
        [
            InlineKeyboardButton("📨 Contact Support", url="https://t.me/hirbodprime")
        ],
        [
            InlineKeyboardButton("🔙 Back to Main Menu", callback_data="menu:main")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)




def build_main_menu(language="en"):
    keyboard = [

        [
        InlineKeyboardButton(f"👤 {t('menu.profile', language)}", callback_data="menu:profile"),
        InlineKeyboardButton(f"🏆 {t('menu.leaderboards', language)}", callback_data="menu:leaderboards")
        ],
        [
        InlineKeyboardButton("🛍️ Shop", callback_data="menu:shop"),
        InlineKeyboardButton("🗣️ Social", callback_data="menu:social"),
        
        ],
        [
            InlineKeyboardButton(f"✨ {t('menu.events', language)}", callback_data="menu:tournaments"),
            InlineKeyboardButton(f"📦 {t('menu.items', language)}", callback_data="menu:items"),],
        [
        # InlineKeyboardButton("🎁 Mystery Boxes",    callback_data="shop:mystery_box"),
        
        ],
        [
            InlineKeyboardButton(f"🎯 {t('menu.quests', language)}", callback_data="menu:quests"),
        ],
        [
            InlineKeyboardButton(f"❓ {t('menu.how_to_play', language)}", callback_data="menu:howtoplay"),
            InlineKeyboardButton(f"🎮 {t('menu.minigames', language)}", callback_data="menu:minigames"),
        ],
        [
        InlineKeyboardButton(f"⚙️ {t('menu.settings', language)}", callback_data="menu:settings"),
        
        InlineKeyboardButton(f"❓ {t('menu.support', language)}", callback_data="menu:support")
        ],
    
    ]
    return InlineKeyboardMarkup(keyboard)
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tg_user   = update.message.from_user
    user_id   = tg_user.id
    user_name = tg_user.first_name

    
    try:
        player = await sync_to_async(Player.objects.get)(id=user_id)
        settings, _ = await sync_to_async(UserSettings.objects.get_or_create)(player=player)


        if not player.referral_code:
            code = generate_referral_code()
            while await sync_to_async(Player.objects.filter(referral_code=code).exclude(id=user_id).exists)():
                code = generate_referral_code()
            player.referral_code = code
            await sync_to_async(player.save)()

    except Player.DoesNotExist:

        if update.message.chat.type != ChatType.PRIVATE:
            await update.message.reply_text(
                "❗️Please message me in *private* to activate your profile.\nTap below 👇",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("📩 Start in Private", url=f"https://t.me/{context.bot.username}?start=start")]
                ])
            )
            return

        player = Player(id=user_id, name=user_name)
        await sync_to_async(player.save)()  # ✅ Save the player first

        settings, _ = await sync_to_async(UserSettings.objects.get_or_create)(player=player)
        settings.onboarding_complete = False
        await sync_to_async(settings.save)(update_fields=("onboarding_complete",))

        base_chips = 200
        bonus_chips = 0

        if context.args:
            code = context.args[0].strip()
            print(f"🔍 Referral code passed: {code}")
            try:
                referrer = await sync_to_async(Player.objects.get)(referral_code__iexact=code)
                if referrer.id != user_id:
                    player.referrer = referrer
                    bonus_chips = SIGNUP_REFERRED_REWARD
                    await award_referral_bonus_async(
                        referrer.id,
                        player.id,
                        SIGNUP_REFERRER_REWARD,
                        description="New-player referral reward",
                        idempotency_key=f"signup-referrer:{player.id}",
                    )
                    print(f"🎯 Referral applied! Referrer: {referrer.id}")
                else:
                    print("⚠️ Self-referral attempt blocked.")
            except Player.DoesNotExist:
                print("❌ Referral code not valid.")

        player.referrer = referrer if bonus_chips else None
        await sync_to_async(player.save)(update_fields=("referrer",))
        await adjust_balance_async(
            player,
            base_chips + bonus_chips,
            category=ChipTransaction.Category.REFERRAL_REWARD if bonus_chips else ChipTransaction.Category.DAILY_REWARD,
            description="New player starting balance",
            reference_type="player_signup",
            reference_id=player.id,
            idempotency_key=f"signup-balance:{player.id}",
        )
        print(f"💾 New player saved with {player.chips} chips")

        if bonus_chips:
            await context.bot.send_message(
                chat_id=player.id,
                text=f"🎉 You received *{bonus_chips} chips* for joining with a referral!",
                parse_mode="Markdown"
            )
            await context.bot.send_message(
                chat_id=player.referrer.id,
                text=f"🎉 Your friend *{player.name}* joined using your referral! You earned *{SIGNUP_REFERRER_REWARD} chips*!",
                parse_mode="Markdown"
            )
            print("📨 Referral bonus messages sent")

    try:
        await sync_to_async(Stats.objects.get)(player=player)
    except Stats.DoesNotExist:
        await sync_to_async(Stats.objects.create)(player=player, wins=0, loses=0, how_many_21=0)
        print("📊 Stats created")

    if not settings.onboarding_complete and update.message.chat.type == ChatType.PRIVATE:
        await update.message.reply_text(
            t("onboarding.language", settings.language),
            reply_markup=onboarding_language_keyboard(),
        )
    else:
        await play_command(update, context)



    print("✅ Start complete")
def build_notification_settings_menu(settings: UserSettings):
    def toggle_label(enabled: bool) -> str:
        return "✅" if enabled else "❌"

    keyboard = [
        [InlineKeyboardButton(f"{toggle_label(settings.notify_classic_blackjack_start)} Classic Blackjack Start", callback_data="toggle:notify_classic_blackjack_start"),
         InlineKeyboardButton(f"{toggle_label(settings.notify_race_start)} Race Start", callback_data="toggle:notify_race_start")
        ],
        [InlineKeyboardButton(f"{toggle_label(settings.notify_new_sales)} New Sales", callback_data="toggle:notify_new_sales"),InlineKeyboardButton(f"{toggle_label(settings.notify_new_events)} New Events", callback_data="toggle:notify_new_events")],
        # [InlineKeyboardButton(f"{toggle_label(settings.daily_token_reminder_enabled)} Daily Token Reminder", callback_data="toggle:daily_token_reminder_enabled"),InlineKeyboardButton(f"{toggle_label(settings.daily_dart_reminder)} Daily Dart Reminder", callback_data="toggle:daily_dart_reminder")],
        [ InlineKeyboardButton(f"{toggle_label(settings.notify_high_roller_blackjack_start)} High roller Blackjack Start", callback_data="toggle:notify_high_roller_blackjack_start")],
        [InlineKeyboardButton("🔙 Back to Settings", callback_data="menu:settings")]
    ]
    return InlineKeyboardMarkup(keyboard)

def build_special_passes_menu():
    keyboard = [
        [
            InlineKeyboardButton("🛡️ Insurance Pass (5k)",   callback_data="shop:insurance_pass"),
            InlineKeyboardButton("🃏 First-Hand-20 Pass (12k)", callback_data="shop:first_hand_20"),
        ],
        [
            InlineKeyboardButton("🔙 Back to Shop Menu", callback_data="shop:main"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)
# 1. Profile submenu
def build_profile_menu():
    keyboard = [
        [
            InlineKeyboardButton("🏅 Achievements", callback_data="profile:achievements"),
            InlineKeyboardButton("📊 Stats",        callback_data="profile:stats"),
        ],
        [
            InlineKeyboardButton("💎 My Tokens",    callback_data="profile:mytokens"),
            # Change this line ↓ to match your handler
            InlineKeyboardButton("🐎 My Races",     callback_data="profile:myraces"),
        ],
        [InlineKeyboardButton("🔙 Back to Main", callback_data="menu:main")],
    ]
    return InlineKeyboardMarkup(keyboard)

def build_leaderboards_menu():
    keyboard = [
        [
            InlineKeyboardButton("🐎 Horse Leaderboard", callback_data="menu:horse_leaderboard"),
            InlineKeyboardButton("🌍 Global Leaderboard", callback_data="menu:global_leaderboard"),
        ],
        [InlineKeyboardButton("🔙 Back to Main", callback_data="menu:main")],
    ]
    return InlineKeyboardMarkup(keyboard)
# ───────────────────────────────────────────────────────────────────────────────
def build_items_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("▶️ Activate Item",   callback_data="items:activate"),
         InlineKeyboardButton("⏸️ Deactivate Item", callback_data="items:deactivate")],
         [InlineKeyboardButton("📈 Use Boosters", callback_data="menu:boosters")],

        [InlineKeyboardButton("🔙 Back to Main",     callback_data="menu:main")],
    ])


def build_items_activate_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🧪 Potions",   callback_data="items:activate_potions"),],
        [InlineKeyboardButton("🛡️ Passes",   callback_data="items:activate_passes")],
        [InlineKeyboardButton("🔙 Back",      callback_data="menu:items")],
    ])


def build_items_deactivate_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🧪 Potions",   callback_data="items:deactivate_potions"),],
        [InlineKeyboardButton("🛡️ Passes",   callback_data="items:deactivate_passes")],
        [InlineKeyboardButton("🔙 Back",      callback_data="menu:items")],
    ])# 2. Shop submenu (placeholder)
# ─────────────────────────────────────────────────────────────────────────────
# Build “main Shop” menu (you already have this—just showing for context):
def build_shop_menu():
    keyboard = [
        [
            InlineKeyboardButton("📈 Boosters",      callback_data="shop:bj_boosters")
        ],
        [
            InlineKeyboardButton("🧪 Potions",       callback_data="shop:bj_potions"),
            InlineKeyboardButton("🛡️ Special Passes", callback_data="shop:bj_special_passes")
        ],
        [
            InlineKeyboardButton("🔙 Back to Main",     callback_data="menu:main"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


# ─────────────────────────────────────────────────────────────────────────────
# (A) “Shop → Blackjack Items” submenu
def build_blackjack_items_menu():
    keyboard = [
        [
            InlineKeyboardButton("🧪 Potions",       callback_data="shop:bj_potions"),
            InlineKeyboardButton("🛡️ Special Passes", callback_data="shop:bj_special_passes")
        ],
        [
            InlineKeyboardButton("🔙 Back to Shop", callback_data="shop:main"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


# ─────────────────────────────────────────────────────────────────────────────
# (B) “Shop → Potions” submenu
def build_bj_potions_menu():
    keyboard = [

        [
            InlineKeyboardButton("✨ Double Chip Potion", callback_data="shop:double_chip_potion"),
            InlineKeyboardButton("✨ Triple Chip Potion", callback_data="shop:triple_chip_potion"),
        ],
        [
            InlineKeyboardButton("✨ 10× Chip Potion",     callback_data="shop:10x_chip_potion"),
        ],
        [
            InlineKeyboardButton("🔙 Back to Shop",   callback_data="menu:shop"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


# ─────────────────────────────────────────────────────────────────────────────
# (C) “Shop → Boosters” submenu
def build_bj_boosters_menu():
    keyboard = [
        [
            InlineKeyboardButton("📈 +500 XP Booster",    callback_data="shop:xp_booster_500"),
            InlineKeyboardButton("📈 +2,000 XP Booster", callback_data="shop:xp_booster_2000"),
        ],
        [
            InlineKeyboardButton("📈 +15,000 XP Booster", callback_data="shop:xp_booster_15000"),
        ],
        [
            InlineKeyboardButton("📈 +50,000 XP Booster", callback_data="shop:xp_booster_50000"),
        ],
        [
            InlineKeyboardButton("🔙 Back to Shop",   callback_data="menu:shop"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


# ─────────────────────────────────────────────────────────────────────────────
# (D) “Shop → Special Passes” submenu
def build_bj_special_passes_menu():
    keyboard = [
        [
            InlineKeyboardButton("🛡️ Insurance Pass (5k)",    callback_data="shop:insurance_pass"),
            InlineKeyboardButton("🃏 First-Hand-20 Pass (8k)", callback_data="shop:first_hand_20_pass"),
            InlineKeyboardButton("🃏 First-Hand-11 Pass (12k)", callback_data="shop:first_hand_11_potion"),
        ],
        [
            InlineKeyboardButton("🔙 Back to Shop", callback_data="menu:shop"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


# ─────────────────────────────────────────────────────────────────────────────
# (E) “Shop → Mystery Boxes” submenu
def build_mystery_box_menu():
    keyboard = [
        [
            InlineKeyboardButton("🎁 Bronze", callback_data="shop:mystery_bronze"),
            InlineKeyboardButton("🎁 Silver", callback_data="shop:mystery_silver"),
        ],
        [
            InlineKeyboardButton("🎁 Gold", callback_data="shop:mystery_gold"),
            InlineKeyboardButton("💎 Platinum", callback_data="shop:mystery_platinum"),
        ],
        [
            
            InlineKeyboardButton("🔷 Diamond", callback_data="shop:mystery_diamond"),
            InlineKeyboardButton("🌟 Legendary", callback_data="shop:mystery_legendary"),
        ],
        [
            InlineKeyboardButton("🌀 Mythic", callback_data="shop:mystery_mythic"),
            InlineKeyboardButton("🌌 Cosmic", callback_data="shop:mystery_cosmic"),
        ],
        [
            InlineKeyboardButton("🔙 Back to Main", callback_data="menu:main"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)





# 4. Tournaments & Events submenu
def build_tournaments_menu():
    keyboard = [
        [
            InlineKeyboardButton("✨ Available Events", callback_data="tournaments:Events"),
            # InlineKeyboardButton("🏁 Upcoming Races", callback_data="tournaments:upcoming_races"),
        ],
        # [
        #     InlineKeyboardButton("🎫 Join Tournament", callback_data="tournaments:join"),
        #     InlineKeyboardButton("🏅 My Tournament History", callback_data="tournaments:history"),
        # ],
        [InlineKeyboardButton("🔙 Back to Main", callback_data="menu:main")],
    ]
    return InlineKeyboardMarkup(keyboard)

# 5. Quests & Rewards submenu
def build_quests_menu():
    keyboard = [
        [
            InlineKeyboardButton("💎 Daily Bonus", callback_data="quests:daily_rewards"),
            InlineKeyboardButton("📆 Daily Quests", callback_data="quests:daily_quests"),
        ],
        [
            InlineKeyboardButton("📅 Quest History", callback_data="quests:quest_history"),
        ],
        [InlineKeyboardButton("🔙 Back to Main", callback_data="menu:main")],
    ]
    return InlineKeyboardMarkup(keyboard)
def build_quests_menu_daily():
    keyboard = [
        [
            InlineKeyboardButton("💎 Daily Tokens", callback_data="quests:daily_bonus"),
            InlineKeyboardButton("🎁 Daily Mystery Box", callback_data="quests:daily_mystery_box"),
        ],
        [
            InlineKeyboardButton("✨ Daily XP", callback_data="quests:daily_xp"),
        ],
        [InlineKeyboardButton("🔙 Back", callback_data="menu:quests")],
    ]
    return InlineKeyboardMarkup(keyboard)
def build_daily_quests_menu():
    keyboard = [
        [InlineKeyboardButton("🃏 Classic Blackjack", callback_data="quest:daily_blackjack")],
        [InlineKeyboardButton("🎮 Minigames", callback_data="quest:daily_minigames")],
        [InlineKeyboardButton("🐎 Horse Race", callback_data="quest:daily_race")],
        [InlineKeyboardButton("🔙 Back", callback_data="menu:quests")]
    ]
    return InlineKeyboardMarkup(keyboard)


# 6. Social submenu
def build_social_menu():
    keyboard = [
        [
            InlineKeyboardButton("👥 Invite a Friend", callback_data="social:invite"),
        ],
        [InlineKeyboardButton("🔙 Back to Main", callback_data="menu:main")],
    ]
    return InlineKeyboardMarkup(keyboard)
# language
# 7. Settings submenu
def build_settings_menu():
    keyboard = [
        [
            InlineKeyboardButton("🌐 Change Language", callback_data="settings:language"),
        ],
        [
            InlineKeyboardButton("🔔 Notification Preferences", callback_data="settings:notifications"),
        ],
        [
            InlineKeyboardButton("🔙 Back to Main", callback_data="menu:main"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)
def build_language_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🇺🇸 English", callback_data="language:set:en")],
        [InlineKeyboardButton("🇮🇷 فارسی", callback_data="language:set:fa")],
        [InlineKeyboardButton("🔙 Back", callback_data="settings:menu")],
    ])

# 8. Support submenu

def build_back_to_profile_button():
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Profile", callback_data="play:profile")]])



ITEM_COSTS = {
    # Potions
    "double_chip_potion": 30000,
    "triple_chip_potion": 80000,
    "10x_chip_potion":    400000,
    # Boosters
    "xp_booster_500":     100000,
    "xp_booster_2000":    400000,
    "xp_booster_15000":   2800000,
    "xp_booster_50000":   9000000,
    # Special Passes
    "insurance_pass":     5000,
    "first_hand_20_pass": 12000,
    "first_hand_11_potion":8000,
    # … (any others, e.g. mystery boxes if you wire them up) …
}
