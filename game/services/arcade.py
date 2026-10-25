"""Server-authoritative solo games for the Arcade mini app: Crash, Mines, Hi-Lo.

The client only animates; every outcome is decided and checked here, and every
chip moves through the ledger (``reference_type="arcade"``).
"""

import hashlib
import hmac
import math
import secrets
from datetime import datetime
from decimal import ROUND_DOWN, Decimal

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from game.economy_config import (
    ARCADE_MAX_BET, ARCADE_MAX_PAYOUT, ARCADE_MIN_BET, ARCADE_RTP, CRASH_GROWTH_PER_SECOND,
    CRASH_RTP, MINES_CHOICES, MINES_TILES,
)
from game.models import ArcadeRound, ChipTransaction, Player
from game.services.economy import adjust_balance
from game.services.operations import ensure_betting_open


class ArcadeError(ValueError):
    pass


_rng = secrets.SystemRandom()
CENT = Decimal("0.01")
RANKS = "A23456789TJQK"  # index + 1 = rank value (A low)
SUITS = "♠♥♦♣"


def _floor2(value) -> Decimal:
    return Decimal(str(value)).quantize(CENT, rounding=ROUND_DOWN)


def _payout(bet: int, multiplier: Decimal) -> int:
    return min(ARCADE_MAX_PAYOUT, int((Decimal(bet) * multiplier).to_integral_value(rounding=ROUND_DOWN)))


def _active(player_id: int, game: str | None = None, *, lock: bool = True) -> ArcadeRound:
    rounds = ArcadeRound.objects.select_for_update() if lock else ArcadeRound.objects
    current = rounds.filter(player_id=player_id, status=ArcadeRound.Status.ACTIVE).first()
    if current is None or (game and current.game != game):
        raise ArcadeError("No active round.")
    return current


def _open(player_id: int, game: str, bet: int, state: dict, chat_id: int | None = None) -> ArcadeRound:
    ensure_betting_open()
    if not ARCADE_MIN_BET <= bet <= ARCADE_MAX_BET:
        raise ArcadeError(f"Bets are {ARCADE_MIN_BET:,}–{ARCADE_MAX_BET:,} chips.")
    player = Player.objects.select_for_update().get(pk=player_id)
    existing = ArcadeRound.objects.filter(player=player, status=ArcadeRound.Status.ACTIVE).first()
    if existing is not None:
        if existing.game == ArcadeRound.Game.CRASH and _crash_finished(existing):
            _settle(existing, won=False)
        else:
            raise ArcadeError("Finish your current round first.")
    round_ = ArcadeRound.objects.create(player=player, game=game, bet=bet, state=state, chat_id=chat_id)
    adjust_balance(
        player, -bet, category=ChipTransaction.Category.BET,
        description=f"Arcade {game} bet", reference_type="arcade", reference_id=round_.pk,
        idempotency_key=f"arcade:{round_.pk}:bet",
    )
    return round_


def _settle(round_: ArcadeRound, *, won: bool, multiplier: Decimal | None = None) -> ArcadeRound:
    round_.status = ArcadeRound.Status.WON if won else ArcadeRound.Status.LOST
    round_.settled_at = timezone.now()
    if won:
        round_.multiplier = multiplier
        round_.payout = _payout(round_.bet, multiplier)
        adjust_balance(
            round_.player_id, round_.payout, category=ChipTransaction.Category.MINIGAME_PAYOUT,
            description=f"Arcade {round_.game} cash-out at {multiplier}x",
            reference_type="arcade", reference_id=round_.pk,
            idempotency_key=f"arcade:{round_.pk}:payout",
        )
    round_.save(update_fields=("status", "settled_at", "multiplier", "payout"))
    return round_


# ── Crash ───────────────────────────────────────────────────────────────────

def crash_point() -> Decimal:
    """P(point ≥ m) = RTP / m, so a perfect cash-out strategy returns the RTP."""
    u = _rng.random()
    return max(Decimal("1.00"), min(Decimal("1000"), _floor2(float(CRASH_RTP) / (1 - u))))


def crash_multiplier_at(seconds: float) -> Decimal:
    return _floor2(math.exp(CRASH_GROWTH_PER_SECOND * max(0.0, seconds)))


