import random
from datetime import (
    datetime,
    timedelta,
)

from game.services.shop import ITEMS as SHOP_ITEMS
from game.telegram.shop import render_bag, render_home as render_shop_home
from asgiref.sync import (
    sync_to_async,
)
from django.core.exceptions import (
    ObjectDoesNotExist,
)
from django.db.models import (
    Avg,
    Count,
    F,
    Sum,
)
from django.utils import (
    timezone,
)
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
)
from telegram.error import (
    BadRequest,
)
from telegram.ext import (
    ContextTypes,
)
from telegram.helpers import (
    escape_markdown,
)

from bot_sections.blackjack_game import (
    help_command,
)
from bot_sections.core_and_menus import (
    build_back_to_profile_button,
    build_bj_boosters_menu,
    build_bj_potions_menu,
    build_bj_special_passes_menu,
    build_blackjack_items_menu,
    build_daily_quests_menu,
    build_items_activate_menu,
    build_items_deactivate_menu,
    build_items_menu,
    build_leaderboards_menu,
    build_main_menu,
    build_mystery_box_menu,
    build_notification_settings_menu,
    build_profile_menu,
    build_quests_menu,
    build_quests_menu_daily,
    build_settings_menu,
    build_shop_menu,
    build_special_passes_menu,
    build_support_menu,
    build_tournaments_menu,
)
from bot_sections.horse_racing_and_social import (
    dispatch_horse_menu,
)
from bot_sections.players_and_progression import (
    normalize_player_level_xp,
    xp_for_next_level,
)
from bot_sections.routing import CallbackRouter
from game.economy_config import (
    MYSTERY_BOX_COOLDOWN_SECONDS,
)
from game.i18n import translate
from game.models import (
    ITEM_TYPE_CHOICES,
    Achievement,
    ChipTransaction,
    DailyQuest,
    Game,
    GameParameter,
    HorseBet,
    HorseRaceWin,
    OwnedHorse,
    Player,
    PlayerAchievement,
    PlayerActiveItem,
    PlayerDailyQuestProgress,
    PlayerItem,
    QuestHistory,
    ReferralEarning,
    Stats,
    UserSettings,
    generate_referral_code,
)
from game.services.blackjack import (
    InsufficientChips,
)
from game.services.economy import (
    adjust_balance_async,
    purchase_item_async,
)
from game.services.items import (
    ItemCategoryAlreadyActive,
    ItemUnavailable,
    activate_inventory_item_async,
    consume_xp_booster_async,
)
from game.services.language import language_for_update
from game.services.mystery import (
    open_mystery_box_async,
)
from game.services.rewards import (
    RewardAlreadyClaimed,
    claim_daily_box_async,
    claim_daily_chips_async,
    claim_daily_xp_async,
)
from game.telegram.player_experience import (
    play_home_keyboard,
)
from lang import (
    t,
)


async def purchase_item(player: Player, item_type: str):
    cost = ITEM_COSTS.get(item_type)
    if cost is None:
        return False, "Invalid item."

    try:
        await purchase_item_async(player.id, item_type, cost)
    except InsufficientChips:
        return False, "You don’t have enough chips."

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

ITEMS_ROUTES = CallbackRouter()


@ITEMS_ROUTES.on('menu:boosters')
async def _items_boosters(update, context, query, data, player):
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
@ITEMS_ROUTES.on('menu:items')
async def _items_items(update, context, query, data, player):
    text, markup = await sync_to_async(render_bag, thread_sensitive=True)(player)
    await query.edit_message_text(text=text, parse_mode="HTML", reply_markup=markup)
    return


# ── (B) “Activate” submenu ───────────────────────────────────────────────────
@ITEMS_ROUTES.on('items:activate')
async def _items_activate(update, context, query, data, player):
    await query.edit_message_text(
        text="▶️ *Activate Item* ▶️\n\nChoose a category:",
        parse_mode="Markdown",
        reply_markup=build_items_activate_menu()
    )
    return


# ── (C.1) “Activate → Potions” ──────────────────────────────────────────────
@ITEMS_ROUTES.on('items:activate_potions')
async def _items_activate_potions(update, context, query, data, player):
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
@ITEMS_ROUTES.on('items:activate_passes')
async def _items_activate_passes(update, context, query, data, player):
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
@ITEMS_ROUTES.on_prefix('items:use_booster:')
async def _items_use_booster(update, context, query, data, player):
    _, _, item_type = data.split(":", 2)

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

    xp_amount = {
        "xp_booster_500": 500,
        "xp_booster_2000": 2000,
        "xp_booster_15000": 15000,
        "xp_booster_50000": 50000,
    }.get(item_type, 0)
    try:
        result = await consume_xp_booster_async(player.id, item_type, xp_amount)
    except ItemUnavailable:
        await query.answer("That booster is no longer available.", show_alert=True)
        return
    for level, chips_reward in result.level_rewards:
        await context.bot.send_message(
            chat_id=player.id,
            text=f"🎉 Congratulations! You've reached level {level}! You've been rewarded with {chips_reward} 💰 chips!",
        )
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
@ITEMS_ROUTES.on_prefix('items:activate:')
async def _items_activate_item(update, context, query, data, player):
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
    print("➡️ Checking for ongoing forced game...")

    chat_id = str(query.message.chat_id)
    print("🔍 Chat ID being used for query:", chat_id)

    ongoing_forced_game = await sync_to_async(Game.objects.filter)(
        chat_id=chat_id,
        forced=True,
        ended=False
    )

    # Check how many matching games there are
    matching_games_list = await sync_to_async(list)(ongoing_forced_game)
    print(f"📊 Found {len(matching_games_list)} matching forced, not-ended game(s):", matching_games_list)

    ongoing_exists = await sync_to_async(ongoing_forced_game.exists)()
    print("✅ Exists check result:", ongoing_exists)

    if ongoing_exists:
        await query.edit_message_text(
            text="⚠️ You can't activate items during an ongoing game.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Back to Activate Menu", callback_data="items:activate")]
            ])
        )
        return
    else:
        print("✅ No forced game blocking activation.")

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

    # ---- No other active item in this category → activate it atomically ----
    try:
        await activate_inventory_item_async(player.id, item_type, category_list)
    except ItemUnavailable:
        await query.answer("That item is no longer available.", show_alert=True)
        return
    except ItemCategoryAlreadyActive:
        await query.answer("Another item in this category is already active.", show_alert=True)
        return

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
@ITEMS_ROUTES.on('items:deactivate')
async def _items_deactivate(update, context, query, data, player):
    await query.edit_message_text(
        text="⏸️ *Deactivate Item* ⏸️\n\nChoose a category:",
        parse_mode="Markdown",
        reply_markup=build_items_deactivate_menu()
    )
    return


