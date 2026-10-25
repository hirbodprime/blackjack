"""Atomic player XP and level progression operations."""

from dataclasses import dataclass

from asgiref.sync import sync_to_async
from django.db import transaction

from game.models import ChipTransaction, Player
from game.services.economy import adjust_balance
from game.services.ranks import RANK_TIERS, level_reward, xp_for_level
from game.services.seasons import add_season_points


@dataclass(frozen=True)
class ProgressionResult:
    level: int
    xp: int
    level_rewards: tuple[tuple[int, int], ...] = ()
    level_changed: bool = False


def _unlock_rank_achievements(player_id: int, old_level: int, new_level: int) -> None:
    from game.services.achievements import RANK_ACHIEVEMENTS, unlock

    for tier in RANK_TIERS:
        if old_level < tier.min_level <= new_level and tier.key in RANK_ACHIEVEMENTS:
            unlock(player_id, RANK_ACHIEVEMENTS[tier.key])


@transaction.atomic
def award_xp(player: Player | int, amount: int) -> ProgressionResult:
    if not isinstance(amount, int) or isinstance(amount, bool) or amount < 0:
        raise ValueError("XP amount must be a non-negative integer")

    player_id = player.pk if isinstance(player, Player) else player
    locked = Player.objects.select_for_update().get(pk=player_id)
    locked.xp += amount
    rewards = []

    while locked.xp >= xp_for_level(locked.level):
        locked.xp -= xp_for_level(locked.level)
        locked.level += 1
        rewards.append((locked.level, level_reward(locked.level)))

    locked.save(update_fields=("xp", "level"))
    add_season_points(locked.pk, amount)
    if rewards:
        adjust_balance(
            locked,
            sum(reward for _, reward in rewards),
            category=ChipTransaction.Category.LEVEL_REWARD,
            description="Level-up rewards",
            reference_type="player_level",
            reference_id=locked.level,
            metadata={"rewards": rewards},
        )

    if rewards:
        _unlock_rank_achievements(locked.pk, rewards[0][0] - 1, locked.level)
        locked.refresh_from_db(fields=("chips", "xp", "level"))

    if isinstance(player, Player):
        player.xp = locked.xp
        player.level = locked.level
        player.chips = locked.chips

    return ProgressionResult(
        level=locked.level,
        xp=locked.xp,
        level_rewards=tuple(rewards),
        level_changed=bool(rewards),
    )


async def award_xp_async(*args, **kwargs) -> ProgressionResult:
    return await sync_to_async(award_xp, thread_sensitive=True)(*args, **kwargs)


@transaction.atomic
def deduct_xp_amount(player: Player | int, amount: int) -> ProgressionResult:
    if not isinstance(amount, int) or isinstance(amount, bool) or amount < 0:
        raise ValueError("XP amount must be a non-negative integer")

    player_id = player.pk if isinstance(player, Player) else player
    locked = Player.objects.select_for_update().get(pk=player_id)
    original_level = locked.level
    locked.xp -= amount

    while locked.xp < 0 and locked.level > 1:
        locked.level -= 1
        locked.xp += xp_for_level(locked.level)

    if locked.xp < 0:
        locked.xp = 0
    locked.save(update_fields=("xp", "level"))

    if isinstance(player, Player):
        player.xp = locked.xp
        player.level = locked.level

    return ProgressionResult(
        level=locked.level,
        xp=locked.xp,
        level_changed=locked.level != original_level,
    )


async def deduct_xp_amount_async(*args, **kwargs) -> ProgressionResult:
    return await sync_to_async(deduct_xp_amount, thread_sensitive=True)(*args, **kwargs)
