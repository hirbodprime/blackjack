from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from game.models import ChipTransaction, Dealer, Player, RouletteTable, RouletteTableBet
from game.services.multiplayer_roulette import (
    bet_wins, create_roulette_table, place_table_bet, settle_table,
)
from game.services.recovery import cancel_roulette_table


class MultiplayerRouletteTests(TestCase):
    def setUp(self):
        self.player = Player.objects.create(id=77001, name="Spinner", chips=10_000)
        self.dealer = Dealer.objects.create(chips=100_000)

    def test_supported_bets_follow_european_roulette_rules(self):
        self.assertTrue(bet_wins(RouletteTableBet.Kind.RED, "red", 1))
        self.assertTrue(bet_wins(RouletteTableBet.Kind.BLACK, "black", 2))
        self.assertTrue(bet_wins(RouletteTableBet.Kind.DOZEN, "2", 19))
        self.assertTrue(bet_wins(RouletteTableBet.Kind.COLUMN, "3", 36))
        self.assertFalse(bet_wins(RouletteTableBet.Kind.EVEN, "even", 0))

    def test_bet_and_settlement_conserve_player_and_dealer_chips(self):
        initial_total = self.player.chips + self.dealer.chips
        table = create_roulette_table(-77001, self.player.pk)
        place_table_bet(table.pk, self.player.pk, "straight", "0", 100, "roulette-test-1")
        table.closes_at = timezone.now() - timedelta(seconds=1)
        table.save(update_fields=("closes_at",))
        settlement = settle_table(table.pk)
        self.player.refresh_from_db()
        self.dealer.refresh_from_db()
        table.refresh_from_db()
        self.assertEqual(self.player.chips + self.dealer.chips, initial_total)
        self.assertEqual(table.status, RouletteTable.Status.COMPLETE)
        self.assertEqual(table.winning_number, settlement.number)
        self.assertEqual(ChipTransaction.objects.filter(reference_type="roulette_table").count(), 1 + int(settlement.number == 0))

    def test_operator_cancel_refunds_every_bet_once(self):
        table = create_roulette_table(-77002, self.player.pk)
        place_table_bet(table.pk, self.player.pk, "red", "red", 250, "roulette-test-2")
        self.assertEqual(cancel_roulette_table(table.pk), 1)
        self.assertEqual(cancel_roulette_table(table.pk), 0)
        self.player.refresh_from_db()
        self.dealer.refresh_from_db()
        table.refresh_from_db()
        self.assertEqual(self.player.chips, 10_000)
        self.assertEqual(self.dealer.chips, 100_000)
        self.assertEqual(table.status, RouletteTable.Status.CANCELLED)

