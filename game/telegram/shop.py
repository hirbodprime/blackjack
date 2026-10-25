"""Season shop and bag screens (callback prefix ``store:``)."""

from html import escape

from asgiref.sync import sync_to_async
from django.utils import timezone
from telegram import InlineKeyboardButton as Btn, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.error import BadRequest

from game.models import ITEM_TYPE_CHOICES, Player
from game.services import shop
from game.services.economy import InsufficientChips


HOME = Btn("🏠 Home", callback_data="hub:home")
LEGACY_NAMES = dict(ITEM_TYPE_CHOICES)
POTION_KEYS = {"double_chip_potion", "triple_chip_potion", "10x_chip_potion"}
PASS_KEYS = {"insurance_pass", "first_hand_20_pass", "first_hand_11_potion"}
BOOSTER_KEYS = {"xp_booster_500", "xp_booster_2000", "xp_booster_15000", "xp_booster_50000"}


def _left(expires) -> str:
    minutes = max(0, int((expires - timezone.now()).total_seconds() // 60))
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes}m" if hours else f"{minutes}m"


def render_home(player: Player):
    deal = shop.deal_of_the_day()
    lines = [
        "<b>🛍 SEASON SHOP</b>",
        f"💰 {player.chips:,} chips",
        "━━━━━━━━━━━━━━━",
        f"🔥 <b>Deal of the day:</b> {deal.emoji} {escape(deal.name)}",
        f"   <s>{deal.price:,}</s> → <b>{shop.price_for(deal.key):,}</b> (−{shop.DEAL_DISCOUNT_PERCENT}%)",
    ]
    rows = [[Btn(f"🔥 Buy deal · {shop.price_for(deal.key):,}", callback_data=f"store:buy:{deal.key}:home")]]
    categories = [Btn(label, callback_data=f"store:cat:{key}") for key, label in shop.CATEGORIES]
    rows += [categories[i:i + 2] for i in range(0, len(categories), 2)]
    rows.append([Btn("🎁 Mystery boxes", callback_data="shop:mystery_box"), Btn("🐎 Horse shop", callback_data="menu:mainhorse")])
    rows.append([Btn("🎒 My bag", callback_data="store:bag"), HOME])
    return "\n".join(lines), InlineKeyboardMarkup(rows)


def render_category(player: Player, category: str):
    label = dict(shop.CATEGORIES).get(category, category)
    owned = dict(shop.inventory(player.pk))
    lines = [f"<b>{label.upper()}</b>", f"💰 {player.chips:,} chips", "━━━━━━━━━━━━━━━"]
    rows = []
    for item in shop.CATALOG:
        if item.category != category:
            continue
        price = shop.price_for(item.key)
        tag = " 🔥" if price != item.price else ""
        have = f" · you have {owned[item.key]}" if owned.get(item.key) else ""
        lines.append(f"{item.emoji} <b>{escape(item.name)}</b> — {price:,}{tag}{have}\n   <i>{escape(item.description)}</i>")
        if item.title and owned.get(item.key):
            rows.append([Btn(f"✅ {item.name} (owned)", callback_data=f"store:equip:{item.key}")])
        else:
            rows.append([Btn(f"{item.emoji} {item.name} · {price:,}", callback_data=f"store:buy:{item.key}:{category}")])
    rows.append([Btn("◀️ Shop", callback_data="store:home"), HOME])
    return "\n".join(lines), InlineKeyboardMarkup(rows)


def render_bag(player: Player):
    lines = ["<b>🎒 MY BAG</b>", "━━━━━━━━━━━━━━━"]
    if player.title:
        lines.append(f"🎩 Title: <b>{escape(player.title)}</b>")
    active = [
        (shop.ITEMS[key], boost)
        for key in sorted(shop.TIMED_KEYS)
        if (boost := shop.active_boost(player.pk, key))
    ]
    for item, boost in active:
        lines.append(f"{item.emoji} {escape(item.name)} active · {_left(shop.boost_expires_at(boost))} left")
    if player.title or active:
        lines.append("")
    rows = []
    items = shop.inventory(player.pk)
    if not items:
        lines.append("Your bag is empty — visit the shop!")
    for key, quantity in items:
        item = shop.ITEMS.get(key)
        name = f"{item.emoji} {item.name}" if item else LEGACY_NAMES.get(key, key)
        lines.append(f"{name} × {quantity}")
        if key in shop.TIMED_KEYS:
            rows.append([Btn(f"▶️ Use {name}", callback_data=f"store:use:{key}")])
        elif item and item.title:
            if player.title != item.title:
                rows.append([Btn(f"🎩 Wear {item.title}", callback_data=f"store:equip:{key}")])
        elif key in POTION_KEYS or key in PASS_KEYS:
            rows.append([Btn(f"▶️ Activate {name}", callback_data=f"items:activate:{key}")])
        elif key in BOOSTER_KEYS:
            rows.append([Btn(f"▶️ Use {name}", callback_data=f"items:use_booster:{key}")])
    if items and "streak_freeze" in dict(items):
        lines.append("\n<i>🧊 Streak Freezes are used automatically if you miss a day.</i>")
    if player.title:
        rows.append([Btn("🎩 Remove title", callback_data="store:equip:none")])
    rows.append([Btn("⏸ Deactivate potions/passes", callback_data="items:deactivate")])
    rows.append([Btn("🛍 Shop", callback_data="store:home"), HOME])
    return "\n".join(lines), InlineKeyboardMarkup(rows)


async def _show(query, text, markup):
    try:
        await query.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.HTML)
    except BadRequest as exc:
        if "not modified" not in str(exc).lower():
            raise


