"""Season shop catalog, purchases, timed boosts, streak freezes, and titles."""

import random
from dataclasses import dataclass
from datetime import timedelta

from asgiref.sync import sync_to_async
from django.db import transaction
from django.utils import timezone

from game.models import ChipTransaction, Player, PlayerActiveItem, PlayerItem
from game.services.economy import adjust_balance


@dataclass(frozen=True)
class ShopItem:
    key: str
    emoji: str
    name: str
    description: str
    price: int
    category: str
    hours: int = 0  # >0 for timed boosts
    title: str = ""  # set for cosmetic titles


CATEGORIES = (
    ("boosts", "⚡ Boosts"),
    ("blackjack", "🃏 Blackjack"),
    ("protection", "🛡 Protection"),
    ("titles", "🎩 Titles"),
)

CATALOG = (
    ShopItem("xp_charm", "🍀", "Lucky Charm", "+25% XP (and season points) for 24h", 5_000, "boosts", hours=24),
    ShopItem("daily_doubler", "📆", "Daily Doubler", "Double chip rewards from daily challenges for 24h", 4_000, "boosts", hours=24),
    ShopItem("xp_booster_500", "📈", "XP Booster", "Instantly gain 500 XP", 2_500, "boosts"),
    ShopItem("xp_booster_2000", "🚀", "Mega XP Booster", "Instantly gain 2,000 XP", 9_000, "boosts"),
    ShopItem("double_chip_potion", "🧪", "Double Potion", "Your next blackjack win pays double", 3_000, "blackjack"),
    ShopItem("triple_chip_potion", "⚗️", "Triple Potion", "Your next blackjack win pays triple", 8_000, "blackjack"),
    ShopItem("10x_chip_potion", "💥", "10× Potion", "Your next blackjack win pays 10× (bonus capped)", 40_000, "blackjack"),
    ShopItem("insurance_pass", "🛡️", "Insurance Pass", "Discard a bad hit and draw again", 1_500, "blackjack"),
    ShopItem("first_hand_11_potion", "🂫", "Opening 11", "Start your next game holding 11", 2_500, "blackjack"),
    ShopItem("first_hand_20_pass", "🂮", "Opening 20", "Start your next game holding 20", 4_000, "blackjack"),
    ShopItem("streak_freeze", "🧊", "Streak Freeze", "Miss one day without losing your daily streak", 2_500, "protection"),
    ShopItem("title_lucky", "🍀", "Title: Lucky", "Show 🍀 Lucky on your profile and leaderboards", 10_000, "titles", title="🍀 Lucky"),
    ShopItem("title_shark", "🦈", "Title: Card Shark", "Show 🦈 Card Shark", 20_000, "titles", title="🦈 Card Shark"),
    ShopItem("title_jockey", "🏇", "Title: Jockey", "Show 🏇 Jockey", 20_000, "titles", title="🏇 Jockey"),
    ShopItem("title_ghost", "👻", "Title: Ghost", "Show 👻 Ghost", 30_000, "titles", title="👻 Ghost"),
    ShopItem("title_highroller", "💎", "Title: High Roller", "Show 💎 High Roller", 75_000, "titles", title="💎 High Roller"),
    ShopItem("title_tycoon", "🏦", "Title: Tycoon", "Show 🏦 Tycoon", 200_000, "titles", title="🏦 Tycoon"),
    ShopItem("title_kingpin", "👑", "Title: Kingpin", "Show 👑 Kingpin — the rarest flex", 1_000_000, "titles", title="👑 Kingpin"),
)
ITEMS = {item.key: item for item in CATALOG}
TIMED_KEYS = {item.key for item in CATALOG if item.hours}
XP_CHARM_BONUS_PERCENT = 25


class ShopError(ValueError):
    pass


