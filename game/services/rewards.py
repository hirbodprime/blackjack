"""Atomic daily reward claims."""

from dataclasses import dataclass
from datetime import date, datetime

from asgiref.sync import sync_to_async
from django.db import transaction

from game.models import ChipTransaction, Player, PlayerItem
from game.services.economy import adjust_balance
from game.services.progression import ProgressionResult, award_xp


class RewardAlreadyClaimed(ValueError):
    pass


@dataclass(frozen=True)
class DailyBoxResult:
    balance: int
    progression: ProgressionResult
    item_type: str | None


@transaction.atomic
def claim_daily_chips(player_id: int, amount: int, claimed_at: datetime) -> int:
    player = Player.objects.select_for_update().get(pk=player_id)
    if player.last_claimed_tokens and player.last_claimed_tokens.date() == claimed_at.date():
        raise RewardAlreadyClaimed
    change = adjust_balance(
        player,
        amount,
        category=ChipTransaction.Category.DAILY_REWARD,
        description="Daily chip reward",
        reference_type="daily_reward",
        reference_id=claimed_at.date().isoformat(),
        idempotency_key=f"daily-chips:{player_id}:{claimed_at.date().isoformat()}",
    )
    player.last_claimed_tokens = claimed_at
    player.save(update_fields=("last_claimed_tokens",))
    return change.balance


async def claim_daily_chips_async(*args, **kwargs) -> int:
    return await sync_to_async(claim_daily_chips, thread_sensitive=True)(*args, **kwargs)


@transaction.atomic
def claim_daily_xp(
    player_id: int, amount: int, claimed_at: datetime
) -> ProgressionResult:
    player = Player.objects.select_for_update().get(pk=player_id)
    if player.last_claimed_tokens and player.last_claimed_tokens.date() == claimed_at.date():
        raise RewardAlreadyClaimed
    result = award_xp(player, amount)
    player.last_claimed_tokens = claimed_at
    player.save(update_fields=("last_claimed_tokens",))
    return result


async def claim_daily_xp_async(*args, **kwargs) -> ProgressionResult:
    return await sync_to_async(claim_daily_xp, thread_sensitive=True)(*args, **kwargs)


@transaction.atomic
def claim_daily_box(
    player_id: int,
    claimed_on: date,
    chips: int,
    xp: int,
    item_type: str | None = None,
) -> DailyBoxResult:
    player = Player.objects.select_for_update().get(pk=player_id)
    if player.last_spin == claimed_on:
        raise RewardAlreadyClaimed
    change = adjust_balance(
        player,
        chips,
        category=ChipTransaction.Category.DAILY_REWARD,
        description="Daily mystery box chips",
        reference_type="daily_mystery_box",
        reference_id=claimed_on.isoformat(),
        idempotency_key=f"daily-box-chips:{player_id}:{claimed_on.isoformat()}",
    )
    progression = award_xp(player, xp)
    if item_type:
        item, _ = PlayerItem.objects.select_for_update().get_or_create(
            player=player, item_type=item_type, defaults={"quantity": 0}
        )
        item.quantity += 1
        item.save(update_fields=("quantity",))
    player.last_spin = claimed_on
    player.save(update_fields=("last_spin",))
    return DailyBoxResult(change.balance, progression, item_type)


async def claim_daily_box_async(*args, **kwargs) -> DailyBoxResult:
    return await sync_to_async(claim_daily_box, thread_sensitive=True)(*args, **kwargs)
