from collections import Counter
from unittest import TestCase
from unittest.mock import patch

from game.services.cards import (
    DECK,
    all_players_busted,
    calculate_hand_value,
    deal_card,
    dealer_should_hit,
    resolve_round,
)


class CardServiceTests(TestCase):
    def test_deck_has_four_of_every_rank(self):
        self.assertEqual(len(DECK), 52)
        self.assertEqual(set(Counter(DECK).values()), {4})

    def test_number_cards_keep_their_value(self):
        self.assertEqual(calculate_hand_value([2, 5, 10]), 17)

    def test_face_cards_are_worth_ten(self):
        self.assertEqual(calculate_hand_value(["J", "Q"]), 20)
        self.assertEqual(calculate_hand_value(["K", 7]), 17)

    def test_ace_is_eleven_when_it_does_not_bust(self):
        self.assertEqual(calculate_hand_value(["A", 9]), 20)

    def test_ace_is_one_when_eleven_would_bust(self):
        self.assertEqual(calculate_hand_value(["K", 5, "A"]), 16)

    def test_multiple_aces_adjust_individually(self):
        self.assertEqual(calculate_hand_value(["A", "A", 9]), 21)
        self.assertEqual(calculate_hand_value(["A", "A", "A", 9]), 12)

    def test_empty_hand_is_zero(self):
        self.assertEqual(calculate_hand_value([]), 0)

    def test_dealer_uses_standard_hit_through_16_stand_on_17_rule(self):
        self.assertTrue(dealer_should_hit([10, 6]))
        self.assertFalse(dealer_should_hit([10, 7]))
        self.assertFalse(dealer_should_hit(["A", 6]))

    @patch("game.services.cards.random.choice", return_value="A")
    def test_deal_card_uses_the_shared_deck(self, choice):
        self.assertEqual(deal_card(), "A")
        choice.assert_called_once_with(DECK)


class RoundResolutionTests(TestCase):
    def test_highest_hand_beating_the_dealer_wins(self):
        result = resolve_round([10, 8], [("a", [10, 9]), ("b", [10, "A"]), ("c", [10, 7])])
        self.assertEqual(result.winners, ("b",))
        self.assertEqual(result.winning_value, 21)
        self.assertEqual(result.dealer_value, 18)
        self.assertFalse(result.dealer_busted)

    def test_ties_at_the_top_all_win_in_seat_order(self):
        result = resolve_round([10, 7], [("a", [10, 9]), ("b", [9, 10]), ("c", [10, 8])])
        self.assertEqual(result.winners, ("a", "b"))

    def test_push_and_lower_hands_lose_to_the_dealer(self):
        result = resolve_round([10, 9], [("a", [10, 9]), ("b", [10, 8])])
        self.assertEqual(result.winners, ())

    def test_busted_players_never_win(self):
        result = resolve_round([10, 6, 10], [("a", [10, 6, 9]), ("b", [2, 3])])
        self.assertTrue(result.dealer_busted)
        self.assertEqual(result.winners, ("b",))
        self.assertEqual(result.winning_value, 5)

    def test_all_players_busted(self):
        self.assertTrue(all_players_busted([[10, 10, 5], ["K", "Q", 2]]))
        self.assertFalse(all_players_busted([[10, 10, 5], [10, "A"]]))
        self.assertTrue(all_players_busted([]))
