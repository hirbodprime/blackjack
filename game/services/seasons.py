"""Season lifecycle: points, standings, the relaunch reset, and settlement."""

from datetime import timedelta

from asgiref.sync import sync_to_async
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from game.economy_config import SEASON_LENGTH_DAYS, SEASON_PRIZES
from game.models import (
    ChipTransaction, CompetitionPayout, Player, Season, SeasonProgress,
)
from game.services.economy import adjust_balance


def active_season() -> Season | None:
    return Season.objects.filter(is_active=True).first()


def add_season_points(player_id: int, points: int) -> None:
    """Season points mirror XP earned while a season is running."""
    if points <= 0:
        return
    season = active_season()
    if season is None or timezone.now() >= season.ends_at:
        return
    progress, _ = SeasonProgress.objects.get_or_create(season=season, player_id=player_id)
    SeasonProgress.objects.filter(pk=progress.pk).update(points=F("points") + points)


def standings(season: Season, limit: int = 10) -> list[SeasonProgress]:
    return list(
        SeasonProgress.objects.filter(season=season, points__gt=0)
        .select_related("player")
        .order_by("-points", "updated_at")[:limit]
    )


def player_position(season: Season, player_id: int) -> tuple[int, int] | None:
    """Return ``(rank, points)`` or ``None`` when the player has no points yet."""
    mine = SeasonProgress.objects.filter(season=season, player_id=player_id).first()
    if mine is None or mine.points == 0:
        return None
    ahead = SeasonProgress.objects.filter(season=season, points__gt=mine.points).count()
    return ahead + 1, mine.points


@transaction.atomic
def start_season(number: int, name: str, starting_chips: int, *, reset_balances: bool) -> Season:
    """Open a season. With ``reset_balances`` every player is set to ``starting_chips``.

    Loans are forgiven along with the reset, and every change goes through the
    ledger so the reset is fully auditable.
    """
    Season.objects.filter(is_active=True).update(is_active=False)
    now = timezone.now()
    season = Season.objects.create(
        number=number, name=name, starts_at=now,
        ends_at=now + timedelta(days=SEASON_LENGTH_DAYS),
        starting_chips=starting_chips, is_active=True,
    )
    if reset_balances:
        for player in Player.objects.select_for_update().order_by("pk"):
            delta = starting_chips - player.chips
            if delta:
                adjust_balance(
                    player, delta,
                    category=ChipTransaction.Category.SEASON_RESET,
                    description=f"Season {number} reset to {starting_chips:,}",
                    reference_type="season", reference_id=season.pk,
                    idempotency_key=f"season:{season.pk}:reset:{player.pk}",
                    metadata={"previous_balance": player.chips, "previous_loan": player.loan},
                    allow_negative=True,
                )
        Player.objects.filter(loan__gt=0).update(loan=0)
    return season


@transaction.atomic
def settle_season(season_id: int) -> list[CompetitionPayout]:
    """Pay the season's top players once and close it. Safe to call repeatedly."""
    from game.services.achievements import unlock

    season = Season.objects.select_for_update().get(pk=season_id)
    if season.settled_at:
        return []
    key = f"season:{season.number}"
    payouts = []
    for rank, row in enumerate(standings(season, len(SEASON_PRIZES)), start=1):
        prize = SEASON_PRIZES[rank - 1]
        payout, created = CompetitionPayout.objects.get_or_create(
            competition=key, rank=rank,
            defaults={"player": row.player, "score": row.points, "prize_chips": prize},
        )
        if created:
            adjust_balance(
                row.player, prize,
                category=ChipTransaction.Category.COMPETITION_PRIZE,
                description=f"Season {season.number} – #{rank}",
                reference_type="season", reference_id=season.pk,
                idempotency_key=f"{key}:rank:{rank}",
            )
            unlock(row.player, "season_top10")
            if rank == 1:
                unlock(row.player, "season_champion")
            payouts.append(payout)
    season.settled_at = timezone.now()
    season.is_active = False
    season.save(update_fields=("settled_at", "is_active"))
    return payouts


active_season_async = sync_to_async(active_season, thread_sensitive=True)
standings_async = sync_to_async(standings, thread_sensitive=True)
player_position_async = sync_to_async(player_position, thread_sensitive=True)
