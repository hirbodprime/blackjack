"""Core blackjack card operations.

This module deliberately has no Django or Telegram dependencies so the rules
can be tested without starting the bot.
"""

import random
from collections.abc import Sequence
from typing import TypeAlias


Card: TypeAlias = int | str

DECK: list[Card] = [2, 3, 4, 5, 6, 7, 8, 9, 10, "J", "Q", "K", "A"] * 4

# Compatibility alias used throughout the existing bot.
deck = DECK


def deal_card() -> Card:
    """Return one randomly selected card from the existing four-suit deck."""
    return random.choice(DECK)


def calculate_hand_value(hand: Sequence[Card]) -> int:
    """Calculate a blackjack hand value, treating aces as 11 when safe."""
    value = 0
    aces = 0

    for card in hand:
        if card in ("J", "Q", "K"):
            value += 10
        elif card == "A":
            aces += 1
        else:
            value += card

    # Count every ace as one first, then promote one ace to eleven when safe.
    # At most one ace can be worth eleven in a non-busting blackjack hand.
    value += aces
    if aces and value + 10 <= 21:
        value += 10

    return value


def dealer_should_hit(hand: Sequence[Card]) -> bool:
    """Standard, auditable house rule: hit through 16 and stand on all 17s."""
    return calculate_hand_value(hand) < 17