# ── (D.1) “Deactivate → Potions” ───────────────────────────────────────────────
@ITEMS_ROUTES.on('items:deactivate_potions')
async def _items_deactivate_potions(update, context, query, data, player):
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
@ITEMS_ROUTES.on('items:deactivate_passes')
async def _items_deactivate_passes(update, context, query, data, player):
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
@ITEMS_ROUTES.on_prefix('items:deactivate:')
async def _items_deactivate_item(update, context, query, data, player):
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


async def handle_items_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle callback_data "menu:items", "menu:boosters" and "items:*".
    handle_menu_callback answers the query afterwards.
    For BOOSTERS, we now 'use' them (granting XP) rather than leaving them 'active.'
    The UI text has been adjusted so that Boosters show up under "Activate Boosters" but 
    their buttons read "Use <Booster Name>."
    """
    query = update.callback_query
    data = query.data
    user_id = query.from_user.id

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
    handler = ITEMS_ROUTES.resolve(data)
    if handler is not None:
        return await handler(update, context, query, data, player)
    

    # ── (FALL‐THROUGH) ────────────────────────────────────────────────────────────
    await query.edit_message_text(
        text="⚠️ Something went wrong. Returning to Main Menu.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Home", callback_data="hub:home")]])
    )
    return



# Prices follow the Season shop catalog; the 15k/50k boosters are legacy-only.
ITEM_COSTS = {
    **{key: item.price for key, item in SHOP_ITEMS.items() if not item.hours and not item.title},
    "xp_booster_15000": 60_000,
    "xp_booster_50000": 180_000,
}

MYSTERY_BOXES = {
    "shop:mystery_bronze": {
        "name": "🎁 Bronze Mystery Box",
        "cost": 1_000,
        "chip_range": (50, 500),
        "xp_range": (10, 100),
        "rare_items": [
            ("double_chip_potion", 0.033),
        ]
    },
    "shop:mystery_silver": {
        "name": "🎁 Silver Mystery Box",
        "cost": 2_500,
        "chip_range": (200, 1_250),
        "xp_range": (10, 50),
        "rare_items": [
            ("triple_chip_potion", 0.031),
            ("xp_booster_500",     0.025),
        ]
    },
    "shop:mystery_gold": {
        "name": "🎁 Gold Mystery Box",
        "cost": 10_000,
        "chip_range": (1_000, 5_000),
        "xp_range": (10, 100),
        "rare_items": [
            ("10x_chip_potion",    0.025),
            ("xp_booster_50000",   0.001),
        ]
    },
    "shop:mystery_platinum": {
        "name": "💎 Platinum Mystery Box",
        "cost": 25_000,
        "chip_range": (2_500, 12_500),
        "xp_range": (80, 250),
        "rare_items": [
            ("xp_booster_2000",    0.063),
            ("xp_booster_15000",   0.009),
        ]
    },
    "shop:mystery_diamond": {
        "name": "🔷 Diamond Mystery Box",
        "cost": 50_000,
        "chip_range": (5_000, 25_000),
        "xp_range": (160, 300),
        "rare_items": [
            ("xp_booster_15000",   0.018),
            ("xp_booster_50000",   0.006),
        ]
    },
    "shop:mystery_legendary": {
        "name": "🌟 Legendary Mystery Box",
        "cost": 100_000,
        "chip_range": (10_000, 50_000),
        "xp_range": (220, 500),
        "rare_items": [
            ("10x_chip_potion",    0.05),
            ("xp_booster_50000",   0.011),
        ]
    },
    "shop:mystery_mythic": {
        "name": "🌀 Mythic Mystery Box",
        "cost": 1_000_000,
        "chip_range": (100_000, 500_000),
        "xp_range": (440, 5_000),
        "rare_items": [
            ("xp_booster_15000",   0.05),
            ("xp_booster_50000",   0.02),
        ]
    },
    "shop:mystery_cosmic": {
        "name": "🌌 Cosmic Mystery Box",
        "cost": 1_000_000_000,
        "chip_range": (10_000_000, 500_000_000),
        "xp_range": (6_280, 50_000),
        "rare_items": [
            ("xp_booster_500",     0.10),
            ("xp_booster_2000",    0.05),
            ("xp_booster_15000",   0.01),
        ]
    },
}









COOLDOWN_SECONDS = MYSTERY_BOX_COOLDOWN_SECONDS


async def countdown_cooldown(context: ContextTypes.DEFAULT_TYPE):
    job_data = context.job.data
    now = datetime.utcnow()
    remaining = int((job_data["expires_at"] - now).total_seconds())

    if remaining > 0:
        try:
            await context.bot.edit_message_text(
                chat_id=job_data["chat_id"],
                message_id=job_data["message_id"],
                text=f"⌛️ Mystery Box cooldown: {remaining}s",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 Back to Mystery Boxes", callback_data="shop:mystery_box")]
                ])
            )
        except BadRequest as e:
            if "Message is not modified" not in str(e):
                raise
    else:
        try:
            await context.bot.edit_message_text(
                chat_id=job_data["chat_id"],
                message_id=job_data["message_id"],
                text="✅ You can open this Mystery Box again!",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔁 Open Another", callback_data=job_data["callback_data"])]
                ])
            )
        except BadRequest as e:
            if "Message is not modified" not in str(e):
                raise

        # clear the cooldown flag and stop the job
        context.application.user_data[job_data["user_id"]].pop("mystery_cooldown", None)
        context.job.schedule_removal()


async def handle_mystery_box_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    data = query.data  # e.g. "shop:mystery_gold"
    now = datetime.utcnow()

    box = MYSTERY_BOXES.get(data)
    if not box:
        await query.answer("Unknown mystery box!", show_alert=True)
        return True

    # 1) Cooldown check
    expires_at = context.user_data.get("mystery_cooldown")
    if expires_at and now < expires_at:
        remaining = int((expires_at - now).total_seconds())
        msg = await query.edit_message_text(
            text=f"⌛️ Mystery Boxes cooldown: {remaining}s",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Back to Mystery Boxes", callback_data="shop:mystery_box")]
            ])
        )

        # schedule timer updates every 10s, including the exact box key
        context.job_queue.run_repeating(
            countdown_cooldown,
            interval=10,
            first=10,
            data={
                "chat_id":       msg.chat_id,
                "message_id":    msg.message_id,
                "expires_at":    expires_at,
                "user_id":       user_id,
                "callback_data": data,
            }
        )
        return True

    # 2) Not on cooldown → open the box
    reward_type = random.choices(
        ["chips", "xp", "item"],
        weights=[20, 65, 15],
        k=1
    )[0]

    if reward_type == "chips":
        reward_value = random.randint(*box["chip_range"])
    elif reward_type == "xp":
        reward_value = random.randint(*box["xp_range"])
    else:
        reward_value = None
        pool = box["rare_items"].copy()
        random.shuffle(pool)
        for item_type, chance in pool:
            if random.random() <= chance:
                reward_value = item_type
                break

    try:
        result = await open_mystery_box_async(
            user_id,
            data,
            box["cost"],
            reward_type,
            reward_value,
            query.id,
        )
    except InsufficientChips:
        player = await sync_to_async(Player.objects.get)(id=user_id)
        await query.edit_message_text(
            text=(
                f"❗️ You don’t have enough chips to open {box['name']}.\n"
                f"Required: {box['cost']} 💰  You have: {player.chips} 💰"
            ),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Back to Mystery Boxes", callback_data="shop:mystery_box")]
            ])
        )
        return True

    if result.reward_type == "chips":
        reward_text = f"💰 Chips: +{result.chips}"
    elif result.reward_type == "xp":
        reward_text = f"✨ XP: +{result.xp}"
        for level, chips_reward in result.level_rewards:
            await context.bot.send_message(
                chat_id=user_id,
                text=(
                    f"🎉 Congratulations! You've reached level {level}! "
                    f"You've been rewarded with {chips_reward} 💰 chips!"
                ),
            )
    elif result.item_type:
        human_name = dict(ITEM_TYPE_CHOICES).get(result.item_type, result.item_type)
        reward_text = f"🎁 Bonus Item: {human_name}"
    else:
        reward_text = "🎁 Bonus Item: nothing this time… 😢"

    # 3) Set new cooldown expiry
    context.user_data["mystery_cooldown"] = now + timedelta(seconds=COOLDOWN_SECONDS)

    # 4) Show the result with “Open Another” for this same box
    await query.edit_message_text(
        text=f"{box['name']} opened! 🎉\n{reward_text}",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔁 Open Another", callback_data=data)],
            [InlineKeyboardButton("🔙 Back to Mystery Boxes", callback_data="shop:mystery_box")]
        ])
    )
    return True













# This assumes you have: Player, PlayerItem, ITEM_TYPE_CHOICES, add_xp
# async def handle_mystery_box_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
#     query = update.callback_query
#     user_id = query.from_user.id
#     data = query.data

#     box = MYSTERY_BOXES.get(data)
#     if not box:
#         await query.answer("Unknown mystery box!", show_alert=True)
#         return

#     player = await sync_to_async(Player.objects.get)(id=user_id)

#     # Not enough chips
#     if player.chips < box["cost"]:
#         await query.edit_message_text(
#             text=f"❗️ You don’t have enough chips to open the {box['name']}.\n\n"
#                  f"Required: {box['cost']} 💰\nYour balance: {player.chips} 💰",
#             reply_markup=InlineKeyboardMarkup([
#                 [InlineKeyboardButton("🔙 Back to Mystery Boxes", callback_data="shop:mystery_box")],
#             ])
#         )
#         return

#     # Deduct cost
#     player.chips -= box["cost"]

#     # Roll chips and XP
#     reward_type = random.choices(
#         ["chips", "xp", "item"],
#         weights=[30, 80, 50],
#         k=1
#     )[0]
#     reward_result = ""
#     awarded_items = []

#     if reward_type == "chips":
#         chips_reward = random.randint(*box["chip_range"])
#         player.chips += chips_reward
#         reward_result = f"💰 Chips: +{chips_reward}"

#     elif reward_type == "xp":
#         xp_reward = random.randint(*box["xp_range"])
#         reward_result = f"✨ XP: +{xp_reward}"
#         await add_xp(player, xp_reward, context)

#     elif reward_type == "item":
#         rare_pool = box["rare_items"]
#         random.shuffle(rare_pool)
#         for item_type, chance in rare_pool:
#             if random.random() <= chance:
#                 item_obj, _ = await sync_to_async(PlayerItem.objects.get_or_create)(
#                     player=player, item_type=item_type, defaults={"quantity": 0}
#                 )
#                 item_obj.quantity += 1
#                 await sync_to_async(item_obj.save)()
#                 human_name = dict(ITEM_TYPE_CHOICES).get(item_type, item_type)
#                 reward_result = f"🎁 Bonus Item: {human_name}"
#                 awarded_items.append(human_name)
#                 break
#         if not awarded_items:
#             reward_result = "🎁 Bonus Item: nothing this time… 😢"


#     await sync_to_async(player.save)()

#     # Build result message
#     lines = [
#         f"{box['name']} opened! 🎉",
#         reward_result,
#     ]


#     reply_markup = InlineKeyboardMarkup([
#         [InlineKeyboardButton("🔁 Open Another", callback_data=data)],
#         [InlineKeyboardButton("🔙 Back to Mystery Boxes", callback_data="shop:mystery_box")],
#     ])

#     try:
#         await query.edit_message_text(
#             text="\n".join(lines),
#             parse_mode="Markdown",
#             reply_markup=reply_markup
#         )
#     except BadRequest as e:
#         if "Message is not modified" in str(e):
#             # Ignore silently or send a subtle poke if you want
#             pass
#         else:
#             raise

SHOP_ROUTES = CallbackRouter()


# ── (A) Main Shop menu ────────────────────────────────────────────────────
@SHOP_ROUTES.on('menu:shop')
async def _shop_shop(update, context, query, data, player):
    text, markup = await sync_to_async(render_shop_home, thread_sensitive=True)(player)
    await query.edit_message_text(text=text, parse_mode="HTML", reply_markup=markup)
    return True


# ── (B) Blackjack Items submenu ────────────────────────────────────────────
@SHOP_ROUTES.on('shop:blackjack_items')
async def _shop_blackjack_items(update, context, query, data, player):
    await query.edit_message_text(
        text="🧪 *Blackjack Items* 🧪\n\nSelect a subcategory:",
        parse_mode="Markdown",
        reply_markup=build_blackjack_items_menu()
    )
    return True


# ── (B.1) Potions submenu ─────────────────────────────────────────────────
@SHOP_ROUTES.on('shop:bj_potions')
async def _shop_bj_potions(update, context, query, data, player):
    text = (
        "✨ *Blackjack Potions* ✨\n\n"
            "• *Double Chip Potion* — Double chips won on your next hand. (Cost: 30,000 chips)\n"
            "• *Triple Chip Potion* — Triple chips won on your next hand. (Cost: 80,000 chips)\n"
            "• *10× Chip Potion* — 10× chips won on your next hand. (Cost: 400,000 chips)\n\n"
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
@SHOP_ROUTES.on_prefix('shop:double_xp_potion', 'shop:triple_xp_potion', 'shop:10x_xp_potion', 'shop:double_chip_potion', 'shop:triple_chip_potion', 'shop:10x_chip_potion')
async def _shop_double_xp_potion(update, context, query, data, player):
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
    ongoing_forced_game = await sync_to_async(Game.objects.filter)(
        chat_id=str(query.message.chat_id),
        forced=True,
        ended=False
    )
    ongoing_forced_game_exists = await sync_to_async(ongoing_forced_game.exists)()
    if ongoing_forced_game_exists:
        await query.edit_message_text(
            text="⚠️ You can't Buy items during an ongoing game.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Back to Shop", callback_data="menu:shop")]
            ])
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
@SHOP_ROUTES.on('shop:bj_boosters')
async def _shop_bj_boosters(update, context, query, data, player):
    text = (
        "📈 *Blackjack Boosters* 📈\n\n"
            "• *+500 XP Booster* — 500 XP for 100,000 chips.\n"
            "• *+2,000 XP Booster* — 2,000 XP for 400,000 chips.\n"
            "• *+15,000 XP Booster* — 15,000 XP for 2,800,000 chips.\n"
            "• *+50,000 XP Booster* — 50,000 XP for 9,000,000 chips.\n\n"
            "Tap a booster below to purchase it."
    )
    await query.edit_message_text(
        text=text,
        parse_mode="Markdown",
        reply_markup=build_bj_boosters_menu()
    )
    return True


# ── (B.2.1) Purchase a specific Booster ───────────────────────────────────────
@SHOP_ROUTES.on_prefix('shop:xp_booster_500', 'shop:xp_booster_2000', 'shop:xp_booster_15000', 'shop:xp_booster_50000')
async def _shop_xp_booster_500(update, context, query, data, player):
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
@SHOP_ROUTES.on('shop:bj_special_passes')
async def _shop_bj_special_passes(update, context, query, data, player):
    text = (
        "🛡️ *Blackjack Special Passes* 🛡️\n\n"
            "• *Insurance Pass* — Discard a bad hit and draw again. (Cost: 5,000 chips)\n"
            "• *First-Hand-20 Pass* — Start with a 20 on your first hand. (Cost: 12,000 chips)\n\n"
            "• *First-Hand-11 Pass* — Start with a 1 on your first hand. (Cost: 8,000 chips)\n\n"
            "Tap a pass below to purchase it."
    )
    await query.edit_message_text(
        text=text,
        parse_mode="Markdown",
        reply_markup=build_bj_special_passes_menu()
    )
    return True


    # ── (B.3.1) Purchase a specific Special Pass ──────────────────────────────────
@SHOP_ROUTES.on_prefix('shop:insurance_pass', 'shop:first_hand_20_pass', 'shop:first_hand_11_potion')
async def _shop_insurance_pass(update, context, query, data, player):
    print("ASfdasdfsafd")
    try:
        item_key = data.split("shop:")[1]
        print("Item key:", item_key)

        if item_key not in ITEM_COSTS:
            print("Item not in ITEM_COSTS")
            return True

        if player is None:
            await query.answer(
                "❗️ You don’t have a player profile yet. Send /start in private to create one.",
                show_alert=True
            )
            return True

        if item_key == "insurance_pass":
            print("here")
            ongoing_forced_game = await sync_to_async(Game.objects.filter)(
                chat_id=str(query.message.chat_id),
                forced=True,
                ended=False
            )
            ongoing_forced_game_exists = await sync_to_async(ongoing_forced_game.exists)()
            if ongoing_forced_game_exists:
                await query.edit_message_text(
                    text= "⚠️ You can't buy an Insurance Pass while a game is still in progress.",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🔙 Back to Shop", callback_data="menu:shop")]
                    ])
                )
                return True

        success, msg = await purchase_item(player, item_key)
        print("Success:", success, "| Message:", msg)

        if not success:
            await query.answer(msg, show_alert=True)
            return True

        human_name = dict(ITEM_TYPE_CHOICES)[item_key]
        cost = ITEM_COSTS[item_key]
        text = f"✅ You purchased 1× {human_name} for {cost:,} chips!"

        keyboard = [
            [InlineKeyboardButton("🔙 Back to Passes", callback_data="shop:bj_special_passes")],
            [InlineKeyboardButton("🔙 Back to Shop", callback_data="menu:shop")],
        ]
        await query.edit_message_text(
            text=text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
        return True
    except Exception as e:
        print("❌ Exception occurred:", e)
        await query.answer("Something went wrong.", show_alert=True)
        return True


# ── (C) Mystery Box submenu ─────────────────────────────────────────────────
@SHOP_ROUTES.on('shop:mystery_box')
async def _shop_mystery_box(update, context, query, data, player):
    text = (
        "*🎁 Mystery Boxes Shop* 🎁\n\n"
            "Each box contains random chips, XP, and possibly rare items.\n\n"
            "*Available Boxes:*\n"
            "🎁 *Bronze* — 1,000 💰\n"
            "🎁 *Silver* — 2,500 💰\n"
            "🎁 *Gold* — 5,000 💰\n"
            "💎 *Platinum* — 25,000 💰\n"
            "🔷 *Diamond* — 50,000 💰\n"
            "🌟 *Legendary* — 100,000 💰\n"
            "🌀 *Mythic* — 1,000,000 💰\n"
            "🌌 *Cosmic* — 1,000,000,000 💰\n\n"
            "_Tap a box to open it if you have enough chips!_"
    )

    await query.edit_message_text(
        text=text,
        parse_mode="Markdown",
        reply_markup=build_mystery_box_menu()
    )
    return True


# ── (C.1) Open Mystery Box (stub) ───────────────────────────────────────────
@SHOP_ROUTES.on('shop:mystery_bronze', 'shop:mystery_silver', 'shop:mystery_gold', 'shop:mystery_platinum', 'shop:mystery_diamond', 'shop:mystery_legendary', 'shop:mystery_mythic', 'shop:mystery_cosmic')
async def _shop_mystery_bronze(update, context, query, data, player):
    box_name = data.split("shop:")[1].replace("_", " ").title()
    await query.answer(
        f"You tapped to open: {box_name}",
        show_alert=True
    )
    return True


# ── (D) Shop “Special Passes” if you have a separate menu entry ──────────────
@SHOP_ROUTES.on('shop:special_passes')
async def _shop_special_passes(update, context, query, data, player):
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
@SHOP_ROUTES.on('shop:main', 'menu:shop')
async def _shop_main(update, context, query, data, player):
    text, markup = await sync_to_async(render_shop_home, thread_sensitive=True)(player)
    await query.edit_message_text(text=text, parse_mode="HTML", reply_markup=markup)
    return True


async def handle_shop_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Handle shop callbacks; return whether the callback was handled."""
    query = update.callback_query
    data = query.data
    if data in MYSTERY_BOXES:
        return await handle_mystery_box_callback(update, context)

    handler = SHOP_ROUTES.resolve(data)
    if handler is None:
        return False
    player = await sync_to_async(Player.objects.filter(id=query.from_user.id).first)()
    return await handler(update, context, query, data, player)

















