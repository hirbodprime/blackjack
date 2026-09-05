"""Atomic mystery-box purchases and rewards."""

from dataclasses import dataclass

from asgiref.sync import sync_to_async
from django.db import transaction

from game.models import ChipTransaction, Player, PlayerItem
from game.services.economy import InsufficientChips, adjust_balance


@dataclass(frozen=True)
class MysteryBoxResult:
    reward_type: str
    chips: int = 0
    xp: int = 0
    item_type: str | None = None
    level_rewards: tuple[tuple[int, int], ...] = ()
    replayed: bool = False


@transaction.atomic
def open_mystery_box(
    player_id: int,
    box_key: str,
    cost: int,
    reward_type: str,
    reward_value: int | str | None,
    operation_id: str,
) -> MysteryBoxResult:
    cost_key = f"mystery:{operation_id}:cost"
    existing = ChipTransaction.objects.filter(idempotency_key=cost_key).first()
    if existing:
        data = existing.metadata
        return MysteryBoxResult(
            reward_type=data["reward_type"],
            chips=int(data.get("chips", 0)),
            xp=int(data.get("xp", 0)),
            item_type=data.get("item_type"),
            level_rewards=tuple(tuple(row) for row in data.get("level_rewards", [])),
            replayed=True,
        )

    player = Player.objects.select_for_update().get(pk=player_id)
    cost_change = adjust_balance(
        player,
        -cost,
        category=ChipTransaction.Category.ITEM_PURCHASE,
        description=f"Opened mystery box {box_key}",
        reference_type="mystery_box",
        reference_id=box_key,
        idempotency_key=cost_key,
    )

    chips = 0
    xp = 0
    item_type = None
    level_rewards: list[tuple[int, int]] = []
    if reward_type == "chips":
        chips = int(reward_value or 0)
        if chips:
            adjust_balance(
                player,
                chips,
                category=ChipTransaction.Category.MINIGAME_PAYOUT,
                description=f"Mystery box chip reward from {box_key}",
                reference_type="mystery_box",
                reference_id=box_key,
                idempotency_key=f"mystery:{operation_id}:chips",
            )
    elif reward_type == "xp":
        xp = int(reward_value or 0)
        player.xp += xp
        total_level_chips = 0
        while player.xp >= player.level * 50:
            player.xp -= player.level * 50
            player.level += 1
            reward = player.level * 50
            total_level_chips += reward
            level_rewards.append((player.level, reward))
        player.save(update_fields=("xp", "level"))
        if total_level_chips:
            adjust_balance(
                player,
                total_level_chips,
                category=ChipTransaction.Category.LEVEL_REWARD,
                description="Level rewards earned from mystery-box XP",
                reference_type="mystery_box",
                reference_id=box_key,
                idempotency_key=f"mystery:{operation_id}:levels",
            )
    elif reward_type == "item" and reward_value:
        item_type = str(reward_value)
        item, _ = PlayerItem.objects.select_for_update().get_or_create(
            player=player,
            item_type=item_type,
            defaults={"quantity": 0},
        )
        item.quantity += 1
        item.save(update_fields=("quantity",))

    result = MysteryBoxResult(
        reward_type=reward_type,
        chips=chips,
        xp=xp,
        item_type=item_type,
        level_rewards=tuple(level_rewards),
    )
    cost_change.transaction.metadata = {
        "reward_type": result.reward_type,
        "chips": result.chips,
        "xp": result.xp,
        "item_type": result.item_type,
        "level_rewards": list(result.level_rewards),
    }
    cost_change.transaction.save(update_fields=("metadata",))
    return result


async def open_mystery_box_async(*args, **kwargs) -> MysteryBoxResult:
    return await sync_to_async(open_mystery_box, thread_sensitive=True)(*args, **kwargs)