async def store_callback(update, context) -> None:
    query = update.callback_query
    parts = query.data.split(":")
    page = parts[1]
    player = await Player.objects.filter(pk=query.from_user.id).afirst()
    if player is None:
        await query.answer("Start the bot first with /start.", show_alert=True)
        return

    def run(fn, *args):
        return sync_to_async(fn, thread_sensitive=True)(*args)

    if page == "buy":
        key, back = parts[2], parts[3] if len(parts) > 3 else "home"
        try:
            await shop.buy_async(player.pk, key)
        except InsufficientChips:
            await query.answer("Not enough chips.", show_alert=True)
            return
        except shop.ShopError as exc:
            await query.answer(str(exc), show_alert=True)
            return
        item = shop.ITEMS[key]
        hint = "Equip it from 🎒 My bag." if item.title else "It's in 🎒 My bag."
        await query.answer(f"✅ Bought {item.name}! {hint}", show_alert=True)
        await player.arefresh_from_db()
        text, markup = await run(render_home if back == "home" else render_category, *((player,) if back == "home" else (player, back)))
        await _show(query, text, markup)
        return
    if page == "use":
        try:
            boost = await shop.activate_timed_async(player.pk, parts[2])
        except shop.ShopError as exc:
            await query.answer(str(exc), show_alert=True)
            return
        await query.answer(f"✅ Active for {_left(shop.boost_expires_at(boost))}", show_alert=True)
        text, markup = await run(render_bag, player)
        await _show(query, text, markup)
        return
    if page == "equip":
        try:
            title = await shop.equip_title_async(player.pk, None if parts[2] == "none" else parts[2])
        except shop.ShopError as exc:
            await query.answer(str(exc), show_alert=True)
            return
        await query.answer(f"🎩 {title}" if title else "Title removed")
        await player.arefresh_from_db()
        text, markup = await run(render_bag, player)
        await _show(query, text, markup)
        return

    await query.answer()
    if page == "cat":
        text, markup = await run(render_category, player, parts[2])
    elif page == "bag":
        text, markup = await run(render_bag, player)
    else:
        text, markup = await run(render_home, player)
    await _show(query, text, markup)


async def shop_command(update, context) -> None:
    player = await Player.objects.filter(pk=update.effective_user.id).afirst()
    if player is None:
        await update.effective_message.reply_text("Start the bot first with /start.")
        return
    text, markup = await sync_to_async(render_home, thread_sensitive=True)(player)
    await update.effective_message.reply_text(text, reply_markup=markup, parse_mode=ParseMode.HTML)
