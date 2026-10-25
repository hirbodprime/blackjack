"""Mini-app leaderboards: net winnings per game, globally or for one group.

Arcade rounds carry the group they were opened from; roulette bets inherit
their table's group. Score = payouts minus stakes over settled play only.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from django.db.models import Count, F, Max, Sum

from game.models import ArcadeRound, Player, RouletteTable, RouletteTableBet
from game.services.competitions import week_bounds


ARCADE_GAMES = tuple(ArcadeRound.Game.values)
GAMES = ("all", *ARCADE_GAMES, "roulette")
PERIODS = ("week", "all")


@dataclass
class RankRow:
    player_id: int
    name: str = ""
    score: int = 0
    rounds: int = 0
    best: str | None = None  # best cash-out multiplier, arcade only


def _since(period: str) -> datetime | None:
    return week_bounds()[0] if period == "week" else None


def _arcade_totals(game: str, chat_id: int | None, since: datetime | None) -> dict[int, RankRow]:
    rounds = ArcadeRound.objects.exclude(status=ArcadeRound.Status.ACTIVE)
    if game != "all":
        rounds = rounds.filter(game=game)
    if chat_id is not None:
        rounds = rounds.filter(chat_id=chat_id)
    if since is not None:
        rounds = rounds.filter(created_at__gte=since)
    totals = rounds.values("player_id").annotate(net=Sum(F("payout") - F("bet")), n=Count("id"))
    best = dict(
        rounds.filter(status=ArcadeRound.Status.WON).values("player_id")
        .annotate(m=Max("multiplier")).values_list("player_id", "m")
    )
    return {
        r["player_id"]: RankRow(
            r["player_id"], score=r["net"], rounds=r["n"],
            best=f"{Decimal(best[r['player_id']]):.2f}" if r["player_id"] in best else None,
        )
        for r in totals
    }


def _roulette_totals(chat_id: int | None, since: datetime | None) -> dict[int, RankRow]:
    bets = RouletteTableBet.objects.filter(table__status=RouletteTable.Status.COMPLETE)
    if chat_id is not None:
        bets = bets.filter(table__chat_id=chat_id)
    if since is not None:
        bets = bets.filter(created_at__gte=since)
    totals = bets.values("player_id").annotate(net=Sum(F("payout") - F("amount")), n=Count("table_id", distinct=True))
    return {r["player_id"]: RankRow(r["player_id"], score=r["net"], rounds=r["n"]) for r in totals}


def _totals(game: str, chat_id: int | None, period: str) -> dict[int, RankRow]:
    since = _since(period)
    if game == "roulette":
        return _roulette_totals(chat_id, since)
    rows = _arcade_totals(game, chat_id, since)
    if game == "all":
        for pid, r in _roulette_totals(chat_id, since).items():
            merged = rows.setdefault(pid, RankRow(pid))
            merged.score += r.score
            merged.rounds += r.rounds
    return rows


def leaderboard(game: str = "all", chat_id: int | None = None, period: str = "week",
                player_id: int | None = None, limit: int = 10) -> dict:
    """Top ``limit`` by net winnings, plus the viewer's own rank when given."""
    if game not in GAMES:
        raise ValueError("Unknown game.")
    if period not in PERIODS:
        raise ValueError("Unknown period.")
    rows = sorted(_totals(game, chat_id, period).values(), key=lambda r: (-r.score, -r.rounds, r.player_id))
    names = dict(Player.objects.filter(pk__in=[r.player_id for r in rows[:limit]] + [player_id or 0])
                 .values_list("pk", "name"))
    for r in rows:
        r.name = names.get(r.player_id, "")

    def public(position, r):
        return {"rank": position, "name": r.name, "score": r.score, "rounds": r.rounds,
                "best": r.best, "me": r.player_id == player_id}

    top = [public(i, r) for i, r in enumerate(rows[:limit], start=1)]
    me = next((public(i, r) for i, r in enumerate(rows, start=1) if r.player_id == player_id), None)
    return {"game": game, "period": period, "players": len(rows), "top": top, "me": me}