MENU_ROUTES = CallbackRouter()


@MENU_ROUTES.on('menu:settings')
async def _menu_settings(update, context, query, data):
    await query.edit_message_text(
        text="⚙️ *Settings* ⚙️\n\nChoose an option below:",
        parse_mode="Markdown",
        reply_markup=build_settings_menu()  # You need to implement this function
    )
    return


@MENU_ROUTES.on('settings:notifications')
async def _menu_settings_notifications(update, context, query, data):
    user_id = query.from_user.id

    try:
        player = await sync_to_async(Player.objects.get)(id=user_id)
        settings, _ = await sync_to_async(UserSettings.objects.get_or_create)(player=player)

    except Player.DoesNotExist:
        await query.edit_message_text("❌ You are not registered.")
        return

    await query.edit_message_text(
        text="🔔 *Notification Preferences*\nNotify you when Something is going on or not?.",
        parse_mode="Markdown",
        reply_markup=build_notification_settings_menu(settings)
    )
    return


@MENU_ROUTES.on_prefix('toggle:')
async def _menu_toggle(update, context, query, data):
    field = data.split(":")[1]
    user_id = query.from_user.id

    try:
        player = await sync_to_async(Player.objects.get)(id=user_id)
        settings, _ = await sync_to_async(UserSettings.objects.get_or_create)(player=player)
    except Player.DoesNotExist:
        await query.edit_message_text("❌ You are not registered.")
        return

    if hasattr(settings, field):
        current = getattr(settings, field)
        setattr(settings, field, not current)
        await sync_to_async(settings.save)()
    else:
        await query.answer("Unknown setting.")
        return

    # Refresh the settings menu
    await query.edit_message_text(
        text="🔔 *Notification Preferences*\n\nTap to toggle any setting.",
        parse_mode="Markdown",
        reply_markup=build_notification_settings_menu(settings)
    )
    return


