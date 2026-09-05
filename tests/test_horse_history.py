from django.db.models.deletion import ProtectedError
from django.test import TestCase
from django.utils import timezone

from game.models import HorseBet, HorseRace, HorseRaceWin, Player
from game.services.racing import place_race_bet
from game.services.recovery import recover_interrupted_games


class HorseHistoryRetentionTests(TestCase):
    def setUp(self):
        self.player = Player.objects.create(id=85001, name="Racer", chips=1000)

    def test_completed_race_and_win_survive_startup_recovery(self):
        race = HorseRace.objects.create(
            chat_id=-85001, race_started=True, completed=True,
            completed_at=timezone.now(),
        )
        win = HorseRaceWin.objects.create(
            race=race, user=self.player, horse_number=2, amount=100,
        )
        recover_interrupted_games()
        self.assertTrue(HorseRace.objects.filter(pk=race.pk).exists())
        self.assertTrue(HorseRaceWin.objects.filter(pk=win.pk).exists())

    def test_completed_bet_does_not_block_a_new_race(self):
        old_race = HorseRace.objects.create(
            chat_id=-85001, race_started=True, completed=True,
            completed_at=timezone.now(),
        )
        HorseBet.objects.create(
            race=old_race, user_id=self.player.id, horse_number=2,
            bet_amount=10, username="racer",
        )
        new_race = HorseRace.objects.create(chat_id=-85001)
        bet = place_race_bet(
            race_id=new_race.id, player_id=self.player.id,
            horse_number=3, amount=20, username="racer",
        )
        self.assertEqual(bet.race_id, new_race.id)

    def test_recorded_win_protects_race_from_accidental_deletion(self):
        race = HorseRace.objects.create(chat_id=-85001, completed=True)
        HorseRaceWin.objects.create(
            race=race, user=self.player, horse_number=2, amount=100,
        )
        with self.assertRaises(ProtectedError):
            race.delete()
