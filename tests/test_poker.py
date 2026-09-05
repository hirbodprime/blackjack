from django.test import TestCase

from game.models import ChipTransaction, Dealer, Game, Player, PokerHand, PokerSeat, PokerTable
from game.services.poker import (
    PokerError, act, act_bot, add_bot, cash_out, close_table, create_table,
    describe_visible_hand, evaluate_hand,
    join_table, remove_bot, start_hand,
)
from game.services.recovery import cancel_poker_table
from game.services.table_games import GroupTableBusy, ensure_blackjack_can_open, ensure_poker_can_open


class PokerEvaluatorTests(TestCase):
    def test_categories_and_kickers_are_ranked_correctly(self):
        straight_flush = evaluate_hand(["A♠", "K♠", "Q♠", "J♠", "T♠", "2♥", "3♣"])
        quads = evaluate_hand(["A♠", "A♥", "A♦", "A♣", "K♠", "2♥", "3♣"])
        wheel = evaluate_hand(["A♠", "2♥", "3♦", "4♣", "5♠", "K♥", "Q♣"])
        self.assertGreater(straight_flush, quads)
        self.assertEqual(wheel[:2], (4, 5))

    def test_visible_hand_description_works_before_and_after_flop(self):
        self.assertEqual(describe_visible_hand(["A♠", "A♥"], []), "one pair")
        self.assertEqual(describe_visible_hand(["A♠", "K♠"], ["Q♠", "J♠", "T♠"]), "straight flush")


