import random
from telegram import Update, Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode,ChatType
from telegram.ext import ApplicationBuilder, CommandHandler, PollAnswerHandler, ContextTypes, MessageHandler, filters,CallbackQueryHandler
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
from game.models import (Game, Player, JoinGame,Stats,Dealer,RoundWinner,Group,ITEM_TYPE_CHOICES,PlayerItem,PlayerActiveItem,
                         NextGameNotification,Achievement,ReferralEarning,
                         PlayerAchievement,HorseRaceWin,OwnedHorse,
                         HorseAppliedUpgrade,HorseSale,CrashGame,PlayerUpgrade,HorseUpgrade,generate_referral_code)

from django.core.exceptions import ObjectDoesNotExist
from asgiref.sync import sync_to_async
from game.models import HorseRace, HorseBet, Player


from datetime import datetime, timedelta
from django.utils import timezone

load_dotenv()
from asgiref.sync import sync_to_async


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

    bonus = int(won_amount * 0.10)
    if bonus <= 0:
        return

    # ── (2) Add bonus to referrer’s chips and total_referral_bonus
    # We already have `ref` as a Player instance; updating fields is fine in memory.
    ref.chips += bonus
    ref.total_referral_bonus += bonus
    # Persist it asynchronously
    await sync_to_async(ref.save)()

    # ── (3) Create the ReferralEarning record in a thread
    await sync_to_async(ReferralEarning.objects.create)(
        referrer=ref,
        referred=winner,
        amount=bonus
    )

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




def build_main_menu():
    keyboard = [

        [
        InlineKeyboardButton("👤 Profile", callback_data="menu:profile"),
        InlineKeyboardButton("🏆 Leaderboards", callback_data="menu:leaderboards")
        ],
        [
        InlineKeyboardButton("🛍️ Shop", callback_data="menu:shop"),
        InlineKeyboardButton("🗣️ Social", callback_data="menu:social"),
        
        ],
        [
            InlineKeyboardButton("🎁 Mystery Boxes",    callback_data="shop:mystery_box"),
            InlineKeyboardButton("📦 Items",    callback_data="menu:items"),],
        # [
        # InlineKeyboardButton("🎯 Quests & Rewards", callback_data="menu:quests"),
        # InlineKeyboardButton("🏁 Tournaments & Events", callback_data="menu:tournaments")
        # ],
        [
            InlineKeyboardButton("❓ How to Play", callback_data="menu:howtoplay"),
            InlineKeyboardButton("🎮 Minigames",   callback_data="menu:minigames"),
        ],
        [
        # InlineKeyboardButton("⚙️ Settings", callback_data="menu:settings"),
        
        InlineKeyboardButton("❓ Support", callback_data="menu:support")
        ],
    
    ]
    return InlineKeyboardMarkup(keyboard)
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tg_user   = update.message.from_user
    user_id   = tg_user.id
    user_name = tg_user.first_name

    print(f"➡️ /start from {user_id} - {user_name}")
    
    try:
        player = await sync_to_async(Player.objects.get)(id=user_id)
        print(f"✅ Player {user_id} already exists")

        if not player.referral_code:
            print("🔧 Generating referral code for existing user")
            code = generate_referral_code()
            while await sync_to_async(Player.objects.filter(referral_code=code).exclude(id=user_id).exists)():
                code = generate_referral_code()
            player.referral_code = code
            await sync_to_async(player.save)()
            print(f"✅ Referral code set: {player.referral_code}")

    except Player.DoesNotExist:
        print(f"🆕 New player: {user_id}")
        if update.message.chat.type != ChatType.PRIVATE:
            print("❗️ Not in private chat — aborting.")
            await update.message.reply_text(
                "❗️Please message me in *private* to activate your profile.\nTap below 👇",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("📩 Start in Private", url=f"https://t.me/{context.bot.username}?start=start")]
                ])
            )
            return

        player = Player(id=user_id, name=user_name)
        base_chips = 200
        bonus_chips = 0

        if context.args:
            code = context.args[0].strip()
            print(f"🔍 Referral code passed: {code}")
            try:
                referrer = await sync_to_async(Player.objects.get)(referral_code__iexact=code)
                if referrer.id != user_id:
                    player.referrer = referrer
                    bonus_chips = 400
                    referrer.chips += 1000
                    await sync_to_async(referrer.save)()
                    print(f"🎯 Referral applied! Referrer: {referrer.id}")
                else:
                    print("⚠️ Self-referral attempt blocked.")
            except Player.DoesNotExist:
                print("❌ Referral code not valid.")

        player.chips = base_chips + bonus_chips
        await sync_to_async(player.save)()
        print(f"💾 New player saved with {player.chips} chips")

        if bonus_chips:
            await context.bot.send_message(
                chat_id=player.id,
                text=f"🎉 You received *{bonus_chips} chips* for joining with a referral!",
                parse_mode="Markdown"
            )
            await context.bot.send_message(
                chat_id=player.referrer.id,
                text=f"🎉 Your friend *{player.name}* joined using your referral! You earned *1000 chips*!",
                parse_mode="Markdown"
            )
            print("📨 Referral bonus messages sent")

    try:
        await sync_to_async(Stats.objects.get)(player=player)
    except Stats.DoesNotExist:
        await sync_to_async(Stats.objects.create)(player=player, wins=0, loses=0, how_many_21=0)
        print("📊 Stats created")

    await update.message.reply_text(
        "*BlackJack Bot Menu* 💥\n\nChoose an option below:",
        parse_mode="Markdown",
        reply_markup=build_main_menu()
    )
    print("✅ Start complete")

