"""Atomic horse ownership, customization, upgrades, gifting, and marketplace sales."""

from dataclasses import dataclass

from asgiref.sync import sync_to_async
from django.db import transaction

from game.models import (
    ChipTransaction,
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
    if sale is None or sale.horse.user_id == buyer_id:
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