class PokerCashTableTests(TestCase):
    def setUp(self):
        self.host = Player.objects.create(id=101, name="Host", chips=10_000)
        self.guest = Player.objects.create(id=202, name="Guest", chips=10_000)
        self.dealer = Dealer.objects.create(chips=100_000)

    def test_heads_up_all_in_conserves_all_chips_and_cash_out_is_audited(self):
        table, _ = create_table(-500, self.host.pk, 1_000, 10)
        join_table(table.pk, self.guest.pk)
        hand = start_hand(table.pk, self.host.pk)
        current = PokerSeat.objects.get(table=table, seat_number=hand.current_seat)
        result = act(hand.pk, current.player_id, "allin")
        if not result.hand_complete:
            hand.refresh_from_db()
            current = PokerSeat.objects.get(table=table, seat_number=hand.current_seat)
            result = act(hand.pk, current.player_id, "call")
        self.assertTrue(result.hand_complete)
        self.assertEqual(sum(table.seats.values_list("stack", flat=True)), 2_000)
        first = cash_out(table.pk, self.host.pk)
        second = cash_out(table.pk, self.guest.pk)
        self.assertEqual(first + second, 2_000)
        self.host.refresh_from_db()
        self.guest.refresh_from_db()
        self.assertEqual(self.host.chips + self.guest.chips, 20_000)
        self.assertEqual(ChipTransaction.objects.filter(category=ChipTransaction.Category.POKER_BUY_IN).count(), 2)
        self.assertGreaterEqual(ChipTransaction.objects.filter(category=ChipTransaction.Category.POKER_CASH_OUT).count(), 1)

    def test_operator_cancel_refunds_stacks_and_live_commitments(self):
        table, _ = create_table(-501, self.host.pk, 1_000, 10)
        join_table(table.pk, self.guest.pk)
        start_hand(table.pk, self.host.pk)
        self.assertEqual(cancel_poker_table(table.pk), 2)
        self.host.refresh_from_db()
        self.guest.refresh_from_db()
        table.refresh_from_db()
        self.assertEqual((self.host.chips, self.guest.chips), (10_000, 10_000))
        self.assertEqual(table.status, PokerTable.Status.CLOSED)
        self.assertFalse(PokerSeat.objects.filter(table=table).exists())
        self.assertEqual(PokerHand.objects.get(table=table).phase, PokerHand.Phase.COMPLETE)

    def test_only_host_can_start(self):
        table, _ = create_table(-502, self.host.pk, 1_000, 10)
        join_table(table.pk, self.guest.pk)
        with self.assertRaises(PokerError):
            start_hand(table.pk, self.guest.pk)

    def test_new_player_can_join_between_hands(self):
        third = Player.objects.create(id=303, name="Third", chips=10_000)
        table, _ = create_table(-503, self.host.pk, 1_000, 10)
        join_table(table.pk, self.guest.pk)
        hand = start_hand(table.pk, self.host.pk)
        current = PokerSeat.objects.get(table=table, seat_number=hand.current_seat)
        act(hand.pk, current.player_id, "fold")
        table.refresh_from_db()
        self.assertEqual(table.status, PokerTable.Status.BETWEEN_HANDS)
        seat, _ = join_table(table.pk, third.pk)
        self.assertEqual(seat.stack, 1_000)

    def test_bot_stack_is_backed_by_dealer_bankroll(self):
        table, _ = create_table(-504, self.host.pk, 1_000, 10)
        bot = add_bot(table.pk, self.host.pk)
        self.dealer.refresh_from_db()
        self.assertTrue(bot.is_bot)
        self.assertEqual(self.dealer.chips, 99_000)
        self.assertEqual(remove_bot(table.pk, self.host.pk), 1_000)
        self.dealer.refresh_from_db()
        self.assertEqual(self.dealer.chips, 100_000)

    def test_each_bot_at_a_table_has_a_distinct_name(self):
        table, _ = create_table(-508, self.host.pk, 1_000, 10)
        names = {add_bot(table.pk, self.host.pk).bot_name for _ in range(3)}
        self.assertEqual(len(names), 3)

    def test_host_close_returns_every_human_and_bot_stack(self):
        table, _ = create_table(-507, self.host.pk, 1_000, 10)
        join_table(table.pk, self.guest.pk)
        add_bot(table.pk, self.host.pk)
        self.assertEqual(close_table(table.pk, self.host.pk), 2)
        self.host.refresh_from_db()
        self.guest.refresh_from_db()
        self.dealer.refresh_from_db()
        table.refresh_from_db()
        self.assertEqual((self.host.chips, self.guest.chips, self.dealer.chips), (10_000, 10_000, 100_000))
        self.assertEqual(table.status, PokerTable.Status.CLOSED)

    def test_bot_can_complete_heads_up_hand_and_conserve_casino_chips(self):
        initial_total = self.host.chips + self.guest.chips + self.dealer.chips
        table, _ = create_table(-505, self.host.pk, 1_000, 10)
        add_bot(table.pk, self.host.pk)
        hand = start_hand(table.pk, self.host.pk)
        for _ in range(30):
            hand.refresh_from_db()
            if hand.phase == PokerHand.Phase.COMPLETE:
                break
            seat = PokerSeat.objects.get(table=table, seat_number=hand.current_seat)
            if seat.is_bot:
                act_bot(hand.pk, seat.pk)
            elif hand.current_bet > seat.committed_round:
                act(hand.pk, seat.player_id, "call")
            else:
                act(hand.pk, seat.player_id, "check")
        self.assertEqual(PokerHand.objects.get(pk=hand.pk).phase, PokerHand.Phase.COMPLETE)
        cash_out(table.pk, self.host.pk)
        self.host.refresh_from_db()
        self.guest.refresh_from_db()
        self.dealer.refresh_from_db()
        self.assertEqual(self.host.chips + self.guest.chips + self.dealer.chips, initial_total)

    def test_blackjack_and_poker_are_mutually_exclusive_per_group(self):
        table, _ = create_table(-506, self.host.pk, 1_000, 10)
        with self.assertRaises(GroupTableBusy):
            ensure_blackjack_can_open(-506)
        cash_out(table.pk, self.host.pk)
        Game.objects.create(chat_id="-506", ended=False)
        with self.assertRaises(GroupTableBusy):
            ensure_poker_can_open(-506)