@MENU_ROUTES.on('menu:howtoplay')
async def _menu_howtoplay(update, context, query, data):
    user_id = query.from_user.id
    user_name = query.from_user.first_name
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
@MENU_ROUTES.on('menu:minigames')
async def _menu_minigames(update, context, query, data):
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
            "🎯 `/dart` – /dart [chip amount].\n\n"
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
@MENU_ROUTES.on('menu:social')
async def _menu_social(update, context, query, data):
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
        await sync_to_async(player.save)(update_fields=("referral_code",))
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
        f"Share this link to invite friends and earn 5000:\n`{referral_link}`\n",
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
            fname = escape_markdown(friend["name"], version=2)

            lines.append(f" • {fname} (earned you {friend_bonus} chips)")


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


@MENU_ROUTES.on('menu:horse_leaderboard')
async def _menu_horse_leaderboard(update, context, query, data):
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
@MENU_ROUTES.on('menu:global_leaderboard')
async def _menu_global_leaderboard(update, context, query, data):
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
@MENU_ROUTES.on('menu:main')
async def _menu_main(update, context, query, data):
    from game.telegram.hub import show_home

    if await show_home(update, context, edit=True):
        return
    await query.edit_message_text(
        text=t("play.title", "en"),
        reply_markup=play_home_keyboard("en")
    )
    return


