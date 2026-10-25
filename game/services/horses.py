"""Atomic horse ownership, customization, upgrades, gifting, and marketplace sales."""

import random
from dataclasses import dataclass

from asgiref.sync import sync_to_async
from django.db import transaction

from game.models import (
    ChipTransaction,
    HorseAppliedUpgrade,
    HorseSale,
    HorseUpgrade,
    OwnedHorse,
    Player,
    PlayerUpgrade,
)
from game.services.economy import InsufficientChips, adjust_balance


class HorseUnavailable(ValueError):
    pass


class HorseNotOwned(ValueError):
    pass


class UpgradeAlreadyOwned(ValueError):
    pass


class InvalidHorseSale(ValueError):
    pass


class StarterHorseLocked(ValueError):
    """Starter horses are free, so they stay with the player who claimed them."""


@transaction.atomic
def buy_horse(player_id: int, horse_number: int, cost: int) -> OwnedHorse:
    player = Player.objects.select_for_update().get(pk=player_id)
    if OwnedHorse.objects.select_for_update().filter(horse_number=horse_number).exists():
        raise HorseUnavailable
    adjust_balance(
        player,
        -cost,
        category=ChipTransaction.Category.HORSE_PURCHASE,
        description=f"Purchased horse {horse_number}",
        reference_type="horse",
        reference_id=horse_number,
    )
    return OwnedHorse.objects.create(user=player, horse_number=horse_number)


async def buy_horse_async(*args, **kwargs) -> OwnedHorse:
    return await sync_to_async(buy_horse, thread_sensitive=True)(*args, **kwargs)


@transaction.atomic
def buy_horse_for_recipient(
    payer_id: int,
    recipient_id: int,
    horse_number: int,
    cost: int,
) -> OwnedHorse:
    players = {
        player.pk: player
        for player in Player.objects.select_for_update().filter(
            pk__in=sorted(set((payer_id, recipient_id)))
        )
    }
    payer = players[payer_id]
    recipient = players[recipient_id]
    if OwnedHorse.objects.select_for_update().filter(horse_number=horse_number).exists():
        raise HorseUnavailable
    adjust_balance(
        payer,
        -cost,
        category=ChipTransaction.Category.HORSE_PURCHASE,
        description=f"Purchased horse {horse_number} for player {recipient_id}",
        reference_type="horse_gift_purchase",
        reference_id=horse_number,
        metadata={"recipient_id": recipient_id},
    )
    return OwnedHorse.objects.create(user=recipient, horse_number=horse_number)


async def buy_horse_for_recipient_async(*args, **kwargs) -> OwnedHorse:
    return await sync_to_async(buy_horse_for_recipient, thread_sensitive=True)(
        *args,
        **kwargs,
    )


@transaction.atomic
def buy_horse_upgrade(player_id: int, upgrade_id: int) -> PlayerUpgrade:
    player = Player.objects.select_for_update().get(pk=player_id)
    upgrade = HorseUpgrade.objects.select_for_update().get(pk=upgrade_id)
    if PlayerUpgrade.objects.filter(player=player, upgrade=upgrade).exists():
        raise UpgradeAlreadyOwned
    adjust_balance(
        player,
        -upgrade.cost,
        category=ChipTransaction.Category.HORSE_PURCHASE,
        description=f"Purchased horse upgrade {upgrade.name}",
        reference_type="horse_upgrade",
        reference_id=upgrade.pk,
    )
    return PlayerUpgrade.objects.create(player=player, upgrade=upgrade)


async def buy_horse_upgrade_async(*args, **kwargs) -> PlayerUpgrade:
    return await sync_to_async(buy_horse_upgrade, thread_sensitive=True)(*args, **kwargs)


@transaction.atomic
def customize_horse(
    player_id: int,
    horse_number: int,
    cost: int,
    *,
    emoji: str | None = None,
    name: str | None = None,
) -> OwnedHorse:
    player = Player.objects.select_for_update().get(pk=player_id)
    horse = OwnedHorse.objects.select_for_update().filter(
        user=player,
        horse_number=horse_number,
    ).first()
    if horse is None:
        raise HorseNotOwned
    adjust_balance(
        player,
        -cost,
        category=ChipTransaction.Category.HORSE_PURCHASE,
        description=f"Customized horse {horse_number}",
        reference_type="horse",
        reference_id=horse_number,
        metadata={"emoji": emoji, "name": name},
    )
    fields = []
    if emoji is not None:
        horse.emoji = emoji
        fields.append("emoji")
    if name is not None:
        horse.name = name
        fields.append("name")
    horse.save(update_fields=fields)
    return horse


async def customize_horse_async(*args, **kwargs) -> OwnedHorse:
    return await sync_to_async(customize_horse, thread_sensitive=True)(*args, **kwargs)