@transaction.atomic
def buy(player_id: int, key: str) -> PlayerItem:
    item = ITEMS.get(key)
    if item is None:
        raise ShopError("That item isn't sold here.")
    if item.title and PlayerItem.objects.filter(player_id=player_id, item_type=key, quantity__gt=0).exists():
        raise ShopError("You already own this title.")
    adjust_balance(
        player_id, -price_for(key),
        category=ChipTransaction.Category.ITEM_PURCHASE,
        description=f"Shop: {item.name}",
        reference_type="player_item", reference_id=key,
    )
    owned, _ = PlayerItem.objects.select_for_update().get_or_create(
        player_id=player_id, item_type=key, defaults={"quantity": 0}
    )
    owned.quantity += 1
    owned.save(update_fields=("quantity",))
    return owned


@transaction.atomic
def activate_timed(player_id: int, key: str) -> PlayerActiveItem:
    """Start (or extend) a timed boost from inventory."""
    if key not in TIMED_KEYS:
        raise ShopError("That item isn't a timed boost.")
    owned = PlayerItem.objects.select_for_update().filter(
        player_id=player_id, item_type=key, quantity__gt=0
    ).first()
    if owned is None:
        raise ShopError("You don't have that boost.")
    owned.quantity -= 1
    owned.save(update_fields=("quantity",))
    hours = ITEMS[key].hours
    current = active_boost(player_id, key)
    if current is not None:
        # Stack by pushing the start forward, so the remaining time grows by one duration.
        current.activated_at += timedelta(hours=hours)
        current.save(update_fields=("activated_at",))
        return current
    return PlayerActiveItem.objects.create(player_id=player_id, item_type=key, is_active=True)


def active_boost(player_id: int, key: str) -> PlayerActiveItem | None:
    hours = ITEMS[key].hours
    since = timezone.now() - timedelta(hours=hours)
    return (
        PlayerActiveItem.objects.filter(
            player_id=player_id, item_type=key, is_active=True, activated_at__gt=since
        ).order_by("-activated_at").first()
    )


def boost_expires_at(boost: PlayerActiveItem):
    return boost.activated_at + timedelta(hours=ITEMS[boost.item_type].hours)


def xp_with_boosts(player_id: int, amount: int) -> int:
    if amount and active_boost(player_id, "xp_charm"):
        return amount + amount * XP_CHARM_BONUS_PERCENT // 100
    return amount


def daily_chips_with_boosts(player_id: int, amount: int) -> int:
    return amount * 2 if amount and active_boost(player_id, "daily_doubler") else amount


def consume_streak_freeze(player_id: int) -> bool:
    """Spend one Streak Freeze if the player has one; caller holds the transaction."""
    owned = PlayerItem.objects.select_for_update().filter(
        player_id=player_id, item_type="streak_freeze", quantity__gt=0
    ).first()
    if owned is None:
        return False
    owned.quantity -= 1
    owned.save(update_fields=("quantity",))
    return True


@transaction.atomic
def equip_title(player_id: int, key: str | None) -> str:
    player = Player.objects.select_for_update().get(pk=player_id)
    if key is None:
        player.title = ""
    else:
        item = ITEMS.get(key)
        if item is None or not item.title:
            raise ShopError("Unknown title.")
        if not PlayerItem.objects.filter(player=player, item_type=key, quantity__gt=0).exists():
            raise ShopError("Buy the title first.")
        player.title = item.title
    player.save(update_fields=("title",))
    return player.title


def inventory(player_id: int) -> list[tuple[str, int]]:
    return list(
        PlayerItem.objects.filter(player_id=player_id, quantity__gt=0)
        .order_by("item_type").values_list("item_type", "quantity")
    )


buy_async = sync_to_async(buy, thread_sensitive=True)
activate_timed_async = sync_to_async(activate_timed, thread_sensitive=True)
equip_title_async = sync_to_async(equip_title, thread_sensitive=True)


DEAL_DISCOUNT_PERCENT = 30


def deal_of_the_day(day=None) -> ShopItem:
    day = day or timezone.localdate()
    candidates = [item for item in CATALOG if not item.title]
    return random.Random(day.toordinal() * 7919).choice(candidates)


def price_for(key: str, day=None) -> int:
    item = ITEMS[key]
    if deal_of_the_day(day).key == key:
        return item.price * (100 - DEAL_DISCOUNT_PERCENT) // 100
    return item.price