# ── (2) Profile submenu selected (reset text → “Profile Menu” + buttons) ────
@MENU_ROUTES.on('menu:profile')
async def _menu_profile(update, context, query, data):
    await query.edit_message_text(
        text="👤 *Profile Menu* 👤\n\nSelect an action:",
        parse_mode="Markdown",
        reply_markup=build_profile_menu()
    )
    return


# ── (3) Achievements (Profile → Achievements) ───────────────────────────────
@MENU_ROUTES.on('profile:achievements')
async def _menu_profile_achievements(update, context, query, data):
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
@MENU_ROUTES.on('profile:stats')
async def _menu_profile_stats(update, context, query, data):
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
            id=user_id, name=user_first, chips=0, xp=0, level=1
        )
        await adjust_balance_async(
            player, 200,
            category=ChipTransaction.Category.DAILY_REWARD,
            description="Legacy profile signup balance",
            reference_type="player_signup",
            reference_id=player.id,
            idempotency_key=f"profile-signup:{player.id}",
        )
        stats  = await sync_to_async(Stats.objects.create)(
            wins=0, loses=0, how_many_21=0, player=player
        )
        text = (
            f"Welcome to Blackjack, {user_first}! You have been given 200 💰 chips to start.\n\n"
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
@MENU_ROUTES.on('profile:mytokens')
async def _menu_profile_mytokens(update, context, query, data):
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
@MENU_ROUTES.on('profile:myraces')
async def _menu_profile_myraces(update, context, query, data):
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
@MENU_ROUTES.on('menu:leaderboards')
async def _menu_leaderboards(update, context, query, data):
    await query.edit_message_text(
        text="🏆 *Leaderboards* 🏆\n\nChoose one:",
        parse_mode="Markdown",
        reply_markup=build_leaderboards_menu()
    )
    return


@MENU_ROUTES.on('tournaments:Events')
async def _menu_tournaments_events(update, context, query, data):
    params, _ = await sync_to_async(GameParameter.objects.get_or_create)(pk=1)

    events = []

    if params.join_bonus:
        events.append(f"🎁 *Join Bonus*: All users get *{params.join_bonus_amount} chips* when a game starts.")

    if params.buyhorse_event:
        events.append(f"🐎 *Flat Horse Price*: All horses cost exactly *{params.todays_horse_price} chips* today.")

    if params.rename_horse_event:
        events.append("🏷 *Rename Horse Discount*: Renaming a horse costs only *1 chip*!")

    if not events:
        text = "❌ No active events at the moment."
    else:
        text = "✨ *Active Events:*\n\n" + "\n\n".join(events)

    await query.edit_message_text(
        text=text,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 Back", callback_data="menu:main")]
        ]),
        parse_mode="Markdown"
    )


