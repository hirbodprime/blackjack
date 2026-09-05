from collections import Counter
from unittest import TestCase
from unittest.mock import patch

from game.services.cards import DECK, calculate_hand_value, dealer_should_hit, deal_card


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
