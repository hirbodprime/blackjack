"""Weekly leaderboards and tournaments, scored straight from the chip ledger.

A player's score for a window is their net game result (payouts and refunds
minus stakes), so no game needs extra bookkeeping to take part.
"""

from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone as dt_timezone

from asgiref.sync import sync_to_async
from django.db import IntegrityError, transaction
from django.db.models import Q, Sum
from django.utils import timezone

from game.economy_config import (
    MIN_COMPETITION_SCORE, TOURNAMENT_HOUR_UTC, TOURNAMENT_LENGTH_HOURS,
    TOURNAMENT_PRIZE_POOL, TOURNAMENT_ROTATION, WEEKLY_PRIZES, tournament_prizes,
)
from game.models import ChipTransaction, CompetitionPayout, Player, Tournament
from game.services.economy import adjust_balance


GAME_CATEGORIES = (
    ChipTransaction.Category.BET,
    ChipTransaction.Category.REFUND,
    ChipTransaction.Category.BLACKJACK_PAYOUT,
    ChipTransaction.Category.POKER_BUY_IN,
    ChipTransaction.Category.POKER_CASH_OUT,
    ChipTransaction.Category.RACE_PAYOUT,
    ChipTransaction.Category.MINIGAME_PAYOUT,
)

KIND_REFERENCE_TYPES = {
    Tournament.Kind.BLACKJACK: ("blackjack_game",),
    Tournament.Kind.HORSES: ("horse_race",),
    Tournament.Kind.POKER: ("poker_table",),
    Tournament.Kind.MINIGAMES: (
        "minigame", "telegram_update", "spin", "roulette", "crash_game",
        "roulette_table", "friend_challenge",
    ),
}

KIND_EMOJI = {
    Tournament.Kind.BLACKJACK: "🃏",
    Tournament.Kind.HORSES: "🏇",
    Tournament.Kind.POKER: "♠️",
    Tournament.Kind.MINIGAMES: "🎰",
    Tournament.Kind.ALL: "🎪",
}


def _display_name(name: str, title: str) -> str:
    return f"{name} · {title}" if title else name


@dataclass(frozen=True)
class ScoreRow:
    player_id: int
    name: str
    score: int


def _game_rows(kind: str = Tournament.Kind.ALL):
    rows = ChipTransaction.objects.filter(category__in=GAME_CATEGORIES)
    if kind == Tournament.Kind.ALL:
        return rows.exclude(reference_type="mystery_box")
    return rows.filter(reference_type__in=KIND_REFERENCE_TYPES[kind])


def leaderboard(start: datetime, end: datetime, kind: str = Tournament.Kind.ALL, limit: int = 10) -> list[ScoreRow]:
    totals = (
        _game_rows(kind)
        .filter(created_at__gte=start, created_at__lt=end)
        .values("player_id", "player__name", "player__title")
        .annotate(score=Sum("amount"))
        .filter(score__gte=MIN_COMPETITION_SCORE)
        .order_by("-score", "player_id")[:limit]
    )
    return [ScoreRow(r["player_id"], _display_name(r["player__name"], r["player__title"]), r["score"]) for r in totals]


def player_score(player_id: int, start: datetime, end: datetime, kind: str = Tournament.Kind.ALL) -> int:
    total = (
        _game_rows(kind)
        .filter(player_id=player_id, created_at__gte=start, created_at__lt=end)
        .aggregate(total=Sum("amount"))["total"]
    )
    return total or 0


# ── Weekly leaderboard ──────────────────────────────────────────────────────

def week_bounds(moment: datetime | None = None) -> tuple[datetime, datetime]:
    """Monday 00:00 UTC to the next Monday."""
    moment = moment or timezone.now()
    monday = (moment - timedelta(days=moment.weekday())).date()
    start = datetime.combine(monday, time.min, tzinfo=dt_timezone.utc)
    return start, start + timedelta(days=7)


def week_key(start: datetime) -> str:
    year, week, _ = start.isocalendar()
    return f"weekly:{year}-W{week:02d}"


def _pay(key: str, rank: int, row: ScoreRow, prize: int, description: str) -> CompetitionPayout | None:
    try:
        with transaction.atomic():
            payout = CompetitionPayout.objects.create(
                competition=key, rank=rank, player_id=row.player_id,
                score=row.score, prize_chips=prize,
            )
            adjust_balance(
                row.player_id, prize,
                category=ChipTransaction.Category.COMPETITION_PRIZE,
                description=description, reference_type="competition",
                reference_id=key, idempotency_key=f"{key}:rank:{rank}",
            )
    except IntegrityError:
        return None  # already paid by an earlier tick
    return payout