@MENU_ROUTES.on('menu:tournaments')
async def _menu_tournaments(update, context, query, data):
    await query.edit_message_text(
        text="✨ *Events* 🏁\n\nChoose an action:",
        parse_mode="Markdown",
        reply_markup=build_tournaments_menu()
    )
    return  


@MENU_ROUTES.on_prefix('quest:')
async def _menu_quest(update, context, query, data):
    print("asfd")
    quest_type = data.split(":")[1].replace("daily_", "")
    user_id = query.from_user.id

    exists = await sync_to_async(Player.objects.filter(id=user_id).exists)()
    if not exists:
        await query.answer("❌ You need to register first.", show_alert=True)
        return

    player = await sync_to_async(Player.objects.get)(id=user_id)
    today = timezone.now().date()

    # Fetch quests of that type today (shared for all players)
    print(quest_type)
    quests = await sync_to_async(list)(
        DailyQuest.objects.filter(quest_type=quest_type,available=True)
    )

    if not quests:
        await query.edit_message_text(
            f"No active quests found for {quest_type.replace('_', ' ').title()} today.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Back", callback_data="quests:daily_quests")]
            ])
        )
        return

    # Fetch progress rows (only those created by gameplay)
    progress_list = await sync_to_async(list)(
        PlayerDailyQuestProgress.objects.select_related("quest").filter(player=player, quest__in=quests)
    )

    progress_map = {p.quest.id: p for p in progress_list}

    lines = [f"*{quest_type.replace('_', ' ').title()} Quests*\n"]
    for quest in quests:
        progress = progress_map.get(quest.id)

        if progress:
            status = "✅ Completed" if progress.completed else f"📊 {progress.progress}/{quest.target}"
        else:
            status = f"📊 0/{quest.target}"  # No progress yet

        lines.append(
            f"*{quest.get_quest_type_display()}*\n"
                f"📝 {quest.description}\n"
                f"{status} | 🎁 {quest.reward_chips} chips, {quest.reward_xp} XP\n"
                f"──────────────"
        )

    await query.edit_message_text(
        "\n".join(lines),
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 Back", callback_data="quests:daily_quests")]
        ])
    )
    return