def crash_seconds_to(multiplier: Decimal) -> float:
    return math.log(float(multiplier)) / CRASH_GROWTH_PER_SECOND


def _crash_started(round_: ArcadeRound) -> datetime:
    return datetime.fromisoformat(round_.state["started_at"])


def _crash_finished(round_: ArcadeRound, now: datetime | None = None) -> bool:
    now = now or timezone.now()
    elapsed = (now - _crash_started(round_)).total_seconds()
    return crash_multiplier_at(elapsed) >= Decimal(round_.state["point"])


@transaction.atomic
def crash_start(player_id: int, bet: int, chat_id: int | None = None) -> ArcadeRound:
    return _open(player_id, ArcadeRound.Game.CRASH, bet, {
        "point": str(crash_point()), "started_at": timezone.now().isoformat(),
    }, chat_id)


@transaction.atomic
def crash_cashout(player_id: int, now: datetime | None = None) -> ArcadeRound:
    round_ = _active(player_id, ArcadeRound.Game.CRASH)
    now = now or timezone.now()
    reached = crash_multiplier_at((now - _crash_started(round_)).total_seconds())
    if reached >= Decimal(round_.state["point"]):
        return _settle(round_, won=False)
    return _settle(round_, won=True, multiplier=max(Decimal("1.00"), reached))


# ── Mines ───────────────────────────────────────────────────────────────────

def mines_multiplier(mines: int, revealed: int) -> Decimal:
    odds = Decimal(1)
    for k in range(revealed):
        odds *= Decimal(MINES_TILES - k) / Decimal(MINES_TILES - mines - k)
    return _floor2(odds * ARCADE_RTP) if revealed else Decimal("1.00")


@transaction.atomic
def mines_start(player_id: int, bet: int, mines: int, chat_id: int | None = None) -> ArcadeRound:
    if mines not in MINES_CHOICES:
        raise ArcadeError("Choose 1, 3, 5 or 10 mines.")
    layout = _rng.sample(range(MINES_TILES), mines)
    return _open(player_id, ArcadeRound.Game.MINES, bet, {"mines": layout, "count": mines, "revealed": []}, chat_id)


@transaction.atomic
def mines_reveal(player_id: int, tile: int) -> ArcadeRound:
    round_ = _active(player_id, ArcadeRound.Game.MINES)
    state = round_.state
    if not 0 <= tile < MINES_TILES or tile in state["revealed"]:
        raise ArcadeError("Pick a hidden tile.")
    state["revealed"].append(tile)
    round_.state = state
    if tile in state["mines"]:
        state["boom"] = tile
        round_.save(update_fields=("state",))
        return _settle(round_, won=False)
    round_.multiplier = mines_multiplier(state["count"], len(state["revealed"]))
    round_.save(update_fields=("state", "multiplier"))
    if len(state["revealed"]) == MINES_TILES - state["count"]:
        return _settle(round_, won=True, multiplier=round_.multiplier)
    return round_


@transaction.atomic
def mines_cashout(player_id: int) -> ArcadeRound:
    round_ = _active(player_id, ArcadeRound.Game.MINES)
    if not round_.state["revealed"]:
        raise ArcadeError("Reveal at least one tile first.")
    return _settle(round_, won=True, multiplier=mines_multiplier(round_.state["count"], len(round_.state["revealed"])))


# ── Hi-Lo ───────────────────────────────────────────────────────────────────

def _draw() -> str:
    return _rng.choice(RANKS) + _rng.choice(SUITS)


def _rank(card: str) -> int:
    return RANKS.index(card[0]) + 1


def hilo_odds(card: str, guess: str) -> Decimal:
    """Probability of winning; ties count for the guesser ("higher or same")."""
    rank = _rank(card)
    wins = 14 - rank if guess == "higher" else rank
    return Decimal(wins) / Decimal(13)


def hilo_step_multiplier(card: str, guess: str) -> Decimal:
    return ARCADE_RTP / hilo_odds(card, guess)


@transaction.atomic
def hilo_start(player_id: int, bet: int, chat_id: int | None = None) -> ArcadeRound:
    return _open(player_id, ArcadeRound.Game.HILO, bet, {"cards": [_draw()], "mult": "1"}, chat_id)


