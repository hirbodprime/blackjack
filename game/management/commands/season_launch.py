"""Open a new season: back up, badge veterans, reset balances, seed competitions.

Run with the bot stopped. Without --confirm it only reports what would happen.
"""

import sqlite3
from pathlib import Path

from django.conf import settings
from django.core.management import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from game.economy_config import SEASON_STARTING_CHIPS
from game.models import (
    ChipTransaction, CrashGame, Game, HorseRace, PendingAchievement, Player, PokerTable,
    RouletteTable, Season,
)
from game.services.achievements import sync_catalog
from game.services.challenges import ensure_daily_challenges
from game.services.competitions import schedule_tournaments
from game.services.seasons import start_season


class Command(BaseCommand):
    help = "Start a season. Season 1 also resets every balance to the same amount."

    def add_arguments(self, parser):
        parser.add_argument("--number", type=int, default=None)
        parser.add_argument("--name", default="The Comeback")
        parser.add_argument("--starting-chips", type=int, default=SEASON_STARTING_CHIPS)
        parser.add_argument("--no-reset", action="store_true", help="Keep balances (later seasons)")
        parser.add_argument("--confirm", action="store_true", help="Actually apply the changes")

    def handle(self, *args, **options):
        number = options["number"] or (
            (Season.objects.order_by("-number").values_list("number", flat=True).first() or 0) + 1
        )
        reset = not options["no_reset"]
        chips = options["starting_chips"]

        live = self._live_games()
        if live:
            raise CommandError("Finish or cancel live games first: " + ", ".join(live))
        if Season.objects.filter(is_active=True, settled_at__isnull=True).exists():
            raise CommandError("A season is already active; settle it before starting another.")

        players = Player.objects.count()
        veterans = self._veteran_ids()
        founders = list(Player.objects.order_by("-chips").values_list("pk", flat=True)[:10])
        self.stdout.write(
            f"Season {number} \"{options['name']}\": {players} players, "
            f"{len(veterans)} veterans, {len(founders)} founders, "
            f"{'reset every balance to ' + format(chips, ',') if reset else 'balances kept'}."
        )
        if not options["confirm"]:
            self.stdout.write(self.style.WARNING("Dry run. Re-run with --confirm to apply."))
            return

        backup = self._backup()
        if backup:
            self.stdout.write(f"Backed up database to {backup}")

        sync_catalog()
        with transaction.atomic():
            if number == 1:
                # Badges are handed over the first time each returning player plays.
                PendingAchievement.objects.bulk_create(
                    [PendingAchievement(player_id=pid, condition="season0_veteran") for pid in veterans]
                    + [PendingAchievement(player_id=pid, condition="season0_founder") for pid in founders],
                    ignore_conflicts=True,
                )
            season = start_season(number, options["name"], chips, reset_balances=reset)
        ensure_daily_challenges()
        schedule_tournaments()
        self.stdout.write(self.style.SUCCESS(
            f"Season {season.number} is live until {season.ends_at:%Y-%m-%d %H:%M} UTC."
        ))

    def _veteran_ids(self) -> set[int]:
        played = set(Player.objects.filter(games__gt=0).values_list("pk", flat=True))
        transacted = set(
            ChipTransaction.objects.exclude(reference_type="player_signup")
            .values_list("player_id", flat=True).distinct()
        )
        return played | transacted

    def _live_games(self) -> list[str]:
        checks = {
            "blackjack": Game.objects.filter(ended=False).filter(started=True).exists(),
            "horse race": HorseRace.objects.filter(completed=False, race_started=True).exists(),
            "poker": PokerTable.objects.filter(status=PokerTable.Status.PLAYING).exists(),
            "crash": CrashGame.objects.filter(crashed=False, cashed_out=False).exists(),
            "roulette": RouletteTable.objects.filter(status=RouletteTable.Status.BETTING).exists(),
        }
        return [name for name, busy in checks.items() if busy]

    def _backup(self) -> Path | None:
        database = settings.DATABASES["default"]
        if database["ENGINE"] != "django.db.backends.sqlite3":
            return None
        source_path = Path(database["NAME"])
        if not source_path.exists():
            return None
        target = source_path.with_name(
            f"{source_path.name}.pre-season-{timezone.now():%Y%m%d%H%M%S}"
        )
        source, dest = sqlite3.connect(source_path), sqlite3.connect(target)
        source.backup(dest)
        dest.close()
        source.close()
        return target