def settle_week(start: datetime, not_before: datetime | None = None) -> list[CompetitionPayout]:
    """Pay the week that began at ``start``; ``not_before`` ignores pre-season play."""
    from game.services.achievements import unlock

    key = week_key(start)
    paid = []
    window_start = max(start, not_before) if not_before else start
    rows = leaderboard(window_start, start + timedelta(days=7), limit=len(WEEKLY_PRIZES))
    for rank, row in enumerate(rows, start=1):
        payout = _pay(key, rank, row, WEEKLY_PRIZES[rank - 1], f"Weekly leaderboard #{rank}")
        if payout:
            unlock(row.player_id, "weekly_top5")
            if rank == 1:
                unlock(row.player_id, "weekly_first")
            paid.append(payout)
    return paid


# ── Tournaments ─────────────────────────────────────────────────────────────

def tournament_title(kind: str) -> str:
    return f"{KIND_EMOJI[kind]} {Tournament.Kind(kind).label} Showdown"


def schedule_tournaments(days_ahead: int = 2, now: datetime | None = None) -> int:
    """Make sure each evening for the next few days has its rotation tournament."""
    now = now or timezone.now()
    created = 0
    for offset in range(days_ahead + 1):
        day = (now + timedelta(days=offset)).date()
        kind = TOURNAMENT_ROTATION[day.weekday()]
        starts = datetime.combine(day, time(TOURNAMENT_HOUR_UTC), tzinfo=dt_timezone.utc)
        _, was_created = Tournament.objects.get_or_create(
            kind=kind, starts_at=starts,
            defaults={
                "title": tournament_title(kind),
                "ends_at": starts + timedelta(hours=TOURNAMENT_LENGTH_HOURS),
                "prize_pool": TOURNAMENT_PRIZE_POOL,
            },
        )
        created += was_created
    return created


def live_tournament(now: datetime | None = None) -> Tournament | None:
    now = now or timezone.now()
    return Tournament.objects.filter(starts_at__lte=now, ends_at__gt=now).exclude(
        status=Tournament.Status.SETTLED
    ).first()


def next_tournament(now: datetime | None = None) -> Tournament | None:
    now = now or timezone.now()
    return Tournament.objects.filter(starts_at__gt=now).order_by("starts_at").first()


def tournament_standings(tournament: Tournament, limit: int = 10) -> list[ScoreRow]:
    return leaderboard(tournament.starts_at, tournament.ends_at, tournament.kind, limit)


def settle_tournament(tournament_id: int) -> list[CompetitionPayout]:
    from game.services.achievements import unlock

    tournament = Tournament.objects.get(pk=tournament_id)
    if tournament.status == Tournament.Status.SETTLED:
        return []
    prizes = tournament_prizes(tournament.prize_pool)
    key = f"tournament:{tournament.pk}"
    paid = []
    for rank, row in enumerate(tournament_standings(tournament, len(prizes)), start=1):
        payout = _pay(key, rank, row, prizes[rank - 1], f"{tournament.title} #{rank}")
        if payout:
            unlock(row.player_id, "tournament_podium")
            if rank == 1:
                unlock(row.player_id, "tournament_champion")
            paid.append(payout)
    Tournament.objects.filter(pk=tournament.pk).update(
        status=Tournament.Status.SETTLED, settled_at=timezone.now()
    )
    return paid


@dataclass
class TickReport:
    started: list
    settled: list  # (title, payouts)
    weekly: list
    season: list


def tick(now: datetime | None = None) -> TickReport:
    """Advance every automatic competition. Idempotent; run it every few minutes."""
    from game.services.seasons import active_season, settle_season

    now = now or timezone.now()
    report = TickReport([], [], [], [])
    season = active_season()
    if season is None:
        return report  # competitions only run inside a season
    schedule_tournaments(now=now)

    for tournament in Tournament.objects.filter(
        status=Tournament.Status.SCHEDULED, starts_at__lte=now, ends_at__gt=now
    ):
        Tournament.objects.filter(pk=tournament.pk).update(status=Tournament.Status.LIVE)
        tournament.status = Tournament.Status.LIVE
        report.started.append(tournament)

    for tournament in Tournament.objects.filter(
        ~Q(status=Tournament.Status.SETTLED), ends_at__lte=now
    ):
        report.settled.append((tournament, settle_tournament(tournament.pk)))

    previous_week_start, previous_week_end = week_bounds(now - timedelta(days=7))
    if previous_week_end > season.starts_at and not CompetitionPayout.objects.filter(
        competition=week_key(previous_week_start)
    ).exists():
        report.weekly = settle_week(previous_week_start, not_before=season.starts_at)

    if season.ends_at <= now:
        report.season = settle_season(season.pk)
    return report


tick_async = sync_to_async(tick, thread_sensitive=True)
leaderboard_async = sync_to_async(leaderboard, thread_sensitive=True)
player_score_async = sync_to_async(player_score, thread_sensitive=True)
live_tournament_async = sync_to_async(live_tournament, thread_sensitive=True)
next_tournament_async = sync_to_async(next_tournament, thread_sensitive=True)
tournament_standings_async = sync_to_async(tournament_standings, thread_sensitive=True)