@transaction.atomic
def hilo_guess(player_id: int, guess: str) -> ArcadeRound:
    if guess not in {"higher", "lower"}:
        raise ArcadeError("Guess higher or lower.")
    round_ = _active(player_id, ArcadeRound.Game.HILO)
    state = round_.state
    current = state["cards"][-1]
    if (guess == "higher" and _rank(current) == 13) or (guess == "lower" and _rank(current) == 1):
        raise ArcadeError("That guess can't win — pick the other one.")
    nxt = _draw()
    state["cards"].append(nxt)
    won = _rank(nxt) >= _rank(current) if guess == "higher" else _rank(nxt) <= _rank(current)
    round_.state = state
    if not won:
        round_.save(update_fields=("state",))
        return _settle(round_, won=False)
    mult = Decimal(state["mult"]) * hilo_step_multiplier(current, guess)
    state["mult"] = str(mult)
    round_.multiplier = _floor2(mult)
    round_.save(update_fields=("state", "multiplier"))
    return round_


@transaction.atomic
def hilo_cashout(player_id: int) -> ArcadeRound:
    round_ = _active(player_id, ArcadeRound.Game.HILO)
    if len(round_.state["cards"]) < 2:
        raise ArcadeError("Make at least one guess first.")
    return _settle(round_, won=True, multiplier=_floor2(Decimal(round_.state["mult"])))


# ── Group launch ────────────────────────────────────────────────────────────

GROUP_PREFIX = "ag"


def _group_signature(chat_id: int) -> str:
    return hmac.new(settings.SECRET_KEY.encode(), f"arcade-group:{chat_id}".encode(), hashlib.sha256).hexdigest()[:16]


def group_start_param(chat_id: int) -> str:
    """``startapp`` payload that opens the arcade tied to one group (≤64 chars, [A-Za-z0-9_-])."""
    return f"{GROUP_PREFIX}_{chat_id}_{_group_signature(chat_id)}"


def parse_group_start_param(value: str) -> int | None:
    """The group id from a launch payload, or None for a private launch; rejects forged ones."""
    if not value.startswith(GROUP_PREFIX + "_"):
        return None
    try:
        _, chat, signature = value.split("_", 2)
        chat_id = int(chat)
    except ValueError:
        raise ArcadeError("This arcade link is invalid.")
    if not hmac.compare_digest(signature, _group_signature(chat_id)):
        raise ArcadeError("This arcade link is invalid.")
    return chat_id


# ── Client view ─────────────────────────────────────────────────────────────

def public_state(round_: ArcadeRound | None) -> dict | None:
    """What the browser may see: never the crash point or mine layout while live."""
    if round_ is None:
        return None
    data = {
        "id": round_.pk, "game": round_.game, "bet": round_.bet, "status": round_.status,
        "multiplier": str(round_.multiplier), "payout": round_.payout,
    }
    state = round_.state
    live = round_.status == ArcadeRound.Status.ACTIVE
    if round_.game == ArcadeRound.Game.CRASH:
        data["started_at"] = state["started_at"]
        data["growth"] = CRASH_GROWTH_PER_SECOND
        if not live:
            data["point"] = state["point"]
    elif round_.game == ArcadeRound.Game.MINES:
        data.update(count=state["count"], revealed=state["revealed"])
        data["next_multiplier"] = str(mines_multiplier(state["count"], len(state["revealed"]) + 1))
        if not live:
            data["mines"] = state["mines"]
            data["boom"] = state.get("boom")
    else:
        current = state["cards"][-1]
        data["cards"] = state["cards"]
        data["odds"] = {
            guess: {"chance": round(float(hilo_odds(current, guess)) * 100),
                    "next": str(_floor2(Decimal(state["mult"]) * hilo_step_multiplier(current, guess)))}
            for guess in ("higher", "lower")
        }
    return data


def current_round(player_id: int) -> ArcadeRound | None:
    round_ = ArcadeRound.objects.filter(player_id=player_id, status=ArcadeRound.Status.ACTIVE).first()
    if round_ and round_.game == ArcadeRound.Game.CRASH and _crash_finished(round_):
        with transaction.atomic():
            locked = ArcadeRound.objects.select_for_update().get(pk=round_.pk)
            if locked.status == ArcadeRound.Status.ACTIVE:
                _settle(locked, won=False)
        round_.refresh_from_db()
    return round_