@transaction.atomic
def gift_owned_horse(
    owner_id: int,
    recipient_id: int,
    horse_number: int,
    fee: int,
) -> OwnedHorse:
    players = {
        player.pk: player
        for player in Player.objects.select_for_update().filter(
            pk__in=sorted((owner_id, recipient_id))
        )
    }
    owner = players[owner_id]
    recipient = players[recipient_id]
    horse = OwnedHorse.objects.select_for_update().filter(
        user=owner,
        horse_number=horse_number,
    ).first()
    if horse is None:
        raise HorseNotOwned
    if horse.is_starter:
        raise StarterHorseLocked
    adjust_balance(
        owner,
        -fee,
        category=ChipTransaction.Category.HORSE_PURCHASE,
        description=f"Gifted horse {horse_number} to player {recipient_id}",
        reference_type="horse",
        reference_id=horse_number,
        metadata={"recipient_id": recipient_id},
    )
    horse.user = recipient
    horse.save(update_fields=("user",))
    return horse


async def gift_owned_horse_async(*args, **kwargs) -> OwnedHorse:
    return await sync_to_async(gift_owned_horse, thread_sensitive=True)(*args, **kwargs)


@dataclass(frozen=True)
class HorseSaleResult:
    horse: OwnedHorse
    buyer: Player
    seller: Player
    price: int


@transaction.atomic
def purchase_horse_sale(buyer_id: int, horse_number: int) -> HorseSaleResult:
    sale = (
        HorseSale.objects.select_for_update()
        .select_related("horse__user")
        .filter(horse__horse_number=horse_number)
        .first()
    )
    if sale is None or sale.horse.user_id == buyer_id or sale.horse.is_starter:
        raise InvalidHorseSale
    players = {
        player.pk: player
        for player in Player.objects.select_for_update().filter(
            pk__in=sorted((buyer_id, sale.horse.user_id))
        )
    }
    buyer = players[buyer_id]
    seller = players[sale.horse.user_id]
    adjust_balance(
        buyer,
        -sale.price,
        category=ChipTransaction.Category.HORSE_PURCHASE,
        description=f"Purchased horse {horse_number} from player {seller.pk}",
        reference_type="horse_sale",
        reference_id=sale.pk,
        metadata={"seller_id": seller.pk},
    )
    adjust_balance(
        seller,
        sale.price,
        category=ChipTransaction.Category.TRANSFER,
        description=f"Sold horse {horse_number} to player {buyer.pk}",
        reference_type="horse_sale",
        reference_id=sale.pk,
        metadata={"buyer_id": buyer.pk},
    )
    horse = sale.horse
    horse.user = buyer
    horse.save(update_fields=("user",))
    price = sale.price
    sale.delete()
    return HorseSaleResult(horse, buyer, seller, price)


async def purchase_horse_sale_async(*args, **kwargs) -> HorseSaleResult:
    return await sync_to_async(purchase_horse_sale, thread_sensitive=True)(*args, **kwargs)


# ── Starter horses ──────────────────────────────────────────────────────────

STARTER_NUMBER_RANGE = range(100, 1000)
STARTER_NAME_MAX = 20


class StarterAlreadyClaimed(ValueError):
    pass


class InvalidStarterChoice(ValueError):
    pass


def _is_premium_number(number: int) -> bool:
    digits = str(number)
    return len(set(digits)) == 1


def starter_powerup_offers(player_id: int, count: int = 3) -> list[HorseUpgrade]:
    """Three upgrades offered to this player; stable so a callback can verify the pick."""
    upgrades = list(HorseUpgrade.objects.order_by("pk"))
    return random.Random(player_id).sample(upgrades, min(count, len(upgrades)))


def clean_horse_name(raw: str) -> str:
    name = " ".join((raw or "").split())
    if not 1 <= len(name) <= STARTER_NAME_MAX or name.startswith("/"):
        raise InvalidStarterChoice(f"Names must be 1–{STARTER_NAME_MAX} characters")
    return name


@transaction.atomic
def claim_starter_horse(player_id: int, name: str, upgrade_id: int, uses: int) -> OwnedHorse:
    from game.services.achievements import unlock

    player = Player.objects.select_for_update().get(pk=player_id)
    if OwnedHorse.objects.filter(user=player, is_starter=True).exists():
        raise StarterAlreadyClaimed
    name = clean_horse_name(name)
    offers = {u.pk: u for u in starter_powerup_offers(player_id)}
    if upgrade_id not in offers:
        raise InvalidStarterChoice("That powerup was not offered")
    taken = set(
        OwnedHorse.objects.filter(
            horse_number__gte=STARTER_NUMBER_RANGE.start,
            horse_number__lt=STARTER_NUMBER_RANGE.stop,
        ).values_list("horse_number", flat=True)
    )
    number = next(
        n for n in STARTER_NUMBER_RANGE if n not in taken and not _is_premium_number(n)
    )
    horse = OwnedHorse.objects.create(
        user=player, horse_number=number, name=name, emoji="🐎", is_starter=True
    )
    HorseAppliedUpgrade.objects.create(
        owner=player, horse=horse, upgrade=offers[upgrade_id], uses_remaining=uses
    )
    unlock(player, "starter_horse")
    return horse


def starter_horse_for(player_id: int) -> OwnedHorse | None:
    return OwnedHorse.objects.filter(user_id=player_id, is_starter=True).first()


claim_starter_horse_async = sync_to_async(claim_starter_horse, thread_sensitive=True)
starter_powerup_offers_async = sync_to_async(starter_powerup_offers, thread_sensitive=True)
starter_horse_for_async = sync_to_async(starter_horse_for, thread_sensitive=True)
