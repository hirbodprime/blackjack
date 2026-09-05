"""Restore completed horse-race history from a compatible SQLite backup."""

import sqlite3
from pathlib import Path

from django.core.management import BaseCommand, CommandError
from django.db import transaction

from game.models import HorseBet, HorseRace, HorseRaceWin


class Command(BaseCommand):
    help = "Restore races with recorded outcomes from an older SQLite database."

    def add_arguments(self, parser):
        parser.add_argument("--source", required=True)
        parser.add_argument("--apply", action="store_true")

    def handle(self, *args, **options):
        source = Path(options["source"]).resolve()
        if not source.is_file():
            raise CommandError(f"Backup does not exist: {source}")
        connection = sqlite3.connect(f"file:{source}?mode=ro&immutable=1", uri=True)
        connection.row_factory = sqlite3.Row
        try:
            race_ids = [
                row[0] for row in connection.execute(
                    "SELECT DISTINCT race_id FROM game_horseracewin ORDER BY race_id"
                )
            ]
            if not race_ids:
                self.stdout.write("No completed race history found in source.")
                return
            placeholders = ",".join("?" for _ in race_ids)
            races = list(connection.execute(
                f"SELECT * FROM game_horserace WHERE id IN ({placeholders})", race_ids
            ))
            wins = list(connection.execute(
                f"SELECT * FROM game_horseracewin WHERE race_id IN ({placeholders})", race_ids
            ))
            bets = list(connection.execute(
                f"SELECT * FROM game_horsebet WHERE race_id IN ({placeholders})", race_ids
            ))
        finally:
            connection.close()

        self.stdout.write(
            f"Source contains {len(races)} completed races, {len(wins)} wins, "
            f"and {len(bets)} associated bets."
        )
        if not options["apply"]:
            self.stdout.write("Dry run only; pass --apply to restore them.")
            return

        latest_win = {}
        for win in wins:
            latest_win[win["race_id"]] = max(
                latest_win.get(win["race_id"], win["created_at"]), win["created_at"]
            )

        created_races = created_wins = created_bets = 0
        with transaction.atomic():
            for row in races:
                race, created = HorseRace.objects.get_or_create(
                    pk=row["id"],
                    defaults={
                        "chat_id": row["chat_id"],
                        "race_started": True,
                        "race_distance": row["race_distance"],
                        "completed": True,
                        "completed_at": latest_win.get(row["id"]),
                    },
                )
                if not created and race.chat_id != row["chat_id"]:
                    raise CommandError(f"Race ID collision at #{row['id']}")
                HorseRace.objects.filter(pk=race.pk).update(
                    completed=True,
                    completed_at=latest_win.get(row["id"]),
                    created_at=row["created_at"],
                )
                created_races += int(created)

            for row in bets:
                _, created = HorseBet.objects.get_or_create(
                    pk=row["id"],
                    defaults={
                        "race_id": row["race_id"], "user_id": row["user_id"],
                        "horse_number": row["horse_number"],
                        "bet_amount": row["bet_amount"], "username": row["username"],
                    },
                )
                created_bets += int(created)

            for row in wins:
                win, created = HorseRaceWin.objects.get_or_create(
                    pk=row["id"],
                    defaults={
                        "race_id": row["race_id"], "user_id": row["user_id"],
                        "horse_number": row["horse_number"],
                        "horse_name": row["horse_name"], "amount": row["amount"],
                    },
                )
                if not created and win.race_id != row["race_id"]:
                    raise CommandError(f"Win ID collision at #{row['id']}")
                HorseRaceWin.objects.filter(pk=win.pk).update(created_at=row["created_at"])
                created_wins += int(created)

        self.stdout.write(self.style.SUCCESS(
            f"Restored {created_races} races, {created_wins} wins, and {created_bets} bets."
        ))