@MENU_ROUTES.on('menu:quests')
async def _menu_quests(update, context, query, data):
    await query.edit_message_text(
        text="🎯 *Quests & Rewards* 🎯\n\nChoose an action:",
        parse_mode="Markdown",
        reply_markup=build_quests_menu()
    )
    return


@MENU_ROUTES.on('quests:daily_quests')
async def _menu_quests_daily_quests(update, context, query, data):
    await query.edit_message_text(
        text="📆 *Daily Quests* 📆\n\nComplete these to earn chips and XP:",
        parse_mode="Markdown",
        reply_markup=build_daily_quests_menu()
    )
    return


@MENU_ROUTES.on('quests:daily_rewards')
async def _menu_quests_daily_rewards(update, context, query, data):
    await query.edit_message_text(
        text="📆 *Daily Quests* 📆\n\nComplete these to earn chips and XP:",
        parse_mode="Markdown",
        reply_markup=build_quests_menu_daily()
    )
    return


@MENU_ROUTES.on('quests:daily_bonus')
async def _menu_quests_daily_bonus(update, context, query, data):
    user = update.effective_user
    user_id = user.id

    # ✅ Ensure player is registered
    exists = await sync_to_async(Player.objects.filter(id=user_id).exists)()
    if not exists:
        await query.answer("❌ You need to register first.", show_alert=True)
        return

    now = timezone.now()
    try:
        balance = await claim_daily_chips_async(user_id, 200, now)
    except RewardAlreadyClaimed:
        await query.edit_message_text(
            "🎁 You’ve already claimed your daily 200 chips! Come back tomorrow.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Back", callback_data="menu:quests")]
            ])
        )
    else:
        await query.edit_message_text(
            f"🎉 Here are your 200 daily chips! You now have 💰{balance} chips.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Back", callback_data="menu:quests")]
            ])
        )
    return


@MENU_ROUTES.on('quests:daily_mystery_box')
async def _menu_quests_daily_mystery_box(update, context, query, data):
    user = update.effective_user
    user_id = user.id

    now = timezone.now()

    # 🧩 Mystery Box values (adjust here easily)
    box_name = "🎁 Bronze Mystery Box"
    chip_range = (100, 400)  # updated from 100–1000
    xp_range = (5, 20)      # updated from 10–100
    rare_items = [("double_chip_potion", 0.05)]  # 5% chance

    chips = random.randint(*chip_range)
    xp = random.randint(*xp_range)
    reward_item = None

    for item_type, chance in rare_items:
        if random.random() < chance:
            reward_item = item_type
            break

    try:
        await claim_daily_box_async(user_id, now.date(), chips, xp, reward_item)
    except RewardAlreadyClaimed:
        await query.edit_message_text(
            "🎁 You’ve already opened your daily Mystery Box today!",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="menu:quests")]])
        )
        return

    message = f"🎁 You opened a {box_name}!\n\n💰 Chips: +{chips}\n✨ XP: +{xp}"
    if reward_item:
        message += f"\n🍀 Lucky! You also got a **{reward_item}**!"

    await query.edit_message_text(
        message,
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="menu:quests")]])
    )
    return


