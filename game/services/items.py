"""Atomic inventory consumption and item activation."""

from asgiref.sync import sync_to_async
from django.db import transaction
from django.utils import timezone

from game.models import PlayerActiveItem, PlayerItem
from game.services.progression import ProgressionResult, award_xp


class ItemUnavailable(ValueError):
    pass


class ItemCategoryAlreadyActive(ValueError):
    pass


@transaction.atomic
def consume_xp_booster(
    player_id: int, item_type: str, xp_amount: int
) -> ProgressionResult:
    item = PlayerItem.objects.select_for_update().filter(
        player_id=player_id, item_type=item_type, quantity__gt=0
    ).first()
    if item is None:
        raise ItemUnavailable
    result = award_xp(player_id, xp_amount)
    item.quantity -= 1
    item.save(update_fields=("quantity",))
    return result


async def consume_xp_booster_async(*args, **kwargs) -> ProgressionResult:
    return await sync_to_async(consume_xp_booster, thread_sensitive=True)(*args, **kwargs)


@transaction.atomic
def activate_inventory_item(
    player_id: int, item_type: str, mutually_exclusive_types: list[str]
) -> PlayerActiveItem:
    item = PlayerItem.objects.select_for_update().filter(
        player_id=player_id, item_type=item_type, quantity__gt=0
    ).first()
    if item is None:
        raise ItemUnavailable
    if mutually_exclusive_types and PlayerActiveItem.objects.select_for_update().filter(
        player_id=player_id,
        item_type__in=mutually_exclusive_types,
        is_active=True,
    ).exists():
        raise ItemCategoryAlreadyActive
    active = PlayerActiveItem.objects.create(
        player_id=player_id,
        item_type=item_type,
        activated_at=timezone.now(),
        is_active=True,
    )
    item.quantity -= 1
    item.save(update_fields=("quantity",))
    return active


async def activate_inventory_item_async(*args, **kwargs) -> PlayerActiveItem:
    return await sync_to_async(activate_inventory_item, thread_sensitive=True)(
        *args, **kwargs
    )
