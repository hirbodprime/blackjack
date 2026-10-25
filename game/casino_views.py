"""Authenticated HTTP surface for the Telegram roulette Mini App."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from urllib.parse import parse_qsl

import httpx

from django.conf import settings
from django.core import signing
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST
from django.views.decorators.clickjacking import xframe_options_exempt

from django.utils import timezone

from game.economy_config import ARCADE_MAX_BET, ARCADE_MIN_BET, MINES_CHOICES
from game.models import Group, Player, RouletteTable, RouletteTableBet
from game.services import arcade
from game.services import arcade_ranks as ranks
from game.services.achievements import grant_on_play
from game.services.economy import InsufficientChips
from game.services.operations import BettingPaused
from game.services.multiplayer_roulette import RouletteTableError, place_table_bet


AUTH_MAX_AGE = 900


def _json_error(message, status=400):
    return JsonResponse({"ok": False, "error": message}, status=status)


def _validate_init_data(raw: str) -> dict:
    values = dict(parse_qsl(raw, keep_blank_values=True))
    received_hash = values.pop("hash", "")
    if not received_hash:
        raise ValueError("Telegram authentication is missing.")
    data_check = "\n".join(f"{key}={values[key]}" for key in sorted(values))
    secret = hmac.new(b"WebAppData", settings.TELEGRAM_BOT_TOKEN.encode(), hashlib.sha256).digest()
    expected = hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, received_hash):
        raise ValueError("Telegram authentication is invalid.")
    auth_date = int(values.get("auth_date", "0"))
    if auth_date <= 0 or abs(time.time() - auth_date) > AUTH_MAX_AGE:
        raise ValueError("Telegram authentication has expired. Reopen the game.")
    values["user"] = json.loads(values.get("user", "{}"))
    return values


def _session(request):
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        raise ValueError("Authentication required.")
    return signing.loads(header[7:], salt="casino-mini-app", max_age=AUTH_MAX_AGE)


def _authorized_table(session):
    table = RouletteTable.objects.get(pk=session["table_id"])
    if not hmac.compare_digest(table.access_token, session["access"]):
        raise ValueError("This table link is invalid.")
    return table


def _is_chat_member(chat_id: int, user_id: int) -> bool:
    try:
        response = httpx.get(
            f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/getChatMember",
            params={"chat_id": chat_id, "user_id": user_id}, timeout=5,
        )
        payload = response.json()
        return bool(payload.get("ok") and payload.get("result", {}).get("status") not in {"left", "kicked"})
    except Exception:
        return False


@require_GET
def casino_home(request):
    response = render(request, "casino/home.html")
    response["Cache-Control"] = "public, max-age=300"
    response["Content-Security-Policy"] = (
        "default-src 'self'; style-src 'self' 'unsafe-inline'; "
        "img-src 'self' https://bigpapagames.com; "
        "connect-src 'none'; frame-ancestors 'none';"
    )
    return response


@require_GET
@xframe_options_exempt
def roulette_app(request):
    response = render(request, "casino/roulette.html")
    response["Cache-Control"] = "no-store"
    response["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self' 'unsafe-inline' https://telegram.org; "
        "style-src 'self' 'unsafe-inline'; connect-src 'self'; img-src 'self' data:;"
    )
    return response


@csrf_exempt
@require_POST
def telegram_auth(request):
    try:
        payload = json.loads(request.body or b"{}")
        data = _validate_init_data(payload.get("init_data", ""))
        start_param = data.get("start_param", "")
        prefix, table_id, access = start_param.split("_", 2)
        if prefix != "rt":
            raise ValueError("This roulette link is invalid.")
        table = RouletteTable.objects.get(pk=int(table_id), access_token=access)
        user_id = int(data["user"]["id"])
        if not Player.objects.filter(pk=user_id, is_frozen=False).exists():
            raise ValueError("Start the bot privately before opening the casino.")
        if not _is_chat_member(table.chat_id, user_id):
            raise ValueError("You must be a member of the group that opened this table.")
        token = signing.dumps(
            {"uid": user_id, "table_id": table.pk, "access": table.access_token},
            salt="casino-mini-app", compress=True,
        )
        return JsonResponse({"ok": True, "token": token})
    except (ValueError, KeyError, TypeError, RouletteTable.DoesNotExist, json.JSONDecodeError) as exc:
        return _json_error(str(exc), 403)


def _state_payload(table, user_id):
    player = Player.objects.get(pk=user_id)
    bets = list(table.bets.filter(player_id=user_id).values("kind", "selection", "amount", "won", "payout"))
    participants = table.bets.values("player_id").distinct().count()
    return {
        "ok": True,
        "table": {
            "id": table.pk,
            "status": table.status,
            "closes_at": table.closes_at.isoformat(),
            "winning_number": table.winning_number,
            "seed_hash": table.seed_hash,
            "seed_reveal": table.seed_reveal if table.status == RouletteTable.Status.COMPLETE else None,
            "participants": participants,
            "total_bets": sum(table.bets.values_list("amount", flat=True)),
        },
        "player": {"id": player.pk, "name": player.name, "chips": player.chips},
        "bets": bets,
    }


@require_GET
def table_state(request):
    try:
        session = _session(request)
        table = _authorized_table(session)
        return JsonResponse(_state_payload(table, session["uid"]))
    except (ValueError, signing.BadSignature, signing.SignatureExpired, RouletteTable.DoesNotExist, Player.DoesNotExist) as exc:
        return _json_error(str(exc), 403)


@csrf_exempt
@require_POST
def place_bet(request):
    try:
        session = _session(request)
        table = _authorized_table(session)
        payload = json.loads(request.body or b"{}")
        request_id = str(payload.get("request_id", ""))
        if not request_id or len(request_id) > 64:
            raise ValueError("A valid request ID is required.")
        place_table_bet(
            table.pk, session["uid"], str(payload.get("kind", "")),
            str(payload.get("selection", "")), int(payload.get("amount", 0)),
            f"web:{session['uid']}:{request_id}",
        )
        table.refresh_from_db()
        return JsonResponse(_state_payload(table, session["uid"]))
    except (ValueError, TypeError, signing.BadSignature, signing.SignatureExpired, RouletteTable.DoesNotExist, RouletteTableError, InsufficientChips, json.JSONDecodeError) as exc:
        return _json_error(str(exc), 400)


# ── Arcade (solo games opened from the bot's private chat) ─────────────────

ARCADE_SALT = "casino-arcade"
ARCADE_SESSION_AGE = 3600
ARCADE_ACTIONS = {
    "crash_start": lambda uid, chat, p: arcade.crash_start(uid, int(p.get("bet", 0)), chat),
    "crash_cashout": lambda uid, chat, p: arcade.crash_cashout(uid),
    "mines_start": lambda uid, chat, p: arcade.mines_start(uid, int(p.get("bet", 0)), int(p.get("mines", 3)), chat),
    "mines_reveal": lambda uid, chat, p: arcade.mines_reveal(uid, int(p.get("tile", -1))),
    "mines_cashout": lambda uid, chat, p: arcade.mines_cashout(uid),
    "hilo_start": lambda uid, chat, p: arcade.hilo_start(uid, int(p.get("bet", 0)), chat),
    "hilo_guess": lambda uid, chat, p: arcade.hilo_guess(uid, str(p.get("guess", ""))),
    "hilo_cashout": lambda uid, chat, p: arcade.hilo_cashout(uid),
}


def _arcade_session(request) -> tuple[int, int | None]:
    """(player id, group id or None) from the signed arcade session."""
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        raise ValueError("Authentication required.")
    session = signing.loads(header[7:], salt=ARCADE_SALT, max_age=ARCADE_SESSION_AGE)
    return session["uid"], session.get("chat")


def _group_name(chat_id: int | None) -> str | None:
    if chat_id is None:
        return None
    group = Group.objects.filter(group_chat_id=str(chat_id)).exclude(group_name=None).first()
    return group.group_name if group else "This group"


def _arcade_payload(uid: int, round_=None, chat_id: int | None = None) -> dict:
    player = Player.objects.get(pk=uid)
    if round_ is None:
        round_ = arcade.current_round(uid)
    return {
        "ok": True,
        "now": timezone.now().isoformat(),
        "player": {"name": player.name, "chips": player.chips},
        "round": arcade.public_state(round_),
        "limits": {"min": ARCADE_MIN_BET, "max": ARCADE_MAX_BET, "mines": list(MINES_CHOICES)},
        "group": {"name": _group_name(chat_id)} if chat_id is not None else None,
    }


@require_GET
@xframe_options_exempt
def arcade_app(request):
    response = render(request, "casino/arcade.html")
    response["Cache-Control"] = "no-store"
    response["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self' 'unsafe-inline' https://telegram.org; "
        "style-src 'self' 'unsafe-inline'; connect-src 'self'; img-src 'self' data:;"
    )
    return response


@csrf_exempt
@require_POST
def arcade_auth(request):
    try:
        payload = json.loads(request.body or b"{}")
        data = _validate_init_data(payload.get("init_data", ""))
        uid = int(data["user"]["id"])
        if not Player.objects.filter(pk=uid, is_frozen=False).exists():
            raise ValueError("Start the bot privately before opening the arcade.")
        chat_id = arcade.parse_group_start_param(data.get("start_param", ""))
        if chat_id is not None and not _is_chat_member(chat_id, uid):
            raise ValueError("You must be a member of the group that opened this arcade.")
        token = signing.dumps({"uid": uid, "chat": chat_id}, salt=ARCADE_SALT, compress=True)
        return JsonResponse({"token": token, **_arcade_payload(uid, chat_id=chat_id)})
    except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        return _json_error(str(exc), 403)


@require_GET
def arcade_state(request):
    try:
        uid, chat_id = _arcade_session(request)
        return JsonResponse(_arcade_payload(uid, chat_id=chat_id))
    except (ValueError, signing.BadSignature, signing.SignatureExpired, Player.DoesNotExist) as exc:
        return _json_error(str(exc), 403)


@require_GET
def arcade_ranks(request):
    try:
        uid, chat_id = _arcade_session(request)
    except (ValueError, signing.BadSignature, signing.SignatureExpired) as exc:
        return _json_error(str(exc), 403)
    scope = request.GET.get("scope", "global")
    if scope == "group" and chat_id is None:
        return _json_error("Open the arcade from a group to see its ranking.")
    try:
        board = ranks.leaderboard(
            request.GET.get("game", "all"), chat_id if scope == "group" else None,
            request.GET.get("period", "week"), player_id=uid,
        )
    except ValueError as exc:
        return _json_error(str(exc))
    return JsonResponse({"ok": True, "scope": scope, **board})


@csrf_exempt
@require_POST
def arcade_action(request, action):
    try:
        uid, chat_id = _arcade_session(request)
    except (ValueError, signing.BadSignature, signing.SignatureExpired) as exc:
        return _json_error(str(exc), 403)
    handler = ARCADE_ACTIONS.get(action)
    if handler is None:
        return _json_error("Unknown action.", 404)
    try:
        round_ = handler(uid, chat_id, json.loads(request.body or b"{}"))
        grant_on_play(uid)
        return JsonResponse(_arcade_payload(uid, round_, chat_id))
    except InsufficientChips:
        return _json_error("Not enough chips.")
    except (arcade.ArcadeError, BettingPaused, ValueError, TypeError, json.JSONDecodeError) as exc:
        return _json_error(str(exc))