@MENU_ROUTES.on('quests:daily_xp')
async def _menu_quests_daily_xp(update, context, query, data):
    user = update.effective_user
    user_id = user.id

    now = timezone.now()
    try:
        result = await claim_daily_xp_async(user_id, 10, now)
    except RewardAlreadyClaimed:
        await query.edit_message_text(
            "✨ You’ve already claimed your 10 XP today! Come back tomorrow.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="menu:quests")]])
        )
        return

    for level, chips_reward in result.level_rewards:
        await context.bot.send_message(
            chat_id=user_id,
            text=f"🎉 Congratulations! You've reached level {level}! You've been rewarded with {chips_reward} 💰 chips!",
        )

    await query.edit_message_text(
        f"✅ You claimed +10 XP. Keep it up!",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="menu:quests")]])
    )
    return


@MENU_ROUTES.on('quests:quest_history')
async def _menu_quests_quest_history(update, context, query, data):
    player = await sync_to_async(Player.objects.get)(id=query.from_user.id)
    histories = await sync_to_async(list)(
        QuestHistory.objects.filter(player=player).order_by("-date_completed")
    )

    type_display = {
        "blackjack": "🃏 Blackjack",
        "minigames": "🎯 Minigames",
        "race": "🐎 Horse Race"
    }

    if not histories:
        preview_text = "📜 You have no completed quests yet."
        await query.edit_message_text(
            text=preview_text,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Back", callback_data="menu:quests")]
            ]),
            parse_mode="Markdown"
        )
        return

    # If too many quests, send preview and full details via DM
    if len(histories) > 10:
        await query.edit_message_text(
            text="📬 You’ve completed a lot of quests! Check your private messages for the full list.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Back", callback_data="menu:quests")]
            ]),
            parse_mode="Markdown"
        )

        # Compose long message and split if too big
        chunks = []
        chunk = "🏅 *Your Completed Quests:*\n"
        for quest in histories:
            quest_type_label = type_display.get(quest.quest_type, quest.quest_type)
            line = (
                f"\n*{quest_type_label}*\n"
                    f"• {quest.description}\n"
                    f"🎯 {quest.progress}/{quest.target} | 💰 {quest.reward_chips} chips | XP: {quest.reward_xp}\n"
                    f"📆 {quest.date_assigned.strftime('%Y-%m-%d')}\n"
            )
            if len(chunk + line) >= 3900:  # Leave room for Markdown and safety
                chunks.append(chunk)
                chunk = ""
            chunk += line
        if chunk:
            chunks.append(chunk)

        for i, msg in enumerate(chunks):
            try:
                await context.bot.send_message(
                    chat_id=player.id,
                    text=msg,
                    parse_mode="Markdown"
                )
            except Exception as e:
                print(f"[QUEST_HISTORY] Failed to DM user: {e}")
                break
    else:
        # Send normal preview if few quests
        lines = ["🏅 *Your Completed Quests:*"]
        for quest in histories[:10]:
            quest_type_label = type_display.get(quest.quest_type, quest.quest_type)
            line = (
                f"*{quest_type_label}*\n"
                    f"• {quest.description}\n"
                    f"🎯 {quest.progress}/{quest.target} | 💰 {quest.reward_chips} chips | XP: {quest.reward_xp}\n"
                    f"📆 {quest.date_assigned.strftime('%Y-%m-%d')}"
            )
            lines.append(line)

        preview_text = "\n\n".join(lines)
        await query.edit_message_text(
            text=preview_text,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Back", callback_data="menu:quests")]
            ]),
            parse_mode="Markdown"
        )


@MENU_ROUTES.on("menu:support")
async def _menu_support(update, context, query, data):
    await query.edit_message_text(
        text="❓ *Support* ❓\n\nChoose an option:",
        parse_mode="Markdown",
        reply_markup=build_support_menu()
    )


@MENU_ROUTES.on("settings:language")
async def _menu_settings_language(update, context, query, data):
    language = await language_for_update(update)
    await query.edit_message_text(
        text=translate("language.usage", language),
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 Back", callback_data="menu:settings")]
        ]),
    )


async def handle_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Entry point for every inline-keyboard callback not claimed by an earlier handler."""
    query = update.callback_query
    try:
        await _dispatch_callback(update, context, query, query.data)
    finally:
        # Answer after handling so a handler can answer first with an alert.
        try:
            await query.answer()
        except BadRequest:
            pass


async def _dispatch_callback(update, context, query, data):
    if data in ("menu:items", "menu:boosters") or data.startswith("items:"):
        return await handle_items_callback(update, context)
    if await handle_shop_callback(update, context):
        return

    handler = MENU_ROUTES.resolve(data)
    if handler is not None:
        return await handler(update, context, query, data)
    return await dispatch_horse_menu(update, context, query, data)


