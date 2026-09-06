"""Atomic horse-race betting operations."""

from asgiref.sync import sync_to_async
from django.db import transaction
from django.utils import timezone

from game.models import ChipTransaction, HorseBet, HorseRace, Player
from game.services.economy import InsufficientChips, adjust_balance
from game.services.operations import BettingPaused, ensure_betting_open


class AlreadyBet(ValueError):
    """Raised when a player already has a bet in a race."""


class RaceAlreadyStarted(ValueError):
    """Raised when a bet targets a race that has begun."""


class ActiveRaceBet(ValueError):
    """Raised when a player already has a bet in another live race."""


@transaction.atomic
def place_race_bet(
    *,
    race_id: int,
    player_id: int,
    horse_number: int,
    amount: int,
    username: str,
) -> HorseBet:
    ensure_betting_open()
    race = HorseRace.objects.select_for_update().get(pk=race_id)
    player = Player.objects.select_for_update().get(pk=player_id)
    if race.race_started or race.completed:
        raise RaceAlreadyStarted
    existing_bet = HorseBet.objects.filter(
        user_id=player_id, race__completed=False
    ).first()
    if existing_bet:
        if existing_bet.race_id == race.pk:
            raise AlreadyBet
        raise ActiveRaceBet

    adjust_balance(
        player,
        -amount,
        category=ChipTransaction.Category.BET,
        description=f"Horse race bet on horse {horse_number}",
        reference_type="horse_race",
        reference_id=race.pk,
    )
    return HorseBet.objects.create(
        race=race,
        user_id=player_id,
        horse_number=horse_number,
        bet_amount=amount,
        username=username,
    )


@transaction.atomic
def complete_race(race_id: int) -> bool:
    """Close a persisted race exactly once after its result is recorded."""
    return bool(HorseRace.objects.filter(pk=race_id, completed=False).update(
        completed=True, completed_at=timezone.now()
    ))


@transaction.atomic
def repair_recorded_races(chat_id: int | None = None) -> int:
    """Repair legacy races that have a winner record but were never closed."""
    races = HorseRace.objects.filter(completed=False, wins__isnull=False)
    if chat_id is not None:
        races = races.filter(chat_id=chat_id)
    return races.update(completed=True, completed_at=timezone.now())


async def place_race_bet_async(**kwargs) -> HorseBet:
    return await sync_to_async(place_race_bet, thread_sensitive=True)(**kwargs)


complete_race_async = sync_to_async(complete_race, thread_sensitive=True)
repair_recorded_races_async = sync_to_async(repair_recorded_races, thread_sensitive=True)


__all__ = [
    "AlreadyBet",
    "ActiveRaceBet",
    "BettingPaused",
    "InsufficientChips",
    "RaceAlreadyStarted",
    "complete_race_async",
    "place_race_bet_async",
    "repair_recorded_races_async",
]
