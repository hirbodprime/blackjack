from django.test import TestCase

from game.models import HorseRace, HorseRaceWin
from game.services.racing import complete_race, repair_recorded_races


class HorseRaceCompletionTests(TestCase):
    def test_completion_is_idempotent(self):
        race = HorseRace.objects.create(chat_id=-88001, race_started=True)
        self.assertTrue(complete_race(race.pk))
        self.assertFalse(complete_race(race.pk))
        race.refresh_from_db()
        self.assertTrue(race.completed)
        self.assertIsNotNone(race.completed_at)

    def test_recorded_dealer_win_repairs_legacy_stuck_race(self):
        race = HorseRace.objects.create(chat_id=-88002, race_started=True)
        HorseRaceWin.objects.create(
            race=race, user=None, horse_number=1, horse_name="Dealer", amount=100
        )
        self.assertEqual(repair_recorded_races(race.chat_id), 1)
        race.refresh_from_db()
        self.assertTrue(race.completed)

    def test_unfinished_race_without_result_is_not_repaired(self):
        race = HorseRace.objects.create(chat_id=-88003, race_started=True)
        self.assertEqual(repair_recorded_races(race.chat_id), 0)
        race.refresh_from_db()
        self.assertFalse(race.completed)
