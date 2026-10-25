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


# ── Season 1 competitions ───────────────────────────────────────────────────
SEASON_STARTING_CHIPS = 10_000
SEASON_LENGTH_DAYS = 28
# Prizes by finishing rank (index 0 = 1st place).
SEASON_PRIZES = (100_000, 60_000, 40_000, 25_000, 20_000, 15_000, 12_000, 10_000, 8_000, 5_000)
WEEKLY_PRIZES = (25_000, 15_000, 10_000, 6_000, 4_000)
TOURNAMENT_SPLIT = (Decimal("0.5"), Decimal("0.3"), Decimal("0.2"))
TOURNAMENT_PRIZE_POOL = 30_000
TOURNAMENT_HOUR_UTC = 17  # 20:30 Tehran
TOURNAMENT_LENGTH_HOURS = 2
# Weekday (Mon=0) → tournament kind; one tournament per evening.
TOURNAMENT_ROTATION = {
    0: "blackjack",
    1: "horses",
    2: "minigames",
    3: "blackjack",
    4: "poker",
    5: "horses",
    6: "all",
}
# A score has to be positive to win anything, so idle players never collect.
MIN_COMPETITION_SCORE = 1

DAILY_STREAK_BONUS = 1_000  # times streak length, capped below
DAILY_STREAK_BONUS_CAP = 7_000
STARTER_HORSE_POWERUP_USES = 5


def tournament_prizes(pool: int) -> tuple[int, ...]:
    return tuple(
        int((Decimal(pool) * share).to_integral_value(rounding=ROUND_DOWN))
        for share in TOURNAMENT_SPLIT
    )
