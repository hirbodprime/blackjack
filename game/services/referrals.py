"""Atomic and auditable referral rewards."""

from asgiref.sync import sync_to_async
from django.db import transaction

from game.models import ChipTransaction, Player, ReferralEarning
from game.services.economy import BalanceChange, adjust_balance


@transaction.atomic
def award_referral_bonus(
    referrer_id: int,
    referred_id: int,
    amount: int,
    *,
    description: str,
    idempotency_key: str | None = None,
) -> BalanceChange:
    referrer = Player.objects.select_for_update().get(pk=referrer_id)
    change = adjust_balance(
        referrer,
        amount,
        category=ChipTransaction.Category.REFERRAL_REWARD,
        description=description,
        reference_type="referral",
        reference_id=referred_id,
        idempotency_key=idempotency_key,
        metadata={"referred_player_id": referred_id},
    )
    if change.applied:
        referrer.total_referral_bonus += amount
        referrer.save(update_fields=("total_referral_bonus",))
        ReferralEarning.objects.create(
            referrer=referrer,
            referred_id=referred_id,
            amount=amount,
        )
    return change


async def award_referral_bonus_async(*args, **kwargs) -> BalanceChange:
    return await sync_to_async(award_referral_bonus, thread_sensitive=True)(*args, **kwargs)
