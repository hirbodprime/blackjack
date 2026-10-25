"""Core blackjack card operations.

This module deliberately has no Django or Telegram dependencies so the rules
can be tested without starting the bot.
"""

import random
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Generic, TypeAlias, TypeVar


Card: TypeAlias = int | str
Seat = TypeVar("Seat")

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


@dataclass(frozen=True)
class RoundResult(Generic[Seat]):
    dealer_value: int
    dealer_busted: bool
    winners: tuple[Seat, ...]
    winning_value: int


def all_players_busted(hands: Iterable[Sequence[Card]]) -> bool:
    """True when no hand is 21 or under (including when there are no hands)."""
    return all(calculate_hand_value(hand) > 21 for hand in hands)


def resolve_round(
    dealer_hand: Sequence[Card],
    seats: Iterable[tuple[Seat, Sequence[Card]]],
) -> RoundResult[Seat]:
    """Find the round winners: the highest non-busted hands that beat the dealer.

    Ties at the top all win, in seat order. With no winner the dealer takes
    the round.
    """
    dealer_value = calculate_hand_value(dealer_hand)
    dealer_busted = dealer_value > 21
    winning_value = 0
    winners = []

    for seat, hand in seats:
        value = calculate_hand_value(hand)
        if value > 21 or not (dealer_busted or value > dealer_value):
            continue
        if value > winning_value:
            winning_value = value
            winners = [seat]
        elif value == winning_value:
            winners.append(seat)

    return RoundResult(dealer_value, dealer_busted, tuple(winners), winning_value)


def format_cards(hand: Iterable[Card]) -> str:
    """Render cards as 『K』『7』 — safe inside Telegram MarkdownV2 and plain text."""
    return "".join(f"『{card}』" for card in hand)


def format_hand(hand: Sequence[Card]) -> str:
    value = calculate_hand_value(hand)
    flag = " 💥" if value > 21 else " ⭐" if value == 21 else ""
    return f"{format_cards(hand)} → {value}{flag}"