def build_special_passes_menu():
    keyboard = [
        [
            InlineKeyboardButton("🛡️ Insurance Pass (5k)",   callback_data="shop:insurance_pass"),
            InlineKeyboardButton("🃏 First-Hand-20 Pass (8k)", callback_data="shop:first_hand_20"),
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
            InlineKeyboardButton("✨ Double Chip Potion (7.5k)", callback_data="shop:double_chip_potion"),
            InlineKeyboardButton("✨ Triple Chip Potion (15k)", callback_data="shop:triple_chip_potion"),
        ],
        [
            InlineKeyboardButton("✨ 10× Chip Potion (30k)",     callback_data="shop:10x_chip_potion"),
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
            InlineKeyboardButton("📈 +500 XP Booster (20k)",    callback_data="shop:xp_booster_500"),
            InlineKeyboardButton("📈 +2,000 XP Booster (100k)", callback_data="shop:xp_booster_2000"),
        ],
        [
            InlineKeyboardButton("📈 +15,000 XP Booster (400k)", callback_data="shop:xp_booster_15000"),
        ],
        [
            InlineKeyboardButton("📈 +50,000 XP Booster (1M)", callback_data="shop:xp_booster_50000"),
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
            InlineKeyboardButton("🃏 First-Hand-11 Pass (16k)", callback_data="shop:first_hand_11_potion"),
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
            InlineKeyboardButton("🎁 Bronze Mystery Box (1k)",  callback_data="shop:mystery_bronze"),
            InlineKeyboardButton("🎁 Silver Mystery Box (2.5k)", callback_data="shop:mystery_silver"),
        ],
        [
            InlineKeyboardButton("🎁 Gold Mystery Box (5k)",     callback_data="shop:mystery_gold"),
        ],
        [
            InlineKeyboardButton("🔙 Back to Shop",              callback_data="shop:main"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)





# 4. Tournaments & Events submenu
def build_tournaments_menu():
    keyboard = [
        [
            InlineKeyboardButton("🏁 Upcoming Races", callback_data="tournaments:upcoming_races"),
        ],
        [
            InlineKeyboardButton("🎫 Join Tournament", callback_data="tournaments:join"),
            InlineKeyboardButton("🏅 My Tournament History", callback_data="tournaments:history"),
        ],
        [InlineKeyboardButton("🔙 Back to Main", callback_data="menu:main")],
    ]
    return InlineKeyboardMarkup(keyboard)

# 5. Quests & Rewards submenu
def build_quests_menu():
    keyboard = [
        [
            InlineKeyboardButton("💎 Daily Bonus", callback_data="quests:daily_bonus"),
            InlineKeyboardButton("📆 Daily Quests", callback_data="quests:daily_quests"),
        ],
        [
            InlineKeyboardButton("📅 Weekly Challenges", callback_data="quests:weekly_challenges"),
        ],
        [InlineKeyboardButton("🔙 Back to Main", callback_data="menu:main")],
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

# 7. Settings submenu
def build_settings_menu():
    keyboard = [
        [
            InlineKeyboardButton("🔔 Notification Preferences", callback_data="settings:notifications"),
        ],
        [InlineKeyboardButton("🔙 Back to Main", callback_data="menu:main")],
    ]
    return InlineKeyboardMarkup(keyboard)

# 8. Support submenu

def build_back_to_profile_button():
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Profile", callback_data="menu:profile")]])



ITEM_COSTS = {
    # Potions
    "double_chip_potion": 17500,
    "triple_chip_potion": 40000,
    "10x_chip_potion":    100000,
    # Boosters
    "xp_booster_500":     20000,
    "xp_booster_2000":    100000,
    "xp_booster_15000":   400000,
    "xp_booster_50000":   1000000,
    # Special Passes
    "insurance_pass":     5000,
    "first_hand_20_pass": 8000,
    "first_hand_11_potion":12000,
    # … (any others, e.g. mystery boxes if you wire them up) …
}

async def purchase_item(player: Player, item_type: str):
    cost = ITEM_COSTS.get(item_type)
    if cost is None:
        return False, "Invalid item."

    if player.chips < cost:
        return False, "You don’t have enough chips."

    # Deduct cost
    player.chips -= cost
    await sync_to_async(player.save)()

    # Add to inventory (PlayerItem)
    pi, _ = await sync_to_async(PlayerItem.objects.get_or_create)(
        player=player, item_type=item_type
    )
    pi.quantity += 1
    await sync_to_async(pi.save)()

    human_name = dict(ITEM_TYPE_CHOICES)[item_type]
    return True, f"✅ You purchased 1× {human_name} for {cost:,} chips."



async def purchase_item(player: Player, item_type: str):
    cost = ITEM_COSTS.get(item_type)
    if cost is None:
        return False, "Invalid item."

    if player.chips < cost:
        return False, "You don’t have enough chips."

    # Deduct cost
    player.chips -= cost
    await sync_to_async(player.save)()

    # Add to inventory (PlayerItem)
    pi, _ = await sync_to_async(PlayerItem.objects.get_or_create)(
        player=player, item_type=item_type
    )
    pi.quantity += 1
    await sync_to_async(pi.save)()

    human_name = dict(ITEM_TYPE_CHOICES)[item_type]
    return True, f"✅ You purchased 1× {human_name} for {cost:,} chips."
# At the top of your module, define category‐lists so we know which item types belong where:
POTION_TYPES = [
    
    "double_chip_potion", "triple_chip_potion", "10x_chip_potion"
]
BOOSTER_TYPES = [
    "xp_booster_500", "xp_booster_2000", "xp_booster_15000", "xp_booster_50000"
]
PASS_TYPES = ["insurance_pass", "first_hand_20_pass", "first_hand_11_potion"]

# Your existing imports should include something like:
# from datetime import datetime
# from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
# from telegram.ext import ContextTypes
# from asgiref.sync import sync_to_async
# from your_app.models import Player, PlayerItem, PlayerActiveItem, ITEM_TYPE_CHOICES
# from your_app.xp_utils import add_xp  # the helper that grants XP + levels

async def handle_items_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Dedicated handler for all callback_data beginning with "items:" or exactly "menu:items".
    For BOOSTERS, we now 'use' them (granting XP) rather than leaving them 'active.'
    The UI text has been adjusted so that Boosters show up under "Activate Boosters" but 
    their buttons read "Use <Booster Name>."
    """
    query = update.callback_query
    data = query.data
    user_id = query.from_user.id

    # Answer every callback to remove the “loading” state spinner
    await query.answer()

    # 1) Ensure player exists
    try:
        player = await sync_to_async(Player.objects.get)(id=user_id)
    except Player.DoesNotExist:
        # If no Player record, prompt them to /start
        await query.edit_message_text(
            text="❗️ You don’t have a player profile yet. Send /start in private to create one.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Back to Main", callback_data="menu:main")]
            ])
        )
        return
    if data == "menu:boosters":
        qs = PlayerItem.objects.filter(player=player, item_type__in=BOOSTER_TYPES, quantity__gt=0)
        owned = await sync_to_async(list)(qs)

        if not owned:
            await query.edit_message_text(
                text="📈 *Your Boosters* 📈\n\nYou don’t have any boosters to use.",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 Back", callback_data="menu:items")]
                ])
            )
            return

        lines = ["📈 *Your Boosters* 📈", ""]
        keyboard = []
        for item in owned:
            name = dict(ITEM_TYPE_CHOICES)[item.item_type]
            lines.append(f"• {name} (x{item.quantity})")
            keyboard.append([
                InlineKeyboardButton(f"Use {name}", callback_data=f"items:use_booster:{item.item_type}")
            ])

        keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="menu:items")])

        await query.edit_message_text(
            text="\n".join(lines),
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    # ── (A) Top‐level “Items” menu ─────────────────────────────────────────────────
    if data == "menu:items":
        await query.edit_message_text(
            text="📦 *Your Items* 📦\n\nDo you want to activate or deactivate an item?",
            parse_mode="Markdown",
            reply_markup=build_items_menu()
        )
        return

    # ── (B) “Activate” submenu ───────────────────────────────────────────────────
    if data == "items:activate":
        await query.edit_message_text(
            text="▶️ *Activate Item* ▶️\n\nChoose a category:",
            parse_mode="Markdown",
            reply_markup=build_items_activate_menu()
        )
        return

    # ── (C.1) “Activate → Potions” ──────────────────────────────────────────────
    if data == "items:activate_potions":
        qs = PlayerItem.objects.filter(
            player=player,
            item_type__in=POTION_TYPES,
            quantity__gt=0
        )
        owned_items = await sync_to_async(list)(qs)

        if not owned_items:
            await query.edit_message_text(
                text="🧪 *Activate Potions* 🧪\n\nYou don’t own any potions.",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 Back", callback_data="items:activate")]
                ])
            )
            return

        lines = ["🧪 *Activate Potions* 🧪", ""]
        keyboard = []
        for pi in owned_items:
            human_name = dict(ITEM_TYPE_CHOICES)[pi.item_type]
            lines.append(f"• {human_name}  (You have: {pi.quantity})")
            keyboard.append([
                InlineKeyboardButton(
                    f"Activate {human_name}",
                    callback_data=f"items:activate:{pi.item_type}"
                )
            ])

        lines.append("")
        keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="items:activate")])
        text = "\n".join(lines)

        await query.edit_message_text(
            text=text,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    # ── (C.2) “Activate → Passes” ─────────────────────────────────────────────────
    if data == "items:activate_passes":
        qs = PlayerItem.objects.filter(
            player=player,
            item_type__in=PASS_TYPES,
            quantity__gt=0
        )
        owned_items = await sync_to_async(list)(qs)

        if not owned_items:
            await query.edit_message_text(
                text="🛡️ *Activate Passes* 🛡️\n\nYou don’t own any passes.",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 Back", callback_data="items:activate")]
                ])
            )
            return

        lines = ["🛡️ *Activate Passes* 🛡️", ""]
        keyboard = []
        for pi in owned_items:
            human_name = dict(ITEM_TYPE_CHOICES)[pi.item_type]
            lines.append(f"• {human_name}  (You have: {pi.quantity})")
            keyboard.append([
                InlineKeyboardButton(
                    f"Activate {human_name}",
                    callback_data=f"items:activate:{pi.item_type}"
                )
            ])

        lines.append("")
        keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="items:activate")])
        text = "\n".join(lines)

        await query.edit_message_text(
            text=text,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

  
    # ── (C.4) “Use Booster → items:use_booster:<item_type>” ────────────────────────
    if data.startswith("items:use_booster:"):
        _, _, item_type = data.split(":", 2)
        print(f"[DEBUG] Using booster: {item_type}")

        # 1) Fetch PlayerItem
        try:
            pi = await sync_to_async(PlayerItem.objects.get)(player=player, item_type=item_type)
        except PlayerItem.DoesNotExist:
            await query.edit_message_text(
                text="❗️ You don’t own that booster.",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton(
                        "🔙 Back to Items",
                        callback_data="menu:items"
                    )],
                    [InlineKeyboardButton("🔙 Back to Activate Menu",    callback_data="items:activate")]
                ])
            )
            return

        if pi.quantity < 1:
            await query.edit_message_text(
                text="❗️ You don’t have any of that booster left.",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton(
                        "🔙 Back to Items",
                        callback_data="menu:items"
                    )],
                    [InlineKeyboardButton("🔙 Back to Activate Menu",    callback_data="items:activate")]
                ])
            )
            return

        # 2) Decrement inventory
        pi.quantity -= 1
        await sync_to_async(pi.save)()
        print(f"[DEBUG] Decremented {item_type}, new qty={pi.quantity}")

        # 3) Determine XP amount based on item_type
        if item_type == "xp_booster_500":
            xp_amount = 500
        elif item_type == "xp_booster_2000":
            xp_amount = 2000
        elif item_type == "xp_booster_15000":
            xp_amount = 15000
        elif item_type == "xp_booster_50000":
            xp_amount = 50000
        else:
            xp_amount = 0

        # 4) Award XP (this will handle leveling, chip rewards, and level‐up messages)
        if xp_amount > 0:
            await add_xp(player, xp_amount, context)
            print(f"[DEBUG] Added {xp_amount} XP to player {player.id}")
        else:
            print(f"[WARN] No XP rule for {item_type}")

        human_name = dict(ITEM_TYPE_CHOICES)[item_type]
        await query.edit_message_text(
            text=f"✅ You activated 1× {human_name}! You gained {xp_amount} XP.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "🔙 Back to Items",
                        callback_data="menu:items"
                    )
                ],

            ])
        )
        return

    # ── (C.5) “Activate → Potions or Passes” (handles activating potions & passes) ─
    if data.startswith("items:activate:"):
        _, _, item_type = data.split(":", 2)

        # ---- Fetch PlayerItem ----
        try:
            pi = await sync_to_async(PlayerItem.objects.get)(player=player, item_type=item_type)
        except PlayerItem.DoesNotExist:
            await query.answer("❗️ You don’t own that item.", show_alert=True)
            return

        if pi.quantity < 1:
            await query.answer("❗️ You don’t have any left to activate.", show_alert=True)
            return

        # ---- Determine category of item_type ----
        if item_type in POTION_TYPES:
            category_list = POTION_TYPES
            category_name = "potion"
        elif item_type in PASS_TYPES:
            category_list = PASS_TYPES
            category_name = "pass"
        else:
            category_list = []
            category_name = None

        # ---- Check if another item in same category is already active ----
        if category_list:
            already_active = await sync_to_async(
                PlayerActiveItem.objects.filter(
                    player=player,
                    item_type__in=category_list,
                    is_active=True
                ).exists
            )()
            if already_active:
                # Edit the message to tell them to deactivate first
                # The “Back to Deactivate X” button depends on category
                if category_name == "potion":
                    back_btn = InlineKeyboardButton(
                        "🔙 Back to Deactivate Potions",
                        callback_data="items:deactivate_potions"
                    )
                else:  # category_name == "pass"
                    back_btn = InlineKeyboardButton(
                        "🔙 Back to Deactivate Passes",
                        callback_data="items:deactivate_passes"
                    )

                await query.edit_message_text(
                    text=(
                        f"❗️ You already have an active {category_name}. "
                        "Deactivate it before activating a new one."
                    ),
                    parse_mode="Markdown",
                    reply_markup=InlineKeyboardMarkup([
                        [back_btn],
                        [InlineKeyboardButton("🔙 Back to Activate Menu", callback_data="items:activate")]
                    ])
                )
                return

        # ---- No other active item in this category → activate it now ----
        pi.quantity -= 1
        await sync_to_async(pi.save)()

        await sync_to_async(PlayerActiveItem.objects.create)(
            player=player,
            item_type=item_type,
            activated_at=datetime.utcnow(),
            is_active=True
        )

        human_name = dict(ITEM_TYPE_CHOICES)[item_type]

        # Build “Back to <category>” dynamically
        if category_name == "potion":
            back_to_category = InlineKeyboardButton(
                "🔙 Back to Potions",
                callback_data="items:activate_potions"
            )
        else:  # category_name == "pass"
            back_to_category = InlineKeyboardButton(
                "🔙 Back to Passes",
                callback_data="items:activate_passes"
            )

        await query.edit_message_text(
            text=f"✅ You activated 1× {human_name}!",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [back_to_category],
                [InlineKeyboardButton("🔙 Back to Activate Menu", callback_data="items:activate")]
            ])
        )
        return

    # ── (D) “Deactivate” submenu ──────────────────────────────────────────────────
    if data == "items:deactivate":
        await query.edit_message_text(
            text="⏸️ *Deactivate Item* ⏸️\n\nChoose a category:",
            parse_mode="Markdown",
            reply_markup=build_items_deactivate_menu()
        )
        return

    # ── (D.1) “Deactivate → Potions” ───────────────────────────────────────────────
    if data == "items:deactivate_potions":
        qs = PlayerActiveItem.objects.filter(
            player=player,
            item_type__in=POTION_TYPES,
            is_active=True
        )
        active_list = await sync_to_async(list)(qs)

        if not active_list:
            await query.edit_message_text(
                text="🧪 *Deactivate Potions* 🧪\n\nYou have no active potions.",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 Back", callback_data="items:deactivate")]
                ])
            )
            return

        lines = ["🧪 *Deactivate Potions* 🧪", ""]
        keyboard = []
        for ai in active_list:
            human_name = dict(ITEM_TYPE_CHOICES)[ai.item_type]
            ts = ai.activated_at.strftime("%Y-%m-%d %H:%M")
            lines.append(f"• {human_name} (activated at {ts})")
            keyboard.append([
                InlineKeyboardButton(
                    f"Deactivate {human_name}",
                    callback_data=f"items:deactivate:{ai.id}"
                )
            ])

        lines.append("")
        keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="items:deactivate")])
        text = "\n".join(lines)

        await query.edit_message_text(
            text=text,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

 

    # ── (D.3) “Deactivate → Passes” ────────────────────────────────────────────────
    if data == "items:deactivate_passes":
        qs = PlayerActiveItem.objects.filter(
            player=player,
            item_type__in=PASS_TYPES,
            is_active=True
        )
        active_list = await sync_to_async(list)(qs)

        if not active_list:
            await query.edit_message_text(
                text="🛡️ *Deactivate Passes* 🛡️\n\nYou have no active passes.",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 Back", callback_data="items:deactivate")]
                ])
            )
            return

        lines = ["🛡️ *Deactivate Passes* 🛡️", ""]
        keyboard = []
        for ai in active_list:
            human_name = dict(ITEM_TYPE_CHOICES)[ai.item_type]
            ts = ai.activated_at.strftime("%Y-%m-%d %H:%M")
            lines.append(f"• {human_name} (activated at {ts})")
            keyboard.append([
                InlineKeyboardButton(
                    f"Deactivate {human_name}",
                    callback_data=f"items:deactivate:{ai.id}"
                )
            ])

        lines.append("")
        keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="items:deactivate")])
        text = "\n".join(lines)

        await query.edit_message_text(
            text=text,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    # ── (D.4) “Actually deactivate → items:deactivate:<active_id>” ─────────────────
    if data.startswith("items:deactivate:"):
        _, _, active_id_str = data.split(":", 2)
        try:
            active_id = int(active_id_str)
        except ValueError:
            await query.answer("❗️ Invalid selection.", show_alert=True)
            return

        try:
            ai = await sync_to_async(PlayerActiveItem.objects.get)(id=active_id, player=player)
        except PlayerActiveItem.DoesNotExist:
            await query.answer("❗️ That active item no longer exists.", show_alert=True)
            return

        if not ai.is_active:
            await query.answer("❗️ That item is already deactivated.", show_alert=True)
            return

        # Deactivate it
        ai.is_active = False
        await sync_to_async(ai.save)()

        human_name = dict(ITEM_TYPE_CHOICES)[ai.item_type]

        # Build “Back to Deactivate <Category>” dynamically
        if ai.item_type in POTION_TYPES:
            back_to_category_btn = InlineKeyboardButton(
                "🔙 Back to Deactivate Potions",
                callback_data="items:deactivate_potions"
            )
        else:  # ai.item_type in PASS_TYPES
            back_to_category_btn = InlineKeyboardButton(
                "🔙 Back to Deactivate Passes",
                callback_data="items:deactivate_passes"
            )

        back_to_menu_btn = InlineKeyboardButton(
            "🔙 Back to Deactivate Menu",
            callback_data="items:deactivate"
        )

        await query.edit_message_text(
            text=f"⏹️ You deactivated 1× {human_name}.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [back_to_category_btn],
                [back_to_menu_btn],
            ])
        )
        return

    # ── (FALL‐THROUGH) ────────────────────────────────────────────────────────────
    await query.edit_message_text(
        text="⚠️ Something went wrong. Returning to Main Menu.",
        reply_markup=build_main_menu()
    )
    return




# Define mystery box contents
MYSTERY_BOXES = {
    "shop:mystery_bronze": {
        "name": "🎁 Bronze Mystery Box",
        "cost": 1000,
        "chip_range": (1000, 3000),
        "xp_range": (10, 200),
        "rare_items": [
            ("double_chip_potion", 0.05),
        ]
    },
    "shop:mystery_silver": {
        "name": "🎁 Silver Mystery Box",
        "cost": 2500,
        "chip_range": (2500, 4000),
        "xp_range": (10, 300),
        "rare_items": [
            ("triple_chip_potion", 0.05),
            ("xp_booster_500", 0.03),
        ]
    },
    "shop:mystery_gold": {
        "name": "🎁 Gold Mystery Box",
        "cost": 10000,
        "chip_range": (10000, 25000),
        "xp_range": (10, 500),
        "rare_items": [
            ("10x_chip_potion", 0.05),
            ("xp_booster_50000", 0.01),
        ]
    },
}

# This assumes you have: Player, PlayerItem, ITEM_TYPE_CHOICES, add_xp
async def handle_mystery_box_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    data = query.data

    box = MYSTERY_BOXES.get(data)
    if not box:
        await query.answer("Unknown mystery box!", show_alert=True)
        return

    player = await sync_to_async(Player.objects.get)(id=user_id)

    # Not enough chips
    if player.chips < box["cost"]:
        await query.edit_message_text(
            text=f"❗️ You don’t have enough chips to open the {box['name']}.\n\n"
                 f"Required: {box['cost']} 💰\nYour balance: {player.chips} 💰",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Back to Mystery Boxes", callback_data="shop:mystery_box")],
            ])
        )
        return

    # Deduct cost
    player.chips -= box["cost"]

    # Roll chips and XP
    reward_type = random.choice(["chips", "xp", "item"])
    reward_result = ""
    awarded_items = []

    if reward_type == "chips":
        chips_reward = random.randint(*box["chip_range"])
        player.chips += chips_reward
        reward_result = f"💰 Chips: +{chips_reward}"

    elif reward_type == "xp":
        xp_reward = random.randint(*box["xp_range"])
        reward_result = f"✨ XP: +{xp_reward}"
        await add_xp(player, xp_reward, context)

    elif reward_type == "item":
        rare_pool = box["rare_items"]
        random.shuffle(rare_pool)
        for item_type, chance in rare_pool:
            if random.random() <= chance:
                item_obj, _ = await sync_to_async(PlayerItem.objects.get_or_create)(
                    player=player, item_type=item_type, defaults={"quantity": 0}
                )
                item_obj.quantity += 1
                await sync_to_async(item_obj.save)()
                human_name = dict(ITEM_TYPE_CHOICES).get(item_type, item_type)
                reward_result = f"🎁 Bonus Item: {human_name}"
                awarded_items.append(human_name)
                break
        if not awarded_items:
            reward_result = "🎁 Bonus Item: nothing this time… 😢"


    await sync_to_async(player.save)()

    # Build result message
    lines = [
        f"{box['name']} opened! 🎉",
        reward_result,
    ]


    reply_markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔁 Open Another", callback_data=data)],
        [InlineKeyboardButton("🔙 Back to Mystery Boxes", callback_data="shop:mystery_box")],
    ])

    try:
        await query.edit_message_text(
            text="\n".join(lines),
            parse_mode="Markdown",
            reply_markup=reply_markup
        )
    except BadRequest as e:
        if "Message is not modified" in str(e):
            # Ignore silently or send a subtle poke if you want
            pass
        else:
            raise

async def handle_shop_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    query   = update.callback_query
    data    = query.data                       # E.g. "shop:double_xp_potion"
    user_id = query.from_user.id
    # ── If the user tapped “📦 Items” (or any items:… callback), redirect here ──
    if data in ("menu:items", "menu:boosters") or data.startswith("items:"):
        # We assume handle_items_callback(...) is already defined elsewhere
        await handle_items_callback(update, context)
        return True
    if data in (
        "menu:mainhorse",
        "menu:buy_horse",
        "menu:set_emoji",
        "menu:my_horses",
        "menu:my_spells",
        "menu:buy_spell",
        "menu:apply_spell",
        "menu:unapply_spell",
        "menu:rename_horse",
        "menu:gift_horse",
        "menu:global_horse_leaderboard",
        "menu:my_horse_statsrace",
        "menu:list_horse",
        "menu:sale_horses",
    ) or any(
        data.startswith(prefix) for prefix in [
            "menu:unapply_choose_spell",
            "menu:unapply_choose_horse",
            "menu:apply_choose_spell",
            "menu:apply_choose_horse",
            "menu:buy_spell_choose",
            "menu:rename_choose",
            "menu:list_choose",
            "menu:setemoji_choose",
            "menu:gift_owned_choose",
        ]
    ):
        await horse_menu_callback(update, context)
        return True

    if data in MYSTERY_BOXES:
        await handle_mystery_box_callback(update, context)
        return True
    print(f"[DEBUG] handle_shop_callback called: data={data!r}, user_id={user_id}")

    # Fetch Player if it exists
    try:
        player = await sync_to_async(Player.objects.get)(id=user_id)
        print(f"[DEBUG] Found Player: id={player.id}, chips={player.chips}")
    except Player.DoesNotExist:
        player = None
        print(f"[DEBUG] No Player found for user_id={user_id}")

    # ── (A) Main Shop menu ────────────────────────────────────────────────────
    if data == "menu:shop":
        print("[DEBUG] Branch: data == 'menu:shop'")
        await query.edit_message_text(
            text="🛒 *Shop* 🛒\n\nChoose a category:",
            parse_mode="Markdown",
            reply_markup=build_shop_menu()
        )
        return True

    # ── (B) Blackjack Items submenu ────────────────────────────────────────────
    if data == "shop:blackjack_items":
        print("[DEBUG] Branch: data == 'shop:blackjack_items'")
        await query.edit_message_text(
            text="🧪 *Blackjack Items* 🧪\n\nSelect a subcategory:",
            parse_mode="Markdown",
            reply_markup=build_blackjack_items_menu()
        )
        return True

    # ── (B.1) Potions submenu ─────────────────────────────────────────────────
    if data == "shop:bj_potions":
        print("[DEBUG] Branch: data == 'shop:bj_potions'")
        text = (
            "✨ *Blackjack Potions* ✨\n\n"
            "• *Double Chip Potion* — Double chips won on your next hand. (Cost: 7,500 chips)\n"
            "• *Triple Chip Potion* — Triple chips won on your next hand. (Cost: 15,000 chips)\n"
            "• *10× Chip Potion* — 10× chips won on your next hand. (Cost: 30,000 chips)\n\n"
            "Tap a potion below to purchase it."
        )
        await query.edit_message_text(
            text=text,
            parse_mode="Markdown",
            reply_markup=build_bj_potions_menu()
        )
        return True

    # ── (B.1.1) Purchase a specific Potion ────────────────────────────────────────
# ── (B.1.1) Purchase a Potion ─────────────────────────────────────────────────
    if data.startswith("shop:double_xp_potion")    or \
    data.startswith("shop:triple_xp_potion")    or \
    data.startswith("shop:10x_xp_potion")       or \
    data.startswith("shop:double_chip_potion")  or \
    data.startswith("shop:triple_chip_potion")  or \
    data.startswith("shop:10x_chip_potion"):

        item_key = data.split("shop:")[1]  # e.g. "double_xp_potion"

        # If the key isn’t in our dictionary, just “eat” it
        if item_key not in ITEM_COSTS:
            return True

        # If they never ran /start, remind them
        if player is None:
            await query.answer(
                "❗️ You don’t have a player profile yet. Send /start in private to create one.",
                show_alert=True
            )
            return True

        success, msg = await purchase_item(player, item_key)
        if not success:
            # On failure (e.g. “not enough chips”) show a pop‐up
            await query.answer(msg, show_alert=True)
            return True

        # ── SUCCESS: edit the shop message in place to show the confirmation ──────────
        human_name = dict(ITEM_TYPE_CHOICES)[item_key]
        cost = ITEM_COSTS[item_key]
        text = f"✅ You purchased 1× {human_name} for {cost:,} chips!"

        # Build “Back” buttons so they can return to the Potions menu or up one level
        keyboard = [
            [InlineKeyboardButton("🔙 Back to Potions",      callback_data="shop:bj_potions")],
            [InlineKeyboardButton("🔙 Back to Shop", callback_data="menu:shop")],
        ]
        await query.edit_message_text(
            text=text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
        return True

    # ── (B.2) Boosters submenu ──────────────────────────────────────────────────
    if data == "shop:bj_boosters":
        print("[DEBUG] Branch: data == 'shop:bj_boosters'")
        text = (
            "📈 *Blackjack Boosters* 📈\n\n"
            "• *+500 XP Booster* — 500 XP for 20000 chips.\n"
            "• *+2,000 XP Booster* — 2,000 XP for 100000 chips.\n"
            "• *+15,000 XP Booster* — 15,000 XP for 400000 chips.\n"
            "• *+50,000 XP Booster* — 50,000 XP for 1000000 chips.\n\n"
            "Tap a booster below to purchase it."
        )
        await query.edit_message_text(
            text=text,
            parse_mode="Markdown",
            reply_markup=build_bj_boosters_menu()
        )
        return True

    # ── (B.2.1) Purchase a specific Booster ───────────────────────────────────────
    if data.startswith("shop:xp_booster_500")  or \
    data.startswith("shop:xp_booster_2000") or \
    data.startswith("shop:xp_booster_15000") or \
    data.startswith("shop:xp_booster_50000"):

        item_key = data.split("shop:")[1]
        if item_key not in ITEM_COSTS:
            return True

        if player is None:
            await query.answer(
                "❗️ You don’t have a player profile yet. Send /start in private to create one.",
                show_alert=True
            )
            return True

        success, msg = await purchase_item(player, item_key)
        if not success:
            await query.answer(msg, show_alert=True)
            return True

        human_name = dict(ITEM_TYPE_CHOICES)[item_key]
        cost = ITEM_COSTS[item_key]
        text = f"✅ You purchased 1× {human_name} for {cost:,} chips!"

        keyboard = [
            [InlineKeyboardButton("🔙 Back to Boosters",      callback_data="shop:bj_boosters")],
            [InlineKeyboardButton("🔙 Back to Shop", callback_data="menu:shop")],
        ]
        await query.edit_message_text(text=text,
                                    reply_markup=InlineKeyboardMarkup(keyboard),
                                    parse_mode="Markdown")
        return True

    # ── (B.3) Special Passes submenu ───────────────────────────────────────────────
    if data == "shop:bj_special_passes":
        print("[DEBUG] Branch: data == 'shop:bj_special_passes'")
        text = (
            "🛡️ *Blackjack Special Passes* 🛡️\n\n"
            "• *Insurance Pass* — Discard a bad hit and draw again. (Cost: 5,000 chips)\n"
            "• *First-Hand-20 Pass* — Start with a 20 on your first hand. (Cost: 8,000 chips)\n\n"
            "Tap a pass below to purchase it."
        )
        await query.edit_message_text(
            text=text,
            parse_mode="Markdown",
            reply_markup=build_bj_special_passes_menu()
        )
        return True

        # ── (B.3.1) Purchase a specific Special Pass ──────────────────────────────────
    if data.startswith("shop:insurance_pass") or data.startswith("shop:first_hand_20_pass") or data.startswith("shop:first_hand_11_potion"):
        item_key = data.split("shop:")[1]
        if item_key not in ITEM_COSTS:
            return True

        if player is None:
            await query.answer(
                "❗️ You don’t have a player profile yet. Send /start in private to create one.",
                show_alert=True
            )
            return True

        success, msg = await purchase_item(player, item_key)
        if not success:
            await query.answer(msg, show_alert=True)
            return True

        human_name = dict(ITEM_TYPE_CHOICES)[item_key]
        cost = ITEM_COSTS[item_key]
        text = f"✅ You purchased 1× {human_name} for {cost:,} chips!"

        keyboard = [
            [InlineKeyboardButton("🔙 Back to Passes",      callback_data="shop:bj_special_passes")],
            [InlineKeyboardButton("🔙 Back to Shop", callback_data="menu:shop")],
        ]
        await query.edit_message_text(text=text,
                                    reply_markup=InlineKeyboardMarkup(keyboard),
                                    parse_mode="Markdown")
        return True

    # ── (C) Mystery Box submenu ─────────────────────────────────────────────────
    if data == "shop:mystery_box":
        print("[DEBUG] Branch: data == 'shop:mystery_box'")
        text = (
            "🎁 *Mystery Boxes* 🎁\n\n"
            # … etc …
        )
        await query.edit_message_text(
            text=text,
            parse_mode="Markdown",
            reply_markup=build_mystery_box_menu()
        )
        return True

    # ── (C.1) Open Mystery Box (stub) ───────────────────────────────────────────
    if data in {"shop:mystery_bronze", "shop:mystery_silver", "shop:mystery_gold"}:
        print(f"[DEBUG] Branch: Open Mystery Box → data={data!r}")
        await query.answer(
            f"You tapped to open: {data.split('shop:')[1].replace('_', ' ').title()}",
            show_alert=True
        )
        return True

    # ── (D) Shop “Special Passes” if you have a separate menu entry ──────────────
    if data == "shop:special_passes":
        print("[DEBUG] Branch: data == 'shop:special_passes'")
        text = (
            "🛡️ *Shop Special Passes* 🛡️\n\n"
            # … etc …
        )
        await query.edit_message_text(
            text=text,
            parse_mode="Markdown",
            reply_markup=build_special_passes_menu()
        )
        return True

    # ── (E) Back to Shop Menu ─────────────────────────────────────────────────
    if data in {"shop:main", "menu:shop"}:
        print("[DEBUG] Branch: data in {'shop:main','menu:shop'}")
        await query.edit_message_text(
            text="🛒 *Shop* 🛒\n\nChoose a category:",
            parse_mode="Markdown",
            reply_markup=build_shop_menu()
        )
        return True

    # ── (UNHANDLED) ──────────────────────────────────────────────────────────────
    print(f"[DEBUG] handle_shop_callback: UNHANDLED data={data!r}")
    return False

















async def handle_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    user_id = query.from_user.id
    user_name = query.from_user.first_name

    await query.answer()
# Inside your handle_menu_callback(...) function:
    handled = await handle_shop_callback(update, context)
    if handled:
        return
    if data == "menu:howtoplay":
        # 1) Edit the menu message to notify them
        keyboard = [
            [InlineKeyboardButton("🔙 Back to Main", callback_data="menu:main")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_text(
            "📩 A message with all available commands and instructions has been sent to your private chat.",
            reply_markup=reply_markup
        )   

        # 2) Create a minimal “fake” Update to call help_command, 
        #    since help_command expects update.message.chat_id == user_id.
        class FakeMessage:
            def __init__(self, chat_id, first_name):
                self.chat_id = chat_id
                self.from_user = type("U", (), {"id": chat_id, "first_name": first_name})
            async def reply_text(self, *args, **kwargs):
                # Not needed, because help_command only replies in a group if chat_id != user_id
                pass

        fake_update = Update(
            update.update_id,
            message=FakeMessage(user_id, user_name)
        )

        # Call the existing help_command logic
        await help_command(fake_update, context)


        return

    # ─── If “Minigames” was clicked ────────────────────────────────────────────
    if data == "menu:minigames":
        # We edit the same message to display the minigames list
        keyboard = [
            [InlineKeyboardButton("🔙 Back to Main", callback_data="menu:main")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            "🎮 *Available Minigames* 🎮\n\n"
            "🎲 `/dice` – Roll a dice and test your luck! (`/dice [chips amount]`)\n\n"
            "🎰 `/slot` – Try your luck at the slot machine. Will you hit the jackpot? (`/slot [chips amount]`)\n\n"
            "🪙 `/coin` – Flip a coin and see if it’s heads or tails. (`/coin [heads/tails] [chips amount]`)\n\n"
            "🎟 `/draw` – Participate in a lucky draw. Will you be the lucky one? (`/draw [chips amount]`)\n\n"
            "🎯 `/dart` – Play dart twice a day to win 200 chips.\n\n"
            "✊🖐✌️ `/rps` – Play Rock, Paper, Scissors against the bot. (`/rps [rock/paper/scissors] [chips amount]`)\n\n"
            "🎡 `/spin` – Spin the wheel once a day for a chance to win chips, XP, or levels! Type `/spin <low/mid/high>` and let the wheel decide your fate.\n\n"
            "🎲 `/roulette` – Bet on red, black, or a number (`0–36`).\n"
            "Usage: `/roulette <red|black|0–36> <bet amount>`.\n"
            "If you guess the color, you win double; if you guess the number, you win 35× your bet! Good luck!\n\n"
            "📈 `/crash` – Bet chips and watch the multiplier rise. Type `/cashout` before it crashes to lock in your winnings!\n\n"
            "🟥 `/double` – Feeling lucky? Bet to win double your chips or lose it all. (`/double [amount]`)\n\n"
            "🐎 `/horserace` – Start a new horse race.\n"
            "🐎 `/joinrace` – Join the ongoing race with your horse. (`/joinrace <horse_number> <amount>`)\n"
            "🐎 `/startrace` – Start the race and watch it live!",
            reply_markup=reply_markup,
            parse_mode="Markdown",

        )

        # 5) Send (edit) the message with a “Back to Main” button

        return

    # ── (Social submenu) ─────────────────────────────────────────────────────────
    if data == "menu:social":
        user_id = query.from_user.id

        # 1) Ensure this Player exists and has a referral_code
        try:
            player = await sync_to_async(Player.objects.get)(id=user_id)
        except Player.DoesNotExist:
            # If the user somehow has no Player record, prompt them to /start
            await query.edit_message_text(
                text="You don’t have a player profile yet. Type /start to create one.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 Back to Main", callback_data="menu:main")]
                ])
            )
            return

        # If for any reason referral_code is blank (unlikely if save() logic is correct), generate and save one
        if not player.referral_code:
            code = generate_referral_code()
            # Make sure it's unique
            while await sync_to_async(Player.objects.filter(referral_code=code).exclude(id=user_id).exists)():
                code = generate_referral_code()
            player.referral_code = code
            await sync_to_async(player.save)()
        else:
            code = player.referral_code

        # 2) Build the user’s personal referral link
        bot_username  = context.bot.username  # e.g. "MyBlackjackBot"
        referral_link = f"https://t.me/{bot_username}?start={code}"

        # 3) Fetch all friends this user has referred
        referred_qs = await sync_to_async(
            lambda: list(
                Player.objects.filter(referrer__id=user_id).values("id", "name")
            )
        )()

        # 4) Start composing the Social menu text
        lines = [
            "🤝 *Social Menu* 🤝",
            "",
            f"Your referral code: *`{code}`*",
            f"Share this link to invite friends and earn 1000:\n`{referral_link}`\n",
            "Friends you referred:"
        ]

        total_bonus = 0
        if referred_qs:
            # For each referred friend, sum the ReferralEarning amounts
            for friend in referred_qs:
                fid   = friend["id"]
                fname = friend["name"]

                bonus_q = await sync_to_async(
                    lambda: ReferralEarning.objects.filter(
                        referrer__id=user_id,
                        referred__id=fid
                    ).aggregate(total=Sum("amount"))
                )()
                friend_bonus = bonus_q["total"] or 0
                total_bonus += friend_bonus

                lines.append(f" • {fname:<10} (earned you {friend_bonus} chips)")

            lines.append("")  # blank line before total
            lines.append(f"Total referral bonus: *{total_bonus}* chips")
        else:
            lines.append(" • (you haven’t referred anyone yet)\n")
            lines.append("Total referral bonus: *0* chips")

        text = "\n".join(lines)

        # 5) Send (edit) the message with a “Back to Main” button
        keyboard = [
            [InlineKeyboardButton("🔙 Back to Main", callback_data="menu:main")]
        ]
        await query.edit_message_text(
            text=text,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    if data == "menu:horse_leaderboard":
        # 1) Annotate wins & chips per player from HorseRaceWin
        leaderboard_qs = await sync_to_async(
            lambda: list(
                HorseRaceWin.objects
                    .filter(user__isnull=False)
                    .values("user__id", "user__name")
                    .annotate(
                        wins=Count("id"),
                        chips=Sum("amount")
                    )
                    .order_by("-wins", "-chips")
            )
        )()

        # Show only top 5
        top5 = leaderboard_qs[:5]
        user_id = query.from_user.id

        # Find the calling user’s index (0-based) in the full leaderboard list
        user_index = next(
            (idx for idx, e in enumerate(leaderboard_qs) if e["user__id"] == user_id),
            None
        )

        lines = ["🐎 *Horse Leaderboard* 🐎", ""]  # renamed header

        # (A.1) Top 5 entries
        for idx, entry in enumerate(top5, start=1):
            name = entry["user__name"] or f"User {entry['user__id']}"
            wins = entry["wins"]
            chips_amt = entry["chips"] or 0
            # Fixed‐width padding for name (~12 chars) so columns align
            lines.append(
                f"{idx:>2}. {name:<12}  🏆 Wins: {wins:<3}  💰 Chips: {chips_amt}"
            )

        lines.append("")  # blank line before “Your Position”

        # (A.2) Your Position in the full leaderboard
        if user_index is None:
            lines.append("🏅 *Your Position* (Not Ranked Yet):")
            lines.append("   • No wins recorded.")
        else:
            user_rank = user_index + 1
            lines.append(f"🏅 *Your Position* (Rank {user_rank}):")

            # Show two above and two below the user (if they exist)
            start = max(0, user_index - 2)
            end = min(len(leaderboard_qs), user_index + 3)
            for idx2 in range(start, end):
                e = leaderboard_qs[idx2]
                name = e["user__name"] or f"User {e['user__id']}"
                wins = e["wins"]
                chips_amt = e["chips"] or 0
                display_rank = idx2 + 1
                prefix = "👉" if e["user__id"] == user_id else "   "
                lines.append(
                    f"{prefix}{display_rank:>2}. {name:<12}  🏆 Wins: {wins:<3}  💰 Chips: {chips_amt}"
                )

        text = "\n".join(lines)

        # Single “Back to Main” button
        keyboard = [[InlineKeyboardButton("🔙 Back to Leaderboards", callback_data="menu:leaderboards")]]

        await query.edit_message_text(
            text=text,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    # ── (B) Global Leaderboard ────────────────────────────────────────────────────
    if data == "menu:global_leaderboard":
        user_id = query.from_user.id

        # (A) Fetch top 5 players by total wins from Stats
        top_players = await sync_to_async(list)(
            Stats.objects.select_related("player")
                         .annotate(total_wins=F("wins"))
                         .order_by("-total_wins")[:5]
        )

        # Build plain-text lines for Top 5
        lines = ["🌍 Global Leaderboard 🌍", ""]
        if top_players:
            for idx, stats in enumerate(top_players, start=1):
                # Truncate names longer than 8 chars
                name = stats.player.name
                if len(name) > 8:
                    name = name[:5] + "..."
                # Format: "1. Reza     🏆 Wins: 19   💰 Chips: 3750"
                line = f"{idx:<2}. {name:<8} 🏆 Wins: {stats.wins:<3}   💰 Chips: {stats.player.chips}"
                lines.append(line)
            lines.append("")  # blank separator
        else:
            lines.append("No players have ranked yet.")
            lines.append("")

        # (B) Fetch every player ordered by wins to find this user’s rank & neighbors
        all_players = await sync_to_async(list)(
            Stats.objects.select_related("player")
                         .annotate(total_wins=F("wins"))
                         .order_by("-total_wins")
        )

        user_rank = None
        nearby_lines = []
        for idx, stats in enumerate(all_players, start=1):
            if stats.player.id == user_id:
                user_rank = idx
                start = max(idx - 2, 0)
                end = min(idx + 2, len(all_players))
                slice_players = all_players[start:end]
                for r, pstats in enumerate(slice_players, start=start + 1):
                    name = pstats.player.name
                    if len(name) > 8:
                        name = name[:5] + "..."
                    prefix = "👉" if pstats.player.id == user_id else "  "
                    line = (
                        f"{prefix}{r:<2}. {name:<8} 🏆 Wins: {pstats.wins:<3}   "
                        f"💰 Chips: {pstats.player.chips}"
                    )
                    nearby_lines.append(line)
                break

        if user_rank:
            lines.append(f"🏅 Your Position (Rank {user_rank}):")
            lines.extend(nearby_lines)
        else:
            lines.append("🏅 Your Position (Not Ranked Yet):")
            lines.append("   • No wins recorded.")

        # Join into a single Markdown string
        text = "\n".join(lines)

        # “Back to Leaderboards” button
        keyboard = [[InlineKeyboardButton("🔙 Back to Leaderboards", callback_data="menu:leaderboards")]]

        await query.edit_message_text(
            text=text,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return


    # ── (1) Main Menu (reset text + buttons) ────────────────────────────────────
    if data == "menu:main":
        await query.edit_message_text(
            text="*BlackJack Bot Menu* 💥\n\nChoose an option below:",
            parse_mode="Markdown",
            reply_markup=build_main_menu()
        )
        return

    # ── (2) Profile submenu selected (reset text → “Profile Menu” + buttons) ────
    if data == "menu:profile":
        await query.edit_message_text(
            text="👤 *Profile Menu* 👤\n\nSelect an action:",
            parse_mode="Markdown",
            reply_markup=build_profile_menu()
        )
        return

    # ── (3) Achievements (Profile → Achievements) ───────────────────────────────
    if data == "profile:achievements":
        user_id    = query.from_user.id
        user_first = query.from_user.first_name

        try:
            player = await sync_to_async(Player.objects.get)(id=user_id)
        except Player.DoesNotExist:
            await query.edit_message_text(
                text=f"{user_first}, you don't have a player profile. Start a game first!",
                reply_markup=build_back_to_profile_button()
            )
            return

        player_achievements = await sync_to_async(list)(
            PlayerAchievement.objects.filter(player=player).select_related("achievement")
        )
        total_achievements = await sync_to_async(Achievement.objects.count)()

        if not player_achievements:
            await query.edit_message_text(
                text=(
                    f"{user_first}, you haven't unlocked any achievements yet.\n\n"
                    f"0/{total_achievements} achievements unlocked."
                ),
                reply_markup=build_back_to_profile_button()
            )
            return

        unlocked_count = len(player_achievements)
        achievements_list = "\n".join([
            f"🏅 *{pa.achievement.name}*: {pa.achievement.description}"
            for pa in player_achievements
        ])

        await query.edit_message_text(
            text=(
                f"🎉 *{user_first}'s Achievements* 🎉\n\n"
                f"Progress: {unlocked_count}/{total_achievements} achievements unlocked.\n\n"
                f"{achievements_list}"
            ),
            parse_mode="Markdown",
            reply_markup=build_back_to_profile_button()
        )
        return

    # ── (4) Stats (Profile → Stats) ──────────────────────────────────────────────
    if data == "profile:stats":
        user_id    = query.from_user.id
        user_first = query.from_user.first_name

        try:
            player = await sync_to_async(Player.objects.get)(id=user_id)
            stats  = await sync_to_async(Stats.objects.get)(player=player)

            # Normalize XP/Level before calculating
            await normalize_player_level_xp(player)

            xp         = player.xp
            level      = player.level
            threshold  = xp_for_next_level(level)
            xp_to_next = threshold - xp

            text = (
                f"🎮 *Your Stats* 🎮\n\n"
                f"🏆 *Wins*: {stats.wins}\n"
                f"❌ *Losses*: {stats.loses}\n"
                f"💥 *Blackjacks*: {stats.how_many_21}\n"
                f"💪 *XP (this level)*: {xp}\n"
                f"📈 *Level*: {level}\n"
                f"🔜 *XP to next level*: {xp_to_next} XP\n"
            )
        except ObjectDoesNotExist:
            # First-time user: create Player & Stats
            player = await sync_to_async(Player.objects.create)(
                id=user_id, name=user_first, chips=200, xp=0, level=1
            )
            stats  = await sync_to_async(Stats.objects.create)(
                wins=0, loses=0, how_many_21=0, player=player
            )
            text = (
                f"Welcome to Blackjack, {user_first}! You have been given 20 💰 chips to start.\n\n"
                f"🎮 *Your Stats* 🎮\n\n"
                f"🏆 *Wins*: {stats.wins}\n"
                f"❌ *Losses*: {stats.loses}\n"
                f"💥 *Blackjacks*: {stats.how_many_21}\n"
                f"💪 *XP (this level)*: 0\n"
                f"📈 *Level*: 1\n"
                f"🔜 *XP to next level*: 50 XP\n\n"
                "Keep playing to earn XP and level up!"
            )

        await query.edit_message_text(
            text=text,
            parse_mode="Markdown",
            reply_markup=build_back_to_profile_button()
        )
        return

    # ── (5) My Tokens (Profile → My Tokens) ───────────────────────────────────────
    if data == "profile:mytokens":
        user_id = query.from_user.id
        try:
            player = await sync_to_async(Player.objects.get)(id=user_id)
            text = (
                f"💰 *Chips*: {player.chips}\n"
                f"💵 *Real Tokens*: {player.real_tokens}\n"
            )
        except ObjectDoesNotExist:
            text = "You don't have a player profile yet. Start the bot in private to create one."

        await query.edit_message_text(
            text=text,
            parse_mode="Markdown",
            reply_markup=build_back_to_profile_button()
        )
        return

    # ── (6) My Races (Profile → My Races) ────────────────────────────────────────
    if data == "profile:myraces":
        user_id = query.from_user.id

        # 1) Distinct races participated
        races_participated = await sync_to_async(
            lambda: HorseBet.objects.filter(user_id=user_id)
                                     .values_list("race", flat=True)
                                     .distinct()
                                     .count()
        )()

        # 2) Total chips wagered
        total_wagered_q = await sync_to_async(
            lambda: HorseBet.objects.filter(user_id=user_id)
                                     .aggregate(total=Sum("bet_amount"))
        )()
        total_wagered = total_wagered_q["total"] or 0

        # 3) Average bet size
        avg_bet_q = await sync_to_async(
            lambda: HorseBet.objects.filter(user_id=user_id)
                                     .aggregate(avg=Avg("bet_amount"))
        )()
        avg_bet = avg_bet_q["avg"] or 0

        # 4) Total horses owned
        horses_owned = await sync_to_async(
            lambda: OwnedHorse.objects.filter(user__id=user_id).count()
        )()

        # 5) Total wins
        total_wins = await sync_to_async(
            lambda: HorseRaceWin.objects.filter(user__id=user_id).count()
        )()

        # 6) Total chips earned
        total_earned_q = await sync_to_async(
            lambda: HorseRaceWin.objects.filter(user__id=user_id)
                                         .aggregate(total=Sum("amount"))
        )()
        total_earned = total_earned_q["total"] or 0

        # 7) Horse‐Level Win Rate
        horse_nums = await sync_to_async(
            lambda: list(
                OwnedHorse.objects.filter(user__id=user_id)
                                  .values_list("horse_number", flat=True)
            )
        )()

        if horse_nums:
            win_rate_list = []
            for hnum in horse_nums:
                wins_for_horse = await sync_to_async(
                    lambda: HorseRaceWin.objects.filter(
                        user__id=user_id, horse_number=hnum
                    ).count()
                )()
                bets_on_horse = await sync_to_async(
                    lambda: HorseBet.objects.filter(
                        user_id=user_id, horse_number=hnum
                    ).count()
                )()
                if bets_on_horse > 0:
                    win_rate_list.append(wins_for_horse / bets_on_horse)
                else:
                    win_rate_list.append(0.0)

            horse_win_rate = (sum(win_rate_list) / len(win_rate_list)) * 100
        else:
            horse_win_rate = 0.0

        # 8) Player Win Rate
        races_won = await sync_to_async(
            lambda: HorseRaceWin.objects.filter(user__id=user_id)
                                        .values_list("race", flat=True)
                                        .distinct()
                                        .count()
        )()

        if races_participated > 0:
            player_win_rate = (races_won / races_participated) * 100
        else:
            player_win_rate = 0.0

        lines = [
            "🎮 *Your Horse‐Racing Stats* 🎮",
            "",
            f"🐎 Races participated: *{races_participated}*",
            f"💰 Total chips wagered: *{total_wagered:,}* chips",
            f"📊 Avg. bet size: *{avg_bet:.2f}* chips",
            f"🏠 Horses owned: *{horses_owned}*",
            f"🏆 Total wins: *{total_wins}*",
            f"🎉 Total chips earned: *{total_earned:,}* chips",
            f"🐴 Horse‐level win rate: *{horse_win_rate:.1f}%*",
            f"🎲 Player win rate: *{player_win_rate:.1f}%*",
        ]
        text = "\n".join(lines)

        await query.edit_message_text(
            text=text,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Back to Profile", callback_data="menu:profile")]
            ])
        )
        return

    # ── (7) Other submenus (Shop, Leaderboards, etc.) ───────────────────────────
    if data == "menu:shop":
        await query.edit_message_text(
            text="🛍️ *Shop Menu* 🛍️\n\nChoose an option:",
            parse_mode="Markdown",
            reply_markup=build_shop_menu()
        )
        return

    if data == "menu:leaderboards":
        await query.edit_message_text(
            text="🏆 *Leaderboards* 🏆\n\nChoose one:",
            parse_mode="Markdown",
            reply_markup=build_leaderboards_menu()
        )
        return

    if data == "menu:tournaments":
        await query.edit_message_text(
            text="🏁 *Tournaments & Events* 🏁\n\nChoose an action:",
            parse_mode="Markdown",
            reply_markup=build_tournaments_menu()
        )
        return

    if data == "menu:quests":
        await query.edit_message_text(
            text="🎯 *Quests & Rewards* 🎯\n\nChoose an action:",
            parse_mode="Markdown",
            reply_markup=build_quests_menu()
        )
        return

    if data == "menu:social":
        await query.edit_message_text(
            text="🗣️ *Social* 🗣️\n\nChoose an option:",
            parse_mode="Markdown",
            reply_markup=build_social_menu()
        )
        return

    if data == "menu:settings":
        await query.edit_message_text(
            text="⚙️ *Settings* ⚙️\n\nChoose an option:",
            parse_mode="Markdown",
            reply_markup=build_settings_menu()
        )
        return

    if data == "menu:support":
        await query.edit_message_text(
            text="❓ *Support* ❓\n\nChoose an option:",
            parse_mode="Markdown",
            reply_markup=build_support_menu()
        )
        return










# xpppppppppppppp




def xp_for_next_level(level: int) -> int:
    """
    Returns the XP required *to complete* the current `level` and bump to `level+1`.
    E.g. level=1 → need 50 XP, level=2 → need 100 XP, level=3 → need 150 XP, etc.
    """
    return level * 50

# Function to add XP, check for level-up, and give rewards
async def add_xp(player, amount, context):
    player.xp += amount  # Add the XP amount to the player's total XP
    level_up = False  # Track if player leveled up

    # Loop to handle multiple level-ups in case of large XP gain
    while player.xp >= xp_for_next_level(player.level):
        next_level_xp = xp_for_next_level(player.level)  # Calculate the XP needed for the next level
        player.xp -= next_level_xp  # Subtract the XP required for the current level
        player.level += 1  # Increase the player's level
        level_up = True

        # Reward player with 50 chips per level
        chips_reward = player.level * 50
        player.chips += chips_reward
        
        # Send level-up and reward message
        await context.bot.send_message(
            chat_id=player.id, 
            text=f"🎉 Congratulations! You've reached level {player.level}! You've been rewarded with {chips_reward} 💰 chips!"
        )

    await sync_to_async(player.save)()  # Save the player data

async def normalize_player_level_xp(player: Player):
    """
    If player.xp is already ≥ xp_for_next_level(player.level),
    then remove that threshold from xp, increment level, and repeat until
    xp < xp_for_next_level(level). This ensures the stored xp is always "in‐level."
    No chips or messages are awarded here; it's purely a data‐correction step.
    """
    changed = False

    # Keep leveling up as long as xp reaches the threshold for the current level
    while player.xp >= xp_for_next_level(player.level):
        threshold = xp_for_next_level(player.level)
        player.xp -= threshold
        player.level += 1
        changed = True

    # Just in case someone’s XP was negative, clamp it at 0 at level 1:
    if player.xp < 0 and player.level == 1:
        player.xp = 0
        changed = True

    # If anything changed, save
    if changed:
        await sync_to_async(player.save)()

async def safe_send_reaction(bot, chat_id, reaction, max_retries=10):
    retries = 0
    while retries < max_retries:
        try:
            await bot.send_message(chat_id=chat_id, text=reaction)
            return  # Exit the loop if successful
        except TimedOut:
            retries += 1
            print(f"Timeout occurred while sending message. Retrying {retries}/{max_retries}...")
            await asyncio.sleep(4)  # Non-blocking wait
        except RetryAfter as e:
            retry_after = int(e.retry_after)
            print(f"Rate limit exceeded. Retrying in {retry_after} seconds...")
            await asyncio.sleep(retry_after)  # Wait for the retry after time
            retries += 1
        except Exception as e:
            print(f"Failed to send message: {e}")
            break  # Exit on other exceptions

    print("Failed to send reaction after multiple retries.")

# Function to deduct XP and check for level-down
async def deduct_xp(player, amount, context):
    player.xp -= amount  # Subtract the XP amount

    level_down = False  # Track if player levels down

    # Loop to handle level-down in case of large XP loss
    while player.xp < 0 and player.level > 1:
        previous_level_xp = xp_for_next_level(player.level - 1)  # XP required for the previous level
        player.level -= 1  # Decrease the player's level
        player.xp += previous_level_xp  # Add the XP required for the previous level
        level_down = True

    # Handle level-down to minimum level
    if player.xp < 0 and player.level == 1:
        player.xp = 0  # Ensure XP doesn't go negative at level 1

    # Send a level-down message if the player leveled down
    if level_down:
        await context.bot.send_message(
            chat_id=player.id,
            text=f"⚠️ You lost {amount} XP and have been demoted to level {player.level}."
        )

    await sync_to_async(player.save)()  # Save the player data




# achievementssssssssssssssss ------------------------------------------------ 


async def unlock_achievement(player, condition_name, context):
    try:
        # Fetch the achievement by its condition name
        achievement = await sync_to_async(Achievement.objects.get)(condition=condition_name)
        
        # Check if the player already has this achievement
        already_unlocked = await sync_to_async(lambda: PlayerAchievement.objects.filter(player=player, achievement=achievement).exists())()

        if not already_unlocked:
            # Unlock the achievement for the player
            await sync_to_async(PlayerAchievement.objects.create)(
                player=player, achievement=achievement, unlocked_at=datetime.now()
            )

            # Notify the player
            await add_xp(player, 20, context)

            await context.bot.send_message(
                chat_id=player.id,
                text=f"🎉 Congratulations! You've unlocked the '{achievement.name}' achievement: {achievement.description}"
            )
        else:
            print(f"{player.name} already has the {achievement.name} achievement.")

    except ObjectDoesNotExist:
        print(f"Achievement with condition '{condition_name}' does not exist.")





async def my_achievements(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await check_player(update, context):
        return
    user_id = update.message.from_user.id
    user_name = update.message.from_user.first_name
    chat_id = update.message.chat_id  # This is the chat where the command was used
    
    try:
        # Fetch the player from the database
        player = await sync_to_async(Player.objects.get)(id=user_id)
    except Player.DoesNotExist:
        await update.message.reply_text(f"{user_name}, you don't seem to have a player profile. Start a game first!")
        return

    # Fetch all achievements for the player
    player_achievements = await sync_to_async(list)(
        PlayerAchievement.objects.filter(player=player).select_related('achievement')
    )

    # Fetch total achievements available in the system
    total_achievements = await sync_to_async(Achievement.objects.count)()

    # If no achievements found
    if not player_achievements:
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"{user_name}, you haven't unlocked any achievements yet.\n\n0/{total_achievements} achievements unlocked.",
            parse_mode="Markdown"
        )
        return

    # Calculate the player's achievement progress
    unlocked_achievements_count = len(player_achievements)

    # Prepare the achievement list
    achievements_list = "\n".join([f"🏅 *{pa.achievement.name}*: {pa.achievement.description}" for pa in player_achievements])

    # Send the message with the achievements list and progress to the player's private chat
    await context.bot.send_message(
        chat_id=chat_id,
        text=f"🎉 *{user_name}'s Achievements* 🎉\n\n"
             f"Progress: {unlocked_achievements_count}/{total_achievements} achievements unlocked.\n\n"
             f"{achievements_list}",
        parse_mode="Markdown"
    )




async def achievement_info(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.message.from_user.id
    chat_id = update.message.chat_id

    # Fetch all achievements from the database
    achievements = await sync_to_async(list)(Achievement.objects.all())

    # Check if there are any achievements available
    if not achievements:
        await update.message.reply_text("There are no achievements available yet.")
        return

    # Prepare the list of achievements with descriptions
    achievement_list = "\n".join([f"🏅 *{achievement.name}*: {achievement.description}" for achievement in achievements])

    # Send the achievements list to the player
    await context.bot.send_message(
        chat_id=user_id,  # Send to player's private chat
        text=f"🎉 *Achievements Info* 🎉\n\n"
             f"Here’s how you can unlock the achievements:\n\n{achievement_list}",
        parse_mode="Markdown"
    )

    # Inform the user in the group chat if the message is sent in a group
    if chat_id != user_id:
        await update.message.reply_text("📩 A message with the achievements info has been sent to your private chat.")




async def is_player_in_another_game(player_id: int, current_chat_id: int) -> bool:
    """
    Check if the player is already joined in another game in a different group.
    
    Args:
        player_id (int): The ID of the player.
        current_chat_id (int): The ID of the current group chat.

    Returns:
        bool: True if the player is in another game, False otherwise.
    """
    # Query to check if the player is active in another game in a different group
    is_in_another_game = await sync_to_async(
        JoinGame.objects.filter(
            player_id=player_id, 
            is_active=True
        ).exclude(game__chat_id=current_chat_id).exists
    )()
    
    return is_in_another_game
from telegram.error import TelegramError

async def check_player(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user_id = update.message.from_user.id
    user_name = update.message.from_user.first_name

    try:
        # Try to get the Player instance from the database
        player = await sync_to_async(Player.objects.get)(id=user_id)

        try:
            # Test if the bot can send a chat action (e.g., typing) to check if the user has blocked the bot
            await context.bot.send_chat_action(chat_id=user_id, action="typing")

            # If no exception is raised, the bot can message the user
            return True

        except TelegramError as e:
            # Handle case where the bot is blocked or cannot message the user
            await update.message.reply_text(
                "It seems like I can't message you in private. Please make sure to start the bot in private chat first: "
                "t.me/blackjack_21_game_bot"
            )
            return False

    except ObjectDoesNotExist:
        # If no player exists, prompt the user to start the bot in private chat
        await update.message.reply_text(
            "It looks like you don't have a player profile. Please start the bot in private chat to create one. "
            "Use the following link: t.me/blackjack_21_game_bot"
        )
        return False  # Player does not exist

from datetime import timedelta


async def claim_tokens(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.message.from_user.id

    # 1) Ensure they’re a registered player
    if not await check_player(update, context):
        return

    # 2) Fetch the Player row
    player = await sync_to_async(Player.objects.get)(id=user_id)
    now = timezone.now()

    # 3) If they’ve never claimed, or if their last claim was ≥24 h ago, reset counter:
    if player.last_claimed_tokens is None or (now - player.last_claimed_tokens) >= timedelta(hours=24):
        print("nigga what")
        player.tokens_claimed_today = 0
        player.last_claimed_tokens = now
        await sync_to_async(player.save)()

    # 4) If they’ve already rolled twice in the past 24 h, tell them how much longer to wait
    print("baba",player.tokens_claimed_today)
    if player.tokens_claimed_today >= 3:
        print("boo0",player.tokens_claimed_today)

        # Next allowed time = last_claimed_tokens + 24 h
        next_allowed = player.last_claimed_tokens + timedelta(hours=24)
        remaining = next_allowed - now

        # If somehow “remaining” is negative, we treat it as zero
        if remaining.total_seconds() <= 0:
            # in case of clock drift, do a final reset and let them roll now:
            player.tokens_claimed_today = 0
            player.last_claimed_tokens = now
            await sync_to_async(player.save)()
        else:
            # Compute hours and minutes
            total_seconds = math.floor(remaining.total_seconds())
            hours = total_seconds // 3600
            minutes = (total_seconds % 3600) // 60

            # Build a friendly “X h Y m” string
            if hours > 0:
                time_str = f"{hours} hour{'s' if hours != 1 else ''}"
                if minutes > 0:
                    time_str += f" and {minutes} minute{'s' if minutes != 1 else ''}"
            else:
                time_str = f"{minutes} minute{'s' if minutes != 1 else ''}"

            await update.message.reply_text(
                f"You’ve already 3 Times in the past 24 hours.\n"
                f"Please try again in {time_str}."
            )
            return
    player.tokens_claimed_today += 1
    await sync_to_async(player.save)()
    player.last_claimed_tokens = now

    # 5) If we get here, they have at least one roll left. Send the 🎯 dice.
    message = await context.bot.send_dice(chat_id=update.message.chat_id, emoji="🎯")
    await asyncio.sleep(3)

    # 6) Check result
    if message.dice.value == 6:
        player.chips += 200
        await update.message.reply_text(
            f"🎯 Bullseye! You've received 💰200 chips! You now have 💰{player.chips} chips."
        )
    else:
        await update.message.reply_text("🎯 You missed the bullseye! Better luck next time!")




async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id   = update.message.from_user.id
    user_name = update.message.from_user.first_name

    try:
        # Fetch the Player & Stats objects for this user
        player = await sync_to_async(Player.objects.get)(id=user_id)
        stats  = await sync_to_async(Stats.objects.get)(player=player)

        # Normalize their xp/level before computing "xp to next"
        await normalize_player_level_xp(player)

        # Now player.level and player.xp are guaranteed to satisfy:
        #    player.xp < xp_for_next_level(player.level)

        xp    = player.xp
        level = player.level
        threshold = xp_for_next_level(level)  # how much XP needed *this* level

        xp_to_next_level = threshold - xp  # always > 0, unless xp==threshold (in which
                                           # case normalize would have bumped them already)

        message = (
            f"🎮 *Your Stats* 🎮\n\n"
            f"🏆 *Wins*: {stats.wins}\n"
            f"❌ *Losses*: {stats.loses}\n"
            f"💥 *Blackjacks*: {stats.how_many_21}\n"
            f"💪 *XP (this level)*: {xp}\n"
            f"📈 *Level*: {level}\n"
            f"🔜 *XP to next level*: {xp_to_next_level} XP\n"
        )
        await update.message.reply_text(message, parse_mode="Markdown")

    except ObjectDoesNotExist:
        # First‐time user: create Player & Stats, give 20 chips
        player = await sync_to_async(Player.objects.create)(
            id=user_id,
            name=user_name,
            chips=20,
            xp=0,
            level=1
        )
        stats  = await sync_to_async(Stats.objects.create)(
            wins=0, loses=0, how_many_21=0, player=player
        )

        message = (
            f"Welcome to Blackjack, {user_name}! You have been given 20 💰 chips to start.\n\n"
            f"🎮 *Your Stats* 🎮\n\n"
            f"🏆 *Wins*: {stats.wins}\n"
            f"❌ *Losses*: {stats.loses}\n"
            f"💥 *Blackjacks*: {stats.how_many_21}\n"
            f"💪 *XP (this level)*: 0\n"
            f"📈 *Level*: 1\n"
            f"🔜 *XP to next level*: 50 XP\n"
            f"\nKeep playing to earn XP and level up!"
        )
        await update.message.reply_text(message, parse_mode="Markdown")



# # Deck of cards
deck = [2, 3, 4, 5, 6, 7, 8, 9, 10, 'J', 'Q', 'K', 'A'] * 4

# Function to deal cards
def deal_card():
    return random.choice(deck)

# # Function to calculate hand value
def calculate_hand_value(hand):
    value = 0
    aces = 0

    for card in hand:
        if card in ['J', 'Q', 'K']:
            value += 10
        elif card == 'A':
            aces += 1  # Count Aces separately
        else:
            value += card

    # Now calculate the value of Aces
    for _ in range(aces):
        if value + 11 <= 21:  # Try to count the Ace as 11
            value += 11
        else:
            value += 1  # If counting as 11 would bust, count as 1

    return value
game_start_reactions = [
    "A new round begins! Are you ready? 🃏",
    "let the cards decide your fate! 💰",
    "Good luck to all! Let’s have a great round. 🍀",
    "New round, new chances to win! Let’s get started. 🎯",
    "It’s time to deal the cards Losers. Ready? 🃏",
    "A fresh round begins! May the best hand win. 👑",
    "Let’s shuffle up and deal! Good luck! 🔄",
    "The cards are ready. Who’s going to win this one? 👀",
    "Let the round begin! Who’s feeling lucky? 🔥"
]

# Dealer reactions for betting phase
betting_phase_reactions = [
    "Place your bets! It’s time to see who’s daring today. 💰",
    "Bet wisely! The game is about to heat up. 🔥",
    "Time to put your chips on the table! Who’s going big? 💸",
    "Betting is open! Will you play it safe or take a risk? 🎲",
    "Place your bets now! Will you go all in? 🤑",
    "How much are you willing to risk? Place your bets! 💪",
    "The pot is waiting! Let’s see who’s feeling bold. 💼",
    "Bet smart! The cards don’t lie. 🃏",
    "Who’s betting big this round? Let’s see! 💰",
    "Betting is open! Choose your risk carefully. 🎯"
]
async def create_highroller_poll(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.message.chat_id

    try:
        group = await sync_to_async(Group.objects.get)(group_chat_id=chat_id)
    except Group.DoesNotExist:
        group = await sync_to_async(Group.objects.create)(group_chat_id=chat_id)

    # Define the high-roller choices
    options = [
        "1000000 (1M) chips💰",
        "5000000 (5M) chips💰",
        "10000000 (10M) chips💰",
        "50000000 (50M) chips💰",
        "100000000 (100M) chips💰",
        "200000000 (200M) chips💰",
        "500000000 (500M) chips💰",
        "1000000000 (1B) chips💰"
    ]

    question = "High-roller Bet (in chips 💰):"

    # Send the poll
    message = await safe_send_poll(context.bot, chat_id, question, options)

    # Store everything in bot_data, including the options list itself:
    if 'poll_data' not in context.bot_data:
        context.bot_data['poll_data'] = {}

    context.bot_data['poll_data'][message.poll.id] = {
        'chat_id': chat_id,
        'poll_message_id': message.message_id,
        'options': options,               # <— store this!
        'voted_player_ids': [],
        'correct_guess_player_ids': [],
        'wrong_guess_player_ids': [],
        # 'chips' and 'xp' keys will be added later if guesses are correct
    }


# --- New command handler: highroller ---
async def highroller(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Exactly mirrors start_blackjack, but uses create_highroller_poll() instead of create_poll().
    """
    if not await check_player(update, context):
        return

    chat_id = update.message.chat_id
    group_name = update.message.chat.title  # Get the group name

    # Check if a game exists and if it has ended
    game = await sync_to_async(lambda: Game.objects.filter(chat_id=chat_id).order_by('-id').first())()

    if not game or game.ended:
        # (Create or get a fresh Game, set betting=True, started=False)
        game, created = await sync_to_async(Game.objects.get_or_create)(chat_id=chat_id, ended=False)
        game.betting = True
        game.started = False
        await sync_to_async(game.save)()

        # Notify anyone who subscribed to /nextgame
        next_game_users = await sync_to_async(list)(
            NextGameNotification.objects.filter(chat_id=chat_id)
        )
        for next_user in next_game_users:
            try:
                await context.bot.send_message(
                    chat_id=next_user.user_id,
                    text=f"A new HIGH-ROLLER Blackjack game has started in the group {group_name}!"
                )
            except Exception as e:
                print(f"Failed to send message to {next_user.user_id}: {e}")

        # Clear notifications
        await sync_to_async(lambda: NextGameNotification.objects.filter(chat_id=chat_id).delete())()

        await asyncio.sleep(2)
        await context.bot.send_message(chat_id=chat_id, text="🃏 Set your high-roller bet amount to start.")

        # Use create_highroller_poll() instead of create_poll()
        await create_highroller_poll(update, context)

        await asyncio.sleep(2)
        await context.bot.send_message(chat_id=chat_id, text="🃏 High-roller betting process has started!")
        await asyncio.sleep(1)
        reaction = random.choice(betting_phase_reactions)
        await safe_send_reaction(context.bot, chat_id, reaction)
        return

    # If a Game exists and hasn't ended yet, behave exactly as start_blackjack does:
    if game.betting:
        await update.message.reply_text("A Blackjack game is in betting progress. Wait for the betting process to end and use /join to join the game.")
    elif game.started:
        await update.message.reply_text("A game has already started. Use the /nextgame command to be notified when the next game starts.")
    elif game.join_time:
        await update.message.reply_text("A game is in join time. Use the /join command to join the game.")
    else:
        await update.message.reply_text("An error occurred, please try again.")

async def start_blackjack(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await check_player(update, context):
        return
    chat_id = update.message.chat_id
    group_name = update.message.chat.title  # Get the group name

    # Check if a game exists and if it has ended
    game = await sync_to_async(lambda: Game.objects.filter(chat_id=chat_id).order_by('-id').first())()

    if not game or game.ended:
        game, created = await sync_to_async(Game.objects.get_or_create)(chat_id=chat_id, ended=False)
        game.betting = True
        game.started = False
        await sync_to_async(game.save)()

        # Notify users who subscribed to the next game
        next_game_users = await sync_to_async(list)(
            NextGameNotification.objects.filter(chat_id=chat_id)
        )

        # Send a message to each user in their private chat, using the group's actual name
        for next_user in next_game_users:
            try:
                await context.bot.send_message(
                    chat_id=next_user.user_id,
                    text=f"A new Blackjack game has started in the group {group_name}!"
                )
            except Exception as e:
                print(f"Failed to send message to {next_user.user_id}: {e}")

        # Optionally, clear the list after notifying
        await sync_to_async(lambda: NextGameNotification.objects.filter(chat_id=chat_id).delete())()

        await asyncio.sleep(2)
        await context.bot.send_message(chat_id=chat_id, text="🃏 Set the bet amount for the blackjack game to start.")

        await create_poll(update, context)
        

        await asyncio.sleep(2)
        await context.bot.send_message(chat_id=chat_id, text="🃏 Betting process has started!")
        await asyncio.sleep(1)
        reaction = random.choice(betting_phase_reactions)
        await safe_send_reaction(context.bot, chat_id, reaction)
        return


    # Check the game state and respond accordingly
    if game.betting:
        await update.message.reply_text("A Blackjack game is in betting progress. Wait for the betting process to end and use /join to join the game.")
    elif game.started:
        await update.message.reply_text("A game has already started. Use the /nextgame command to be notified when the next game starts.")
    elif game.join_time:
        await update.message.reply_text("A game is in join time. Use the /join command to join the game.")
    else:
        await update.message.reply_text("An error occurred, please try again.")


async def safe_send_poll(bot, chat_id, question, options, max_retries=10):
    retries = 0
    while retries < max_retries:
        try:
            message = await bot.send_poll(chat_id=chat_id, question=question, options=options, is_anonymous=False)
            return message  # Exit if successful
        except TimedOut:
            retries += 1
            await asyncio.sleep(4)  # Use async sleep
        except RetryAfter as e:
            retry_after = int(e.retry_after)
            await asyncio.sleep(retry_after)  # Use async sleep
            retries += 1
# Create poll function for setting bet amounts
async def create_poll(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.message.chat_id

    # Retrieve or create Group instance using sync_to_async
    try:
        group = await sync_to_async(Group.objects.get)(group_chat_id=chat_id)
    except Group.DoesNotExist:
        group = await sync_to_async(Group.objects.create)(group_chat_id=chat_id)

    # Determine if the game should be based on real tokens or chips
    if group.vip and group.real_money:
        options = ["100 $", "200 $", "500 $", "1000 $"]
        if group.games >= 100:
            options.extend(["10000 $", "20000 $", "50000 $"])
        question = "How much do you want to bet (real tokens 💵)?"
    else:
        options = ["10 chips💰", "50 chips💰", "100 chips💰", "200 chips💰", "500 chips💰", "1000 chips💰"]
        if group.games >= 100:
            options.extend(["10000 chips💰", "20000 chips💰", "50000 chips💰"])
        question = "How much do you want to bet (virtual chips 💰)?"

    # Send the poll asynchronously
    message = await safe_send_poll(context.bot, chat_id, question, options)

    # Store poll data in context.bot_data using poll_id as key
    if 'poll_data' not in context.bot_data:
        context.bot_data['poll_data'] = {}
    
    context.bot_data['poll_data'][message.poll.id] = {
        'chat_id': chat_id,
        'poll_message_id': message.message_id
    }

async def poll_answer_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # chat_id = update.message.chat_id

    poll_answer = update.poll_answer
    user_id = poll_answer.user.id
    user_name = poll_answer.user.first_name
    selected_option = poll_answer.option_ids[0]  # Get the index of the selected option

    # Retrieve the poll data from context using poll_id
    poll_data = context.bot_data.get('poll_data', {}).get(poll_answer.poll_id)

    if not poll_data:
        print("No poll data found.")
        return
    else:
        print("Poll data exists.")
        try:
            chat_id = poll_data['chat_id']
            print(f"Chat ID: {chat_id}")

            game = await sync_to_async(Game.objects.get)(
                chat_id=chat_id, betting=False, started=True, ended=False
            )
            print("Game found with betting=False, started=True, ended=False.")
        except Game.DoesNotExist:
            print("No game found with betting=False, started=True, ended=False.")
            try:
                game = await sync_to_async(Game.objects.get)(
                    chat_id=chat_id, betting=True, started=False, ended=False
                )
                print("Game found with betting=True, started=False, ended=False.")
            except Game.DoesNotExist:
                print("Game not found?")
                return

        if game.bet_phase != "total_pot":
            print(f"Current bet phase: {game.bet_phase}")
            if game.bet_phase == "dealer":
                print("Handling dealer poll response.")
                await handle_poll_response(update, context)
            else:
                print("Poll data not found.")
                return


    chat_id = poll_data['chat_id']
    try:
        game = await sync_to_async(Game.objects.get)(chat_id=chat_id, betting=True, started=False, ended=False)
    except Game.DoesNotExist:
        print("Game not found?")
        return
    # Retrieve the group using sync_to_async
    group = await sync_to_async(Group.objects.get)(group_chat_id=chat_id)

    # Set bet amounts based on real tokens or chips
    stored_options = poll_data.get('options')
    if stored_options:
        # This was a HIGH-ROLLER poll, so use that array:
        options = stored_options
    else:
        # It wasn’t a highroller poll—fall back to your “normal betting” array:
        group = await sync_to_async(Group.objects.get)(group_chat_id=chat_id)
        if group.vip and group.real_money:
            options = ["100 $", "200 $", "500 $", "1000 $", "10000 $", "20000 $", "50000 $"]
        else:
            options = [
                "10 chips💰", "50 chips💰", "100 chips💰", "200 chips💰", 
                "500 chips💰", "1000 chips💰", "10000 chips💰", 
                "20000 chips💰", "50000 chips💰"
            ]

    # Now pick the chosen option by index:
    chosen_option = options[selected_option]

    # If “chosen_option” is something like "1 000 000 chips💰", split out the number:
    bet_amount_str = chosen_option.split()[0].replace(" ", "").replace(",", "")  
    # (the .replace() is in case you have non-standard thousands separators)
    bet_amount = int(bet_amount_str)

    # Update the game and save:
    game.bet_amount = bet_amount
    game.betting = False
    game.join_time = True
    game.bet_phase = "dealer"
    await sync_to_async(game.save)()

    # Then send your confirmation to the group (escaping markdown, etc.) as usual
    escaped_user_name = escape_markdown(user_name, version=2)
    currency_type = "$" if (group.vip and group.real_money) else "chips💰"
    chosen_option_escaped = escape_markdown(chosen_option, version=2)

    await context.bot.send_message(
        chat_id=chat_id,
        text=(
            f"[{escaped_user_name}](tg://user?id={user_id}) has set "
            f"the bet amount to {chosen_option_escaped}\n"
            "Use /join to join the game"
        ),
        parse_mode="MarkdownV2"
    )


async def safe_send_message_join(bot, chat_id, text, max_retries=10):
    retries = 0
    while retries < max_retries:
        try:
            await bot.send_message(chat_id=chat_id, text=text)
            return  # Exit the loop if the message is sent successfully
        except TimedOut:
            retries += 1
            print(f"Timeout occurred while sending message. Retrying {retries}/{max_retries}...")
            await asyncio.sleep(4)  # Non-blocking sleep
    print("Failed to send the message after retries.")

async def join_blackjack(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_player(update, context):
        return

    chat_id = update.message.chat_id
    user_id = update.message.from_user.id
    user_name = update.message.from_user.first_name

    try:
        game = await sync_to_async(Game.objects.get)(chat_id=chat_id, join_time=True, started=False, ended=False, betting=False)
    except Game.DoesNotExist:
        await update.message.reply_text("No active game found or the game is not in join time.")
        return

    try:
        player = await sync_to_async(Player.objects.get)(id=user_id)
    except Player.DoesNotExist:
        await update.message.reply_text(f"{user_name}, please start the bot in private first.")
        return

    group = await sync_to_async(Group.objects.get)(group_chat_id=chat_id)

    # Check if the player already joined
    if await sync_to_async(JoinGame.objects.filter(game=game, player=player, is_active=True).exists)():
        await update.message.reply_text(f"{user_name}, you are already in the game!")
        return

    if group.vip and group.real_money:
        # Real token game
        if player.real_tokens < game.bet_amount:
            await update.message.reply_text(
                f"{user_name}, you do not have enough 💵real tokens to join the game.\nMinimum bet is {game.bet_amount} 💵real tokens."
            )
            return
        # Deduct real tokens **when joining**
        player.real_tokens -= game.bet_amount
    else:
        # Chips game
        if player.chips < game.bet_amount:
            await update.message.reply_text(
                f"{user_name}, you do not have enough 💰chips to join the game.\nMinimum bet is {game.bet_amount} 💰chips."
            )
            return
        # Deduct chips **when joining**
        player.chips -= game.bet_amount

    await sync_to_async(player.save)()
    await sync_to_async(JoinGame.objects.create)(player=player, game=game, is_active=True)

    escaped_user_name = escape_markdown(user_name, version=2)

    await context.bot.send_message(
        chat_id=chat_id,
        text=f"[{escaped_user_name}](tg://user?id={user_id}) has joined the game\\!",
        parse_mode="MarkdownV2"
    )
    await context.bot.send_message(
        chat_id=player.id,
        text=f"You have successfully joined a game in group {update.message.chat.title}, Good Luck😃"
    )



scare_players_reactions = [
    "I wouldn’t get too comfortable if I were you. 😈",
    "Do you really think you can win this? Think again. 😏",
    "I can already see the outcome, and it’s not in your favor. 👀",
    "You might want to start preparing for a loss. 🎲",
    "The cards don’t look good for you. Better luck next time. 😎",
    "Feeling lucky? You might need more than that. 😏",
    "Oh, I wouldn’t bet too much on this round if I were you. 🃏",
    "Your fate is sealed. This won’t end well. 😈",
    "I’ve seen better hands, and trust me, this isn’t one of them. 😅",
    "Get ready to lose everything, because that’s where this is heading. 💥",
    "I hope you didn’t go all in, because this might hurt. 💸",
    "The house always wins, and today is no exception. 🤑",
    "I wouldn’t count on winning this one. Better get used to losing. 🎯",
    "This is where it all goes downhill for you. 😎",
    "Enjoy your last moments of hope, because they’re fading fast. 🃏"
]


# Force start the Blackjack game
# Force start the Blackjack game
async def force_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_player(update, context):
        return

    chat_id = update.message.chat_id

    # Find an existing game in join_time state; otherwise walk through other states
    try:
        game = await sync_to_async(Game.objects.get)(
            chat_id=chat_id,
            join_time=True,
            started=False,
            ended=False,
            betting=False
        )
    except Game.DoesNotExist:
        try:
            game = await sync_to_async(Game.objects.get)(
                chat_id=chat_id,
                join_time=False,
                started=False,
                ended=False,
                betting=True
            )
            await safe_send_message_join(
                context.bot,
                chat_id,
                "The game is in the betting process. Please wait for it to end, then /forcestart the game."
            )
            return
        except Game.DoesNotExist:
            try:
                game = await sync_to_async(Game.objects.get)(
                    chat_id=chat_id,
                    join_time=False,
                    started=True,
                    ended=False,
                    betting=False
                )
                await safe_send_message_join(
                    context.bot,
                    chat_id,
                    "A game has already started. You cannot /forcestart. Use /nextgame to be prompted when another game is started."
                )
                return
            except Game.DoesNotExist:
                await safe_send_message_join(
                    context.bot,
                    chat_id,
                    "No active Blackjack game. Start one by typing /startblackjack."
                )
                return

    # Fetch all active players who have joined the game
    joined_players = await sync_to_async(lambda: list(
        JoinGame.objects.filter(game=game, is_active=True)
    ))()

    # If fewer than 1 player, cancel the game immediately
    if len(joined_players) < 1:
        await sync_to_async(Game.objects.filter(chat_id=chat_id).delete)()
        await update.message.reply_text(
            'At least 1 player is required to start the game. Ending the game!'
        )
        return

    # If the game was already forced, no need to do it again
    if game.forced:
        await context.bot.send_message(
            chat_id=chat_id,
            text="This game has already been force\\-started\\."
        )
        return

    game.forced = True
    await sync_to_async(game.save)()

    # Fetch dealer and group
    dealer = await sync_to_async(Dealer.objects.first)()
    group_game, created = await sync_to_async(Group.objects.get_or_create)(
        group_chat_id=chat_id
    )
    group_game.games += 1
    await sync_to_async(group_game.save)()

    # Determine currency type (real tokens vs. chips)
    is_real_token_game = group_game.vip and group_game.real_money
    currency_type = "$" if is_real_token_game else "chips💰"

    # -------------------------------------------
    # CHECK: Does the dealer have enough chips?
    # -------------------------------------------
    if dealer:
        # (If you ever support real tokens, you’d do that check here;
        #  for now, we're only checking chips, as in your original code.)
        if dealer.chips < game.bet_amount:
            # *** REFUND EVERY JOINED PLAYER BEFORE ENDING THE GAME ***
            for join_entry in joined_players:
                player = await sync_to_async(lambda: join_entry.player)()

                # Refund the bet amount:
                if is_real_token_game:
                    player.real_tokens += game.bet_amount
                else:
                    player.chips += game.bet_amount

                await sync_to_async(player.save)()

                # Delete the JoinGame entry so they’re no longer marked "in a game"
                await sync_to_async(join_entry.delete)()

                # Optionally, notify each player privately that they were refunded:
                # (You can comment this out if you prefer not to spam DMs.)
                try:
                    await context.bot.send_message(
                        chat_id=player.id,
                        text=(
                            f"You have been refunded {game.bet_amount} {currency_type} "
                            f"because the dealer could not participate. The game is ending."
                        )
                    )
                except Exception:
                    # In case sending a private message fails, ignore it.
                    pass

            # Delete the Game record entirely
            await sync_to_async(Game.objects.filter(chat_id=chat_id).delete)()

            # Inform the group that the dealer lacked funds and everyone was refunded
            await context.bot.send_message(
                chat_id=chat_id,
                text="🤖 Dealer doesn't have enough chips to participate. "
                     "All players have been refunded and the game is ending."
            )
            return
        else:
            # Dealer **does** have enough chips; deduct from dealer and proceed
            dealer.chips -= game.bet_amount
            dealer.games += 1
            await sync_to_async(dealer.save)()

            reaction = random.choice(scare_players_reactions)
            await safe_send_reaction(context.bot, chat_id, reaction)

            await asyncio.sleep(2)
            await context.bot.send_message(
                chat_id=chat_id,
                text=(
                    f"🤖 Dealer is in the game with {game.bet_amount} {currency_type} on the table\\."
                ),
                parse_mode="MarkdownV2"
            )

    # -------------------------------------------
    # CONTINUE: Deduct each player's bet & start
    # -------------------------------------------

    # If there were ≥5 joined players, unlock the "5_or_more_player" achievement
    if len(joined_players) >= 5:
        for join_entry in joined_players:
            player = await sync_to_async(lambda: join_entry.player)()
            await unlock_achievement(player, "5_or_more_player", context)

    for join_entry in joined_players:
        player = await sync_to_async(lambda: join_entry.player)()

        # Add XP for joining
        await add_xp(player, 10, context)

        # If the bet amount is ≥5000, unlock that achievement
        if game.bet_amount >= 5000:
            await unlock_achievement(player, "5000_game_join", context)

        # Deduct each player’s chips (already checked above that they all had enough)
        if is_real_token_game:
            player.real_tokens -= game.bet_amount
        else:
            player.chips -= game.bet_amount

        # If they went all‐in (chips now 0), unlock that achievement
        if player.chips == 0:
            await unlock_achievement(player, "all_in", context)

        player.games += 1
        await sync_to_async(player.save)()

        # Build the Markdown‐escaped mention & send a group message
        user_name_escaped = re.sub(r'([_*[\]()~`>#+\-=|{}.!])', r'\\\1', player.name)
        mention = f"[{user_name_escaped}](tg://user?id={player.id})"
        remaining_tokens = player.chips if not is_real_token_game else player.real_tokens

        # Fetch active items for this player (excluding XP boosters)
        BOOSTER_TYPES = ["xp_booster_500", "xp_booster_2000", "xp_booster_15000", "xp_booster_50000"]
        active_items = await sync_to_async(lambda: list(
            PlayerActiveItem.objects.filter(player=player, is_active=True)
                              .exclude(item_type__in=BOOSTER_TYPES)
        ))()

        if active_items:
            item_names = [
                escape_md(dict(ITEM_TYPE_CHOICES).get(item.item_type, item.item_type))
                for item in active_items
            ]
            items_text = "🧪 Active: " + ", ".join(item_names)
        else:
            items_text = "🧪 Active: None"

        await asyncio.sleep(2)
        await context.bot.send_message(
            chat_id=chat_id,
            text=(
                f"{mention} has bet {game.bet_amount} {currency_type}\\.\n"
                f"Remaining {currency_type}: {remaining_tokens}\\.\n"
                f"{items_text}"
            ),
            parse_mode="MarkdownV2"
        )

    # Set up turn order, pot, etc., and mark the game as started
    game.turn_order = [join_entry.player.id for join_entry in joined_players]
    game.current_round = 1
    players_count = len(joined_players) + 1  # +1 for the dealer
    game.pot = game.bet_amount * players_count
    game.started = True
    game.join_time = False
    await sync_to_async(game.save)()

    # Proceed to the first round
    await start_round(update, context, game, joined_players)



# # Function to start each round
async def safe_pin_chat_message(bot, chat_id, message_id, max_retries=10):
    retries = 0
    while retries < max_retries:
        try:
            await bot.pin_chat_message(chat_id=chat_id, message_id=message_id)  # Assuming timeout is 20
            return  # Exit the loop if successful
        except TimedOut:
            retries += 1
            print(f"Timeout occurred while pinning message. Retrying {retries}/{max_retries}...")
            await asyncio.sleep(4)  # Non-blocking exponential backoff
        except RetryAfter as e:
            retry_after = int(e.retry_after)
            print(f"Rate limit exceeded. Retrying in {retry_after} seconds...")
            await asyncio.sleep(retry_after)  # Wait for the retry after time
            retries += 1

    print("Failed to pin message after multiple retries.")

async def start_round(update: Update, context: ContextTypes.DEFAULT_TYPE, game, joined_players):
    chat_id = update.message.chat_id

    print(game.current_round)

    if game.current_round >= 2:

        bot_member = await context.bot.get_chat_member(chat_id=chat_id, user_id=context.bot.id)

        round_winners = await sync_to_async(list)(RoundWinner.objects.filter(game=game, is_dealer=False))
        dealer_wins = await sync_to_async(RoundWinner.objects.filter(game=game, is_dealer=True).count)()
        winner_count = {}

        for winner in round_winners:
            # Accessing related 'winner' field asynchronously
            winner_player = await sync_to_async(lambda: winner.winner)()
            if winner_player in winner_count:
                winner_count[winner_player] += 1
            else:
                winner_count[winner_player] = 1

        winners = []
        no_wins = []

        # Fetch related fields with sync_to_async
        for join_entry in joined_players:
            player_name = await sync_to_async(lambda: join_entry.player.name)()
            player_id = await sync_to_async(lambda: join_entry.player.id)()
            wins = winner_count.get(join_entry.player, 0)

            if wins > 0:
                winners.append((player_name, wins, player_id))
            else:
                no_wins.append((player_name, player_id))

        winners = sorted(winners, key=lambda x: x[1], reverse=True)

        await asyncio.sleep(1)
        standings_message = "📊 Current standings:\n"

        if dealer_wins > 0:
            standings_message += f"🤖 Dealer: {dealer_wins} round\\(s\\) won\n"
        else:
            standings_message += "🤖 Dealer: No wins yet\n"

        for winner_name, wins, user_id in winners:
            user_name_escaped = escape_markdown(winner_name, version=2)
            mention = f"[{user_name_escaped}](tg://user?id={user_id})"
            standings_message += f"🏆 {mention}: {wins} round\\(s\\) won\n"

        for player_name, player_id in no_wins:
            user_name_escaped = escape_markdown(player_name, version=2)
            mention = f"[{user_name_escaped}](tg://user?id={player_id})"
            standings_message += f"🎲 {mention}: No wins yet\n"

        message = await context.bot.send_message(chat_id=chat_id, text=standings_message, parse_mode="MarkdownV2")

        # if bot_member.status in ['administrator', 'creator']:
        #     await safe_pin_chat_message(context.bot, chat_id, message.message_id)

    await asyncio.sleep(2)

    await context.bot.send_message(chat_id=chat_id, text=f"Starting round {game.current_round}...")
    await asyncio.sleep(3)
    reaction = random.choice(game_start_reactions)
    await safe_send_reaction(context.bot, chat_id, reaction)

    await asyncio.sleep(2)

    player_blackjacks = []

    for join_entry in joined_players:
        # ── Apply potion/pass only if current round is 1 ──
        used_first_hand_potion = False
        hand_override = None

        if game.current_round == 1:
            active_items = await sync_to_async(list)(
                PlayerActiveItem.objects.filter(player=join_entry.player, is_active=True)
            )

            for item in active_items:
                if item.item_type == "first_hand_20_pass":
                    hand_override = [10, "K"]  # or any 20-point combo you prefer
                    await sync_to_async(item.delete)()  # Consume the pass
                    used_first_hand_potion = True
                    break
                elif item.item_type == "first_hand_11_potion":
                    hand_override = [5, 6]  # 11 points
                    await sync_to_async(item.delete)()  # Consume the potion
                    used_first_hand_potion = True
                    break

        # ── Deal hand ──
        player_hand = hand_override if used_first_hand_potion else [deal_card(), deal_card()]
        join_entry.hand = player_hand
        await sync_to_async(join_entry.save)()

        # ── Show to player if not blackjack ──
        player_hand_value = calculate_hand_value(player_hand)
        if player_hand_value == 21:
            player_blackjacks.append(join_entry)  # ✅ Add to blackjack list
        else:
            await context.bot.send_message(
                chat_id=join_entry.player.id,
                text=f"🃏Your hand: {player_hand}.\n♠️Total value: {player_hand_value}"
            )
        # if player_hand_value != 21:
        #     await context.bot.send_message(
        #         chat_id=join_entry.player.id,
        #         text=f"🃏Your hand: {player_hand}.\n♠️Total value: {player_hand_value}"
        #     )

    dealer_hand = [deal_card(), deal_card()]
    game.dealer_hand = dealer_hand
    await sync_to_async(game.save)()
    

    dealer_value = calculate_hand_value(dealer_hand)
    dealer_has_blackjack = dealer_value == 21

    if dealer_has_blackjack:
        if game.current_round == 1:
            await send_vote_results(update, context,chat_id,game.poll_id)

        await context.bot.send_message(chat_id=chat_id, text="🤖 Dealer has a natural Blackjack! 💥")
        dealer = await sync_to_async(Dealer.objects.get)(id=1)
        dealer.blackjack_count += 1
        await sync_to_async(dealer.save)()

        for join_entry in player_blackjacks:
            await context.bot.send_message(chat_id=chat_id, text=f"{join_entry.player.name} had Blackjack💥 too.")

        await sync_to_async(RoundWinner.objects.create)(game=game, round_number=game.current_round, is_dealer=True)
        game.current_round += 1
        await check_for_next_round(update, context, game, joined_players)
        return

    if player_blackjacks:
        for join_entry in player_blackjacks:
            await unlock_achievement(join_entry.player, "first_natrual_blackjack", context)
            if game.current_round == 1:
                await send_vote_results(update, context,chat_id,game.poll_id)

            await context.bot.send_message(chat_id=chat_id, text=f"{join_entry.player.name} has a natural Blackjack!💥 They win the round.")
            await add_xp(join_entry.player, 35, context)

            stats = await sync_to_async(Stats.objects.get)(player=join_entry.player)

            stats.how_many_21 += 1
            await sync_to_async(stats.save)()
            if stats.how_many_21 >= 21:
                await unlock_achievement(join_entry.player, "21_black_jacks", context)
            if stats.how_many_21 >= 100:
                await unlock_achievement(join_entry.player, "100_black_jacks", context)

            await sync_to_async(RoundWinner.objects.create)(game=game, round_number=game.current_round, winner=join_entry.player)

        game.current_round += 1
        await check_for_next_round(update, context, game, joined_players)
        return

    for join_entry in joined_players:
        if join_entry not in player_blackjacks:
            stats = await sync_to_async(Stats.objects.get)(player=join_entry.player)
            await sync_to_async(stats.save)()

    await player_turn(update, context)

async def send_vote_results(update: Update, context: ContextTypes.DEFAULT_TYPE, chat_id=None, poll_id=None, game=None):
    poll_data = context.bot_data.get('poll_data', {}).get(poll_id)

    if not poll_data:
        print("Poll data not found.")
        return

    correct_guess_player_ids = poll_data.get('correct_guess_player_ids', [])
    wrong_guess_player_ids = poll_data.get('wrong_guess_player_ids', [])
    
    # Set chips and xp based on correct guesses
    if correct_guess_player_ids:
        xp = poll_data.get('xp', [])
        chips = poll_data.get('chips', [])
    else:
        xp = 0
        chips = 0

    # Construct the results message based on correct guesses
    results_message_correct = "✅ Correct Guesses:\n"
    results_message_wrong = "❌ Wrong Guesses:\n"

    if correct_guess_player_ids:
        for player_id in correct_guess_player_ids:
            results_message_correct += f"- Player ID: {player_id}\n"
    else:
        results_message_correct += "No players guessed correctly.\n"

    if wrong_guess_player_ids: 
        for player_id in wrong_guess_player_ids:
            results_message_wrong += f"- Player ID: {player_id}\n"
    else:
        results_message_wrong += "No players guessed incorrectly.\n"

    # Add rewards information
    rewards_message = f"🎉 Players who guessed correctly received:\n💰 {chips} Chips\n📈 {xp} XP"

    # Send the message
    await context.bot.send_message(chat_id=chat_id, text=f"{results_message_correct}\n\n{results_message_wrong}\n\n{rewards_message}")
async def handle_poll_response(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.poll_answer.user.id
    print(f"User ID: {user_id}")

    poll_answer = update.poll_answer
    poll_data = context.bot_data.get('poll_data', {}).get(poll_answer.poll_id)
    
    if not poll_data:
        print("Poll data not found.")
        return

    chat_id = poll_data['chat_id']
    print(f"Chat ID: {chat_id}")

    try:
        join_entry = await sync_to_async(JoinGame.objects.get)(player__id=user_id, game__chat_id=chat_id)
        print(f"Join entry found for user {user_id} in chat {chat_id}.")
    except JoinGame.DoesNotExist:
        print(f"Join entry not found for user {user_id} in chat {chat_id}.")
        return

    try:
        game = await sync_to_async(Game.objects.get)(chat_id=chat_id)
        print(f"Game found for user {game.chat_id}")
    except Game.DoesNotExist:
        print(f"Game not found for user {game.chat_id}")
        return

    if game.dealer_bet_timer == 1:
        return

    poll_id = poll_data['poll_id']
    print(f"Current Poll ID: {poll_id}")

    # Check if the player has already voted
    if user_id in poll_data.get('voted_player_ids', []):
        print(f"Player {user_id} has already voted. Ignoring duplicate vote.")
        return  # Ignore if they've already voted

    # Add user ID to the list of voters
    if 'voted_player_ids' not in poll_data:
        poll_data['voted_player_ids'] = []
    
    poll_data['voted_player_ids'].append(user_id)

    if update.poll_answer.poll_id == poll_id:
        selected_option = update.poll_answer.option_ids[0]
        print(f"Selected option: {selected_option}")

        dealer_value = calculate_hand_value(game.dealer_hand)
        print(f"Dealer's hand value: {dealer_value}")

        correct_guess = (
            (dealer_value < 10 and selected_option == 0) or
            (10 <= dealer_value <= 15 and selected_option == 1) or
            (15 <= dealer_value <= 18 and selected_option == 2) or
            (19 <= dealer_value <= 20 and selected_option == 3) or
            (dealer_value == 21 and selected_option == 4) 
        )
        

        if correct_guess:
            player_playerentry = await sync_to_async(lambda: join_entry.player)()
            player_stats = await sync_to_async(Stats.objects.get)(player=player_playerentry)
            player_stats.correct_dealer_guesses += 1
            await sync_to_async(player_stats.save)()
            player_name = await sync_to_async(lambda: join_entry.player.name)()
            

            pot_amount = game.pot  # Ensure you have access to the pot
            

            bonus = pot_amount // 3  # Calculate 1/3 of the pot
            
            await add_xp(player_playerentry, 50, context)
            

            # Store player ID in the poll data for later use
            context.bot_data['poll_data'][poll_id]['chips'] = bonus
            context.bot_data['poll_data'][poll_id]['xp'] = 50
            
            context.bot_data['poll_data'][poll_id]['correct_guess_player_ids'].append(player_name)

        else:
            player_name = await sync_to_async(lambda: join_entry.player.name)()
            context.bot_data['poll_data'][poll_id]['wrong_guess_player_ids'].append(player_name)
            
    else:
            print("[DEBUG] si")
async def update_statistics(overall_winners, dealer_won_overall, joined_players, context):
    # ─── 1) Handle winners ─────────────────────────────────────────────────────────
    for winner in overall_winners:
        if winner == "dealer":
            await sync_to_async(_increment_dealer_wins)()
        else:
            player = await sync_to_async(Player.objects.get)(id=winner.id)
            stats, _ = await sync_to_async(Stats.objects.get_or_create)(player=player)
            await add_xp(player, 25, context)

            stats.wins += 1
            await sync_to_async(stats.save)()

            total_games = stats.wins + stats.loses
            if stats.wins >= 100:
                await unlock_achievement(player, "100_wins", context)
            if total_games >= 100:
                await unlock_achievement(player, "100_games", context)
            if total_games >= 500:
                await unlock_achievement(player, "500_games", context)

    # ─── 2) Build set of winner IDs (excluding the string 'dealer') ─────────────────
    winner_ids = {w.id for w in overall_winners if w != "dealer"}

    # ─── 3) Determine non‐winners ───────────────────────────────────────────────────
    non_winners = []
    dealer_obj = await sync_to_async(Dealer.objects.first)()
    dealer_id = dealer_obj.id if dealer_obj else None

    for join_entry in joined_players:
        player = await sync_to_async(lambda: join_entry.player)()
        pid = player.id

        if pid not in winner_ids and pid != dealer_id:
            non_winners.append(player)

    # Deduplicate
    non_winners = list({p.id: p for p in non_winners}.values())

    # ─── 4) Apply losses to each non-winner ─────────────────────────────────────────
    for player in non_winners:
        stats, _ = await sync_to_async(Stats.objects.get_or_create)(player=player)
        stats.loses += 1
        await deduct_xp(player, 25, context)
        await sync_to_async(stats.save)()

        total_games = stats.wins + stats.loses
        if stats.loses >= 100:
            await unlock_achievement(player, "100_loses", context)
        if total_games >= 100:
            await unlock_achievement(player, "100_games", context)
        if total_games >= 500:
            await unlock_achievement(player, "500_games", context)

    # ─── 5) Increment dealer losses if dealer did NOT win overall ──────────────────
    if not dealer_won_overall:
        await sync_to_async(_increment_dealer_losses)()

# ─── Synchronous helper: increment dealer.wins ────────────────────────────────────
def _increment_dealer_wins():
    dealer = Dealer.objects.first()
    if dealer:
        dealer.wins += 1
        dealer.save()


# ─── Synchronous helper: increment dealer.loses ──────────────────────────────────
def _increment_dealer_losses():
    dealer = Dealer.objects.first()
    if dealer:
        dealer.loses += 1
        dealer.save()


async def check_for_next_round(update: Update, context: ContextTypes.DEFAULT_TYPE, game, joined_players):
    chat_id = update.message.chat_id
    await asyncio.sleep(3)

    if game.current_round > game.total_rounds:
        # ─── 1) Fetch all RoundWinner rows for this game ──────────────────────────────
        round_winners = await sync_to_async(list)(RoundWinner.objects.filter(game=game))

        # ─── 2) Count how many rounds each player won ─────────────────────────────────
        winner_count = {}
        for row in round_winners:
            winner_player = await sync_to_async(lambda: row.winner)()
            if winner_player:
                winner_count[winner_player] = winner_count.get(winner_player, 0) + 1

        # ─── 3) Count how many rounds the dealer won ─────────────────────────────────
        dealer_rounds_won = await sync_to_async(RoundWinner.objects.filter)(
            game=game, is_dealer=True
        )
        dealer_rounds_won = await sync_to_async(dealer_rounds_won.count)()
        print(f"[DEBUG] Dealer won {dealer_rounds_won} rounds")

        # If dealer won any rounds, put “dealer” into the map for ease of overall-winner logic:
        if dealer_rounds_won > 0:
            winner_count['dealer'] = dealer_rounds_won

        # ─── 4) Determine overall winner(s) ──────────────────────────────────────────
        if winner_count:
            max_wins = max(winner_count.values())
            overall_winners = [w for w, cnt in winner_count.items() if cnt == max_wins]

            # Boolean: did the dealer win the overall game?
            dealer_won_overall = ('dealer' in overall_winners)
            print(f"[DEBUG] overall_winners = {overall_winners}; dealer_won_overall = {dealer_won_overall}")

            if len(overall_winners) == 1:
                single = overall_winners[0]
                if single == 'dealer':
                    await context.bot.send_message(chat_id=chat_id, text="🤖 Dealer is the overall winner of the game! 🏆")
                else:
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text=f"{single.name} is the overall winner of the game! 🏆"
                    )

            else:
                # A tie for top number of rounds
                if len(overall_winners) == (len(joined_players) + 1) and dealer_won_overall:
                    # Everyone (all players + dealer) tied
                    for join_entry in joined_players:
                        player = await sync_to_async(lambda: join_entry.player)()
                        await unlock_achievement(player, "paid_back_tie", context)

                    await context.bot.send_message(
                        chat_id=chat_id,
                        text="All players and the dealer tied and shared the pot! 🏆 Everyone gets the `paid_back_tie` achievement."
                    )
                else:
                    # Multiple winners but not literally everyone
                    pieces = []
                    for w in overall_winners:
                        if w == 'dealer':
                            pieces.append("🤖 Dealer")
                        else:
                            pieces.append(f"[{w.name}](tg://user?id={w.id})")
                    text = ", ".join(pieces) + r" tied and shared the pot\! 🏆"
                    await context.bot.send_message(chat_id=chat_id, text=text, parse_mode="MarkdownV2")

            # ─── 5) Update stats for winners/losers ────────────────────────────────────
            # Pass dealer_won_overall (True/False) instead of raw dealer_rounds_won
            await update_statistics(overall_winners, dealer_won_overall, joined_players, context)
        else:
            await context.bot.send_message(chat_id=chat_id, text="No overall winner was determined.")

        # ─── 6) Finalize / clean up ─────────────────────────────────────────────────
        await end_game(update, context)

        # Prepare standings message (players vs. dealer by round-wins):
        await asyncio.sleep(1)
        standings = "📊 Current standings:\n"
        if dealer_rounds_won > 0:
            standings += f"🤖 Dealer: {dealer_rounds_won} round\\(s\\) won\n"
        else:
            standings += "🤖 Dealer: No wins yet\n"

        # Count only player‐round-winners (exclude dealer)
        player_round_winner_count = {}
        for row in await sync_to_async(list)(RoundWinner.objects.filter(game=game, is_dealer=False)):
            pl = await sync_to_async(lambda: row.winner)()
            player_round_winner_count[pl] = player_round_winner_count.get(pl, 0) + 1

        winners_list = []
        losers_list = []
        for join_entry in joined_players:
            pl = join_entry.player
            wins = player_round_winner_count.get(pl, 0)
            if wins > 0:
                winners_list.append((pl.name, wins, pl.id))
            else:
                losers_list.append((pl.name, pl.id))

        winners_list.sort(key=lambda x: x[1], reverse=True)

        for name, wins, uid in winners_list:
            esc = re.sub(r'([_*[\]()~`>#+\-=|{}.!])', r'\\\1', name)
            mention = f"[{esc}](tg://user?id={uid})"
            standings += f"🏆 {mention}: {wins} round\\(s\\) won\n"

        for name, uid in losers_list:
            esc = re.sub(r'([_*[\]()~`>#+\-=|{}.!])', r'\\\1', name)
            mention = f"[{esc}](tg://user?id={uid})"
            standings += f"🎲 {mention}: No wins yet\n"

        await context.bot.send_message(chat_id=chat_id, text=standings, parse_mode="MarkdownV2")

        # Finally delete the Game record and announce that the game has ended
        await sync_to_async(Game.objects.filter(chat_id=chat_id).delete)()
        await context.bot.send_message(
            chat_id=chat_id,
            text="The game has ended. You can start a new game by typing /startblackjack."
        )

    else:
        # ─── Not finished all rounds: reset for next round ─────────────────────────
        for jp in joined_players:
            jp.has_stood = False
            await sync_to_async(jp.save)()

        game.hands_reset = False
        await sync_to_async(game.save)()
        await asyncio.sleep(2)
        await start_round(update, context, game, joined_players)

async def player_turn(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id

    try:
        # Fetch the active game in the chat
        game = await sync_to_async(Game.objects.get)(chat_id=chat_id, started=True, ended=False)
    except Game.DoesNotExist:
        await update.message.reply_text("No active game or the game has not started.")
        return

    # Get the players in turn order for the current game
    players_in_game = await sync_to_async(list)(
        JoinGame.objects.filter(game=game, is_active=True).order_by('id')
    )

    # Check if turn order exists, initialize if not
    if not game.turn_order or game.current_round > 1:
        game.turn_order = await sync_to_async(list)(
            JoinGame.objects.filter(game=game, is_active=True).values_list('player__id', flat=True)
        )
        await sync_to_async(game.save)()

    # Get the current player from the turn order
    current_player_id = game.turn_order[0]
    current_player = await sync_to_async(Player.objects.get)(id=current_player_id)

    user_name_escaped = re.sub(r'([_*[\]()~`>#+\-=|{}.!])', r'\\\1', current_player.name)
    mention = f"[{user_name_escaped}](tg://user?id={current_player.id})"

    if update.message.from_user.id == current_player_id:
        # Notify the current player it is their turn
        await asyncio.sleep(2)  # Non-blocking sleep
        await context.bot.send_message(
            chat_id=chat_id, 
            text=f"{mention}, it's your turn\\! Type:\n/hit 🎰 to draw a card or \n\n/stand❗ to keep your hand\\.",
            parse_mode="MarkdownV2"
        )
    else:
        # Notify others that the current player is making a decision
        await asyncio.sleep(2)  # Non-blocking sleep
        await context.bot.send_message(
            chat_id=chat_id, 
            text=f"Waiting for {mention}'s decision\\.\\.\\. Type: \n/hit 🎰 to draw a card or \n\n/stand❗ to keep your current hand\\.",
            parse_mode="MarkdownV2"
        )


# # Escape special characters in the player's name

# Asynchronous version of safe_send_message
async def safe_send_message_async(bot, chat_id, text, parse_mode="MarkdownV2", max_retries=10):
    retries = 0
    while retries < max_retries:
        try:
            await bot.send_message(chat_id=chat_id, text=text, parse_mode=parse_mode)
            return  # Exit the loop if the message is sent successfully
        except TimedOut:
            retries += 1
            
            await asyncio.sleep(4)  # Non-blocking exponential backoff
        except RetryAfter as e:
            retry_after = int(e.retry_after)
            
            await asyncio.sleep(retry_after)  # Non-blocking wait for the RetryAfter period before retrying
            retries += 1
    

async def hit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    user_id = update.message.from_user.id
    user_name = update.message.from_user.first_name

    try:
        game = await sync_to_async(Game.objects.get)(chat_id=chat_id, started=True, ended=False)
    except Game.DoesNotExist:
        await update.message.reply_text("No active game or the game has not started.")
        return

    try:
        player = await sync_to_async(Player.objects.get)(id=user_id)
    except Player.DoesNotExist:
        await update.message.reply_text(f"{user_name}, please start the bot in private first.")
        return

    try:
        join_game = await sync_to_async(JoinGame.objects.select_related('player').get)(player=player, game=game, is_active=True)
    except JoinGame.DoesNotExist:
        await update.message.reply_text("You are not part of the game.")
        return

    # Check if it's the player's turn
    try:
        if user_id != game.turn_order[0]:
            await update.message.reply_text("It's not your turn!")
            return
    except:
        await update.message.reply_text("It's not your turn!")
        return
    player_hand = join_game.hand
    hand_value = calculate_hand_value(player_hand)
    if hand_value > 21:
        await update.message.reply_text("You have already busted and cannot take any more actions.")
        return
    elif hand_value == 21:
        await update.message.reply_text("You are automaticly standing and cannot take any more actions.")
        return
    # Add a card to the player's hand
    new_card = deal_card()
    join_game.hand.append(new_card)
    await sync_to_async(join_game.save)()

    user_name_escaped = re.sub(r'([_*[\]()~>#+\-=|{}.!])', r'\\\1', user_name)
    mention = f"[{user_name_escaped}](tg://user?id={user_id})"

    await safe_send_message_async(context.bot, chat_id, f"{mention} drew: {new_card}")

    player_hand = join_game.hand
    hand_value = calculate_hand_value(player_hand)
    
    await safe_send_message_async(context.bot, user_id, f"Your full hand: {player_hand}\\. Total value: {hand_value}")
    # Check for bust or 21
    if hand_value == 21:
        join_game.has_stood = True
        await sync_to_async(join_game.save)()
        await asyncio.sleep(3)
        stats = await sync_to_async(Stats.objects.get)(player=join_game.player)
        stats.how_many_21 += 1
        await sync_to_async(stats.save)()
        if stats.how_many_21 >= 21:
            await unlock_achievement(join_game.player, "21_black_jacks", context)
        if stats.how_many_21 >= 100:
            await unlock_achievement(join_game.player, "100_black_jacks", context)
        

        await safe_send_message_async(context.bot, chat_id, f"{mention} Reached BlackJack💥\\! \n They automatically stand\\.")
        await add_xp(join_game.player, 30, context)
        
        await next_player_turn(update, context)
    elif hand_value > 21:
        insurance = await sync_to_async(PlayerActiveItem.objects.filter)(
            player=join_game.player,
            item_type="insurance_pass",
            is_active=True
        )
        insurance = await sync_to_async(insurance.first)()

        if insurance:
            await sync_to_async(insurance.delete)()

            # Remove last card and save hand
            join_game.hand.pop()
            await sync_to_async(join_game.save)()

            await safe_send_message_async(
                context.bot,
                chat_id,
                f"{mention} busted with {hand_value}, but 🛡️ *Insurance Pass* saved them\\!\nIt's still their turn\\.",
                parse_mode="MarkdownV2"
            )

            # Send updated hand to the player privately
            updated_hand = join_game.hand
            updated_value = calculate_hand_value(updated_hand)
            await safe_send_message_async(
                context.bot,
                user_id,
                f"🛡️ Insurance Pass activated\\!\nYour new hand: {updated_hand}\n♠️ Total value: {updated_value}"
            )
            return
        else:
            if hand_value >= 30:
                await unlock_achievement(join_game.player, "30_or_more_deck", context)
            await asyncio.sleep(3)
            await deduct_xp(join_game.player, 20, context)
            await safe_send_message_async(context.bot, chat_id, f"{mention} busted with a total of {hand_value}\\. ")
            await next_player_turn(update, context)

    else:
        # Check for specific achievements (3 Aces or 3 Sixes)
        ace_count = sum(1 for card in player_hand if card == 'A')
        six_count = sum(1 for card in player_hand if card == '6')

        if ace_count == 3:
            await unlock_achievement(join_game.player, "3_A_in_one_deck", context)
        
        if six_count == 3:
            await unlock_achievement(join_game.player, "thriple_6_in_one_deck", context)

        await asyncio.sleep(3)
        await safe_send_message_async(context.bot, chat_id, f"{mention} Type: \n/hit 🎰 to draw a card or \n\n/stand❗ to keep your current hand\\.")

# Asynchronous stand function
async def stand(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    user_id = update.message.from_user.id
    user_name = update.message.from_user.first_name

    try:
        game = await sync_to_async(Game.objects.get)(chat_id=chat_id, started=True, ended=False)
    except Game.DoesNotExist:
        await update.message.reply_text("No active game or the game has not started.")
        return

    try:
        player = await sync_to_async(Player.objects.get)(id=user_id)
    except Player.DoesNotExist:
        await update.message.reply_text(f"{user_name}, please start the bot in private first.")
        return

    try:
        join_game = await sync_to_async(JoinGame.objects.get)(player=player, game=game, is_active=True)
    except JoinGame.DoesNotExist:
        await update.message.reply_text("You are not part of the game.")
        return
    if join_game.has_stood:
        await update.message.reply_text("You have already chosen to stand and cannot take further actions.")
        return
    # Check if it's the player's turn
    try:
        if user_id != game.turn_order[0]:
            await update.message.reply_text("It's not your turn!")
            return
    except:
        player_hand = join_game.hand
        hand_value = calculate_hand_value(player_hand)

        # Prevent the player from standing if they have already busted
        if hand_value > 21:
            await update.message.reply_text("You have already busted and cannot stand.")
            return
        if hand_value == 21:
            await update.message.reply_text("You are automaticly standing")
            return
        # Check if the player has already chosen to stand
        

    # Mark the player as having stood
    join_game.has_stood = True
    await sync_to_async(join_game.save)()

    user_name_escaped = re.sub(r'([_*[\]()~`>#+\-=|{}.!])', r'\\\1', user_name)
    mention = f"[{user_name_escaped}](tg://user?id={user_id})"

    await safe_send_message_async(context.bot, chat_id, f"{mention} has chosen to stand\\.")

    player_hand = join_game.hand
    hand_value = calculate_hand_value(player_hand)
    await asyncio.sleep(2)

    await safe_send_message_async(context.bot, user_id, f"You have chosen to stand\\. Your final hand: {player_hand}\\. Total value: {hand_value}")

    # Move to the next player's turn
    await next_player_turn(update, context)


# # Function to move to the next player's turn
# # Move to the next player's turn by removing the current player from the turn order
async def safe_send_message_next_player_turn(bot, chat_id, text, max_retries=10):  # Increased timeout
    retries = 0
    while retries < max_retries:
        try:
            await bot.send_message(chat_id=chat_id, text=text, parse_mode="MarkdownV2")
            return  # Exit the loop if the message is sent successfully
        except TimedOut:
            retries += 1
            print(f"Timeout occurred while sending message. Retrying {retries}/{max_retries}...")
            await asyncio.sleep(4)  # Non-blocking sleep before retrying
    print("Failed to send the message after retries.")

# Asynchronous version of next_player_turn
async def next_player_turn(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id

    try:
        game = await sync_to_async(Game.objects.get)(chat_id=chat_id, started=True, ended=False)
    except Game.DoesNotExist:
        await update.message.reply_text("No active game or the game has not started.")
        return

    if not game.turn_order:
        # If no players are left in the turn order, proceed to the dealer's turn
        await dealer_turn(update, context)
        return

    # Remove the current player from the turn order
    game.turn_order.pop(0)
    await sync_to_async(game.save)()

    # Check if there are more players left to take their turn
    if game.turn_order:
        next_player_id = game.turn_order[0]
        next_player = await sync_to_async(Player.objects.get)(id=next_player_id)
        user_name_escaped = re.sub(r'([_*[\]()~`>#+\-=|{}.!])', r'\\\1', next_player.name)
            
        mention = f"[{user_name_escaped}](tg://user?id={next_player_id})"
        await asyncio.sleep(3)  # Non-blocking sleep
        await safe_send_message_next_player_turn(context.bot, chat_id, f"{mention}, it's your turn\\! Type \n/hit 🎰 to draw a card or \n\n/stand❗ to keep your hand\\.")
    else:
        # All players have finished their turns, now it's the dealer's turn
        await dealer_turn(update, context)

# Asynchronous version of safe_send_message_dealer
async def safe_send_message_dealer(bot, chat_id, text, max_retries=10):
    retries = 0
    while retries < max_retries:
        try:
            await bot.send_message(chat_id=chat_id, text=text, parse_mode="MarkdownV2")
            return  # Exit the loop if the message is sent successfully
        except TimedOut:
            retries += 1
            print(f"Timeout occurred while sending message. Retrying {retries}/{max_retries}...")
            await asyncio.sleep(4)  # Non-blocking sleep before retrying
        except RetryAfter as e:
            retry_after = int(e.retry_after)
            print(f"Flood control triggered. Retrying in {retry_after} seconds...")
            await asyncio.sleep(retry_after)  # Non-blocking wait for the RetryAfter period before retrying
            retries += 1
    print("Failed to send the message after retries.")
# Dealer bust reactions
bust_reactions = [
    "Oops! I went over! 😅",
    "Busted! What a surprise! 😬",
    "Uh-oh! I got too greedy. Who would’ve thought? 😳",
    "Looks like I miscalculated. Shocking, right? 😟",
    "Oh no! I’m out! Guess I should have seen that coming! 😖",
    "Well, that didn’t work. Who knew? 😓",
    "I guess I went too far. Wow, what a revelation! 😔",
    "Oops, over the limit! You win this round. How original! 🙈",
    "I should’ve stopped sooner. Classic me! 🤦"
]


# Dealer win reactions
win_reactions = [
    "Better luck next time! Or, you know, maybe just give up! 😎",
    "I win! Care to try again, or is this a one-time deal? 😏",
    "The house always wins! Shocking, right? 🤑",
    "Nice try, but I’ve got this one. How cute! 😌",
    "I told you, I’m unbeatable! You really thought otherwise? 😈",
    "Dealer takes the round! Guess I’ll be here all night! 💪",
    "I got you this time! How unexpected! 😁",
    "Victory is mine! Not that anyone’s surprised! 🎉",
    "A win for the dealer! Ready for another round of disappointment? 🃏",
    "I came out on top this time! Who could’ve seen that coming? 💥"
]


blackjack_reactions = [
    "Blackjack! I’m unbeatable! Shocking, right? 😏",
    "21! Looks like I’ve won this one. What a twist! 🎯",
    "Boom! A perfect 21! Who would’ve guessed? 💥",
    "Blackjack! Can’t do better than that! But hey, keep trying! 🃏",
    "I hit 21! You didn’t stand a chance! Surprise! 😎",
    "Blackjack! The perfect hand. Who knew luck could be this one-sided? 🤑",
    "21! That’s as good as it gets! Try not to cry! 💣",
    "A flawless 21! I win! Again, who saw that coming? 👑",
    "Blackjack! I’m on fire today! Bet you wish you were too! 🔥",
    "21! The perfect game! You know, for me! ✨"
]

all_players_bust_reactions = [
    "Looks like everyone’s out! Guess I’ll just stand here. 😎",
    "Oh, you all busted? Easy win for me! What a surprise! 🃏",
    "Everyone busted? Guess I’ll take this one. How original! 😏",
    "Well, that was quick! I didn’t even have to try. Shocking! 😌",
    "All players busted! I’ll stand and take the win. How unexpected! 👑",
    "I didn’t even need to draw. You made it easy! Thanks for that! 🎉",
    "No cards left for me! You all busted! What a twist! 🃏",
    "Wow, everyone went over! I guess I’ll keep my cards. What a surprise! 💼",
    "Everyone busted? I’ll just take the win, no problem! Not even close! 😎",
    "No need to play it out, I win by default! Shocking outcome! 😈",
    "Well, well, well... looks like you couldn’t keep up! How surprising! 💥",
    "All of you busted? I guess the house wins again! Not that anyone saw that coming! 🏠",
    "Looks like I didn't need to try! I'll take the win. How original! 🎯",
    "You all went over 21? I guess I’ll stand here as the winner. Shocking! 👑",
    "That’s a wrap! Easy win for me. What a surprise! 💥"
]



async def dealer_turn(update: Update, context: ContextTypes.DEFAULT_TYPE):

    chat_id = update.message.chat_id

    try:
        game = await sync_to_async(Game.objects.get)(chat_id=chat_id, started=True, ended=False)
    except Game.DoesNotExist:
        await safe_send_message_dealer(context.bot, chat_id, "No active game or the game has not started.")
        return
    if game.current_round == 1:
        await send_vote_results(update, context,chat_id,game.poll_id)

    await asyncio.sleep(2)
    await safe_send_message_dealer(context.bot, chat_id, "🤖 Dealer's turn\\.\\.\\.")

    dealer_hand = game.dealer_hand
    dealer_value = calculate_hand_value(dealer_hand)

    # Fetch all active players who have joined the game
    joined_players = await sync_to_async(list)(JoinGame.objects.filter(game=game, is_active=True))

    # Check if all players have busted
    all_players_busted = True

    for join_entry in joined_players:
        player_hand_value = calculate_hand_value(join_entry.hand)
        if player_hand_value <= 21:  # If a player has a valid hand
            all_players_busted = False  # At least one player hasn't busted

    # If all players are busted, dealer automatically wins and stands
    if all_players_busted:
        await asyncio.sleep(2)
        await safe_send_message_dealer(context.bot, chat_id, "🤖 All players have busted\\.")
        await asyncio.sleep(2)

        reaction = random.choice(all_players_bust_reactions)
        await safe_send_reaction(context.bot, chat_id, reaction)
        await asyncio.sleep(2)

        await safe_send_message_dealer(context.bot, chat_id, "🤖 Dealer wins🥇 this round\\!")
        
        await sync_to_async(RoundWinner.objects.create)(game=game, round_number=game.current_round, is_dealer=True)
        
        # Move to next round or end game
        game.current_round += 1
        await sync_to_async(game.save)()
        await check_for_next_round(update, context, game, joined_players)
        return  # Exit early since no more actions are needed

    if any(calculate_hand_value(join_entry.hand) == 21 for join_entry in joined_players):
        target_value = 21  # Dealer should aim for 21 if any player has it
    else:
        target_value = 18  # Default target for the dealer

    while dealer_value < target_value:
        # Draw a new card
        new_card = deal_card()
        dealer_hand.append(new_card)
        dealer_value = calculate_hand_value(dealer_hand)
        await asyncio.sleep(2)
        await safe_send_message_dealer(context.bot, chat_id, f"🤖 Dealer draws a 🂾{new_card}\\. 🤖 Dealer's hand: {dealer_hand}")
        
        if dealer_value == 21:
            reaction = random.choice(blackjack_reactions)
            await safe_send_reaction(context.bot, chat_id, reaction)
            break

    # If dealer busts (> 21)
    if dealer_value > 21:
        await asyncio.sleep(2)
        await safe_send_message_dealer(context.bot, chat_id, f"🤖 Dealer busts with a total of {dealer_value}\\!❌")
        reaction = random.choice(bust_reactions)
        await asyncio.sleep(2)
        await safe_send_reaction(context.bot, chat_id, reaction)
        dealer_busted = True
    elif dealer_value == 21:
        await asyncio.sleep(2)
        dealer_busted = False
    else:
        await asyncio.sleep(2)
        await safe_send_message_dealer(context.bot, chat_id, f"🤖 Dealer stands with a total of {dealer_value}\\.")
        dealer_busted = False

    # Save the updated dealer hand
    game.dealer_hand = dealer_hand
    await sync_to_async(game.save)()

    # Fetch all active players who have joined the game
    joined_players = await sync_to_async(list)(JoinGame.objects.filter(game=game, is_active=True))

    # Track the player(s) who win this round
    highest_valid_score = 0
    round_winners = []

    for join_entry in joined_players:
        # Fetch the player asynchronously
        player = await sync_to_async(lambda: join_entry.player)()
        
        player_hand_value = calculate_hand_value(join_entry.hand)
        
        # If player busted, skip them
        if player_hand_value > 21:
            continue
        
        # Track the highest valid hand that beats the dealer (if dealer didn't bust)
        if dealer_busted or player_hand_value > dealer_value:
            if player_hand_value > highest_valid_score:
                highest_valid_score = player_hand_value
                round_winners = [player]
            elif player_hand_value == highest_valid_score:
                round_winners.append(player)
    # Announce the winner(s)
    if not round_winners:
        await asyncio.sleep(2)
        await safe_send_message_dealer(context.bot, chat_id, "🤖 Dealer wins🥇 this round\\!")
        reaction = random.choice(win_reactions)
        await safe_send_reaction(context.bot, chat_id, reaction)
        await sync_to_async(RoundWinner.objects.create)(game=game, round_number=game.current_round, is_dealer=True)
    else:
        for winner in round_winners:
            await asyncio.sleep(2)
            try:
                # Try to tag the winner using their name

                try:
                    escaped_name = escape_markdown(winner.name, version=2)
                    mention = f"[{escaped_name}](tg://user?id={winner.id})"
                except Exception as e:
                    print(f"[WARN] Failed to escape or build MarkdownV2 mention for {winner.name}: {e}")
                    user_name_escaped = re.sub(r'([_*[\]()~`>#+\-=|{}.!])', r'\\\1', winner.name)
                    mention = f"[{user_name_escaped}](tg://user?id={winner.id})"

                # mention = f"[{winner.name}](tg://user?id={winner.id})"
            except Exception as e:
                # Fallback to just using the player's name if tagging fails
                mention = winner.name
                print(f"Error tagging player {winner.name}: {str(e)}")
            await add_xp(winner, 5, context)

            await safe_send_message_dealer(context.bot, chat_id, f"{mention} 🥇wins this round with a hand of {highest_valid_score}\\!")
            if highest_valid_score == 10:
                await unlock_achievement(winner, "win_with_10", context)

            await sync_to_async(RoundWinner.objects.create)(game=game, round_number=game.current_round, winner=winner)

    # Proceed to the next round or end the game if all rounds are done
    game.current_round += 1
    await check_for_next_round(update, context, game, joined_players)


# Asynchronous version of reset_game
async def reset_game(chat_id):
    try:
        # Get the active game with the given chat_id
        game = await sync_to_async(Game.objects.get)(chat_id=chat_id, started=True, ended=False)

        # Mark the game as ended and reset its fields
        game.ended = True
        game.started = False
        game.betting = False
        game.join_time = False
        await sync_to_async(game.save)()

        # Reset all players' is_active status to False for the current game
        await sync_to_async(JoinGame.objects.filter(game=game, is_active=True).update)(is_active=False)

    except Game.DoesNotExist:
        pass
async def end_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id

    try:
        game = await sync_to_async(Game.objects.get)(chat_id=chat_id, started=True, ended=False)
    except Game.DoesNotExist:
        await context.bot.send_message(chat_id=chat_id, text="No active game to end.")
        return

    # Get the group's real money and VIP status
    try:
        group_game = await sync_to_async(Group.objects.get)(group_chat_id=chat_id)
    except Group.DoesNotExist:
        await context.bot.send_message(chat_id=chat_id, text="Group not found.")
        return

    is_real_token_game = group_game.vip and group_game.real_money
    currency_type = "$" if is_real_token_game else "chips💰"

    # Get round winners and determine the final winner
    dealer_rounds_won = await sync_to_async(RoundWinner.objects.filter(game=game, is_dealer=True, rounds_ended=False).count)()
    player_rounds = await sync_to_async(list)(RoundWinner.objects.filter(game=game, is_dealer=False, rounds_ended=False))

    round_wins = {}
    for round_win in player_rounds:
        # Wrap access to the foreign key field in sync_to_async
        winner_player = await sync_to_async(lambda: round_win.winner)()
        if winner_player in round_wins:
            round_wins[winner_player] += 1
        else:
            round_wins[winner_player] = 1

    # Determine the highest number of rounds won
    max_rounds_won = max(max(round_wins.values(), default=0), dealer_rounds_won)

    # Check if any player won all 5 rounds
    if max_rounds_won == 5:
        # If dealer won all 5 rounds
        if dealer_rounds_won == 5:
            for round_win in player_rounds:
                player = await sync_to_async(lambda: round_win.winner)()
                await unlock_achievement(player, "Dealer_wins_5_rounds", context)
            await context.bot.send_message(chat_id=chat_id, text="🤖 Dealer won all 5 rounds!")
        else:
            # If any player won all 5 rounds
            for winner, wins in round_wins.items():
                if wins == 5:
                    await unlock_achievement(winner, "win_5_rounds", context)
    # Find all winners (both dealer and players) who won the maximum number of rounds
    winners = [winner for winner, wins in round_wins.items() if wins == max_rounds_won]
    if dealer_rounds_won == max_rounds_won:
        winners.append('dealer')  # Include the dealer in the winners if they won the max rounds

    # Split the pot evenly among all winners
    if winners:
        MAIN_GROUP_ID = -1002424411318
        # MAIN_GROUP_ID = -1002568101357
    
        if int(chat_id) == MAIN_GROUP_ID:
            # Get all active players in this game
            all_players = await sync_to_async(list)(
                JoinGame.objects.filter(game=game, is_active=True)
            )

            winner_ids = [w.id for w in winners if w != "dealer"]

            # Calculate 10% cashback for each loser
            for join_entry in all_players:
                player = await sync_to_async(lambda: join_entry.player)()

                if player.id not in winner_ids:
                    cashback = int(game.bet_amount * 0.1)

                    if is_real_token_game:
                        player.real_tokens += cashback
                    else:
                        player.chips += cashback

                    await sync_to_async(player.save)()

                    await context.bot.send_message(
                        chat_id=player.id,
                        text=f"🪙 Since you played in the *Main Group*, you’ve received 10% ({cashback} {currency_type}) of your lost bet back!",
                        parse_mode="Markdown"
                    )

        split_pot = game.pot // len(winners)
        
        if 'dealer' in winners:
            winners.remove('dealer')
            dealer = await sync_to_async(Dealer.objects.get)(id=1)
            
            if is_real_token_game:
                dealer.real_tokens += split_pot
            else:
                dealer.chips += split_pot

            await sync_to_async(dealer.save)()
            await context.bot.send_message(chat_id=chat_id, text=f"🤖 Dealer wins {split_pot} {currency_type}!")

        for winner in winners:
            multiplier = 1
            active_items = await sync_to_async(list)(
                PlayerActiveItem.objects.filter(player=winner, is_active=True)
            )

            for item in active_items:
                if item.item_type == "double_chip_potion":
                    multiplier = 2
                elif item.item_type == "triple_chip_potion":
                    multiplier = 3
                elif item.item_type == "10x_chip_potion":
                    multiplier = 10

                if multiplier > 1:
                    await sync_to_async(item.delete)()
                    break  # Only one potion should apply

            final_reward = split_pot * multiplier

            if is_real_token_game:
                winner.real_tokens += final_reward
            else:
                winner.chips += final_reward

            await sync_to_async(winner.save)()
            await apply_referral_bonus(winner, final_reward, context)

            await context.bot.send_message(
                chat_id=chat_id,
                text=f"{winner.name} wins {final_reward} {currency_type}!"
            )


    else:
        await context.bot.send_message(chat_id=chat_id, text="No one won this game.")

    # Mark the game as ended
    game.ended = True
    game.started = False
    game.betting = False
    game.join_time = False
    await sync_to_async(game.save)()
# Asynchronous version of reset_round_state
async def reset_round_state(game):
    # Reset the hands and necessary state for the next round
    await sync_to_async(JoinGame.objects.filter(game=game, is_active=True).update)(hand=[])
    game.dealer_hand = []
    await sync_to_async(game.save)()



# Asynchronous version of get_player_instance
async def get_player_instance(user_id):
    try:
        player = await sync_to_async(Player.objects.get)(id=user_id)
        return player
    except ObjectDoesNotExist:
        return None

# Asynchronous version of get_player_chips
async def get_player_chips(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    
    # Fetch the player instance
    player = await get_player_instance(user_id)
    
    if player:
        stats_message = (
            f"💰 Chips: {player.chips}\n"
            f"💵 Real Tokens: {player.real_tokens}\n"
        )
        
        # Send the stats message to the chat
        await context.bot.send_message(chat_id=update.message.chat_id, text=stats_message)
    else:
        # Handle the case where the player does not exist
        await context.bot.send_message(chat_id=update.message.chat_id, text="You don't have a player profile yet. Start the bot in private to create one.")

# Asynchronous version of get_dealer_blackjack_stats
async def get_dealer_blackjack_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id

    try:
        dealer = await sync_to_async(Dealer.objects.first)()  # Assuming there's only one dealer
        if dealer is None:
            await context.bot.send_message(chat_id=chat_id, text="No dealer stats found.")
            return

        # Format the dealer stats into a readable format
        stats_message = (
            f"🤖 Dealer's Blackjack Stats:\n"
            f"💰 Chips: {dealer.chips}\n"
            f"💵 Real Tokens: {dealer.real_tokens}\n"
            f"Wins: {dealer.wins}\n"
            f"Losses: {dealer.loses}\n"
            f"💥 Blackjacks: {dealer.blackjack_count}"
        )
        
        # Send the stats message to the chat
        await context.bot.send_message(chat_id=chat_id, text=stats_message)

    except Exception as e:
        await context.bot.send_message(chat_id=chat_id, text=f"Error retrieving dealer stats: {str(e)}")
async def flee_game(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.message.from_user.id
    chat_id = update.message.chat_id

    try:
        game = await sync_to_async(Game.objects.get)(chat_id=chat_id, join_time=True, ended=False)

        if game.started:
            await update.message.reply_text("The game has already started, you can no longer flee.")
            return

        join_instance = await sync_to_async(JoinGame.objects.get)(player_id=user_id, game=game, is_active=True)
        player = await sync_to_async(Player.objects.get)(id=user_id)
        group = await sync_to_async(Group.objects.get)(group_chat_id=chat_id)

        # Refund the player's bet (based on whether it was real tokens or chips)
        if group.vip and group.real_money:
            player.real_tokens += game.bet_amount
        else:
            player.chips += game.bet_amount

        await sync_to_async(player.save)()
        await sync_to_async(join_instance.delete)()

        user_name_escaped = escape_markdown(update.message.from_user.first_name, version=2)
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"[{user_name_escaped}](tg://user?id={user_id}) has fled the game and is no longer part of it\\.",
            parse_mode="MarkdownV2"
        )

    except Game.DoesNotExist:
        await update.message.reply_text("No active game to flee from in this chat.")
    except JoinGame.DoesNotExist:
        await update.message.reply_text("You are not currently part of the game.")


async def nextgame(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.message.from_user.id
    chat_id = update.message.chat_id

    # Add the user to the next game notification list
    _, created = await sync_to_async(NextGameNotification.objects.get_or_create)(user_id=user_id, chat_id=chat_id)

    if created:
        await update.message.reply_text("You will be notified when the next game starts!")
    else:
        await update.message.reply_text("You're already signed up to be notified when the next game starts.")
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await check_player(update, context):
        return

    user_id = update.message.from_user.id
    user_name = update.message.from_user.first_name
    chat_id = update.message.chat_id

    # Notify in group that help is in private chat
    if chat_id != user_id:
        await update.message.reply_text(
            "📩 A message with all available commands and instructions has been sent to your private chat."
        )

    # Full help text (plain text, no Markdown formatting)
    full_help = """
Blackjack Bot Help & Command Reference

How to Play a Group Blackjack Game:
  1. Any member types /startblackjack → bot opens a join window.  
  2. Players type /join (in that group) to reserve their seat and lock in their bet.  
  3. Once enough players have joined, use /forcestart to begin.  
  4. The bot deals two cards to each player privately, and two to itself (one face-down).  
  5. In turn order, each player privately chooses /hit or /stand.  
      – If a player’s hand > 21, they bust and lose immediately.  
  6. After all players finish, the dealer reveals the hidden card and draws until ≥ 17.  
  7. Settlement:
      – Dealer higher or tie → player loses.   
  8. XP is awarded/lost accordingly (see “XP & Leveling”).  
      – Winners gain XP, losers lose XP.

────────────────────────────────────────
Getting Started:
  • /start  
    – Register yourself with the bot. You’ll receive 20 chips to begin.

  • /help  
    – Show this help message again (sent to your private chat).

  • /rules  
    – Display detailed rules of the Blackjack game.

  • /stats  
    – View your personal statistics (wins, losses, XP, level, etc.).

  • /nextgame  
    – Ask the bot to send you a private reminder when the next game starts.

────────────────────────────────────────
Blackjack Game Flow:
1) /startblackjack  
   – Initiate a new Blackjack game in the group. The bot will open a “join” period during which players can enter.

2) /join  
   – Join the current game (during the join window). You must have at least the minimum bet in your chips to enter.  
   – As soon as you tap /join, the bot will deduct the required amount from your chips.

3) /forcestart  
   –  Use this command to start the game. Once forced, no new players can join.  
   – The dealer (bot) also contributes the same bet amount. Cards are dealt to each player.

4) During your turn:
   • /hit  
     – Draw one more card. If your hand exceeds 21, you bust and lose immediately.

   • /stand  
     – Keep your current hand and end your turn. The next player goes, and eventually the dealer completes their hand.

   • /flee  
     – Leave the current Blackjack game (forfeit your bet).



────────────────────────────────────────
Minigames & Side Games:
  These can be played anytime in private chat or group. Use /minigames to see a detailed list of them.
  • /dice [betamount]  
    – Roll two dice and guess the outcome. Win up to 6× your bet.

  • /slot [betamount]  
    – Pull the slot machine lever. Match symbols to win big.

  • /coin [heads/tails] [betamount]  
    – Flip a coin. Guess heads or tails; double or lose your bet.

  • /draw [betamount]  
    – Draw a random card. Higher card wins against the bot’s draw.

  • /rps [rock/paper/scissors] [betamount]  
    – Play Rock-Paper-Scissors against the bot. Win or tie.

  • /dart  
    – Throw a dart and earn up to 200 XP. Available twice per day.
  
  • /spin - Spin the wheel once a day for a chance to win chips, XP, or levels! Type /spin <low/mid/high> and let the wheel decide your fate
    
  • /roulette - Bet on red, black, or a number (0-36). Usage: /roulette <red|black|0-36> <bet amount>
       If you guess the color, you win double; if you guess the number, you win 35 times your bet! Good luck!
────────────────────────────────────────
Economy & Token Commands:
  • /my_tokens  
    – Show your current chip balance.

  • /claim_tokens  
    – Claim free chips twice per day (if available).

────────────────────────────────────────
Achievements & Rewards:
  • /achievements  
    – View your unlocked achievements and progress toward new ones.

  • /achievements_info  
    – Display how to unlock each achievement (conditions and icons).

  – Achievements grant bonus XP when unlocked (+20 XP each).

────────────────────────────────────────
XP & Leveling System:
  – You earn XP by playing and winning:
      • Play any game: +10 XP  
      • Win a Blackjack round: +5 XP  
      • Win a full Blackjack game: +25 XP  
      • Get Blackjack: +30 XP  
      • Unlock an achievement: +20 XP  

  – You lose XP for poor performance:
      • Bust in a hand: –20 XP  
      • Lose a full Blackjack game: –25 XP  

  – Each level requires 50 XP × current level. Example:
      • Level 1 → need 50 XP to reach Level 2  
      • Level 2 → need 100 XP to reach Level 3 (and so on)

  – Check your progress with /stats (shows “XP to next level”).

────────────────────────────────────────
Loan System:
  • /loan [amount]  
    – Borrow chips. For every 100 chips borrowed, you lose 5 XP.  
      • If you don’t have enough XP, you may lose levels instead.

  • /repay_loan  
    – Repay your outstanding loan plus 3% interest.  
      • E.g., if you borrowed 100 chips, you must repay 103 chips.


────────────────────────────────────────
Use these commands any time the bot is in a chat. If you need more help, type /help again.

Good luck and have fun! 🃏🎉
"""

    # Split into 4000-character chunks
    max_length = 4000
    chunks = []
    text = full_help.strip()
    while text:
        if len(text) <= max_length:
            chunks.append(text)
            break
        # Find last newline before max_length to avoid splitting mid-line
        split_pos = text.rfind("\n", 0, max_length)
        if split_pos == -1:
            split_pos = max_length
        chunks.append(text[:split_pos].rstrip())
        text = text[split_pos:].lstrip()

    # Send each chunk as plain text
    for chunk in chunks:
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=chunk
            )
        except Exception as e:
            print(f"Error sending help message to {user_name} (ID: {user_id}): {e}")
            break


async def rules_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await check_player(update, context):
        return

    user_id = update.message.from_user.id

    # Inform user in the group chat
    await update.message.reply_text("📩 A message with the game rules has been sent to your private chat.")

    # Send the rules message to the user's private chat
    rules_text = """
    🎮 *Blackjack Game Rules* 🎮
    
    The goal of the game is to get as close to 21 as possible without going over.
    
    *Basic Rules*:
    
    1. Each player is dealt two cards, and they can choose to "hit" to get more cards or "stand" to keep their hand.
    2. Numbered cards (2-10) are worth their face value.
    3. Face cards (Jack, Queen, King) are worth 10 points each.
    4. Aces can be worth either 1 or 11 points, depending on what benefits the player.
    
    *Game Flow*:
    
    - Players take turns to either hit or stand.
    - The goal is to reach 21 or as close to it as possible without going over (busting).
    - If a player’s total goes over 21, they lose automatically (bust).
    - If all players bust, the dealer wins the round.

    *Dealer Rules*:
    
    - The dealer will also draw cards but must stand if their total is 18 or higher.
    - The dealer must hit if their total is 16 or lower.
    
    *Betting*:
    
    - Players can place bets before the game starts.
    - The total bet amount is divided among the winners, or goes to the dealer if all players bust.
    
    *Winning*:
    
    - The player closest to 21 without busting wins the round.
    - If the dealer busts and all players stand with a valid hand, the highest hand wins.
    
    Enjoy the game, and good luck! 🍀
    """
    await context.bot.send_message(chat_id=user_id, text=rules_text, parse_mode="Markdown")








async def set_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.message.chat_id
    chat_name = update.message.chat.title  # Get the group's name
    args = context.args

    if len(args) != 1 or args[0] not in ["real_token", "chips"]:
        await update.message.reply_text(
            "Invalid usage. Use /set_status real_token or /set_status chips."
        )
        return

    try:
        # Fetch the group from the database based on chat_id
        group = await sync_to_async(Group.objects.get)(group_chat_id=chat_id)
    except Group.DoesNotExist:
        # If group doesn't exist, create a new one and set the name
        group = await sync_to_async(Group.objects.create)(group_chat_id=chat_id, group_name=chat_name)

    # Update the group name if it has changed
    if group.group_name != chat_name:
        group.group_name = chat_name

    # Check if the group is VIP
    if group.vip:
        # Set status based on the command argument
        if args[0] == "real_token":
            group.real_money = True
            await update.message.reply_text("This group is now using 💵real tokens for the next games.")
        else:
            group.real_money = False
            await update.message.reply_text("This group is now using 💰chips for the next games.")
    else:
        # If group is not VIP, always use chips
        group.real_money = False
        await update.message.reply_text("This group is not VIP. Using chips for the next games.")

    # Save the updated group settings
    await sync_to_async(group.save)()







ADMIN_CHAT_ID = '1628536823'

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.message.from_user.id
    chat_id = update.message.chat_id

    # Ensure the message is sent in private chat (user_id == chat_id)
    if chat_id == user_id:
        # Get the player's profile information
        try:
            player = await sync_to_async(Player.objects.get)(id=user_id)
            profile_info = (
                f"Player Profile:\n"
                f"Name: {player.name}\n"
                f"Chips: {player.chips}\n"
                f"Games Played: {player.games}\n"
                f"Real Tokens: {player.real_tokens}\n"
            )
        except ObjectDoesNotExist:
            profile_info = "Player profile not found."

        # Get the highest resolution of the photo
        photo_file = update.message.photo[-1].file_id
        caption = update.message.caption if update.message.caption else "No caption"

        # Combine the caption with the player's profile info
        message_text = f"Photo from {update.message.from_user.first_name} (ID: {user_id})\n\n{profile_info}\nCaption: {caption}"

        # Forward the photo to your own private chat
        await context.bot.send_photo(
            chat_id=ADMIN_CHAT_ID,
            photo=photo_file,
            caption=message_text
        )

        # Optionally, send a confirmation message to the user
        await update.message.reply_text("Your photo and profile have been forwarded to the admin.")
    else:
        pass
        # await update.message.reply_text("Please send the photo in private chat.")


photo_handler = MessageHandler(filters.PHOTO, handle_photo)


async def buy_tokens(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.message.from_user.id
    chat_id = update.message.chat_id
    user_name = update.message.from_user.first_name

    # Define the credit card number and token buying details
    credit_card_info = "Credit Card Number: \n6219 8619 4904 7871\nهیربد افلاکی "
    token_info = "💵Each 100 real tokens is : 10 Toman\\."

    # Check if the message was sent in a group or private chat
    if chat_id != user_id:
        # If in a group, notify the user that the message will be sent privately
        await context.bot.send_message(chat_id=chat_id, text="A message has been sent to your private chat with the payment details.")
    
    # Send the message with credit card info and token buying options to the user's private chat
    await context.bot.send_message(
        chat_id=user_id,
        text=f"Hello {user_name},\n\n{token_info}\n{credit_card_info}",
        parse_mode="MarkdownV2"
    )

    # Optionally log or notify in case of failure to send to private chat
    try:
        await context.bot.send_message(chat_id=user_id, text="Send the image here, after the PURCHASE was DONE")
    except Exception as e:
        print(f"Error sending message to user {user_id}: {e}")
# Function to give tokens (real or fake) only if the player is admin
async def give_token(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.message.from_user.id
    try:
        # Check if the player exists and is an admin
        player = await sync_to_async(Player.objects.get)(id=user_id)
        
        if not player.admin:
            await update.message.reply_text("You do not have permission to use this command.")
            return

        # Parse arguments: token type, target player id, and amount
        args = context.args
        if len(args) != 3 or args[0] not in ["real_token", "chips"]:
            await update.message.reply_text("Usage: /give_token real_token|chips [user_id] [amount]")
            return
        
        token_type = args[0]
        target_user_id = args[1]
        amount = int(args[2])

        # Fetch the target player
        try:
            target_player = await sync_to_async(Player.objects.get)(id=target_user_id)
        except ObjectDoesNotExist:
            await update.message.reply_text(f"Player with ID {target_user_id} does not exist.")
            return

        # Update the player's tokens
        if token_type == "real_token":
            target_player.real_tokens += amount
            await update.message.reply_text(f"{amount} 💵 real tokens have been given to {target_player.name}.")
        else:
            target_player.chips += amount
            await update.message.reply_text(f"{amount} 💰 chips have been given to {target_player.name}.")

        # Save the changes
        await sync_to_async(target_player.save)()

        # Send a private message to the target player
        await context.bot.send_message(
            chat_id=target_user_id,
            text=f"{amount} {'💵 real tokens' if token_type == 'real_token' else '💰 chips'} have been given to you by the admin."
        )
    except ObjectDoesNotExist:
        await update.message.reply_text("You are not registered as a player.")

async def get_player_user_id(player_name: str):
    try:
        # Fetch the player by name
        player = await sync_to_async(Player.objects.get)(name=player_name)
        return player.id  # The user_id from the Player model
    except ObjectDoesNotExist:
        return None

# Command handler for /get_user_id
async def get_user_id_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) == 0:
        await update.message.reply_text("Please provide a player name. Usage: /get_user_id [player_name]")
        return
    
    player_name = context.args[0]
    
    # Retrieve the user ID
    user_id = await get_player_user_id(player_name)

    if user_id:
        await update.message.reply_text(f"User ID for {player_name} is {user_id}.")
    else:
        await update.message.reply_text(f"Player with the name {player_name} was not found.")
from django.db import transaction




async def save_player(player):
    """Ensures player data is saved asynchronously."""
    await sync_to_async(player.save)()

async def validate_bet_amount(update, bet_amount):
    if bet_amount <= 0:
        await update.message.reply_text("❌ Invalid bet amount. It must be a positive number.")
        return False
    return True

# games------------------------------
async def slot_machine(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await asyncio.sleep(0.9)
    
    user_id = update.message.from_user.id
    bet_amount = int(context.args[0]) if context.args else 50  # Default bet amount is 50 chips
    if not await validate_bet_amount(update, bet_amount):
            return
    if not await check_player(update, context):
        return

    player = await sync_to_async(Player.objects.get)(id=user_id)

    if player.chips < bet_amount:
        await update.message.reply_text("You don't have enough chips to spin the slot machine!")
        return

    # Deduct the bet amount
    player.chips -= bet_amount
    await save_player(player)  # Ensure it's saved properly

    # Possible slot symbols
    slot_symbols = ['🍒', '🍋', '💰', '🍀', '🔔', '⭐']

    # Send the initial message
    message = await update.message.reply_text('🎰 Spinning...')

    # Simulate spinning effect
    spinning_texts = [
        '🎰 Spinning... 🍒 | 🍋 | 💰',
        '🎰 Spinning... 🍀 | 💰 | 🔔',
        '🎰 Spinning... ⭐ | 🍋 | 🍒',
        '🎰 Spinning... 🔔 | ⭐ | 🍀',
        '🎰 Spinning... 🍒 | 💰 | ⭐'
    ]

    for text in spinning_texts:
        await message.edit_text(text)
        await asyncio.sleep(1)

    # Final result
    slot_result = [random.choice(slot_symbols) for _ in range(3)]
    result_text = ' | '.join(slot_result)

    winnings = 0  # Initialize winnings

    # Check winning conditions
    if len(set(slot_result)) == 1:  # Jackpot (all symbols match)
        winnings = bet_amount * 10
    elif slot_result[0] == slot_result[1] or slot_result[1] == slot_result[2]:  # Two match
        winnings = bet_amount * 3

    # Update player chips if won
    if winnings > 0:
        player.chips += winnings
        await save_player(player)  # Save after updating winnings
        await apply_referral_bonus(player, winnings, context)

        await message.edit_text(f"🎰 {result_text} 🎰\nYou win {winnings} chips! 🎉")
    else:
        await message.edit_text(f"🎰 {result_text} 🎰\nNo match! You lose your bet. 😢")




async def coinflip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await asyncio.sleep(0.9)

    user_id = update.message.from_user.id
    guess = context.args[0].lower() if context.args else 'heads'  # Default to heads if no argument
    bet_amount = int(context.args[1]) if len(context.args) > 1 else 50  # Default bet amount is 50 chips
    if not await validate_bet_amount(update, bet_amount):
            return
    if guess not in ['heads', 'tails']:
        await update.message.reply_text("Please choose either 'heads' or 'tails'.")
        return

    if not await check_player(update, context):
        return

    player = await sync_to_async(Player.objects.get)(id=user_id)

    if player.chips < bet_amount:
        await update.message.reply_text("You don't have enough chips for this bet!")
        return

    # Deduct the bet amount
    player.chips -= bet_amount
    await sync_to_async(player.save)()

    # Send the initial "spinning" message
    message = await update.message.reply_text("🪙 Flipping the coin...")

    # Simulate the flipping effect with several edits
    flip_animation = ['🪙 Heads...', '🪙 Tails...', '🪙 Heads...', '🪙 Tails...']

    for flip in flip_animation:
        await message.edit_text(flip)
        await asyncio.sleep(0.5)

    # Final coin flip result
    flip_result = random.choice(['heads', 'tails'])

    if flip_result == guess:
        winnings = bet_amount * 2
        player.chips += winnings

        await sync_to_async(player.save)()
        await apply_referral_bonus(player, winnings, context)

        await message.edit_text(f"🪙 Coin landed on {flip_result.capitalize()}! You win {winnings} chips!")
    else:
        await message.edit_text(f"🪙 Coin landed on {flip_result.capitalize()}! You lose your bet.")

cards = ['2', '3', '4', '5', '6', '7', '8', '9', '10', 'J', 'Q', 'K', 'A']
card_values = {card: index for index, card in enumerate(cards, start=2)}

async def lucky_draw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await asyncio.sleep(0.9)

    user_id = update.message.from_user.id
    bet_amount = int(context.args[0]) if context.args else 50  # Default bet amount is 50 chips
    if not await validate_bet_amount(update, bet_amount):
            return
    if not await check_player(update, context):
        return

    player = await sync_to_async(Player.objects.get)(id=user_id)

    if player.chips < bet_amount:
        await update.message.reply_text("You don't have enough chips for this bet!")
        return

    # Deduct the bet amount
    player.chips -= bet_amount
    await sync_to_async(player.save)()

    # Send the initial message
    message = await update.message.reply_text("🃏 Drawing your card...")

    # Draw player's card
    await asyncio.sleep(2)  # Wait to build suspense
    player_card = random.choice(cards)
    await message.edit_text(f"🃏 You drew: {player_card}")

    # Wait a bit and simulate dealer's turn
    await asyncio.sleep(2)
    await message.edit_text(f"🃏 You drew: {player_card}\n\nDealer is drawing a card...")

    # Draw dealer's card
    await asyncio.sleep(2)  # More suspense before revealing
    bot_card = random.choice(cards)
    await message.edit_text(f"🃏 You drew: {player_card}\n\nDealer drew: {bot_card}")

    # Compare card values
    player_card_value = card_values[player_card]
    bot_card_value = card_values[bot_card]

    # Determine the result after a short pause
    await asyncio.sleep(2)

    if player_card_value > bot_card_value:
        winnings = bet_amount * 2
        player.chips += winnings
        await sync_to_async(player.save)()
        await apply_referral_bonus(player, winnings, context)

        await message.edit_text(f"🃏 You drew: {player_card}\n\nDealer drew: {bot_card}\n\nYou win {winnings} chips!")
    elif player_card_value == bot_card_value:
        player.chips += bet_amount  # Return the bet for a tie
        await sync_to_async(player.save)()
        await message.edit_text(f"🃏 You drew: {player_card}\n\nDealer drew: {bot_card}\n\nIt's a tie! You get your bet back.")
    else:
        await message.edit_text(f"🃏 You drew: {player_card}\n\nDealer drew: {bot_card}\n\nYou lose your bet.")



choices = ['rock', 'paper', 'scissors']
choice_emojis = {'rock': '🪨', 'paper': '📄', 'scissors': '✂️'}

# Rock-Paper-Scissors game
async def rps_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await asyncio.sleep(0.9)

    user_id = update.message.from_user.id
    # Parse the player's choice and the bet amount from the command
    player_choice = context.args[0].lower() if len(context.args) > 0 else 'rock'  # Default to rock
    bet_amount = int(context.args[1]) if len(context.args) > 1 else 50  # Default bet amount is 50 chips
    if not await validate_bet_amount(update, bet_amount):
            return
    if player_choice not in choices:
        await update.message.reply_text("Please choose either 'rock', 'paper', or 'scissors'.")
        return

    if not await check_player(update, context):
        return

    player = await sync_to_async(Player.objects.get)(id=user_id)

    # Check if the player has enough chips for the bet
    if player.chips < bet_amount:
        await update.message.reply_text(f"You don't have enough chips to place a bet of {bet_amount}!")
        return

    # Deduct the bet amount
    player.chips -= bet_amount
    await sync_to_async(player.save)()

    # Initial message
    message = await update.message.reply_text(f"👊 You chose {choice_emojis[player_choice]} {player_choice.capitalize()}!\nWaiting for the dealer...")

    # Simulate dealer's choice with suspense
    await asyncio.sleep(2)
    bot_choice = random.choice(choices)
    await message.edit_text(f"👊 You chose {choice_emojis[player_choice]} {player_choice.capitalize()}!\n🤖 Dealer is thinking...")

    await asyncio.sleep(2)
    await message.edit_text(f"👊 You chose {choice_emojis[player_choice]} {player_choice.capitalize()}!\n🤖 Dealer chose {choice_emojis[bot_choice]} {bot_choice.capitalize()}!")

    # Compare choices and determine the outcome
    await determine_rps_winner(player_choice, bot_choice, player, message, bet_amount,context)


# Determine the winner of the Rock-Paper-Scissors game
async def determine_rps_winner(player_choice, bot_choice, player, message, bet_amount,context):
    # Rules of Rock-Paper-Scissors
    win_conditions = {
        'rock': 'scissors',
        'scissors': 'paper',
        'paper': 'rock'
    }

    # Win, lose, or tie
    if player_choice == bot_choice:
        player.chips += bet_amount  # Return bet for tie
        await sync_to_async(player.save)()
        await asyncio.sleep(2)
        await message.edit_text(f"🤝 It's a tie! You get your bet of {bet_amount} chips back!")
    elif win_conditions[player_choice] == bot_choice:
        winnings = bet_amount * 2
        player.chips += winnings
        await sync_to_async(player.save)()
        await asyncio.sleep(2)
        await apply_referral_bonus(player, winnings, context)

        await message.edit_text(f"🎉 You win! {choice_emojis[player_choice]} beats {choice_emojis[bot_choice]}!\nYou win {winnings} chips!")
    else:
        await asyncio.sleep(2)
        await message.edit_text(f"😔 You lose! {choice_emojis[bot_choice]} beats {choice_emojis[player_choice]}!\nYou lose your bet of {bet_amount} chips.")

CRASH_SPEED = 0.6  # seconds per tick

# IDs of users who should crash early
RIGGED_USER_IDS = [1936170078, 5501122833]  # Replace with actual user IDs

async def simulate_crash_game(game_id, bot, chat_id):
    try:
        game = await sync_to_async(CrashGame.objects.get)(id=game_id)
    except CrashGame.DoesNotExist:
        return

    # Determine crash range
    user_id = game.user_id  # Or however you store the player
    if user_id in RIGGED_USER_IDS:
        crash_point = round(random.uniform(1.0, 2.5), 2)
    else:
        crash_point = round(random.uniform(1.0, 1.6), 2)

    print(f"Crash point: {crash_point}")

    multiplier = 0.6
    try:
        msg = await bot.send_message(chat_id=chat_id, text=f"🚀 Starting at {multiplier}x")
    except Exception as e:
        print(f"❌ Failed to send start message: {e}")
        return


    while multiplier < crash_point:
        multiplier = round(multiplier + 0.7, 2)
        await asyncio.sleep(CRASH_SPEED)

        game_exists = await sync_to_async(CrashGame.objects.filter(id=game_id).exists)()
        if not game_exists:
            return

        await sync_to_async(CrashGame.objects.filter(id=game_id).update)(multiplier=multiplier)

        is_cashed_out = await sync_to_async(
            lambda: CrashGame.objects.filter(id=game_id, cashed_out=True).exists()
        )()
        if is_cashed_out:
            return

        try:
            await msg.edit_text(f"🚀 {multiplier}x")
        except RetryAfter as e:
            await asyncio.sleep(e.retry_after + 1)
        except Exception:
            continue

    await sync_to_async(CrashGame.objects.filter(id=game_id).update)(crashed=True)

    final_text = f"💥 Crashed at {crash_point}x! You lost your bet."
    try:
        await msg.edit_text(final_text)
    except RetryAfter as e:
        await asyncio.sleep(e.retry_after + 1)
        try:
            await msg.edit_text(final_text)
        except Exception:
            await bot.send_message(chat_id=chat_id, text=final_text)
    except Exception:
        await bot.send_message(chat_id=chat_id, text=final_text)

    await sync_to_async(CrashGame.objects.filter(id=game_id).delete)()

# Your command
async def crash(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    bet = int(context.args[0]) if context.args else 100

    if not await validate_bet_amount(update, bet):
        return

    player = await sync_to_async(Player.objects.get)(id=user_id)
    if player.chips < bet:
        await update.message.reply_text("❌ Not enough chips.")
        return

    already_playing = await sync_to_async(
        lambda: CrashGame.objects.filter(user_id=user_id, crashed=False, cashed_out=False).exists()
    )()
    if already_playing:
        return await update.message.reply_text("🚫 You already have a crash game running. Use /cashout to end it.")

    player.chips -= bet
    await sync_to_async(player.save)()
    crash_game = await sync_to_async(CrashGame.objects.create)(user_id=user_id, bet=bet)

    # Don't send "Game started" here – it's now inside simulate_crash_game
    asyncio.create_task(simulate_crash_game(crash_game.id, context.bot, chat_id))


async def cashout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    try:
        game = await sync_to_async(CrashGame.objects.get)(
            user_id=user_id, crashed=False, cashed_out=False
        )
    except CrashGame.DoesNotExist:
        return await update.message.reply_text("⚠️ You have no active game to cash out from.")

    game.cashed_out = True
    await sync_to_async(game.save)()

    winnings = int(game.bet * game.multiplier)
    player = await sync_to_async(Player.objects.get)(id=user_id)
    player.chips += winnings

    await sync_to_async(player.save)()
    await apply_referral_bonus(player, winnings, context)

    await update.message.reply_text(f"✅ Cashed out at {game.multiplier}x!\n💰 You won {winnings} chips!")

    # Delete the game
    await sync_to_async(game.delete)()




async def double_or_nothing(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    # Parse bet amount
    bet_amount = int(context.args[0]) if context.args else 50
    if not await validate_bet_amount(update, bet_amount):
        return

    if not await check_player(update, context):
        return

    player = await sync_to_async(Player.objects.get)(id=user_id)

    if player.chips < bet_amount:
        await update.message.reply_text("❌ You don't have enough chips for that bet.")
        return

    # Deduct the bet
    player.chips -= bet_amount
    await sync_to_async(player.save)()

    # await asyncio.sleep(0.5)  # Short suspense

    if random.random() < 0.5:
        await update.message.reply_text("😵 You lost your bet. Nothing ❌doubled today.")
    else:
        winnings = bet_amount * 2
        player.chips += winnings
        await sync_to_async(player.save)()
        await apply_referral_bonus(player, winnings, context)
        await update.message.reply_text(
            f"🎉 Lucky! You doubled your bet and won {winnings} chips💰!\n"

        )

async def roll_dice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await asyncio.sleep(0.9)
    user_id = update.message.from_user.id
    bet_amount = int(context.args[0]) if context.args else 50  # Default bet amount is 50 chips
    if not await validate_bet_amount(update, bet_amount):
            return
    if not await check_player(update, context):
        return

    player = await sync_to_async(Player.objects.get)(id=user_id)

    if player.chips < bet_amount:
        await update.message.reply_text("You don't have enough chips for this bet!")
        return

    # Deduct the bet amount
    player.chips -= bet_amount
    await sync_to_async(player.save)()

    # Roll the dice using Telegram's dice feature
    message = await context.bot.send_dice(chat_id=update.message.chat_id, emoji="🎲")

    # Wait for a second for dice to roll
    await asyncio.sleep(4)

    dice_value = message.dice.value  # Get the dice value (1-6)

    # Determine win/loss based on the dice value
    if dice_value > 4:
        winnings = bet_amount * 2
        player.chips += winnings
        await sync_to_async(player.save)()
        await apply_referral_bonus(player, winnings, context)

        await update.message.reply_text(f"🎲 Dice rolled a {dice_value}!\nYou win {winnings} chips!")
    else:
        await update.message.reply_text(f"🎲 Dice rolled a {dice_value}!\nYou lose your bet of {bet_amount} chips.")


from django.db.models import F, Sum, Count
from asgiref.sync import sync_to_async

# Utility function to truncate player names and ensure it doesn't exceed 8 characters
def format_name(name, max_length=8):
    truncated_name = (name[:max_length - 3] + '...') if len(name) > max_length else name
    return f"{truncated_name:<{max_length}}"

# Utility function to format the leaderboard row with monospaced text
def format_leaderboard_row(index, name, wins, tokens):
    # Adjust spacing to account for emojis and varying name lengths
    return f"`{index:<2}. {name:<8} 🏆 Wins: {wins:<3}  💰 Chips: {tokens:<7}`"

# Function to fetch the global leaderboard with top 5 players
async def get_global_leaderboard():
    # Fetching top players based on total wins
    top_players = await sync_to_async(list)(
        Stats.objects.select_related('player')
        .annotate(total_wins=F('wins'))  # Total wins
        .order_by('-total_wins')[:5]  # Fetch top 5 players
    )

    leaderboard = []
    for index, stats in enumerate(top_players, 1):
        formatted_name = format_name(stats.player.name)
        leaderboard.append(
            format_leaderboard_row(
                index=index,
                name=formatted_name,
                wins=stats.wins,
                tokens=stats.player.chips
            )
        )

    return leaderboard

# Function to fetch the user's position and show 2 players above and 2 below
async def get_user_rank(user_id):
    # Fetch all players ordered by wins
    all_players = await sync_to_async(list)(
        Stats.objects.select_related('player')
        .annotate(total_wins=F('wins'))
        .order_by('-total_wins')
    )

    # Find the user's position
    user_rank = None
    leaderboard = []
    for index, stats in enumerate(all_players, 1):
        if stats.player.id == user_id:
            # Get two players above and two below
            start = max(index - 3, 0)
            end = min(index + 2, len(all_players))
            nearby_players = all_players[start:end]

            # Format the leaderboard for nearby players
            for idx, player_stats in enumerate(nearby_players, start=start+1):
                formatted_name = format_name(player_stats.player.name)
                leaderboard.append(
                    format_leaderboard_row(
                        index=idx,
                        name=formatted_name,
                        wins=player_stats.wins,
                        tokens=player_stats.player.chips
                    )
                )

            user_rank = index
            break

    return leaderboard, user_rank
# Command to show the global leaderboard
async def leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id

    # Get top 5 players
    top_5_leaderboard = await get_global_leaderboard()

    # Get the user's rank and nearby players
    user_leaderboard, user_rank = await get_user_rank(user_id)

    # Build the leaderboard message
    if top_5_leaderboard:
        top_5_text = "\n".join(top_5_leaderboard)
        message = f"🌍 *Global Leaderboard* 🌍\n\n{top_5_text}\n\n"
    else:
        message = "No players have ranked yet.\n\n"

    # Add user's position to the message
    if user_leaderboard:
        user_leaderboard_text = "\n".join(user_leaderboard)
        message += f"🏅 *Your Position* (Rank {user_rank}):\n{user_leaderboard_text}"
    else:
        message += "You haven't played enough games to be ranked yet."

    # Send the formatted leaderboard message
    await update.message.reply_text(message)

async def minigames(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.message.chat_id
    text = (
        "🎮 *Available Minigames* 🎮\n\n"
        "🎲 `/dice` – Roll a dice and test your luck! (`/dice [chips amount]`)\n\n"
        "🎰 `/slot` – Try your luck at the slot machine. Will you hit the jackpot? (`/slot [chips amount]`)\n\n"
        "🪙 `/coin` – Flip a coin and see if it’s heads or tails. (`/coin [heads/tails] [chips amount]`)\n\n"
        "🎟 `/draw` – Participate in a lucky draw. Will you be the lucky one? (`/draw [chips amount]`)\n\n"
        "🎯 `/dart` – Play dart twice a day to win 200 chips.\n\n"
        "✊🖐✌️ `/rps` – Play Rock, Paper, Scissors against the bot. (`/rps [rock/paper/scissors] [chips amount]`)\n\n"
        "🎡 `/spin` – Spin the wheel once a day for a chance to win chips, XP, or levels! Type `/spin <low/mid/high>` and let the wheel decide your fate.\n\n"
        "🎲 `/roulette` – Bet on red, black, or a number (`0–36`).\n"
        "Usage: `/roulette <red|black|0–36> <bet amount>`.\n"
        "If you guess the color, you win double; if you guess the number, you win 35× your bet. Good luck!\n\n"
        "📈 `/crash` – Bet chips and watch the multiplier rise. Type `/cashout` before it crashes to lock in your winnings!\n\n"
        "🟥 `/double` – Feeling lucky? Bet to win double your chips or lose it all. (`/double [amount]`)\n\n"
        "🐎 `/horserace` – Start a new horse race.\n"
        "🐎 `/joinrace` – Join the ongoing race with your horse. (`/joinrace <horse_number> <amount>`)\n"
        "🐎 `/startrace` – Start the race and watch it live!"
    )
    await context.bot.send_message(
        chat_id=chat_id,
        text=text,
        parse_mode="Markdown",
    )

async def request_loan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_player(update, context):
        return
    user_id = update.message.from_user.id
    loan_amount = int(context.args[0]) if context.args else 0

    if loan_amount <= 0:
        await update.message.reply_text("Please specify a valid loan amount.")
        return

    # Charge 25 XP per *started* 100 chips,
    # so even loan_amount=1..100 costs 25 XP.
    xp_cost = math.ceil(loan_amount / 100) * 25

    try:
        player = await sync_to_async(Player.objects.get)(id=user_id)
        dealer = await sync_to_async(Dealer.objects.first)()

        if dealer.chips < loan_amount:
            await update.message.reply_text("The Casino doesn't have enough chips to give you this loan.")
            return

        if player.xp < xp_cost:
            if player.level > 1:
                # de-level until you can pay
                remaining_xp = player.xp - xp_cost
                while remaining_xp < 0 and player.level > 1:
                    player.level -= 1
                    remaining_xp += xp_for_next_level(player.level)
                player.xp = remaining_xp
            else:
                await update.message.reply_text("You don't have enough XP to take this loan.")
                return

        # Deduct XP and transfer chips
        player.xp    -= xp_cost
        player.chips += loan_amount
        player.loan  += loan_amount
        dealer.chips -= loan_amount

        await sync_to_async(player.save)()
        await sync_to_async(dealer.save)()

        await update.message.reply_text(
            f"You've received a loan of {loan_amount} 💰 chips.\n"
            f"XP cost: {xp_cost} XP. Don't forget to repay with 3% interest!"
        )

    except Player.DoesNotExist:
        await update.message.reply_text("You need to register with /start first.")

async def repay_loan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_player(update, context):
        return
    user_id = update.message.from_user.id

    try:
        player = await sync_to_async(Player.objects.get)(id=user_id)
        dealer = await sync_to_async(Dealer.objects.first)()  # Assuming there is only one dealer

        # Check if the player has an outstanding loan
        if player.loan <= 0:
            await update.message.reply_text("You don't have any outstanding loans to repay.")
            return

        # Calculate total repayment with 3% interest
        total_repayment = int(player.loan * 1.03)

        # Check if the player has enough chips to repay the loan
        if player.chips < total_repayment:
            await update.message.reply_text(f"You don't have enough chips to repay the loan. You need {total_repayment} 💰.")
            return

        # Deduct chips from player and repay the dealer
        player.chips -= total_repayment
        dealer.chips += total_repayment
        player.loan = 0

        await sync_to_async(player.save)()
        await sync_to_async(dealer.save)()

        await update.message.reply_text(f"Loan repaid successfully! You paid back {total_repayment} 💰 with interest.")

    except Player.DoesNotExist:
        await update.message.reply_text("You need to register with /start first.")





ADMIN_ID = 1553620403

async def give_chips2(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Debug entry
    print(f"[DEBUG] give_chips triggered by user {update.effective_user.id} in chat {update.effective_chat.id}")
    print(f"[DEBUG] Message text: {update.message.text!r}")

    # Admin check
    if update.effective_user.id != ADMIN_ID:
        print(f"[DEBUG] User {update.effective_user.id} is not ADMIN_ID={ADMIN_ID}, exiting.")
        return

    # Reply check
    if not update.message.reply_to_message:
        print("[DEBUG] No reply_to_message found, prompting usage.")
        await update.message.reply_text(
            "❗️ Reply to a user's message and type `/chips <amount>`.",
            parse_mode="Markdown"
        )
        return

    # Args parsing
    args = context.args
    print(f"[DEBUG] context.args = {args}")
    if len(args) != 1:
        print("[DEBUG] Wrong number of args, sending usage.")
        await update.message.reply_text(
            "Usage: `/chips <amount>`",
            parse_mode="Markdown"
        )
        return

    # Amount check
    amount_str = args[0]
    if not amount_str.isdigit():
        print(f"[DEBUG] args[0]={amount_str!r} is not a digit.")
        await update.message.reply_text(
            "❗️ Amount must be a number.",
            parse_mode="Markdown"
        )
        return

    amount = int(amount_str)
    print(f"[DEBUG] Parsed amount = {amount}")

    # Identify target
    target_user = update.message.reply_to_message.from_user
    target_id = target_user.id
    print(f"[DEBUG] Target user is {target_user.full_name} with ID {target_id}")

    # Fetch Player
    try:
        player = await sync_to_async(Player.objects.get)(id=target_id)
        print(f"[DEBUG] Found Player record: {player}")
    except ObjectDoesNotExist:
        print(f"[DEBUG] No Player found with id={target_id}")
        await update.message.reply_text(f"❌ No player with ID {target_id}.")
        return

    # Update and save
    original = player.chips
    player.chips += amount
    print(f"[DEBUG] Updating chips: {original} -> {player.chips}")
    await sync_to_async(player.save)()
    print("[DEBUG] Player.save() completed")

    # Confirm to admin
    resp_admin = f"✅ {amount} 💰 given to {player.name or target_user.full_name}."
    print(f"[DEBUG] Replying to admin: {resp_admin}")
    await update.message.reply_text(resp_admin)

    # Notify the target
    notify_text = f"You've received {amount} 💰 from the admin!"
    print(f"[DEBUG] Sending message to target {target_id}: {notify_text}")
    await context.bot.send_message(chat_id=target_id, text=notify_text)
    print("[DEBUG] Notification sent to target")

async def claim_daily_tokens(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.message.from_user.id

    if not await check_player(update, context):
        return

    player = await sync_to_async(Player.objects.get)(id=user_id)
    now = timezone.now()

    # If already claimed today, bail out
    if player.last_claimed_tokens and player.last_claimed_tokens.date() == now.date():
        await update.message.reply_text("🎁 You’ve already claimed your daily 200 chips! Come back tomorrow.")
        return

    # Grant daily 200 chips
    player.chips += 200
    player.last_claimed_tokens = now
    await sync_to_async(player.save)()

    await update.message.reply_text(f"🎉 Here are your 200 daily chips! You now have 💰{player.chips} chips.")
async def group(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    group_link = "https://t.me/+JLQINcmYLZg3NDM0"  # ← replace with your real link
    await update.message.reply_text(
        f"🎲 Join our main Blackjack group here:\n{group_link}"
    )




async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # only allow admin to run
    if update.effective_user.id != ADMIN_ID:
        return

    # require a message
    if not context.args:
        await update.message.reply_text("Usage: /broadcast <your message here>")
        return

    text = " ".join(context.args)

    # get all player IDs (which are the chat_ids for private chats)
    player_ids = await sync_to_async(
        lambda: list(Player.objects.values_list("id", flat=True))
    )()

    sent = 0
    for uid in player_ids:
        try:
            await context.bot.send_message(chat_id=uid, text=text)
            sent += 1
            # small pause to respect flood limits
            await asyncio.sleep(0.05)
        except Exception as e:
            # log or ignore users who blocked the bot, etc.
            print(f"Failed to send to {uid}: {e}")

    await update.message.reply_text(f"Broadcast sent to {sent} players.")
SPIN_TIERS = {
    "low": {
        "cost": 200,
        "slices": [
            # Positive‐chip rewards
            ("💰 +5 000 chips",  5000,   0,   0),
            ("🎉 +2 500 chips",  2500,   0,   0),
            ("✨ +1 000 chips",  1000,   0,   0),
            ("👍  +500 chips",    500,   0,   0),

            # Exact negative “mirrors” of the above
            ("💸 -5 000 chips", -5000,   0,   0),
            ("💸 -2 500 chips", -2500,   0,   0),
            ("🛑 -1 000 chips", -1000,   0,   0),
            ("🛑 -500 chips",    -500,   0,   0),

            # Neutral / XP / level slots
            ("😐 Nothing happens",   0,    0,   0),
            ("😐 Nothing happens",   0,    0,   0),
            ("🌟 +50 XP",            0,   50,   0),
            ("🧟 -50 XP",            0,  -50,   0),
            ("⭐ +1 level",          0,    0,  +1),
            ("⬇️ -1 level",          0,    0,  -1),
        ],
    },

    "mid": {
        "cost": 2000,
        "slices": [
            ("💰 +25 000 chips",  25000,   0,   0),
            ("🎉 +10 000 chips",  10000,   0,   0),
            ("✨ +5 000 chips",    5000,   0,   0),
            ("👍  +1 000 chips",   1000,   0,   0),

            # Exact negative “mirrors”
            ("💸 -25 000 chips", -25000,   0,   0),
            ("💸 -10 000 chips", -10000,   0,   0),
            ("🛑 -5 000 chips",   -5000,   0,   0),
            ("🛑 -1 000 chips",   -1000,   0,   0),

            ("😐 Nothing happens",   0,    0,   0),
            ("🌟 +200 XP",           0,   200,  0),
            ("🧟 -200 XP",           0,  -200,  0),
            ("⭐ +1 level",          0,    0,  +1),
            ("⬇️ -1 level",          0,    0,  -1),
        ],
    },

    "high": {
        "cost": 20000,
        "slices": [
            ("💰 +100 000 chips", 100000,   0,   0),
            ("🎉 +50 000 chips",   50000,   0,   0),
            ("✨ +25 000 chips",   25000,   0,   0),
            ("👍  +5 000 chips",    5000,   0,   0),

            # Exact negative “mirrors”
            ("💸 -100 000 chips", -100000,   0,   0),
            ("💸 -50 000 chips",  -50000,   0,   0),
            ("🛑 -25 000 chips",  -25000,   0,   0),
            ("🛑 -5 000 chips",    -5000,   0,   0),

            ("😐 Nothing happens",    0,     0,   0),
            ("🌟 +500 XP",            0,   500,  0),
            ("🧟 -500 XP",            0,  -500,  0),
            ("⭐ +2 levels",          0,     0,  +2),
            ("⬇️ -2 levels",          0,     0,  -2),
        ],
    },
}


async def _spin_sequence_longer(bot, chat_id, message_id, user_id, slices):
    """
    Show 3 intermediate “spin” frames (each lasting ~0.5 s),
    then pick one final outcome, update the player, and edit the same message.
    """
    last_label = None
    frames = 3            # <-- only 3 frames now
    sleep_interval = 0.2  # half a second per intermediate frame

    for _ in range(frames):
        label, _, _, _ = random.choice(slices)

        if label != last_label:
            try:
                await bot.edit_message_text(
                    f"🎡 Spinning… {label}",
                    chat_id=chat_id,
                    message_id=message_id
                )
            except RetryAfter as e:
                # If rate-limited, wait exactly e.retry_after then retry once
                await asyncio.sleep(e.retry_after)
                try:
                    await bot.edit_message_text(
                        f"🎡 Spinning… {label}",
                        chat_id=chat_id,
                        message_id=message_id
                    )
                except Exception:
                    pass  # skip if it fails again

            last_label = label

        await asyncio.sleep(sleep_interval)

    # ─── Now choose the final outcome ───
    final_label, chips_d, xp_d, lvl_d = random.choice(slices)

    # Update the player's stats:
    player = await sync_to_async(Player.objects.get)(id=user_id)
    player.chips = max(player.chips + chips_d, 0)  # Prevent negative chips
    player.xp    = max(player.xp + xp_d, 0)        # Prevent negative XP
    player.level = max(player.level + lvl_d, 1)    # Level can't go below 1
    await sync_to_async(player.save)()

    # Build & send the final text in the same message
    final_text = (
        f"🛑 You landed on **{final_label}**!\n"
        f"Chips: {'+' if chips_d >= 0 else ''}{chips_d}\n"
        f"XP:    {'+' if xp_d   >= 0 else ''}{xp_d}\n"
        f"Level: {'+' if lvl_d  >= 0 else ''}{lvl_d}"
    )
    try:
        await bot.edit_message_text(
            final_text,
            chat_id=chat_id,
            message_id=message_id,
            parse_mode="Markdown"
        )
    except RetryAfter as e:
        # If Telegram asks us to wait, honor it and retry once
        await asyncio.sleep(e.retry_after)
        try:
            await bot.edit_message_text(
                final_text,
                chat_id=chat_id,
                message_id=message_id,
                parse_mode="Markdown"
            )
        except Exception:
            pass  # give up if it still fails


async def spin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_player(update, context):
        return
    """
    /spin <tier>
    Tiers: low (cost 200), mid (cost 2 000), high (cost 20 000)
    Now shows 3 intermediate labels (~1.5 s of animation) before final.
    """
    user = update.effective_user
    user_id = user.id

    if not context.args:
        return await update.message.reply_text(
            "❗️ You must specify a tier: `low`, `mid`, or `high`.\n"
            "Example: `/spin low`",
            parse_mode="Markdown"
        )

    tier_name = context.args[0].lower()
    if tier_name not in SPIN_TIERS:
        return await update.message.reply_text(
            "❗️ Invalid tier. Choose one of: `low`, `mid`, `high`.",
            parse_mode="Markdown"
        )

    tier_info = SPIN_TIERS[tier_name]
    cost = tier_info["cost"]

    player = await sync_to_async(Player.objects.get)(id=user_id)
    if player.chips < cost:
        return await update.message.reply_text(
            f"🚫 You need {cost} chips to spin **{tier_name.upper()}**, "
            f"but you only have {player.chips}."
        )

    # Deduct cost immediately
    player.chips -= cost
    await sync_to_async(player.save)()

    # Send one “Spinning…” message, then run the 3-frame animation + final result
    msg = await update.message.reply_text(f"🎡 Spinning the **{tier_name.upper()}** wheel…")
    asyncio.create_task(
        _spin_sequence_longer(
            context.bot,
            update.effective_chat.id,
            msg.message_id,
            user_id,
            tier_info["slices"]
        )
    )

# ─── New /spinrewards command: list each tier, its cost, and possible outcomes ───
async def spinrewards(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_player(update, context):
        return
    """
    /spinrewards
    Lists each tier’s cost and all possible outcomes (including negative-chip penalties).
    """
    lines = ["*Available spin tiers & their costs/rewards:*"]
    
    for tier_name, info in SPIN_TIERS.items():
        cost = info["cost"]
        lines.append(f"\n• *{tier_name.upper()}* (Cost: {cost} chips):")
        
        for label, chips_d, xp_d, lvl_d in info["slices"]:
            parts = [label]
            
            # If there is a chip delta (positive or negative), show it
            if chips_d != 0:
                parts.append(f"{chips_d:+} chips")
            
            # If there is an XP delta (positive or negative), show it
            if xp_d != 0:
                parts.append(f"{xp_d:+} XP")
            
            # If there is a level delta (positive or negative), show it
            if lvl_d != 0:
                parts.append(f"{lvl_d:+} level")
            
            # Join the pieces with " | " and indent under the tier name
            lines.append("    – " + " | ".join(parts))
    
    text = "\n".join(lines)
    await update.message.reply_text(text, parse_mode="Markdown")



RED_NUMS = {1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36}

async def _roulette_sequence(bot, chat_id, message_id, user_id, bet_type, bet_amt):
    # animation
    for _ in range(12):
        spun = random.randint(0,36)
        await bot.edit_message_text(
            f"🎲 Spinning… {spun}",
            chat_id=chat_id,
            message_id=message_id
        )
        await asyncio.sleep(0.15)

    # final outcome
    number = random.randint(0,36)
    win = False
    payout = 0

    if bet_type.lower() in ("red","black"):
        color = "red" if number in RED_NUMS else "black" if number != 0 else "green"
        win = (color == bet_type.lower())
        payout = bet_amt * 2 if win else 0
    else:
        try:
            guess = int(bet_type)
            if 0 <= guess <= 36 and guess == number:
                win = True
                payout = bet_amt * 35
        except ValueError:
            pass

    player = await sync_to_async(Player.objects.get)(id=user_id)
    player.chips += (payout - bet_amt)
    await sync_to_async(player.save)()

    result_text = (
        f"🛑 Landed on **{number}** "
        f"({'🔴' if number in RED_NUMS else '⚫️' if number!=0 else '0️⃣'})\n"
    )
    if win:
        result_text += f"🎉 You win {payout - bet_amt} chips!"
    else:
        result_text += f"😢 You lose {bet_amt} chips."
    await bot.send_message(chat_id=chat_id, text=result_text, parse_mode="Markdown")

async def roulette(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_player(update, context):
        return
    args = context.args
    if len(args) != 2:
        return await update.message.reply_text("Usage: /roulette <red|black|0-36> <bet>")
    bet_type, bet_amt = args[0], int(args[1])
    if not await validate_bet_amount(update, bet_amt):
        return
    user_id = update.effective_user.id
    player = await sync_to_async(Player.objects.get)(id=user_id)
    if player.chips < bet_amt:
        return await update.message.reply_text("❌ Not enough chips.")

    msg = await update.message.reply_text("🎲 Starting roulette…")
    asyncio.create_task(
        _roulette_sequence(
            context.bot,
            update.effective_chat.id,
            msg.message_id,
            user_id,
            bet_type,
            bet_amt
        )
    )





async def give_chips(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_player(update, context):
        return
    # Command format: reply to someone's message with /givechips <amount>
    user_id = update.message.from_user.id
    chat_id = update.message.chat_id

    # Check if command has an argument
    if len(context.args) != 1:
        await update.message.reply_text("Usage: reply to a user’s message with /givechips <amount>")
        return

    # Check if the message is a reply
    if not update.message.reply_to_message:
        await update.message.reply_text("You need to reply to the user you want to give chips to.")
        return

    # Validate the amount
    try:
        amount = int(context.args[0])
        if amount <= 0:
            await update.message.reply_text("Amount must be greater than 0.")
            return
    except ValueError:
        await update.message.reply_text("Invalid amount.")
        return

    # Get the giver and receiver
    giver_id = user_id
    receiver_id = update.message.reply_to_message.from_user.id

    # Check if giver and receiver are not the same
    if giver_id == receiver_id:
        await update.message.reply_text("You cannot give chips to yourself.")
        return

    # Get both players
    try:
        giver = await sync_to_async(Player.objects.get)(id=giver_id)
        receiver = await sync_to_async(Player.objects.get)(id=receiver_id)
    except Player.DoesNotExist:
        await update.message.reply_text("Both players must be registered in the game.")
        return

    # Check if the giver has enough chips
    if giver.chips < amount:
        await update.message.reply_text("You don’t have enough chips to give.")
        return

    # Perform the transfer
    giver.chips -= amount
    receiver.chips += amount
    await sync_to_async(giver.save)()
    await sync_to_async(receiver.save)()

    # Escape user names for Markdown
    giver_name = escape_markdown(update.message.from_user.first_name, version=2)
    receiver_name = escape_markdown(update.message.reply_to_message.from_user.first_name, version=2)

    # Send a confirmation message
    await context.bot.send_message(
        chat_id=chat_id,
        text=(
            f"💸 *{giver_name}* has given *{amount} chips* to *{receiver_name}*\\.\n"
            f"🎉 {receiver_name} now has *{receiver.chips} chips*\\!"
        ),
        parse_mode="MarkdownV2"
    )

async def sync_group_names(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /sync_groups  →  For every Group in our database, call get_chat(group_chat_id),
    pull out the chat.title (or username), and save it into group_name.
    Only the superuser (you) should run this command; it will DM back a summary.
    """
    user_id = update.effective_user.id

    # OPTIONAL: Only allow a specific user ID (e.g. your own Telegram ID) to run this.
    # Replace YOUR_TELEGRAM_ID with your actual numeric user ID.
    if user_id != ADMIN_ID:
        return await update.message.reply_text("🚫 You are not authorized to run this command.")

    all_groups = await sync_to_async(lambda: list(Group.objects.all()))()
    if not all_groups:
        return await update.message.reply_text("⚠️ No groups found in the database.")

    updated = 0
    skipped = 0
    errors = []

    for group in all_groups:
        chat_id = group.group_chat_id

        try:
            # get_chat is async in python-telegram-bot v13.5
            chat = await context.bot.get_chat(chat_id)
        except Exception as e:
            errors.append(f" • Failed to fetch {chat_id!r}: {e}")
            skipped += 1
            # Optional: wait a tiny bit to avoid spamming Telegram
            await asyncio.sleep(0.1)
            continue

        # Telegram’s Chat object might have:
        #   - title (for group/supergroup/channel)
        #   - first_name/last_name (for a private chat)
        #   - username (if it’s a public channel or bot)
        new_title = ""
        if hasattr(chat, "title") and chat.title:
            new_title = chat.title
        elif hasattr(chat, "first_name") and chat.first_name:
            new_title = chat.first_name
            if getattr(chat, "last_name", None):
                new_title += " " + chat.last_name
        elif getattr(chat, "username", None):
            new_title = chat.username
        else:
            new_title = str(chat_id)

        # If we got a valid title, update group_name
        if new_title and new_title != group.group_name:
            group.group_name = new_title
            await sync_to_async(group.save)()
            updated += 1
        else:
            skipped += 1

        # Small pause in case you have many groups, to avoid hitting rate limits
        await asyncio.sleep(0.1)

    # Build a summary message
    summary = [
        f"✅ Synced {len(all_groups)} groups.",
        f"🔄 Updated: {updated}",
        f"⏭️ Skipped (already up‐to‐date or failed): {skipped}",
    ]
    if errors:
        summary.append("\nSome errors:")
        summary.extend(errors[:10])  # show up to 10 errors
        if len(errors) > 10:
            summary.append(f"…and {len(errors)-10} more errors.")

    await update.message.reply_text("\n".join(summary))



async def on_new_chat_members(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Triggered whenever someone joins (or a bot is added to) a chat.
    If the bot itself is among new_chat_members, register that group.
    """
    bot_id = context.bot.id
    chat = update.effective_chat  # the group where this happened

    # Loop through update.message.new_chat_members to see if the bot was added
    for new_member in update.message.new_chat_members:
        if new_member.id == bot_id:
            # The bot was just added to this chat. Save it in your Group model.
            group_chat_id = str(chat.id)
            group_title   = chat.title or ""  # e.g. “My Cool Group”

            # Use get_or_create so we don’t overwrite an existing Group
            group_obj, created = await sync_to_async(Group.objects.get_or_create)(
                group_chat_id=group_chat_id,
                defaults={"group_name": group_title},
            )
            # If it already existed but the title changed, update it
            if not created and group_obj.group_name != group_title:
                group_obj.group_name = group_title
                await sync_to_async(group_obj.save)()

            # (Optionally) announce in the group that you're now watching it:
            await context.bot.send_message(
                chat_id=chat.id,
                text="👋 Thanks for adding me! Use /help to see how to play "
            )
            break




async def list_groups(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /listgroups
    Only list groups where the bot is still present. Do NOT delete stale rows.
    """
    user_id = update.effective_user.id

    # (Optional) restrict usage to your own ID:
    if user_id != ADMIN_ID:
        return await update.message.reply_text("🚫 You’re not authorized to run this command.")

    # Fetch all stored Group rows
    all_groups = await sync_to_async(lambda: list(Group.objects.all()))()
    if not all_groups:
        return await update.message.reply_text("ℹ️ No groups recorded in the database.")

    valid_lines = []

    for g in all_groups:
        chat_id = g.group_chat_id
        try:
            # Try to fetch the chat. If the bot was removed, this will raise.
            await context.bot.get_chat(chat_id)
        except Exception:
            # Skip this group (bot is not in it), but do not delete from DB
            continue

        # If we got here, the bot is still in that chat
        name = g.group_name or "(no name)"
        valid_lines.append(f" • `{chat_id}` → {name}")

        # Small pause to avoid rate limits
        await asyncio.sleep(0.05)

    if not valid_lines:
        return await update.message.reply_text("ℹ️ I’m not currently in any of the stored groups.")

    # Build the response in Markdown
    header = "*I’m currently in the following groups:*"
    message_text = "\n".join([header] + valid_lines)

    # Send in one or more chunks (≤4000 chars each)
    max_length = 4000
    text = message_text
    while text:
        if len(text) <= max_length:
            await update.message.reply_text(text, parse_mode="Markdown")
            break
        # Find a safe newline split
        split_pos = text.rfind("\n", 0, max_length)
        if split_pos == -1:
            split_pos = max_length
        await update.message.reply_text(text[:split_pos], parse_mode="Markdown")
        text = text[split_pos:].lstrip()
async def broadcastgroups(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /broadcast <message>
    Send <message> only to groups where the bot is still a member.
    Do NOT delete stale rows from the database.
    """
    user_id = update.effective_user.id

    # (Optional) restrict to your ID:
    if user_id != ADMIN_ID:
        return await update.message.reply_text("🚫 You’re not authorized to run this command.")

    if not context.args:
        return await update.message.reply_text("❗️ Usage: /broadcast <message text>")

    text_to_send = " ".join(context.args)

    all_groups = await sync_to_async(lambda: list(Group.objects.all()))()
    if not all_groups:
        return await update.message.reply_text("ℹ️ No groups recorded to broadcast to.")

    success = 0
    failures = 0

    for g in all_groups:
        chat_id = g.group_chat_id
        try:
            # Verify bot is still in chat
            await context.bot.get_chat(chat_id)

            # Send the broadcast
            await context.bot.send_message(chat_id=chat_id, text=text_to_send)
            success += 1

        except Exception:
            # Skip (bot not in chat or sending failed), but do NOT delete the row
            failures += 1

        await asyncio.sleep(0.05)

    await update.message.reply_text(
        f"✅ Message sent to {success} groups, skipped {failures} invalid groups."
    )


async def admin_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /admin
    Sends brief descriptions of all admin commands to your private chat.
    """
    user_id = update.effective_user.id
    chat_id = update.message.chat_id
    if user_id != ADMIN_ID:
        return await update.message.reply_text("🚫 You’re not authorized to run this command.")
    # Notify in group that details are in private chat
    # if chat_id != user_id:
    #     await update.message.reply_text(
    #         "📩 Sent you a summary of admin commands in private chat."
    #     )

    help_text = """
*Admin Commands* (use in private chat unless noted):

• `/sync_groups`  
  Sync stored group IDs → names from Telegram.  
  _Example:_ `/sync_groups`

• `/listgroups`  
  List all groups the bot is still in.  
  _Example:_ `/listgroups`

• `/broadcastgroup <text>`  
  Send `<text>` to every group.  
  _Example:_ `/broadcastgroup Hello everyone!`

• `/broadcast <text>`  
  DM `<text>` to every registered player.  
  _Example:_ `/broadcast Maintenance in 5 min.`

• `/give_token <user_id> <amount>`  
  Add `<amount>` chips to that user.  
  _Example:_ `/give_token 1553620403 1000`

• `/user_id`  
  Show your Telegram user ID (works anywhere).  
  _Example:_ `/user_id`
"""

    # Send as plain text (fits under 4096 chars)
    await context.bot.send_message(
        chat_id=user_id,
        text=help_text,
        parse_mode="Markdown"
    )


# ─── Helper: Escape MarkdownV2 ───
def escape_markdown_v2(text: str) -> str:
    escape_chars = r'[_*\[\]()~`>#+\-=\|{}.!]'
    return re.sub(escape_chars, r'\\\g<0>', text)

# ─── Helper: Safe send message with flood control ───
async def safe_send_message(bot, chat_id, text, parse_mode="MarkdownV2", max_retries=10):
    escaped_text = escape_markdown_v2(text)
    retries = 0
    while retries < max_retries:
        try:
            await bot.send_message(chat_id=chat_id, text=escaped_text, parse_mode=parse_mode)
            return
        except TimedOut:
            retries += 1
            await asyncio.sleep(4)
        except RetryAfter as e:
            await asyncio.sleep(int(e.retry_after) + 1)
            retries += 1
        await asyncio.sleep(0.3)  # flood control
    print("❌ Failed to send message after retries.")

# ─── /horserace: Start a new race ───
async def horserace(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_player(update, context):
        return
    chat_id = update.effective_chat.id

    existing_race = await sync_to_async(HorseRace.objects.filter)(chat_id=chat_id, race_started=False)
    if await sync_to_async(existing_race.exists)():
        await update.message.reply_text("❗️ A race is already active in this chat!")
        return

    race = await sync_to_async(HorseRace.objects.create)(chat_id=chat_id)
    await update.message.reply_text(
        "🐎 A new horse race has started!\n"
        "Join with /joinrace <horse_number> <bet_amount> (no bets on Horse 1!)"
    )
# ─── /joinrace: Players place their bets ───
async def joinrace(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_player(update, context):
        return
    user_id = update.effective_user.id
    username = update.effective_user.username or update.effective_user.first_name
    chat_id = update.effective_chat.id
    args = context.args

    if len(args) != 2:
        await update.message.reply_text("Usage: /joinrace <horse_number> <bet_amount>")
        return

    horse_number = int(args[0])
    bet_amount = int(args[1])

    # Prevent negative or zero bets
    if bet_amount <= 0:
        await update.message.reply_text("❌ Bet amount must be a positive number.")
        return

    if horse_number == 1:
        await update.message.reply_text("❌ You can’t bet on the dealer’s horse!")
        return

    owned_entry = await sync_to_async(OwnedHorse.objects.filter)(horse_number=horse_number)
    owned_entry = await sync_to_async(owned_entry.first)()

    if owned_entry:
        owner_id = await sync_to_async(lambda: owned_entry.user.id)()
        if owner_id != user_id:
            try:
                owner_player = await sync_to_async(Player.objects.get)(id=owner_id)
                owner_name = owner_player.name or "another player"
            except:
                owner_name = "another player"

            await update.message.reply_text(
                f"❌ This horse is already owned by {owner_name} and cannot be bet on by others."
            )
            return

    # 🧙 Spell usage logic — must be after owned_entry is defined
    if owned_entry:
        applied_upgrades = await sync_to_async(list)(
            HorseAppliedUpgrade.objects.filter(horse=owned_entry).select_related("upgrade")
        )


        for applied in applied_upgrades:
            applied.uses_remaining -= 1
            await sync_to_async(applied.save)()
            if applied.uses_remaining == 1:
                await context.bot.send_message(
                    chat_id=user_id,
                    text=f"⚠️ Your spell *{applied.upgrade.name}* has only 1 use left!",
                    parse_mode="Markdown"
                )


            else:
                await sync_to_async(applied.save)()
                if applied.uses_remaining == 1:
                    await context.bot.send_message(
                        chat_id=user_id,
                        text=f"⚠️ Your spell *{applied.upgrade.name}* has only 1 use left!",
                        parse_mode="Markdown"
                    )

    # First: find the active race
    race = await sync_to_async(HorseRace.objects.filter)(chat_id=chat_id, race_started=False)
    race = await sync_to_async(race.first)()
    if not race:
        await update.message.reply_text("❌ No active race! Start one with /horserace")
        return

    # Then: check if the user has already placed a bet in this race
    existing_bet = await sync_to_async(HorseBet.objects.filter)(race=race, user_id=user_id)
    if await sync_to_async(existing_bet.exists)():
        await update.message.reply_text("❌ You have already placed a bet in this race!")
        return

    player = await sync_to_async(Player.objects.get)(id=user_id)
    if player.chips < bet_amount:
        await update.message.reply_text("❌ Not enough chips!")
        return

    # Deduct chips
    player.chips -= bet_amount
    await sync_to_async(player.save)()

    # Add bet
    await sync_to_async(HorseBet.objects.create)(
        race=race,
        user_id=user_id,
        horse_number=horse_number,
        bet_amount=bet_amount,
        username=username
    )

    if owned_entry and owned_entry.name:
        label = f"{owned_entry.name} ({horse_number})"
    else:
        label = f"Horse {horse_number}"

    await update.message.reply_text(
        f"✅ Bet placed on {label} for {bet_amount} chips!"
    )


MAX_NAME_LEN     = 20       # max characters per horse name
MAX_MESSAGE_LEN  = 4000     # Telegram’s ~4096-char limit

def is_rtl(text: str) -> bool:
    """
    Return True if any character is in the Arabic/Persian Unicode block.
    """
    for ch in text:
        if '\u0600' <= ch <= '\u06FF' or '\u0750' <= ch <= '\u077F':
            return True
    return False



async def startrace(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # 1) Ensure the user has a Player profile
    if not await check_player(update, context):
        return

    chat_id = update.effective_chat.id

    # 2) FETCH THE ACTIVE RACE (must not have started yet)
    race_qs = await sync_to_async(HorseRace.objects.filter)(chat_id=chat_id, race_started=False)
    race    = await sync_to_async(race_qs.first)()
    if not race:
        await update.message.reply_text("❌ No active race!")
        return

    # 3) GATHER ALL BETS FOR THIS RACE
    bets = await sync_to_async(list)(HorseBet.objects.filter(race=race))
    if not bets:
        await update.message.reply_text("❌ No bets placed!")
        return

    # 4) MARK THE RACE AS “STARTED”
    race.race_started = True
    await sync_to_async(race.save)()

    dealer_horse = 1

    # 5) PICK TWO RANDOM “HOUSE” HORSES FROM 2..4
    random_horses = [2, 3]

    # 6) COLLECT ANY HORSE NUMBERS THAT PLAYERS SPECIFICALLY BET ON (excluding dealer=1)
    player_horses = list({bet.horse_number for bet in bets if bet.horse_number != dealer_horse})

    # 7) BUILD FULL LIST: [dealer=1] + two random + any extra player‐chosen horses
    all_horses = [dealer_horse] + random_horses
    for h in player_horses:
        if h not in all_horses:
            all_horses.append(h)

    distance  = race.race_distance  # e.g. 20
    positions = {h: distance for h in all_horses}

    # ─── LOAD OWNEDHORSE NAMES ──────────────────────────────────────────────────────
    owned_list = await sync_to_async(list)(
        OwnedHorse.objects.filter(horse_number__in=all_horses)
    )
    name_map = {h: f"Horse {h}" for h in all_horses}
    for oh in owned_list:
        if oh.name:
            name_map[oh.horse_number] = oh.name

    # 8) FETCH ALL APPLIED UPGRADES (“spells”) FOR THESE HORSES
    applied_list = await sync_to_async(
        lambda: list(
            HorseAppliedUpgrade.objects.filter(horse__horse_number__in=all_horses)
        )
    )()

    # Build a mapping: horse_number → list of upgrade names
    upgrades_map = {}
    for au in applied_list:
        horse_number = await sync_to_async(lambda: au.horse.horse_number)()
        upgrade_name = await sync_to_async(lambda: au.upgrade.name)()
        upgrades_map.setdefault(horse_number, []).append(upgrade_name)

    # 9) LOAD ANY CUSTOM EMOJI THAT OWNERS HAVE SET ON THEIR OwnedHorse
    owned_horses = await sync_to_async(list)(
        OwnedHorse.objects.filter(horse_number__in=all_horses)
    )
    horse_emojis = {oh.horse_number: oh.emoji for oh in owned_horses if oh.emoji}

    # 10) APPLY “🏁 Head Start” INITIAL POSITION BONUS
    for h in all_horses:
        if "🏁 Head Start" in upgrades_map.get(h, []):
            positions[h] = max(0, positions[h] - 4)

    # 11) INITIALIZE PER‐HORSE STATE FOR SPELLS THAT NEED IT
    tick_count       = 0
    last_movements   = {h: 1 for h in all_horses}
    freeze_used      = set()
    frozen_for_one   = set()
    bounce_used      = set()
    broken           = set()

    # 12) SEND INITIAL MESSAGE, THEN EDIT EACH TICK
    msg    = await update.message.reply_text("🏁 The race begins! 🐎")
    winner = None

    # ─── MAIN ANIMATION LOOP ────────────────────────────────────────────────────────
    while not winner:
        tick_count += 1
        frozen_for_one.clear()

        # 12a) “Freeze Ray”: each horse with that spell freezes one random rival (once per race)
        for h in all_horses:
            if "🧊 Freeze Ray" in upgrades_map.get(h, []):
                rivals = [r for r in all_horses if r != h and positions[r] > 0]
                if rivals:
                    victim = random.choice(rivals)
                    frozen_for_one.add(victim)

        # 12b) Compute each horse's movement this tick
        new_movements = {}
        for h in sorted(all_horses):
            # 1) If the horse has already finished, it doesn't move
            if positions[h] <= 0:
                new_movements[h] = 0
                continue

            # 2) If this horse is frozen this tick, it doesn't move
            if h in frozen_for_one:
                new_movements[h] = 0
                continue

            # 3) SPECIAL CASE: dealer’s horse (number 1) always moves 2–4 (no spells apply)
            if h == dealer_horse:
                new_movements[h] = 2
                continue

            # 4) Otherwise, check spells exactly as before
            spells = upgrades_map.get(h, [])

            # Mirror Trick
            if "🔮 Mirror Trick" in spells:
                others = [o for o in all_horses if o != h]
                if others:
                    chosen = random.choice(others)
                    new_movements[h] = last_movements.get(chosen, random.randint(1, 3))
                else:
                    new_movements[h] = random.randint(1, 3)
                continue

            # Steady Stride
            if "⚖️ Steady Stride" in spells:
                new_movements[h] = random.randint(1, 5)
                continue

            # Power Burst
            if "⚡ Power Burst" in spells:
                new_movements[h] = 4 if random.random() < 0.1 else 1
                continue

            # Triple Dash
            if "💨 Double Dash" in spells:
                new_movements[h] = 3
                continue

            # Cursed Sprint
            if "🛠 Cursed Sprint" in spells:
                if random.random() < 0.4:
                    broken.add(h)
                    new_movements[h] = 0
                else:
                    new_movements[h] = 5
                continue

            # Head Start
            if "🏁 Head Start" in spells:
                new_movements[h] = 2
                continue

            # Mutation
            if "🧬 Mutation" in spells:
                choice = random.choice([
                    "🔮 Mirror Trick",
                    "⚖️ Steady Stride",
                    "⚡ Power Burst",
                    "💨 Double Dash",
                    "🛠 Cursed Sprint",
                    "🏁 Head Start"
                ])
                if choice == "🔮 Mirror Trick":
                    others = [o for o in all_horses if o != h]
                    if others:
                        pick = random.choice(others)
                        new_movements[h] = last_movements.get(pick, random.randint(1, 3))
                    else:
                        new_movements[h] = random.randint(1, 3)
                elif choice == "⚖️ Steady Stride":
                    new_movements[h] = random.randint(1, 5)
                elif choice == "⚡ Power Burst":
                    new_movements[h] = 4 if random.random() < 0.1 else 1
                elif choice == "💨 Double Dash":
                    new_movements[h] = 3
                elif choice == "🛠 Cursed Sprint":
                    if random.random() < 0.4:
                        broken.add(h)
                        new_movements[h] = 0
                    else:
                        new_movements[h] = 5
                elif choice == "🏁 Head Start":
                    new_movements[h] = random.randint(1, 3)
                continue

            # 5) Default: random 1–3 for any non-dealer, non-spell horse
            new_movements[h] = random.randint(1, 3)

        # 12c) Apply all movements to positions
        prev_positions = positions.copy()
        for h, move in new_movements.items():
            positions[h] = max(0, positions[h] - move)

        # 12d) Magnet Pull: on every 3rd tick, horses with that spell slow all others by 1
        if tick_count % 3 == 0:
            for h in all_horses:
                if "🧲 Magnet Pull" in upgrades_map.get(h, []):
                    for other in all_horses:
                        if other != h and positions[other] > 0:
                            positions[other] = max(0, positions[other] + 1)

        # 12e) Bounce Back: if overtaken by ≥2, bounce 5 steps
        for h in all_horses:
            if "🦘 Bounce Back" in upgrades_map.get(h, []) and h not in bounce_used and positions[h] > 0:
                ahead_count = sum(
                    1
                    for o in all_horses
                    if o != h and positions[o] < positions[h] and positions[o] > 0
                )

                if ahead_count >= 2:
                    positions[h] = max(0, positions[h] - 5)
                    bounce_used.add(h)  # ✅ ensure it only happens once per horse


        # 12f) Build the “race_display” string (25‐dash track)
        race_display = ""
        for h in sorted(all_horses):
            emoji = horse_emojis.get(h, "🐎")
            label = name_map[h].replace(" ", "\u00A0")
            if len(label) > MAX_NAME_LEN:
                label = label[: MAX_NAME_LEN - 1] + "…"

            dash_count  = max(1, (positions[h] * 25) // distance)
            trail_count = max(1, 25 - dash_count)
            leading  = "-" * dash_count
            trailing = "-" * trail_count
            raw_track = f"{leading}\u200E{emoji}\u200E{trailing}"
            track = "\u202A" + raw_track + "\u202C"

            if is_rtl(label):
                rtl_label = "\u202B" + label + "\u202C"
            else:
                rtl_label = label

            combined = "\u202A" + track + "\u200E" + " " + rtl_label + "\u202C"

            if h in broken:
                race_display += f"🚫 | 💥 {combined} (broken!)\n"
            elif positions[h] == 0:
                race_display += f"🏆 | 🏁 {combined}\n"
                if winner is None:
                    winner = h
            else:
                race_display += f"🏆 | {combined}\n"

        # 12g) Truncate if too long
        if len(race_display) > MAX_MESSAGE_LEN:
            race_display = race_display[: MAX_MESSAGE_LEN - 1] + "\n…"

        # 12h) Attempt to edit the message; handle flood control
        try:
            await msg.edit_text(race_display)
        except RetryAfter as e:
            await asyncio.sleep(int(e.retry_after) + 1)
            continue

        # 12i) Pause before next tick
        await asyncio.sleep(0.8)
        last_movements = new_movements.copy()

    # ─── Once “winner” is set ───────────────────────────────────────────────────────
    if winner == dealer_horse:
        total_pot = sum(bet.bet_amount for bet in bets)
        dealer_obj, _ = await sync_to_async(Dealer.objects.get_or_create)(id=1)
        dealer_obj.chips += total_pot
        dealer_obj.wins  += 1
        dealer_obj.games += 1
        await sync_to_async(dealer_obj.save)()
        # Record dealer’s win
        await sync_to_async(HorseRaceWin.objects.create)(
            race=race,
            user=None,
            horse_number=dealer_horse,
            horse_name="Dealer",
            amount=total_pot
        )

        await update.message.reply_text(
            "🏆 Dealer's horse 1 wins! All players lose their bets."
        )
        return

    # ─── Players won ───────────────────────────────────────────────────────────────
    winning_bets      = [bet for bet in bets if bet.horse_number == winner]
    total_losing_bets = sum(bet.bet_amount for bet in bets if bet.horse_number != winner)

    if not winning_bets:
        total_pot = sum(bet.bet_amount for bet in bets)
        dealer_obj, _ = await sync_to_async(Dealer.objects.get_or_create)(id=1)
        dealer_obj.chips += total_pot
        dealer_obj.wins  += 1
        dealer_obj.games += 1
        await sync_to_async(dealer_obj.save)()

        # Record dealer’s win when no players bet
        horse_obj = await sync_to_async(lambda: OwnedHorse.objects.filter(horse_number=winner).first())()
        horse_name = horse_obj.name if (horse_obj and horse_obj.name) else ""
        await sync_to_async(HorseRaceWin.objects.create)(
            race=race,
            user=None,
            horse_number=winner,
            horse_name=horse_name,
            amount=total_pot
        )

        await safe_send_message(
            context.bot,
            chat_id,
            (
                f"🏆 Horse {winner} won, but no players bet on it!\n"
                f"🎰 Casino (Dealer) takes the pot: {total_pot:,} chips!"
            )
        )
    else:
        oh = await sync_to_async(lambda: OwnedHorse.objects.filter(horse_number=winner).first())()
        horse_label = oh.name if (oh and oh.name) else f"Horse {winner}"

        # Record each player’s win
        for bet in winning_bets:
            share_of_losing_pot = total_losing_bets // len(winning_bets)
            payout = bet.bet_amount * 2 + share_of_losing_pot

            player_obj = await sync_to_async(Player.objects.get)(id=bet.user_id)
            player_obj.chips += payout
            await sync_to_async(player_obj.save)()

            await sync_to_async(HorseRaceWin.objects.create)(
                race=race,
                user=player_obj,
                horse_number=winner,
                horse_name=(oh.name if (oh and oh.name) else ""),
                amount=payout
            )

            await safe_send_message(
                context.bot,
                bet.user_id,
                f"🎉 You won {payout:,} chips on {horse_label}!"
            )
            await apply_referral_bonus(player_obj, payout, context)

        first_share = total_losing_bets // len(winning_bets) + winning_bets[0].bet_amount * 2
        await safe_send_message(
            context.bot,
            chat_id,
            (
                f"🏆 Race finished! Winner: {horse_label} (#{winner}) 🏆\n"
                f"🎉 First winner’s payout: {first_share:,} chips!"
            )
        )
    # ─── Cleanup Used-Up Spells ────────────────────────────────────────────────────────
    used_up_spells = await sync_to_async(list)(
        HorseAppliedUpgrade.objects.filter(uses_remaining__lte=0).select_related("upgrade", "horse")
    )

    for spell in used_up_spells:
        try:
            # Delete from PlayerUpgrade
            await sync_to_async(PlayerUpgrade.objects.filter(
                player=spell.owner,
                upgrade=spell.upgrade
            ).delete)()
        except Exception:
            pass  # failsafe — sometimes .owner isn't prefetched

        # Delete from applied upgrades
        await sync_to_async(spell.delete)()

    # ─── Do not delete the race; we keep it for history ─────────────────────────────













async def shop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_player(update, context):
        return
    await update.message.reply_text(
        "🏪 Shop Menu:\n"
        "/buyhorse <number> - Buy a horse number,(Costs 60000)\n"
        "/setemoji <horse_number> <emoji> - Set emoji for your horse(Costs 9000)\n"
        "/myhorses - View your owned horses"
    )




async def buyhorse(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    chat_id = update.effective_chat.id

    args = context.args
    if len(args) != 1 or not args[0].isdigit():
        await update.message.reply_text("Usage: /buyhorse <horse_number>")
        return

    horse_number = int(args[0])
    if horse_number == 1:
        await update.message.reply_text("❌ Horse 1 is reserved for the dealer.")
        return

    # Check if already owned
    existing = await sync_to_async(OwnedHorse.objects.filter(horse_number=horse_number).exists)()
    if existing:
        await update.message.reply_text("❌ This horse is already owned.")
        return

    # Get the player
    try:
        player = await sync_to_async(Player.objects.get)(id=user_id)
    except Player.DoesNotExist:
        await update.message.reply_text("❌ You’re not registered.")
        return

    cost = 60000
    if player.chips < cost:
        await update.message.reply_text("❌ Not enough chips! Horse costs 60,000.")
        return

    # Deduct chips and assign horse
    player.chips -= cost
    await sync_to_async(player.save)()

    

    await sync_to_async(OwnedHorse.objects.create)(
        user=player,
        horse_number=horse_number,
        emoji=None
    )


    await update.message.reply_text(f"✅ You now own Horse {horse_number}!")
async def setemoji(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_player(update, context):
        return

    user_id = update.effective_user.id
    args = context.args

    if len(args) != 2:
        await update.message.reply_text("Usage: /setemoji <horse_number> <emoji>")
        return

    try:
        horse_number = int(args[0])
    except ValueError:
        await update.message.reply_text("❌ Horse number must be a valid number.")
        return

    emoji = args[1]
    emoji_cost = 9000

    try:
        player = await sync_to_async(Player.objects.get)(id=user_id)
        horse = await sync_to_async(OwnedHorse.objects.get)(horse_number=horse_number)

        horse_owner_id = await sync_to_async(lambda: horse.user.id)()

        if horse_owner_id != player.id:
            await update.message.reply_text("❌ You don’t own this horse.")
            return

        if player.chips < emoji_cost:
            await update.message.reply_text("❌ Not enough chips to change the emoji.")
            return

        # Deduct chips and update emoji
        player.chips -= emoji_cost
        await sync_to_async(player.save)()

        horse.emoji = emoji
        await sync_to_async(horse.save)()

        await update.message.reply_text(
            f"✅ Emoji updated to {emoji} for horse {horse_number}!\n💸 Cost: {emoji_cost} chips"
        )

    except OwnedHorse.DoesNotExist:
        await update.message.reply_text("❌ You don’t own this horse.")


# ─── /myhorses: Show owned horses, their emojis, and owned/applied upgrades ───
async def myhorses(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_player(update, context):
        return

    user_id = update.effective_user.id
    player = await sync_to_async(Player.objects.get)(id=user_id)

    # Fetch all horses owned by this player
    horses = await sync_to_async(list)(
        OwnedHorse.objects.filter(user=player)
    )

    # Fetch all upgrades the player has purchased
    owned_upgrades = await sync_to_async(list)(
        PlayerUpgrade.objects.filter(player=player).select_related("upgrade")
    )

    if not horses and not owned_upgrades:
        await update.message.reply_text("🐎 You don’t own any horses or spells yet.")
        return

    lines = []

    if horses:
        lines.append("🐴 *Your Horses:*")
        for h in horses:
            # For each horse, list applied upgrades
            applied = await sync_to_async(list)(
                HorseAppliedUpgrade.objects.filter(horse=h).select_related("upgrade")
            )
            applied_names = [ap.upgrade.name for ap in applied]
            emoji_text = f" {h.emoji}" if h.emoji else ""
            if applied_names:
                lines.append(f"• Horse {h.horse_number}{emoji_text}  _(Applied: {', '.join(applied_names)})_")
            else:
                lines.append(f"• Horse {h.horse_number}{emoji_text}")
    else:
        lines.append("🐴 You don’t own any horses.")

    if owned_upgrades:
        lines.append("\n🔧 *Your Purchased spells:*")
        for pu in owned_upgrades:
            lines.append(f"• {pu.upgrade.name}: {pu.upgrade.description} (Cost: {pu.upgrade.cost} chips)")
    else:
        lines.append("\n🔧 You haven’t purchased any spells.")

    message = "\n".join(lines)
    await update.message.reply_text(message, parse_mode="Markdown")


# ─── /shopupgrades: List available upgrades ───
async def shopupgrades(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Fetch all defined upgrades
    upgrades = await sync_to_async(list)(HorseUpgrade.objects.all())
    if not upgrades:
        await update.message.reply_text("No spells available right now.")
        return

    lines = ["🏬 *Available Spells:*",""]
    for up in upgrades:
        lines.append(
            f"{up.id}. *{up.name}* — {up.cost} chips\n"
            f"    _{up.description}_\n"
        )

    # Add instructions at the bottom
    lines.append("")  # blank line
    lines.append("ℹ️ To purchase a spell, type `/buyupgrade <spell_id>`.")

    await update.message.reply_text(
        "\n".join(lines),
        parse_mode="Markdown"
    )

# ─── /buyupgrade <upgrade_id>: Purchase an upgrade ───
async def buyupgrade(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_player(update, context):
        return
    user_id = update.effective_user.id
    args = context.args

    # Must pass exactly one integer (the upgrade’s ID)
    if len(args) != 1 or not args[0].isdigit():
        await update.message.reply_text("Usage: /buyspell <spell_id>")
        return
    upgrade_id = int(args[0])

    try:
        player = await sync_to_async(Player.objects.get)(id=user_id)
    except Player.DoesNotExist:
        await update.message.reply_text("❌ You’re not registered.")
        return

    # Validate upgrade exists
    try:
        upgrade = await sync_to_async(HorseUpgrade.objects.get)(id=upgrade_id)
    except HorseUpgrade.DoesNotExist:
        await update.message.reply_text("❌ Invalid spell ID.")
        return

    # Check if player already owns it
    already = await sync_to_async(PlayerUpgrade.objects.filter)(
        player=player, upgrade=upgrade
    )
    if await sync_to_async(already.exists)():
        await update.message.reply_text("❌ You already own this spell.")
        return

    # Check cost
    if player.chips < upgrade.cost:
        await update.message.reply_text(f"❌ Not enough chips! This costs {upgrade.cost}.")
        return

    # Deduct & create PlayerUpgrade
    player.chips -= upgrade.cost
    await sync_to_async(player.save)()
    await sync_to_async(PlayerUpgrade.objects.create)(player=player, upgrade=upgrade)

    await update.message.reply_text(
        f"✅ You bought *{upgrade.name}*! You can now apply it to any of your horses.",
        parse_mode="Markdown"
    )

async def applyupgrade(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_player(update, context):
        return

    user_id = update.effective_user.id
    args = context.args

    if len(args) != 2:
        await update.message.reply_text("Usage: /applyspell <horse_number> <spell_id>")
        return

    # 1) Parse horse number and upgrade ID
    try:
        horse_number = int(args[0])
    except ValueError:
        await update.message.reply_text("❌ Horse number must be an integer.")
        return

    try:
        upgrade_id = int(args[1])
    except ValueError:
        await update.message.reply_text("❌ spell ID must be an integer.")
        return

    # 2) Verify that this player actually owns that horse:
    try:
        owned_horse = await sync_to_async(OwnedHorse.objects.get)(
            user__id=user_id,
            horse_number=horse_number
        )
    except OwnedHorse.DoesNotExist:
        await update.message.reply_text(f"❌ You do not own a horse numbered {horse_number}.")
        return

    # 3) Verify that the desired HorseUpgrade exists by ID:
    try:
        upgrade_obj = await sync_to_async(HorseUpgrade.objects.get)(pk=upgrade_id)
    except HorseUpgrade.DoesNotExist:
        await update.message.reply_text(f"❌ No upgrade found with ID {upgrade_id}.")
        return

    # 4) Check that the player has purchased this upgrade (PlayerUpgrade must exist)
    owns_upgrade_exists = await sync_to_async(
        lambda: PlayerUpgrade.objects.filter(player__id=user_id, upgrade=upgrade_obj).exists()
    )()
    if not owns_upgrade_exists:
        await update.message.reply_text(
            f"❌ You have not purchased the “{upgrade_obj.name}” spell (ID {upgrade_id})."
        )
        return

    # 5) Fetch all upgrade names already applied to this horse in one go (synchronously wrapped):
    existing_names = await sync_to_async(
        lambda: list(
            HorseAppliedUpgrade.objects.filter(horse=owned_horse)
                                     .values_list("upgrade__name", flat=True)
        )
    )()

    # 6) Prevent “Double Dash” and “Risky Rocket” from coexisting:
    blocking_pair = {"Double Dash", "Risky Rocket"}
    if upgrade_obj.name in blocking_pair:
        other_name = "Risky Rocket" if upgrade_obj.name == "Double Dash" else "Double Dash"
        if other_name in existing_names:
            await update.message.reply_text(
                f"❌ You cannot apply “{upgrade_obj.name}” (ID {upgrade_id}) to Horse {horse_number} "
                f"because it already has “{other_name}” applied."
            )
            return

    # 7) Check if this exact upgrade is already applied to that horse:
    already_applied = await sync_to_async(
        lambda: HorseAppliedUpgrade.objects.filter(
            owner__id=user_id,
            horse=owned_horse,
            upgrade=upgrade_obj
        ).exists()
    )()
    if already_applied:
        await update.message.reply_text(
            f"⚠️ Spell “{upgrade_obj.name}” (ID {upgrade_id}) is already applied to Horse {horse_number}."
        )
        return

    # 8) Finally, create the HorseAppliedUpgrade record:
    player_obj = await sync_to_async(Player.objects.get)(id=user_id)
    await sync_to_async(HorseAppliedUpgrade.objects.create)(
        owner=player_obj,
        horse=owned_horse,
        upgrade=upgrade_obj
    )

    await update.message.reply_text(
        f"✅ “{upgrade_obj.name}” (ID {upgrade_id}) has been applied to Horse {horse_number}!"
    )

# ─── /unapplyupgrade <horse_number> <upgrade_id> ───
async def unapplyupgrade(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_player(update, context):
        return
    user_id = update.effective_user.id
    args = context.args

    if len(args) != 2 or not args[0].isdigit() or not args[1].isdigit():
        await update.message.reply_text("Usage: /unapplyspell <horse_number> <upgrade_id>")
        return
    horse_number = int(args[0])
    upgrade_id = int(args[1])

    # Fetch player
    try:
        player = await sync_to_async(Player.objects.get)(id=user_id)
    except Player.DoesNotExist:
        await update.message.reply_text("❌ You’re not registered.")
        return

    # Check horse
    try:
        owned_horse = await sync_to_async(OwnedHorse.objects.get)(horse_number=horse_number)
    except OwnedHorse.DoesNotExist:
        await update.message.reply_text("❌ You don’t own that horse.")
        return
    owner_id = await sync_to_async(lambda: owned_horse.user.id)()
    if owner_id != user_id:
        await update.message.reply_text("❌ You don’t own this horse.")
        return

    # Fetch upgrade
    try:
        upgrade = await sync_to_async(HorseUpgrade.objects.get)(id=upgrade_id)
    except HorseUpgrade.DoesNotExist:
        await update.message.reply_text("❌ Invalid spell.")
        return

    # Check if applied
    applied_qs = await sync_to_async(HorseAppliedUpgrade.objects.filter)(
        owner=player, horse=owned_horse, upgrade=upgrade
    )
    if not await sync_to_async(applied_qs.exists)():
        await update.message.reply_text("❌ That spell isn’t applied to this horse.")
        return

    # Remove it
    await sync_to_async(applied_qs.delete)()
    await update.message.reply_text(
        f"✅ Unapplied *{upgrade.name}* from Horse {horse_number}.",
        parse_mode="Markdown"
    )

def build_main_menu_keyboard():
    keyboard = [
        [
            InlineKeyboardButton("🐎 Buy Horse", callback_data="menu:buy_horse"),
            InlineKeyboardButton("🎨 Set Emoji", callback_data="menu:set_emoji"),
        ],
        [
            InlineKeyboardButton("🐴 My Horses", callback_data="menu:my_horses"),
            InlineKeyboardButton("📜 My Spells", callback_data="menu:my_spells"),
        ],
        [
            InlineKeyboardButton("💰 Buy Spell", callback_data="menu:buy_spell"),
            InlineKeyboardButton("✨ Apply Spell", callback_data="menu:apply_spell"),
        ],
        [InlineKeyboardButton("❌ Unapply Spell", callback_data="menu:unapply_spell"),],
        [ 
        InlineKeyboardButton("✏️ Name Horse", callback_data="menu:rename_horse"),
        InlineKeyboardButton("🎁 Gift Horse",      callback_data="menu:gift_horse") 
        ],
        [
        InlineKeyboardButton("🐴 Leaderboard", callback_data="menu:global_horse_leaderboard"),
        InlineKeyboardButton("📈 Race Stats", callback_data="menu:my_horse_statsrace"),
        ],

        

        [ InlineKeyboardButton("📈 List Horse For Sale",        callback_data="menu:list_horse") ],
        [ InlineKeyboardButton("🛒 Horses on Sale",       callback_data="menu:sale_horses") ],

        

    ]
    return InlineKeyboardMarkup(keyboard)


# ─── /horse: send the top‐level shop menu ───
async def horse(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🏇 *Horse Racing Shop Menu* 🏇\n\n"
        "Choose an option below:",
        parse_mode="Markdown",
        reply_markup=build_main_menu_keyboard()
    )
































async def horse_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    # ─── Back to main menu ───
    if data == "menu:mainhorse":
        context.user_data.pop("awaiting_buy_horse", None)
        context.user_data.pop("awaiting_set_emoji", None)
        await query.edit_message_text(
            "🏇 *Horse Racing Shop Menu* 🏇\n\n"
            "Choose an option below:",
            parse_mode="Markdown",
            reply_markup=build_main_menu_keyboard()
        )
        return

    # ─── Buy Horse submenu ───
    # ─── Buy Horse submenu (now shows sale listings, too) ───
    if data == "menu:buy_horse":
        # ─── 1) Static pricing rules text ───
        lines = [
            "🐎 *Buy Horse*\n",
            "• Reply with the exact horse number you want to buy (unowned). Pricing rules:\n",
            "  – 1-digit (e.g. 7): 100 000 chips",
            "  – 2-digit (e.g. 42):  80 000 chips",
            "  – 3-digit (e.g. 123): 60 000 chips",
            "  – “All-same” digits (e.g. 11, 777, 2222): 120 000 chips\n"
        ]

        # ─── 2) Fetch all active sale listings ───
        sale_list = await sync_to_async(list)(
            HorseSale.objects
                .select_related("horse__user", "horse")
                .all()
        )

        if sale_list:
            lines.append("🛒 *Horses for Sale:*")
            # Collect OwnedHorse instances to query applied upgrades in bulk
            owned_horses = [listing.horse for listing in sale_list]

            # ─── 3) Bulk fetch all applied upgrades for these horses ───
            applied_list = await sync_to_async(list)(
                HorseAppliedUpgrade.objects
                    .filter(horse__in=owned_horses)
                    .select_related("upgrade", "horse")
            )

            # ─── 4) Build a mapping: horse_number → [list of spell names] ───
            spells_map = {oh.horse_number: [] for oh in owned_horses}
            for au in applied_list:
                num = au.horse.horse_number
                spells_map[num].append(au.upgrade.name)

            # ─── 5) Append each sale to the text block ───
            for listing in sale_list:
                oh = listing.horse
                price = listing.price
                number = oh.horse_number

                # (a) Base label: custom name or “Horse <number>”
                if oh.name:
                    display_label = f"{oh.name} ({number})"
                else:
                    display_label = f"Horse {number}"

                # (b) Emoji if set
                emoji_text = f"{oh.emoji} " if oh.emoji else ""

                # (c) Spells from spells_map
                spell_names = spells_map.get(number, [])
                if spell_names:
                    spells_text = " – Applied: " + ", ".join(spell_names)
                else:
                    spells_text = ""

                lines.append(f"  – {emoji_text}{display_label}{spells_text} — {price:,} chips")

            lines.append("")  # blank line before “↩️ Back”

        lines.append("↩️ Back")

        # ─── 6) Mark that a raw number should run the unowned‐purchase logic ───
        context.user_data["awaiting_buy_horse"] = True

        # ─── 7) Build the keyboard: one button per sale listing, plus Back ───
        keyboard = []
        if sale_list:
            for listing in sale_list:
                oh = listing.horse
                price = listing.price
                number = oh.horse_number

                if oh.name:
                    display_label = f"{oh.name} ({number})"
                else:
                    display_label = f"Horse {number}"

                emoji_text = f"{oh.emoji} " if oh.emoji else ""
                spell_names = spells_map.get(number, [])
                if spell_names:
                    spells_text = " – Applied: " + ", ".join(spell_names)
                else:
                    spells_text = ""

                btn_text = f"{emoji_text}{display_label}{spells_text} — {price:,} chips"
                keyboard.append([
                    InlineKeyboardButton(
                        btn_text,
                        callback_data=f"menu:buy_sale:{number}"
                    )
                ])

        keyboard.append([InlineKeyboardButton("↩️ Back", callback_data="menu:mainhorse")])

        await query.edit_message_text(
            "\n".join(lines),
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    # ─── Global Horse‐Racing Leaderboard (no backticks) ─────────────────────────
    if data == "menu:global_horse_leaderboard":
        # 1) Annotate wins & chips per player
        leaderboard_qs = await sync_to_async(
            lambda: list(
                HorseRaceWin.objects
                    .filter(user__isnull=False)
                    .values("user__id", "user__name")
                    .annotate(
                        wins=Count("id"),
                        chips=Sum("amount")
                    )
                    .order_by("-wins", "-chips")
            )
        )()

        top5 = leaderboard_qs[:5]
        user_id = query.from_user.id

        # Find calling user’s index
        user_index = next(
            (idx for idx, e in enumerate(leaderboard_qs) if e["user__id"] == user_id),
            None
        )

        # Build lines without backticks:
        lines = ["🌍 *Global Leaderboard* 🌍", ""]

        # Top 5 entries
        for idx, entry in enumerate(top5, start=1):
            name = entry["user__name"] or f"User {entry['user__id']}"
            wins = entry["wins"]
            chips_amt = entry["chips"] or 0
            # Format: "1 . Alice      🏆 Wins: 12   💰 Chips: 4800"
            # Use fixed‐width fields by padding/truncating name to ~10 chars
            lines.append(
                f"{idx:>2} . {name:<12}   🏆 Wins: {wins:<3}   💰 Chips: {chips_amt}"
            )

        lines.append("")  # blank separator

        # “Your Position” section
        if user_index is None:
            lines.append("🏅 *Your Position* (Not Ranked Yet):")
            lines.append("   • No wins recorded.")
        else:
            user_rank = user_index + 1
            lines.append(f"🏅 *Your Position* (Rank {user_rank}):")

            # Show up to two above and two below
            start = max(0, user_index - 2)
            end = min(len(leaderboard_qs), user_index + 3)
            for idx in range(start, end):
                e = leaderboard_qs[idx]
                name = e["user__name"] or f"User {e['user__id']}"
                wins = e["wins"]
                chips_amt = e["chips"] or 0
                display_rank = idx + 1
                prefix = "👉" if e["user__id"] == user_id else "  "
                lines.append(
                    f"{prefix}{display_rank:>2} . {name:<12}   🏆 Wins: {wins:<3}   💰 Chips: {chips_amt}"
                )

        text = "\n".join(lines)
        keyboard = [[InlineKeyboardButton("↩️ Back", callback_data="menu:mainhorse")]]
        await query.edit_message_text(
            text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return


    # ─── Race Stats ───────────────────────────────────────────────────────────────
    # ─── My Horse‐Racing Stats ─────────────────────────────────────────────────
    if data == "menu:my_horse_statsrace":
        user_id = query.from_user.id

        # 1) Total races this user has participated in (i.e. placed ≥1 bet)
        races_participated = await sync_to_async(
            lambda: HorseBet.objects.filter(user_id=user_id)
                                     .values_list("race", flat=True)
                                     .distinct()
                                     .count()
        )()

        # 2) Total chips wagered by this user (sum of all their HorseBet.bet_amount)
        total_wagered_q = await sync_to_async(
            lambda: HorseBet.objects.filter(user_id=user_id)
                                     .aggregate(total=Sum("bet_amount"))
        )()
        total_wagered = total_wagered_q["total"] or 0

        # 3) Average bet size for this user
        avg_bet_q = await sync_to_async(
            lambda: HorseBet.objects.filter(user_id=user_id)
                                     .aggregate(avg=Avg("bet_amount"))
        )()
        avg_bet = avg_bet_q["avg"] or 0

        # 4) Total horses owned by this user
        horses_owned = await sync_to_async(
            lambda: OwnedHorse.objects.filter(user__id=user_id).count()
        )()

        # 5) Total wins (number of times this user appears in HorseRaceWin)
        total_wins = await sync_to_async(
            lambda: HorseRaceWin.objects.filter(user__id=user_id).count()
        )()

        # 6) Total chips earned (sum of HorseRaceWin.amount where user=this user)
        total_earned_q = await sync_to_async(
            lambda: HorseRaceWin.objects.filter(user__id=user_id)
                                         .aggregate(total=Sum("amount"))
        )()
        total_earned = total_earned_q["total"] or 0

        # 7) Horse‐Level Win Rate: For each horse this user owns,
        #    compute (wins_of_that_horse) / (bets_on_that_horse by this user).
        #    Then average across all their horses. If user has no horses, skip.
        horse_ids = await sync_to_async(
            lambda: list(
                OwnedHorse.objects.filter(user__id=user_id)
                                  .values_list("horse_number", flat=True)
            )
        )()

        if horse_ids:
            win_rate_list = []
            for hnum in horse_ids:
                wins_for_horse = await sync_to_async(
                    lambda: HorseRaceWin.objects.filter(
                        user__id=user_id, horse_number=hnum
                    ).count()
                )()
                bets_on_horse = await sync_to_async(
                    lambda: HorseBet.objects.filter(
                        user_id=user_id, horse_number=hnum
                    ).count()
                )()
                if bets_on_horse > 0:
                    win_rate_list.append(wins_for_horse / bets_on_horse)
                else:
                    win_rate_list.append(0.0)

            # Average across all horses
            horse_win_rate = (sum(win_rate_list) / len(win_rate_list)) * 100  # as percentage
        else:
            horse_win_rate = 0.0

        # 8) Player Win Rate: (# races in which they bet AND won) / (# races participated)
        #    “Races in which they won” = distinct race IDs from HorseRaceWin for this user
        races_won = await sync_to_async(
            lambda: HorseRaceWin.objects.filter(user__id=user_id)
                                        .values_list("race", flat=True)
                                        .distinct()
                                        .count()
        )()

        if races_participated > 0:
            player_win_rate = (races_won / races_participated) * 100
        else:
            player_win_rate = 0.0

        # ─── Build a Markdown block using the same “🎮 Your Stats 🎮” style ────────
        lines = [
            "🎮 *Your Horse‐Racing Stats* 🎮",
            "",
            f"🐎 Races participated: *{races_participated}*",
            f"💰 Total chips wagered: *{total_wagered:,}* chips",
            f"📊 Avg. bet size: *{avg_bet:.2f}* chips",
            f"🏠 Horses owned: *{horses_owned}*",
            f"🏆 Total wins: *{total_wins}*",
            f"🎉 Total chips earned: *{total_earned:,}* chips",
            f"🐴 Horse‐level win rate: *{horse_win_rate:.1f}%*",
            f"🎲 Player win rate: *{player_win_rate:.1f}%*",
        ]
        text = "\n".join(lines)

        keyboard = [[InlineKeyboardButton("↩️ Back", callback_data="menu:mainhorse")]]
        await query.edit_message_text(
            text,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return








    if data == "menu:set_emoji":
        user_id = query.from_user.id
        owned_horses = await sync_to_async(list)(
            OwnedHorse.objects.filter(user__id=user_id)
        )

        if not owned_horses:
            text = "🎨 You don’t own any horses to set an emoji on.\n\n↩️ Back"
            keyboard = [[InlineKeyboardButton("↩️ Back", callback_data="menu:mainhorse")]]
            await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
            return

        keyboard = []
        for h in owned_horses:
            # Determine display label: “Name (number)” if name exists, else “Horse <number>”
            if h.name:
                display_label = f"{h.name} ({h.horse_number})"
            else:
                display_label = f"Horse {h.horse_number}"

            emoji_text = f"{h.emoji} " if h.emoji else ""
            btn_text = f"{emoji_text}{display_label}"
            keyboard.append([
                InlineKeyboardButton(
                    btn_text,
                    callback_data=f"menu:setemoji_choose:{h.horse_number}"
                )
            ])
        keyboard.append([InlineKeyboardButton("↩️ Back", callback_data="menu:mainhorse")])

        await query.edit_message_text(
            "🎨 *Set Emoji* – Choose which horse to change:\n\n↩️ Back",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return
        #
    # ─── “Sale Horses” submenu ───
    #
    #
    # ─── “Sale Horses” submenu — show spells + name/emoji + price ───
    #
    if data == "menu:sale_horses":
        # 1) Fetch all active listings (with select_related to grab the OwnedHorse itself)
        sale_list = await sync_to_async(list)(
            HorseSale.objects
                .select_related("horse__user", "horse")
                .all()
        )

        if not sale_list:
            text = "🛒 There are currently no horses listed for sale.\n\n↩️ Back"
            keyboard = [[InlineKeyboardButton("↩️ Back", callback_data="menu:mainhorse")]]
            await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
            return

        # 2) Build a list of just the OwnedHorse objects for these listings
        owned_horses = [listing.horse for listing in sale_list]

        # 3) In one bulk call, fetch all HorseAppliedUpgrade records for those OwnedHorse IDs
        #    We use `horse__in=owned_horses` and select_related("upgrade") so we get each upgrade name.
        applied_list = await sync_to_async(list)(
            HorseAppliedUpgrade.objects
                .filter(horse__in=owned_horses)
                .select_related("upgrade", "horse")
        )

        # 4) Build a mapping: horse_number → [list of spell names]
        spells_map = {}
        for h in owned_horses:
            spells_map[h.horse_number] = []
        for au in applied_list:
            num = au.horse.horse_number
            spells_map[num].append(au.upgrade.name)

        # 5) Now build the keyboard—pure Python from here on (no more ORM calls)
        keyboard = []
        for listing in sale_list:
            oh = listing.horse
            price = listing.price
            number = oh.horse_number

            # (a) Display label: custom name or “Horse <number>”
            if oh.name:
                display_label = f"{oh.name} ({number})"
            else:
                display_label = f"Horse {number}"

            # (b) Emoji (if any)
            emoji_text = f"{oh.emoji} " if oh.emoji else ""

            # (c) Spells (look up in spells_map)
            spell_names = spells_map.get(number, [])
            if spell_names:
                spells_text = " – Applied: " + ", ".join(spell_names)
            else:
                spells_text = ""

            # (d) Construct button text
            btn_text = f"{emoji_text}{display_label}{spells_text} — {price:,} chips"
            keyboard.append([
                InlineKeyboardButton(
                    btn_text,
                    callback_data=f"menu:buy_sale:{number}"
                )
            ])

        # 6) Add the Back button at the bottom
        keyboard.append([InlineKeyboardButton("↩️ Back", callback_data="menu:mainhorse")])

        # 7) Finally, edit the message
        await query.edit_message_text(
            "🛒 *Horses for Sale:*  (Tap to buy)\n\n↩️ Back",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return


    #
    # ─── “Buy Sale Listing” handler ───
    #
    if data.startswith("menu:buy_sale:"):
        horse_number = int(data.split(":")[2])
        buyer_id = query.from_user.id

        # 1) Fetch the listing & related OwnedHorse
        try:
            sale = await sync_to_async(HorseSale.objects.select_related("horse__user").get)(
                horse__horse_number=horse_number
            )
        except HorseSale.DoesNotExist:
            await query.edit_message_text("❌ That listing no longer exists.\n\n↩️ Back")
            return

        owned_horse = sale.horse
        seller = owned_horse.user
        price = sale.price

        # 2) Prevent self-purchase
        if seller.id == buyer_id:
            await query.edit_message_text(
                "❌ You cannot buy your own listing.\n\n↩️ Back"
            )
            return

        # 3) Check buyer has enough chips
        buyer = await sync_to_async(Player.objects.get)(id=buyer_id)
        if buyer.chips < price:
            await query.edit_message_text(
                f"❌ Not enough chips! You need {price:,} but you have {buyer.chips:,}.\n\n↩️ Back"
            )
            return

        # 4) Transfer chips: deduct from buyer, add to seller
        buyer.chips -= price
        await sync_to_async(buyer.save)()

        seller_player = await sync_to_async(Player.objects.get)(id=seller.id)
        seller_player.chips += price
        await sync_to_async(seller_player.save)()

        # 5) Transfer ownership: change OwnedHorse.user → buyer
        owned_horse.user = buyer
        await sync_to_async(owned_horse.save)()

        # 6) Delete the sale listing
        await sync_to_async(sale.delete)()

        # 7) Notify both parties
        if owned_horse.name:
            display_label = f"{owned_horse.name} ({horse_number})"
        else:
            display_label = f"Horse {horse_number}"

        await query.edit_message_text(
            f"✅ You bought {display_label} from {seller_player.name or seller_player.id} "
            f"for {price:,} chips!"
        )
        # Notify seller via DM if possible
        try:
            await context.bot.send_message(
                chat_id=seller_player.id,
                text=(
                    f"🎉 Your horse {display_label} was purchased by "
                    f"{buyer.name or buyer.id} for {price:,} chips!"
                )
            )
        except Exception:
            pass

        return

    # ─── My Horses submenu (show horses + owned spells) ───
        # ─── “List Horse” submenu ───
    #
    if data == "menu:list_horse":
        user_id = query.from_user.id
        # Fetch all horses this user owns that are NOT already listed
        owned_horses = await sync_to_async(list)(
            OwnedHorse.objects
                      .filter(user__id=user_id)
                      .exclude(sale_listing__isnull=False)
        )
        if not owned_horses:
            text = "📈 You don’t have any horses available to list for sale.\n\n↩️ Back"
            keyboard = [[InlineKeyboardButton("↩️ Back", callback_data="menu:mainhorse")]]
            await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
            return

        # Build a keyboard listing each owned horse (showing name(number) or “Horse <number>”)
        keyboard = []
        for h in owned_horses:
            if h.name:
                display_label = f"{h.name} ({h.horse_number})"
            else:
                display_label = f"Horse {h.horse_number}"
            emoji_text = f"{h.emoji} " if h.emoji else ""
            btn_text = f"{emoji_text}{display_label}"
            keyboard.append([
                InlineKeyboardButton(
                    btn_text,
                    callback_data=f"menu:list_choose:{h.horse_number}"
                )
            ])
        keyboard.append([InlineKeyboardButton("↩️ Back", callback_data="menu:mainhorse")])

        await query.edit_message_text(
            "📈 *List Horse for Sale* – Choose which of your horses to list:\n\n↩️ Back",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    #
    # ─── “List Horse → Pick Horse” ───
    #
    if data.startswith("menu:list_choose:"):
        horse_number = int(data.split(":")[2])
        user_id = query.from_user.id

        # Verify user still owns that horse and it’s not already listed
        try:
            owned_horse = await sync_to_async(OwnedHorse.objects.get)(
                user__id=user_id, horse_number=horse_number
            )
        except OwnedHorse.DoesNotExist:
            await query.edit_message_text("❌ You do not own that horse.\n\n↩️ Back")
            return

        # Make sure it isn't already listed
        if await sync_to_async(
            HorseSale.objects.filter(horse=owned_horse).exists
        )():
            await query.edit_message_text(
                f"⚠️ That horse is already listed for sale.\n\n↩️ Back",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("↩️ Back", callback_data="menu:mainhorse")]])
            )
            return

        # Save in user_data so text‐handler knows we’re in “awaiting_list_price” mode
        context.user_data["awaiting_list_horse"] = horse_number

        # Ask the user for the price
        if owned_horse.name:
            display_label = f"{owned_horse.name} ({horse_number})"
        else:
            display_label = f"Horse {horse_number}"

        keyboard = [[InlineKeyboardButton("↩️ Back", callback_data="menu:mainhorse")]]
        await query.edit_message_text(
            f"📈 *List → {display_label}*\n\n"
            "Please reply with the price (in chips) at which you want to list this horse for sale.\n\n↩️ Back",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return
    if data == "menu:my_horses":
        user_id = query.from_user.id
        try:
            player = await sync_to_async(Player.objects.get)(id=user_id)
        except Player.DoesNotExist:
            await query.edit_message_text("❌ You’re not registered yet.")
            return

        horses = await sync_to_async(list)(
            OwnedHorse.objects.filter(user=player)
        )
        owned_upgrades = await sync_to_async(list)(
            PlayerUpgrade.objects.filter(player=player).select_related("upgrade")
        )

        if not horses and not owned_upgrades:
            text = "🐎 You don’t own any horses yet.\n\n↩️ Back"
            keyboard = [[InlineKeyboardButton("↩️ Back", callback_data="menu:mainhorse")]]
            await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
            return

        lines = []
        if horses:
            lines.append("🐴 *Your Horses:*")
            for h in horses:
                # Fetch any applied upgrades
                applied = await sync_to_async(list)(
                    HorseAppliedUpgrade.objects.filter(horse=h).select_related("upgrade")
                )
                applied_names = [ap.upgrade.name for ap in applied]

                # Determine display label: if custom name exists, show "Name(number)"
                if h.name:
                    display_label = f"{h.name} ({h.horse_number})"
                else:
                    display_label = f"Horse {h.horse_number}"

                emoji_text = f" {h.emoji}" if h.emoji else ""

                if applied_names:
                    lines.append(
                        f"• {display_label}{emoji_text}  _(Applied: {', '.join(applied_names)})_"
                    )
                else:
                    lines.append(f"• {display_label}{emoji_text}")
        else:
            lines.append("🐴 You don’t own any horses.")

        lines.append("\n↩️ Back")
        keyboard = [[InlineKeyboardButton("↩️ Back", callback_data="menu:mainhorse")]]
        await query.edit_message_text("\n".join(lines), parse_mode="Markdown",
                                      reply_markup=InlineKeyboardMarkup(keyboard))
        return


        # if owned_upgrades:
        #     lines.append("\n🔧 *Your Purchased Spells:*")
        #     for pu in owned_upgrades:
        #         lines.append(
        #             f"• {pu.upgrade.name} – {pu.upgrade.description} _(Cost: {pu.upgrade.cost})_"
        #         )
        # else:
        #     lines.append("\n🔧 You haven’t purchased any spells.")

        # lines.append("\n↩️ Back")
        # keyboard = [[InlineKeyboardButton("↩️ Back", callback_data="menu:main")]]
        # await query.edit_message_text("\n".join(lines), parse_mode="Markdown",
        #                               reply_markup=InlineKeyboardMarkup(keyboard))
        # return
    if data == "menu:rename_horse":
        user_id = query.from_user.id
        # Fetch all horses owned by this user
        owned_horses = await sync_to_async(list)(
            OwnedHorse.objects.filter(user__id=user_id)
        )

        if not owned_horses:
            text = "✏️ You don’t own any horses to rename.\n\n↩️ Back"
            keyboard = [[InlineKeyboardButton("↩️ Back", callback_data="menu:mainhorse")]]
            await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
            return

        # Build a keyboard listing each horse (show name if set, else “Horse <number>”)
        lines = ["✏️ *Rename Horse* (60 000 chips) – Choose which horse to rename:",""]
        keyboard = []
        for h in owned_horses:
            display = h.name if h.name else f"Horse {h.horse_number}"
            keyboard.append([
                InlineKeyboardButton(
                    display,
                    callback_data=f"menu:rename_choose:{h.horse_number}"
                )
            ])

        # Back button
        keyboard.append([ InlineKeyboardButton("↩️ Back", callback_data="menu:mainhorse") ])

        await query.edit_message_text(
            "\n".join(lines),
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return
    if data == "menu:gift_horse":
        user_id = query.from_user.id

        # Offer two choices: gift an owned horse, or buy+gift a new one
        keyboard = [
            [InlineKeyboardButton("🎁 Gift Owned Horse",    callback_data="menu:gift_owned")],
            [InlineKeyboardButton("🎁 Buy & Gift Horse",    callback_data="menu:buy_and_gift")],
            [InlineKeyboardButton("↩️ Back",                 callback_data="menu:mainhorse")],
        ]
        await query.edit_message_text(
            "🎁 *Gift Horse* – Choose an option:",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    #
    # ─── Gift Owned Horse → Show List of Owned Horses ───
    #
    if data == "menu:gift_owned":
        user_id = query.from_user.id
        # Fetch all horses the user owns:
        owned_horses = await sync_to_async(list)(
            OwnedHorse.objects.filter(user__id=user_id)
        )
        if not owned_horses:
            text = "❌ You don’t own any horses to gift.\n\n↩️ Back"
            keyboard = [[InlineKeyboardButton("↩️ Back", callback_data="menu:gift_horse")]]
            await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
            return

        # Build a keyboard listing each owned horse (show name(number) or Horse <number>)
        keyboard = []
        for h in owned_horses:
            if h.name:
                display_label = f"{h.name} ({h.horse_number})"
            else:
                display_label = f"Horse {h.horse_number}"
            emoji_text = f"{h.emoji} " if h.emoji else ""
            btn_text = f"{emoji_text}{display_label}"
            keyboard.append([
                InlineKeyboardButton(btn_text, callback_data=f"menu:gift_owned_choose:{h.horse_number}")
            ])
        keyboard.append([InlineKeyboardButton("↩️ Back", callback_data="menu:gift_horse")])

        await query.edit_message_text(
            "🎁 *Gift Owned Horse* – Choose which horse to gift:\n\n↩️ Back",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    #
    # ─── Gift Owned → Picked a Horse to Gift ───
    #
    if data.startswith("menu:gift_owned_choose:"):
        horse_number = int(data.split(":")[2])
        user_id = query.from_user.id

        # Verify the user still owns that horse
        try:
            owned_horse = await sync_to_async(OwnedHorse.objects.get)(
                user__id=user_id, horse_number=horse_number
            )
        except OwnedHorse.DoesNotExist:
            await query.edit_message_text("❌ You do not own that horse.\n\n↩️ Back")
            return

        # Save flag + which horse they intend to gift
        context.user_data["awaiting_gift_owned"] = horse_number

        # Ask them for the recipient’s Telegram @username or ID
        if owned_horse.name:
            display_label = f"{owned_horse.name} ({horse_number})"
        else:
            display_label = f"Horse {horse_number}"

        keyboard = [[InlineKeyboardButton("↩️ Back", callback_data="menu:gift_horse")]]
        await query.edit_message_text(
            f"🎁 *Gift → {display_label}*\n\n"
            "Please reply with the recipient’s numeric user ID (they can run /myid to see it).\n"
            "Fee: 10 000 chips.\n\n↩️ Back",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    #
    # ─── Buy & Gift Horse → Ask for the horse number to buy & gift ───
    #
    if data == "menu:buy_and_gift":
        # Mark that we’re in “buy and gift” mode
        context.user_data["awaiting_buy_and_gift"] = True

        keyboard = [[InlineKeyboardButton("↩️ Back", callback_data="menu:gift_horse")]]
        await query.edit_message_text(
            "🎁 *Buy & Gift Horse* – Please reply with the horse number you want to purchase and gift.\n\n"
            "Cost = normal purchase cost for that number. ↩️ Back",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    # ─── “My Spells” submenu (new) ───
    if data == "menu:my_spells":
        user_id = query.from_user.id

        # Fetch the Player (if they exist)
        try:
            player = await sync_to_async(Player.objects.get)(id=user_id)
        except Player.DoesNotExist:
            await query.edit_message_text("❌ You’re not registered yet.")
            return

        # Get all spells this player has purchased
        owned_upgrades = await sync_to_async(list)(
            PlayerUpgrade.objects.filter(player=player).select_related("upgrade")
        )

        if not owned_upgrades:
            text = "🔧 You haven’t purchased any spells yet.\n\n↩️ Back"
            keyboard = [[InlineKeyboardButton("↩️ Back", callback_data="menu:mainhorse")]]
            await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
            return

        # Build a simple list of “name – description (cost)”
        lines = ["🔧 *Your Purchased Spells:*",""]
        for pu in owned_upgrades:
            lines.append(f"• *{pu.upgrade.name}* — {pu.upgrade.description} _(Cost: {pu.upgrade.cost})_")
        # lines.append("\n↩️ Back")

        keyboard = [[InlineKeyboardButton("↩️ Back", callback_data="menu:mainhorse")]]
        await query.edit_message_text(
            "\n".join(lines),
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    # ─── Buy Spell submenu ───
    if data == "menu:buy_spell":
        upgrades = await sync_to_async(list)(HorseUpgrade.objects.all())
        if not upgrades:
            text = "📜 No spells available right now.\n\n↩️ Back"
            keyboard = [[InlineKeyboardButton("↩️ Back", callback_data="menu:mainhorse")]]
            await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
            return

        lines = ["📜 *Available Spells:*",""]
        keyboard = []
        for up in upgrades:
            lines.append(f"{up.id}. *{up.name}* – {up.description} _(Cost: {up.cost})_\n")
            keyboard.append([
                InlineKeyboardButton(
                    f"{up.name} (Cost: {up.cost})",
                    callback_data=f"menu:buy_spell_choose:{up.id}"
                )
            ])
        lines.append("\n↩️ Back")
        keyboard.append([InlineKeyboardButton("↩️ Back", callback_data="menu:mainhorse")])

        await query.edit_message_text(
            "\n".join(lines),
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    # ─── Apply Spell submenu ───
    if data == "menu:apply_spell":
        user_id = query.from_user.id
        horses = await sync_to_async(list)(
            OwnedHorse.objects.filter(user__id=user_id)
        )
        if not horses:
            text = "❌ You don’t own any horses to apply a spell to.\n\n↩️ Back"
            keyboard = [[InlineKeyboardButton("↩️ Back", callback_data="menu:mainhorse")]]
            await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
            return

        keyboard = []
        for h in horses:
            # Build display label: “Name (number)” if name exists, else “Horse <number>”
            if h.name:
                display_label = f"{h.name} ({h.horse_number})"
            else:
                display_label = f"Horse {h.horse_number}"

            emoji_text = f"{h.emoji} " if h.emoji else ""
            btn_text = f"{emoji_text}{display_label}"
            keyboard.append([
                InlineKeyboardButton(
                    btn_text,
                    callback_data=f"menu:apply_choose_horse:{h.horse_number}"
                )
            ])
        keyboard.append([InlineKeyboardButton("↩️ Back", callback_data="menu:mainhorse")])
        await query.edit_message_text(
            "✨ *Apply Spell* – Choose which horse to enhance:",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return










    if data == "menu:unapply_spell":
        user_id = query.from_user.id
        horses = await sync_to_async(list)(
            OwnedHorse.objects.filter(user__id=user_id)
        )
        if not horses:
            text = "❌ You don’t own any horses to remove a spell from.\n\n↩️ Back"
            keyboard = [[InlineKeyboardButton("↩️ Back", callback_data="menu:main")]]
            await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
            return

        keyboard = []
        for h in horses:
            # Build display label: “Name (number)” if name exists, else “Horse <number>”
            if h.name:
                display_label = f"{h.name} ({h.horse_number})"
            else:
                display_label = f"Horse {h.horse_number}"

            emoji_text = f"{h.emoji} " if h.emoji else ""
            btn_text = f"{emoji_text}{display_label}"
            keyboard.append([
                InlineKeyboardButton(
                    btn_text,
                    callback_data=f"menu:unapply_choose_horse:{h.horse_number}"
                )
            ])
        keyboard.append([InlineKeyboardButton("↩️ Back", callback_data="menu:mainhorse")])
        await query.edit_message_text(
            "❌ *Unapply Spell* – Pick a horse:",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    if data.startswith("menu:rename_choose:"):
        horse_number = int(data.split(":")[2])
        user_id = query.from_user.id

        # Verify they own that horse
        try:
            await sync_to_async(OwnedHorse.objects.get)(
                user__id=user_id, horse_number=horse_number
            )
        except OwnedHorse.DoesNotExist:
            await query.edit_message_text("❌ You do not own that horse.\n\n↩️ Back")
            return

        # Set the flag so catch_all_text knows we’re in “rename” mode
        context.user_data["awaiting_rename_horse"] = horse_number

        keyboard = [[ InlineKeyboardButton("↩️ Back", callback_data="menu:mainhorse") ]]
        await query.edit_message_text(
            f"✏️ *Rename → Horse {horse_number}*\n\n"
            "Please send the new name for your horse.\n"
            "Cost: 60 000 chips.\n\n↩️ Back",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    if data.startswith("menu:setemoji_choose:"):
        horse_number = int(data.split(":")[2])

        # Fetch the OwnedHorse so we can show its label in the prompt
        try:
            owned_horse = await sync_to_async(OwnedHorse.objects.get)(
                user__id=query.from_user.id, horse_number=horse_number
            )
        except OwnedHorse.DoesNotExist:
            await query.edit_message_text("❌ You do not own that horse.\n\n↩️ Back")
            return

        if owned_horse.name:
            display_label = f"{owned_horse.name} ({horse_number})"
        else:
            display_label = f"Horse {horse_number}"

        # ── INSERT PRINT HERE ──
        print("DEBUG: awaiting_set_emoji set to", horse_number)
        context.user_data["awaiting_set_emoji"] = horse_number

        # Now ask the user to send their new emoji:
        keyboard = [[InlineKeyboardButton("↩️ Back", callback_data="menu:mainhorse")]]
        await query.edit_message_text(
            f"🎨 *Set Emoji → {display_label}*\n\n"
            "Please send the emoji you want to assign to this horse.\n"
            "Cost: 9 000 chips.\n\n↩️ Back",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return











    #
    # ─── SUBMENU: “Buy Spell → Choose Spell” ───
    #
    if data.startswith("menu:buy_spell_choose:"):
        upgrade_id = int(data.split(":")[2])
        user_id = query.from_user.id

        try:
            player = await sync_to_async(Player.objects.get)(id=user_id)
        except Player.DoesNotExist:
            await query.edit_message_text("❌ You’re not registered.")
            return

        try:
            upgrade_obj = await sync_to_async(HorseUpgrade.objects.get)(id=upgrade_id)
        except HorseUpgrade.DoesNotExist:
            await query.edit_message_text("❌ That spell no longer exists.")
            return

        already = await sync_to_async(
            PlayerUpgrade.objects.filter(player=player, upgrade=upgrade_obj).exists
        )()
        if already:
            await query.edit_message_text(
                f"⚠️ You already own *{upgrade_obj.name}*.",
                parse_mode="Markdown"
            )
            return

        if player.chips < upgrade_obj.cost:
            await query.edit_message_text(
                f"❌ Not enough chips! *{upgrade_obj.name}* costs {upgrade_obj.cost}.",
                parse_mode="Markdown"
            )
            return

        player.chips -= upgrade_obj.cost
        await sync_to_async(player.save)()
        await sync_to_async(PlayerUpgrade.objects.create)(player=player, upgrade=upgrade_obj)

        await query.edit_message_text(
            f"✅ You bought *{upgrade_obj.name}*!",
            parse_mode="Markdown"
        )
        return

        #
    # ─── SUBMENU: “Apply Spell → Choose Horse” ───
    #
    if data.startswith("menu:apply_choose_horse:"):
        horse_number = int(data.split(":")[2])
        user_id = query.from_user.id

        # 1) Verify horse ownership
        try:
            owned_horse = await sync_to_async(OwnedHorse.objects.get)(
                user__id=user_id, horse_number=horse_number
            )
        except OwnedHorse.DoesNotExist:
            await query.edit_message_text("❌ You do not own that horse.\n\n↩️ Back")
            return

        # Build display_label = "Name (66)" if name exists, else "Horse 66"
        if owned_horse.name:
            display_label = f"{owned_horse.name} ({horse_number})"
        else:
            display_label = f"Horse {horse_number}"

        # 2) Check if any upgrade is already applied to this horse
        existing_count = await sync_to_async(
            lambda: HorseAppliedUpgrade.objects.filter(horse=owned_horse).count()
        )()
        if existing_count > 0:
            # Only one upgrade allowed per horse
            text = (
                f"⚠️ {display_label} already has an upgrade applied.\n"
                "You can only apply one upgrade per horse.\n\n↩️ Back"
            )
            keyboard = [[InlineKeyboardButton("↩️ Back", callback_data="menu:apply_spell")]]
            await query.edit_message_text(text, parse_mode="Markdown",
                                          reply_markup=InlineKeyboardMarkup(keyboard))
            return

        # 3) Fetch all spells the user has purchased
        player = await sync_to_async(Player.objects.get)(id=user_id)
        owned_spells = await sync_to_async(list)(
            PlayerUpgrade.objects.filter(player=player).select_related("upgrade")
        )
        if not owned_spells:
            text = f"🔧 You haven’t purchased any spells to apply to {display_label}.\n\n↩️ Back"
            keyboard = [[InlineKeyboardButton("↩️ Back", callback_data="menu:apply_spell")]]
            await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
            return

        # 4) Build a keyboard listing each owned spell
        keyboard = []
        for pu in owned_spells:
            up = pu.upgrade
            keyboard.append([InlineKeyboardButton(
                up.name,
                callback_data=f"menu:apply_choose_spell:{horse_number}:{up.id}"
            )])
        keyboard.append([InlineKeyboardButton("↩️ Back", callback_data="menu:apply_spell")])

        # Use display_label in the header
        await query.edit_message_text(
            f"✨ *Apply Spell → {display_label}*\n\n"
            "Choose which spell to apply (only one per horse):",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return










    #
    # ─── SUBMENU: “Apply Spell → Confirm” ───
    #
    if data.startswith("menu:apply_choose_spell:"):
        parts = data.split(":")
        horse_number = int(parts[2])
        upgrade_id = int(parts[3])
        user_id = query.from_user.id

        try:
            owned_horse = await sync_to_async(OwnedHorse.objects.get)(
                user__id=user_id, horse_number=horse_number
            )
        except OwnedHorse.DoesNotExist:
            await query.edit_message_text("❌ You do not own that horse.")
            return

        try:
            upgrade_obj = await sync_to_async(HorseUpgrade.objects.get)(id=upgrade_id)
        except HorseUpgrade.DoesNotExist:
            await query.edit_message_text("❌ That spell no longer exists.")
            return

        has_it = await sync_to_async(
            PlayerUpgrade.objects.filter(player__id=user_id, upgrade=upgrade_obj).exists
        )()
        if not has_it:
            await query.edit_message_text("❌ You haven’t purchased that spell.")
            return

        blocking_pair = {"Double Dash", "Risky Rocket"}
        if upgrade_obj.name in blocking_pair:
            other_name = "Risky Rocket" if upgrade_obj.name == "Double Dash" else "Double Dash"
            existing_names = await sync_to_async(
                lambda: list(
                    HorseAppliedUpgrade.objects.filter(horse=owned_horse)
                                               .values_list("upgrade__name", flat=True)
                )
            )()
            if other_name in existing_names:
                await query.edit_message_text(
                    f"❌ You cannot apply *{upgrade_obj.name}* because *{other_name}* is already on Horse {horse_number}.",
                    parse_mode="Markdown"
                )
                return

        already_applied = await sync_to_async(
            HorseAppliedUpgrade.objects.filter(
                owner__id=user_id,
                horse=owned_horse,
                upgrade=upgrade_obj
            ).exists
        )()
        if already_applied:
            await query.edit_message_text(
                f"⚠️ You already applied *{upgrade_obj.name}* to Horse {horse_number}.",
                parse_mode="Markdown"
            )
            return

        player_obj = await sync_to_async(Player.objects.get)(id=user_id)
        await sync_to_async(HorseAppliedUpgrade.objects.create)(
            owner=player_obj,
            horse=owned_horse,
            upgrade=upgrade_obj
        )
        await query.edit_message_text(
            f"✅ *{upgrade_obj.name}* has been applied to Horse {horse_number}!",
            parse_mode="Markdown"
        )
        return

       #
    # ─── SUBMENU: “Unapply Spell → Choose Horse” ───
    #
    from telegram.error import BadRequest

    if data.startswith("menu:unapply_choose_horse:"):
        horse_number = int(data.split(":")[2])
        user_id = query.from_user.id

        try:
            owned_horse = await sync_to_async(OwnedHorse.objects.get)(
                user__id=user_id, horse_number=horse_number
            )
        except OwnedHorse.DoesNotExist:
            await query.edit_message_text("❌ You do not own that horse.")
            return

        # Build display_label = "Name (66)" if name exists, else "Horse 66"
        if owned_horse.name:
            display_label = f"{owned_horse.name} ({horse_number})"
        else:
            display_label = f"Horse {horse_number}"

        # Fetch all applied upgrades on this horse
        applied_list = await sync_to_async(
            lambda: list(
                HorseAppliedUpgrade.objects
                    .filter(horse=owned_horse)
                    .select_related("upgrade")
            )
        )()

        if not applied_list:
            text = f"⚠️ {display_label} has no spells to remove.\n\n↩️ Back"
            keyboard = [[InlineKeyboardButton("↩️ Back", callback_data="menu:unapply_spell")]]
            try:
                await query.edit_message_text(
                    text,
                    parse_mode="Markdown",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
            except BadRequest as e:
                if "Message is not modified" not in str(e):
                    raise
            return

        # Build a list of “Spell Name” buttons for each applied upgrade
        lines = [f"❌ *Unapply Spell → {display_label}*",""]
        keyboard = []
        for ap in applied_list:
            up = ap.upgrade
            callback_str = f"menu:unapply_choose_spell:{horse_number}:{up.id}"
            lines.append(f"• *{up.name}* — {up.description}")
            keyboard.append([InlineKeyboardButton(up.name, callback_data=callback_str)])

        # Add a Back button at the bottom
        lines.append("\n↩️ Back")
        keyboard.append([InlineKeyboardButton("↩️ Back", callback_data="menu:unapply_spell")])

        await query.edit_message_text(
            "\n".join(lines),
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return










    #
    # ─── SUBMENU: “Unapply Spell → Confirm” ───
    #
    if data.startswith("menu:unapply_choose_spell:"):
        parts = data.split(":")
        horse_number = int(parts[2])
        upgrade_id = int(parts[3])
        user_id = query.from_user.id

        try:
            owned_horse = await sync_to_async(OwnedHorse.objects.get)(
                user__id=user_id, horse_number=horse_number
            )
        except OwnedHorse.DoesNotExist:
            await query.edit_message_text("❌ You do not own that horse.")
            return

        try:
            upgrade_obj = await sync_to_async(HorseUpgrade.objects.get)(id=upgrade_id)
        except HorseUpgrade.DoesNotExist:
            await query.edit_message_text("❌ That spell no longer exists.")
            return

        applied_qs = await sync_to_async(HorseAppliedUpgrade.objects.filter)(
            owner__id=user_id, horse=owned_horse, upgrade=upgrade_obj
        )
        if not await sync_to_async(applied_qs.exists)():
            await query.edit_message_text(
                f"❌ *{upgrade_obj.name}* is not applied to Horse {horse_number}.",
                parse_mode="Markdown"
            )
            return

        # 5) Delete the applied upgrade
        await sync_to_async(applied_qs.delete)()
        await query.edit_message_text(
            f"✅ Unapplied *{upgrade_obj.name}* from Horse {horse_number}.",
            parse_mode="Markdown"
        )
        return


    # ─── Fallback → show main menu ───
    context.user_data.pop("awaiting_buy_horse", None)
    context.user_data.pop("awaiting_set_emoji", None)
    await query.edit_message_text(
        "🏇 *Horse Racing Shop Menu* 🏇\n\n"
        "Choose an option below:",
        parse_mode="Markdown",
        reply_markup=build_main_menu_keyboard()
    )









































async def catch_gift_owned_recipient(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()
    horse_number = context.user_data.pop("awaiting_gift_owned", None)
    if horse_number is None:
        await update.message.reply_text("❌ No horse selected to gift. Aborting.")
        return

    # Re‐verify ownership (same as before) …
    try:
        owned_horse = await sync_to_async(OwnedHorse.objects.get)(
            user__id=user_id, horse_number=horse_number
        )
    except OwnedHorse.DoesNotExist:
        await update.message.reply_text("❌ You no longer own that horse. Aborting.")
        return

    # Deduct fee (same as before) …
    player = await sync_to_async(Player.objects.get)(id=user_id)
    fee = 10_000
    if player.chips < fee:
        await update.message.reply_text(f"❌ Not enough chips! You need {fee:,} to gift this horse.")
        return
    player.chips -= fee
    await sync_to_async(player.save)()

    # ─── NEW: Only accept numeric user ID ───
    try:
        recipient_id = int(text)
    except ValueError:
        # Not a valid integer
        await update.message.reply_text(
            "❌ That is not a valid numeric user ID. "
            "Please have the recipient send /myid to the bot and paste that number here."
        )
        # Refund
        player.chips += fee
        await sync_to_async(player.save)()
        return

    # Look up the Player by ID
    try:
        recipient_player = await sync_to_async(Player.objects.get)(id=recipient_id)
    except Player.DoesNotExist:
        await update.message.reply_text(
            f"❌ No player in our database has ID {recipient_id}. "
            "Make sure they ran /myid and gave you their correct number."
        )
        # Refund
        player.chips += fee
        await sync_to_async(player.save)()
        return

    # Transfer ownership
    owned_horse.user = recipient_player
    await sync_to_async(owned_horse.save)()

    # Notify both parties
    if owned_horse.name:
        display_label = f"{owned_horse.name} ({horse_number})"
    else:
        display_label = f"Horse {horse_number}"

    await update.message.reply_text(
        f"🎁 You gifted {display_label} to player‐ID {recipient_player.id}! (−{fee:,} chips)"
    )
    try:
        await context.bot.send_message(
            chat_id=recipient_player.id,
            text=f"🎁 You have received {display_label}! Enjoy your new horse."
        )
    except Exception:
        # Bot might not be able to DM if user hasn’t started it
        pass

    return



async def catch_buy_and_gift_number(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Called when the user chose “Buy & Gift Horse” and now replies with a <horse_number>.
    Deduct normal purchase cost, then prompt for the recipient.
    """
    user_id = update.effective_user.id
    text = update.message.text.strip()

    # Clear the “awaiting_buy_and_gift” flag
    if not context.user_data.get("awaiting_buy_and_gift"):
        return
    context.user_data.pop("awaiting_buy_and_gift", None)

    # 1) Validate numeric
    if not text.isdigit():
        await update.message.reply_text("❌ That’s not a valid horse number. Aborting.")
        return

    horse_number = int(text)
    # 2) Cannot buy reserved (1,2,3)
    if horse_number in (1, 2, 3):
        await update.message.reply_text(
            "❌ Horse 1, 2, and 3 are reserved. ↩️ Try again."
        )
        return

    # 3) Check if already owned
    exists_qs = await sync_to_async(OwnedHorse.objects.filter)(horse_number=horse_number)
    if await sync_to_async(exists_qs.exists)():
        await update.message.reply_text(
            f"❌ Horse {horse_number} is already owned. Use Gift Owned Horse instead."
        )
        return

    # 4) Compute purchase cost
    s = str(horse_number)
    if len(s) == 1:
        cost = 100_000
    elif len(s) == 2:
        cost = 120_000 if s[0] == s[1] else 80_000
    elif len(s) == 3:
        cost = 120_000 if (s[0] == s[1] == s[2]) else 60_000
    else:
        cost = 120_000 if all(ch == s[0] for ch in s) else 60_000

    # 5) Fetch player & check chips
    player = await sync_to_async(Player.objects.get)(id=user_id)
    if player.chips < cost:
        await update.message.reply_text(
            f"❌ Not enough chips! You need {cost:,} to buy Horse {horse_number}."
        )
        return

    # 6) Deduct chips, record in context, then ask for recipient
    player.chips -= cost
    await sync_to_async(player.save)()

    context.user_data["purchased_gift_horse"] = horse_number
    context.user_data["purchased_cost"] = cost

    keyboard = [[InlineKeyboardButton("↩️ Back", callback_data="menu:gift_horse")]]
    await update.message.reply_text(
        f"🎁 You bought Horse {horse_number} for {cost:,} chips.\n\n"
        "Now reply with the recipient’s Telegram @username or numeric user ID.",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return

async def catch_buy_and_gift_recipient(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()

    horse_number = context.user_data.pop("purchased_gift_horse", None)
    cost         = context.user_data.pop("purchased_cost", None)
    if horse_number is None or cost is None:
        await update.message.reply_text("❌ No purchase in progress to gift.")
        return

    # ─── NEW: Only accept numeric ID ───
    try:
        recipient_id = int(text)
    except ValueError:
        # Refund the purchase cost
        player = await sync_to_async(Player.objects.get)(id=user_id)
        player.chips += cost
        await sync_to_async(player.save)()
        await update.message.reply_text(
            "❌ That is not a valid numeric user ID. "
            "Please have the recipient run /myid and send that number. Purchase refunded."
        )
        return

    # 3) Look up that Player by ID
    try:
        recipient_player = await sync_to_async(Player.objects.get)(id=recipient_id)
    except Player.DoesNotExist:
        # Refund
        player = await sync_to_async(Player.objects.get)(id=user_id)
        player.chips += cost
        await sync_to_async(player.save)()
        await update.message.reply_text(
            f"❌ No player in our database has ID {recipient_id}. Purchase refunded."
        )
        return

    # 4) Create the new OwnedHorse under the recipient
    await sync_to_async(OwnedHorse.objects.create)(
        user=recipient_player,
        horse_number=horse_number,
        emoji=None,
        name=None
    )

    # 5) Notify buyer
    await update.message.reply_text(
        f"🎁 You bought Horse {horse_number} for {cost:,} chips and gifted it to player‐ID {recipient_player.id}!"
    )
    # Notify recipient if possible
    try:
        await context.bot.send_message(
            chat_id=recipient_player.id,
            text=f"🎁 You have received Horse {horse_number}! Enjoy!"
        )
    except Exception:
        pass

    return



async def myid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Reply with the sender’s numeric Telegram user ID.
    """
    user_id = update.effective_user.id
    await update.message.reply_text(f"Your numeric user ID is: {user_id}")

async def catch_all_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()

    # ─── 1) If we’re in “awaiting_list_horse” mode → the text is the sale price ───
    if context.user_data.get("awaiting_list_horse"):
        # Pop out the horse_number flag
        horse_number = context.user_data.pop("awaiting_list_horse")
        try:
            owned_horse = await sync_to_async(OwnedHorse.objects.get)(
                user__id=user_id, horse_number=horse_number
            )
        except OwnedHorse.DoesNotExist:
            await update.message.reply_text("❌ You no longer own that horse. Aborting.")
            return

        # Validate the price is a positive integer
        if not text.isdigit() or int(text) <= 0:
            await update.message.reply_text("❌ That is not a valid price. Aborting.")
            return

        price = int(text)

        # Create the HorseSale listing
        await sync_to_async(HorseSale.objects.create)(
            horse=owned_horse,
            price=price
        )

        # Confirmation message
        if owned_horse.name:
            display_label = f"{owned_horse.name} ({horse_number})"
        else:
            display_label = f"Horse {horse_number}"

        await update.message.reply_text(
            f"✅ {display_label} is now listed for sale at {price:,} chips.\n"
            f"Others can buy from “Buy Horse” or “Horses on Sale.”"
        )
        return

    # ─── 2) If we’re in “awaiting_buy_horse” mode → this is a normal purchase of an unowned horse ───
    if context.user_data.get("awaiting_buy_horse"):
        # [Your existing catch_buy_horse_number logic goes here, exactly as before…]
        return await catch_buy_horse_number(update, context)

    # ─── 3) If we’re in “awaiting_buy_and_gift” mode → …
    if context.user_data.get("awaiting_buy_and_gift"):
        return await catch_buy_and_gift_number(update, context)

    # ─── 4) If we’re in “purchased_gift_horse” mode → …
    if context.user_data.get("purchased_gift_horse"):
        return await catch_buy_and_gift_recipient(update, context)

    # ─── 5) If we’re in “awaiting_set_emoji” mode → …
    if context.user_data.get("awaiting_set_emoji"):
        return await catch_set_emoji(update, context)

    # ─── 6) If we’re in “awaiting_rename_horse” mode → …
    if context.user_data.get("awaiting_rename_horse"):
        return await catch_rename_horse(update, context)

    # ─── 7) If we’re in “awaiting_gift_owned” mode → …
    if context.user_data.get("awaiting_gift_owned"):
        return await catch_gift_owned_recipient(update, context)

    # ─── 8) If we’re in “purchased_gift_horse” mode → …
    if context.user_data.get("purchased_gift_horse"):
        return await catch_buy_and_gift_recipient(update, context)

    # ─── otherwise: ignore or send a default message if you like ───
    return



async def catch_buy_horse_number(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get("awaiting_set_emoji"):
        return await catch_set_emoji(update, context)

    # Only run if they clicked “Buy Horse” and we’re waiting for a number
    if not context.user_data.get("awaiting_buy_horse"):
        return

    user_id = update.effective_user.id
    text = update.message.text.strip()
    # Clear the “awaiting_buy_horse” flag immediately
    context.user_data.pop("awaiting_buy_horse", None)

    # 1) Validate it's numeric
    if not text.isdigit():
        await update.message.reply_text(
            "❌ That’s not a valid horse number. Aborting. ↩️ Run /horse again."
        )
        return

    horse_number = int(text)

    # 2) Reserve 1, 2, 3
    if horse_number in (1, 2, 3):
        await update.message.reply_text(
            "❌ Horse 1, 2, and 3 are reserved and cannot be purchased. ↩️ Run /horse again to pick a different number."
        )
        return

    # 3) Check if already owned (any existing record for this number)
    exists = await sync_to_async(OwnedHorse.objects.filter)(horse_number=horse_number)
    if await sync_to_async(exists.exists)():
        await update.message.reply_text("❌ That horse number is already owned. ↩️ /horse")
        return

    # 4) Determine cost according to your rules
    s = str(horse_number)
    if len(s) == 1:
        cost = 100_000
    elif len(s) == 2:
        cost = 120_000 if s[0] == s[1] else 80_000
    elif len(s) == 3:
        cost = 120_000 if (s[0] == s[1] == s[2]) else 60_000
    else:
        cost = 120_000 if all(ch == s[0] for ch in s) else 60_000

    # 5) Fetch player
    try:
        player = await sync_to_async(Player.objects.get)(id=user_id)
    except Player.DoesNotExist:
        await update.message.reply_text("❌ You’re not registered. ↩️ /horse")
        return

    # 6) Check if they have enough chips
    if player.chips < cost:
        await update.message.reply_text(
            f"❌ You need {cost} chips to buy Horse {horse_number}, but you have {player.chips}. ↩️ /horse"
        )
        return

    # 7) Deduct chips and create the OwnedHorse record
    player.chips -= cost
    await sync_to_async(player.save)()
    await sync_to_async(OwnedHorse.objects.create)(
        user=player,
        horse_number=horse_number,
        emoji=None
    )

    await update.message.reply_text(
        f"✅ You now own Horse {horse_number}! (−{cost} chips) ↩️ Run /horse again."
    )

async def catch_set_emoji(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Only run if we previously put “awaiting_set_emoji” into user_data
    print("DEBUG: in catch_set_emoji; flag =", context.user_data.get("awaiting_set_emoji"))
    if "awaiting_set_emoji" not in context.user_data:
        return

    user_id = update.effective_user.id
    horse_number = context.user_data.pop("awaiting_set_emoji")  # pop so we don't stay in this mode
    new_emoji = update.message.text.strip()
    EMOJI_COST = 9000

    # 1) Validate they sent something
    if not new_emoji:
        await update.message.reply_text(
            "❌ That’s not a valid emoji. Aborting. ↩️ Run /horse again."
        )
        return

    # 2) Fetch Player and OwnedHorse
    try:
        player = await sync_to_async(Player.objects.get)(id=user_id)
    except Player.DoesNotExist:
        await update.message.reply_text("❌ You’re not registered. ↩️ Run /horse again.")
        return

    try:
        horse = await sync_to_async(OwnedHorse.objects.get)(
            user__id=user_id, horse_number=horse_number
        )
    except OwnedHorse.DoesNotExist:
        await update.message.reply_text(
            "❌ You do not own that horse. ↩️ Run /horse again."
        )
        return

    # 3) Check chips
    if player.chips < EMOJI_COST:
        await update.message.reply_text(
            f"❌ Not enough chips! Changing an emoji costs {EMOJI_COST}. ↩️ Run /horse again."
        )
        return

    # 4) Deduct and save
    player.chips -= EMOJI_COST
    await sync_to_async(player.save)()

    horse.emoji = new_emoji
    await sync_to_async(horse.save)()

    # 5) Confirm
    await update.message.reply_text(
        f"✅ Emoji for Horse {horse_number} updated to {new_emoji}! (−{EMOJI_COST} chips)\n"
        "↩️ Run /horse again."
    )


async def catch_rename_horse(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # We know here that awaiting_rename_horse is set.
    # Pop it immediately so we don’t handle the same text again.
    horse_number = context.user_data.pop("awaiting_rename_horse")

    user_id = update.effective_user.id
    new_name = update.message.text.strip()

    # 1) Fetch the OwnedHorse to confirm ownership
    try:
        owned_horse = await sync_to_async(OwnedHorse.objects.get)(
            user__id=user_id, horse_number=horse_number
        )
    except OwnedHorse.DoesNotExist:
        await update.message.reply_text("❌ You do not own that horse anymore.")
        return

    # 2) Fetch Player to check chips
    player = await sync_to_async(Player.objects.get)(id=user_id)
    cost = 60_000
    if player.chips < cost:
        await update.message.reply_text(f"❌ Not enough chips! Renaming costs {cost:,} chips.")
        return

    # 3) Deduct chips and save new name
    player.chips -= cost
    await sync_to_async(player.save)()

    owned_horse.name = new_name
    await sync_to_async(owned_horse.save)()

    await update.message.reply_text(
        f"✅ Your horse #{horse_number} is now named “{new_name}”! (−{cost:,} chips)"
    )
async def richest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # 1) Fetch top 5 players ordered by chips descending
    top_players = await sync_to_async(list)(
        Player.objects.order_by("-chips")[:5]
    )
    if not top_players:
        await update.message.reply_text("ℹ️ No players found in the database yet.")
        return

    # 2) Build a praise‐filled message
    lines = ["🏆 *Top 5 Richest Players* 🏆\n"]
    medals = ["🥇", "🥈", "🥉", "🏅", "🏅"]  # first three special, others identical

    for idx, player in enumerate(top_players, start=1):
        medal = medals[idx - 1]
        name = player.name or f"User {player.id}"
        chips = f"{player.chips:,}"
        lines.append(f"{medal} *{name}* — {chips} chips")

    lines.append("\n🎉 Congratulations to our Unemployed Friends! 🎉")
    text = "\n".join(lines)

    # 3) Send with Markdown formatting
    await update.message.reply_text(text, parse_mode="Markdown")

DEBUG = os.getenv("DEBUG")
if DEBUG == "True":
    app = ApplicationBuilder().token("7094966045:AAEbis5HH6W20Gg1vvziCmc0f9imO2FQ47Q").concurrent_updates(True).build()
elif DEBUG == "False":
    app = ApplicationBuilder().token("7041648826:AAFMkq1-fX740ZTT3OVbPowzbzJooMCi118").concurrent_updates(True).build()
    


app.add_handler(CommandHandler("start", start))
app.add_handler(CallbackQueryHandler(handle_menu_callback))
app.add_handler(
    CallbackQueryHandler(
        handle_items_callback,
        pattern=r"^(menu:items|items:)"     # any callback_data exactly "menu:items" or starting with "items:"
    )
)

# real token 7041648826:AAFMkq1-fX740ZTT3OVbPowzbzJooMCi118
# test token 7094966045:AAEbis5HH6W20Gg1vvziCmc0f9imO2FQ47Q
app.add_handler(CommandHandler("double", double_or_nothing))
app.add_handler(CommandHandler("crash", crash))
app.add_handler(CommandHandler("cashout", cashout))
app.add_handler(CommandHandler("richest", richest))

app.add_handler(CommandHandler("horse", horse))
app.add_handler(
    CallbackQueryHandler(horse_menu_callback, pattern=r"^menu:")
)
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
app.add_handler(CommandHandler("shop", shop))
app.add_handler(CommandHandler("buyhorse", buyhorse))
app.add_handler(CommandHandler("setemoji", setemoji))
app.add_handler(CommandHandler("myhorses", myhorses))
app.add_handler(CommandHandler("shopspells", shopupgrades))
app.add_handler(CommandHandler("buyspell", buyupgrade))
app.add_handler(CommandHandler("applyspell", applyupgrade))
app.add_handler(CommandHandler("unapplyspell", unapplyupgrade))

app.add_handler(CommandHandler("admin", admin_help))
app.add_handler(CommandHandler("listgroups", list_groups))
app.add_handler(CommandHandler("broadcastgroup", broadcastgroups))

app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, on_new_chat_members))
app.add_handler(CommandHandler("roulette", roulette))
app.add_handler(CommandHandler("sync_groups", sync_group_names))

app.add_handler(CommandHandler("spin", spin))
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
app.add_handler(CommandHandler("dart", claim_tokens))
app.add_handler(CommandHandler("daily_token", claim_daily_tokens))
app.add_handler(CommandHandler("leaderboard", leaderboard))
app.add_handler(CommandHandler("group", group))

app.add_handler(CommandHandler("spinrewards", spinrewards))

app.add_handler(photo_handler)
app.add_handler(CommandHandler("user_id", get_user_id_command))
app.add_handler(CommandHandler("give_token", give_token))
# app.add_handler(CommandHandler("buy_tokens", buy_tokens))
# app.add_handler(CommandHandler("set_status", set_status))
app.add_handler(CommandHandler("help", help_command))
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

app.run_polling()


