"""Central economy policy. Values here are intentionally easy to review."""

from decimal import Decimal, ROUND_DOWN


STANDARD_WIN_MULTIPLIER = Decimal("1.90")
SLOT_PAIR_MULTIPLIER = 2
SLOT_JACKPOT_MULTIPLIER = 10
REFERRAL_SHARE_RATE = Decimal("0.01")
SIGNUP_REFERRER_REWARD = 300
SIGNUP_REFERRED_REWARD = 100
MYSTERY_BOX_COOLDOWN_SECONDS = 30
HORSE_RACE_PAYOUT_RATE = Decimal("0.95")
POTION_BONUS_CAPS = {2: 60_000, 3: 160_000, 10: 800_000}


def standard_win_payout(bet: int) -> int:
    """Return stake plus winnings at a 1.9x gross payout."""
    return int((Decimal(bet) * STANDARD_WIN_MULTIPLIER).to_integral_value(
        rounding=ROUND_DOWN
    ))


def referral_share(winnings: int) -> int:
    return int((Decimal(winnings) * REFERRAL_SHARE_RATE).to_integral_value(
        rounding=ROUND_DOWN
    ))


def horse_race_payout_pool(total_stakes: int) -> int:
    return int((Decimal(total_stakes) * HORSE_RACE_PAYOUT_RATE).to_integral_value(
        rounding=ROUND_DOWN
    ))


def apply_potion_multiplier(base_reward: int, multiplier: int) -> int:
    if multiplier <= 1:
        return base_reward
    bonus = base_reward * (multiplier - 1)
    return base_reward + min(bonus, POTION_BONUS_CAPS[multiplier])
