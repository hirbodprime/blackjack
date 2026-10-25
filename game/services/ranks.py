"""Level curve, rank tiers, and progress rendering shared by every surface."""

from dataclasses import dataclass


@dataclass(frozen=True)
class RankTier:
    key: str
    emoji: str
    name: str
    min_level: int


RANK_TIERS = (
    RankTier("bronze", "🥉", "Bronze", 1),
    RankTier("silver", "🥈", "Silver", 5),
    RankTier("gold", "🥇", "Gold", 10),
    RankTier("platinum", "💠", "Platinum", 20),
    RankTier("diamond", "💎", "Diamond", 30),
    RankTier("master", "👑", "Master", 45),
    RankTier("legend", "🌟", "Legend", 60),
)

ROMAN = ("I", "II", "III")


def xp_for_level(level: int) -> int:
    """XP needed to advance from ``level`` to ``level + 1``.

    Gentle early levels so returning players rank up within a session, then a
    quadratic tail so Legend stays rare.
    """
    step = max(1, level) - 1
    return 100 + 40 * step + 5 * step * step


def level_reward(level: int) -> int:
    """Chips granted on reaching ``level``; every fifth level is a milestone."""
    reward = 100 * level
    if level % 5 == 0:
        reward += 1_000 * (level // 5)
    return reward


def rank_for_level(level: int) -> RankTier:
    tier = RANK_TIERS[0]
    for candidate in RANK_TIERS:
        if level >= candidate.min_level:
            tier = candidate
    return tier


def next_rank(level: int) -> RankTier | None:
    for candidate in RANK_TIERS:
        if candidate.min_level > level:
            return candidate
    return None


def rank_label(level: int) -> str:
    """Return e.g. ``🥇 Gold II``; Legend has no division."""
    tier = rank_for_level(level)
    following = next_rank(level)
    if following is None:
        return f"{tier.emoji} {tier.name}"
    span = following.min_level - tier.min_level
    division = min(2, (level - tier.min_level) * 3 // span)
    return f"{tier.emoji} {tier.name} {ROMAN[division]}"


def progress_bar(current: int, total: int, width: int = 10) -> str:
    if total <= 0:
        return "▰" * width
    filled = max(0, min(width, round(width * current / total)))
    return "▰" * filled + "▱" * (width - filled)


def level_line(level: int, xp: int) -> str:
    need = xp_for_level(level)
    return f"Lv {level} {progress_bar(xp, need)} {xp:,}/{need:,} XP"
