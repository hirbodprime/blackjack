"""Atomic, auditable chip balance operations."""

from dataclasses import dataclass
from typing import Any

from asgiref.sync import sync_to_async
from django.db import transaction

from game.models import ChipTransaction, Dealer, Player, PlayerItem
from game.services.ranks import xp_for_level


class InsufficientChips(ValueError):
    """Raised when a debit would make a protected balance negative."""


class InsufficientDealerChips(ValueError):
    """Raised when the casino cannot fund a requested loan."""


class InsufficientExperience(ValueError):
    """Raised when a player cannot pay a loan's XP cost."""


class NoOutstandingLoan(ValueError):
    """Raised when a player tries to repay without an active loan."""


class SelfTransfer(ValueError):
    """Raised when both sides of a transfer are the same player."""


class TransactionAlreadyReversed(ValueError):
    """Raised when an operator tries to reverse the same ledger entry twice."""


@dataclass(frozen=True)
class BalanceChange:
    transaction: ChipTransaction
    applied: bool

    @property
    def balance(self) -> int:
        return self.transaction.balance_after


@transaction.atomic
def adjust_balance(
    player: Player | int,
    amount: int,
    *,
    category: str,
    description: str = "",
    reference_type: str = "",
    reference_id: str | int = "",
    idempotency_key: str | None = None,
    metadata: dict[str, Any] | None = None,
    allow_negative: bool = False,
) -> BalanceChange:
    """Apply one balance mutation and record it in the same transaction."""
    if not isinstance(amount, int) or isinstance(amount, bool):
        raise TypeError("amount must be an integer")
    if amount == 0:
        raise ValueError("amount must not be zero")

    if idempotency_key:
        existing = ChipTransaction.objects.filter(idempotency_key=idempotency_key).first()
        if existing:
            return BalanceChange(transaction=existing, applied=False)

    player_id = player.pk if isinstance(player, Player) else player
    locked_player = Player.objects.select_for_update().get(pk=player_id)
    balance_before = locked_player.chips
    balance_after = balance_before + amount

    if balance_after < 0 and not allow_negative:
        raise InsufficientChips(
            f"Player {locked_player.pk} has {balance_before:,} chips; "
            f"cannot apply {amount:+,}."
        )

    locked_player.chips = balance_after
    locked_player.save(update_fields=("chips",))
    ledger_entry = ChipTransaction.objects.create(
        player=locked_player,
        amount=amount,
        balance_before=balance_before,
        balance_after=balance_after,
        category=category,
        description=description,
        reference_type=reference_type,
        reference_id=str(reference_id) if reference_id != "" else "",
        idempotency_key=idempotency_key,
        metadata=metadata or {},
    )

    if isinstance(player, Player):
        player.chips = balance_after

    return BalanceChange(transaction=ledger_entry, applied=True)


async def adjust_balance_async(*args, **kwargs) -> BalanceChange:
    """Async-safe wrapper for Telegram handlers."""
    return await sync_to_async(adjust_balance, thread_sensitive=True)(*args, **kwargs)


@transaction.atomic
def reverse_chip_transaction(transaction_id: int, *, operator: str) -> BalanceChange:
    original = ChipTransaction.objects.select_for_update().get(pk=transaction_id)
    reversal_key = f"reversal:{original.pk}"
    if ChipTransaction.objects.filter(idempotency_key=reversal_key).exists():
        raise TransactionAlreadyReversed
    return adjust_balance(
        original.player_id,
        -original.amount,
        category=ChipTransaction.Category.ADMIN_ADJUSTMENT,
        description=f"Reversal of transaction {original.pk} by {operator}",
        reference_type="chip_transaction",
        reference_id=original.pk,
        idempotency_key=reversal_key,
        metadata={"reverses_transaction_id": original.pk, "operator": operator},
    )


def _xp_for_next_level(level: int) -> int:
    return xp_for_level(level)


