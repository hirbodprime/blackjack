from unittest.mock import patch

from django.test import TestCase

from game.models import Player, RPSBotProfile
from game.services.rps_bot import choose_and_record_rps


class _PredictableRandom:
    def random(self):
        return 0.0

    def choice(self, values):
        return values[0]


class RPSBotTests(TestCase):
    def test_bot_predicts_from_history_without_peeking_at_current_move(self):
        player = Player.objects.create(id=909, name="Pattern", chips=100)
        RPSBotProfile.objects.create(player=player, recent_choices=["rock", "rock", "rock"])
        with patch("game.services.rps_bot.random.SystemRandom", return_value=_PredictableRandom()):
            bot_choice = choose_and_record_rps(player.pk, "scissors")
        self.assertEqual(bot_choice, "paper")  # counters old rocks, not the current scissors
        self.assertEqual(RPSBotProfile.objects.get(player=player).recent_choices[-1], "scissors")
