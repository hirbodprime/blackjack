"""Mutual-exclusion checks for shared, turn-based group tables."""

from game.models import Game, PokerTable


class GroupTableBusy(RuntimeError):
    pass


def ensure_blackjack_can_open(chat_id: int | str) -> None:
    table = PokerTable.objects.filter(chat_id=int(chat_id)).exclude(
        status=PokerTable.Status.CLOSED
    ).first()
    if table:
        raise GroupTableBusy(f"Poker table #{table.pk} is already open in this group. Cash out and close it first.")


def ensure_poker_can_open(chat_id: int | str) -> None:
    if Game.objects.filter(chat_id=str(chat_id), ended=False).exists():
        raise GroupTableBusy("A Blackjack game is already open in this group. Finish or cancel it first.")