@transaction.atomic
def issue_loan(player_id: int, amount: int, xp_cost: int) -> BalanceChange:
    player = Player.objects.select_for_update().get(pk=player_id)
    dealer = Dealer.objects.select_for_update().first()
    if dealer is None or dealer.chips < amount:
        raise InsufficientDealerChips

    remaining_xp = player.xp - xp_cost
    level = player.level
    while remaining_xp < 0 and level > 1:
        level -= 1
        remaining_xp += _xp_for_next_level(level)
    if remaining_xp < 0:
        raise InsufficientExperience

    change = adjust_balance(
        player,
        amount,
        category=ChipTransaction.Category.LOAN,
        description="Casino loan issued",
        reference_type="loan",
        reference_id=player_id,
    )
    player.xp = remaining_xp
    player.level = level
    player.loan += amount
    player.save(update_fields=("xp", "level", "loan"))
    dealer.chips -= amount
    dealer.save(update_fields=("chips",))
    return change


async def issue_loan_async(player_id: int, amount: int, xp_cost: int) -> BalanceChange:
    return await sync_to_async(issue_loan, thread_sensitive=True)(player_id, amount, xp_cost)


@transaction.atomic
def repay_loan(player_id: int) -> tuple[BalanceChange, int]:
    player = Player.objects.select_for_update().get(pk=player_id)
    dealer = Dealer.objects.select_for_update().first()
    if player.loan <= 0:
        raise NoOutstandingLoan

    repayment = int(player.loan * 1.03)
    change = adjust_balance(
        player,
        -repayment,
        category=ChipTransaction.Category.LOAN_REPAYMENT,
        description="Casino loan repayment including interest",
        reference_type="loan",
        reference_id=player_id,
    )
    player.loan = 0
    player.save(update_fields=("loan",))
    if dealer is not None:
        dealer.chips += repayment
        dealer.save(update_fields=("chips",))
    return change, repayment


async def repay_loan_async(player_id: int) -> tuple[BalanceChange, int]:
    return await sync_to_async(repay_loan, thread_sensitive=True)(player_id)


@transaction.atomic
def transfer_chips(
    giver_id: int,
    receiver_id: int,
    amount: int,
    *,
    idempotency_key: str | None = None,
) -> tuple[BalanceChange, BalanceChange]:
    if giver_id == receiver_id:
        raise SelfTransfer
    locked = {
        player.pk: player
        for player in Player.objects.select_for_update().filter(
            pk__in=sorted((giver_id, receiver_id))
        )
    }
    giver = locked[giver_id]
    receiver = locked[receiver_id]
    reference = idempotency_key or f"{giver_id}:{receiver_id}"
    debit = adjust_balance(
        giver,
        -amount,
        category=ChipTransaction.Category.TRANSFER,
        description=f"Transfer to player {receiver_id}",
        reference_type="player_transfer",
        reference_id=reference,
        idempotency_key=f"{idempotency_key}:debit" if idempotency_key else None,
        metadata={"counterparty_id": receiver_id},
    )
    credit = adjust_balance(
        receiver,
        amount,
        category=ChipTransaction.Category.TRANSFER,
        description=f"Transfer from player {giver_id}",
        reference_type="player_transfer",
        reference_id=reference,
        idempotency_key=f"{idempotency_key}:credit" if idempotency_key else None,
        metadata={"counterparty_id": giver_id},
    )
    return debit, credit


async def transfer_chips_async(*args, **kwargs):
    return await sync_to_async(transfer_chips, thread_sensitive=True)(*args, **kwargs)


@transaction.atomic
def purchase_item(player_id: int, item_type: str, cost: int) -> PlayerItem:
    player = Player.objects.select_for_update().get(pk=player_id)
    adjust_balance(
        player,
        -cost,
        category=ChipTransaction.Category.ITEM_PURCHASE,
        description=f"Purchased item {item_type}",
        reference_type="player_item",
        reference_id=item_type,
    )
    item, _ = PlayerItem.objects.select_for_update().get_or_create(
        player=player,
        item_type=item_type,
        defaults={"quantity": 0},
    )
    item.quantity += 1
    item.save(update_fields=("quantity",))
    return item


async def purchase_item_async(player_id: int, item_type: str, cost: int) -> PlayerItem:
    return await sync_to_async(purchase_item, thread_sensitive=True)(
        player_id,
        item_type,
        cost,
    )
