from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from game.models import (
    FriendChallenge, ItemListing, Player, PlayerItem,
    PlayerWeeklyMissionProgress, WeeklyMission,
)
from game.services.retention import (
    accept_challenge, advance_weekly_missions, buy_item_listing,
    cancel_item_listing, create_challenge, create_item_listing,
    record_challenge_round,
)


class ItemMarketplaceTests(TestCase):
    def setUp(self):
        self.seller = Player.objects.create(id=81001, name="Seller", chips=100)
        self.buyer = Player.objects.create(id=81002, name="Buyer", chips=1000)
        PlayerItem.objects.create(player=self.seller, item_type="insurance_pass", quantity=3)

    def test_sale_escrows_item_and_settles_atomically(self):
        listing = create_item_listing(self.seller.id, "insurance_pass", 2, 400)
        self.assertEqual(PlayerItem.objects.get(player=self.seller, item_type="insurance_pass").quantity, 1)
        buy_item_listing(listing.id, self.buyer.id)
        self.seller.refresh_from_db()
        self.buyer.refresh_from_db()
        listing.refresh_from_db()
        self.assertEqual((self.seller.chips, self.buyer.chips), (500, 600))
        self.assertFalse(listing.active)
        self.assertEqual(PlayerItem.objects.get(player=self.buyer, item_type="insurance_pass").quantity, 2)

    def test_cancel_returns_escrow(self):
        listing = create_item_listing(self.seller.id, "insurance_pass", 2, 400)
        cancel_item_listing(listing.id, self.seller.id)
        self.assertEqual(PlayerItem.objects.get(player=self.seller, item_type="insurance_pass").quantity, 3)


class FriendChallengeTests(TestCase):
    def setUp(self):
        self.a = Player.objects.create(id=82001, name="A", chips=1000)
        self.b = Player.objects.create(id=82002, name="B", chips=1000)

    def test_best_of_three_escrow_and_payout(self):
        challenge = create_challenge(self.a.id, self.b.id, FriendChallenge.Mode.DICE, 100)
        accept_challenge(challenge.id, self.b.id)
        self.a.refresh_from_db(); self.b.refresh_from_db()
        self.assertEqual((self.a.chips, self.b.chips), (900, 900))
        record_challenge_round(challenge.id, self.a.id, self.a.id, {"round": 1})
        challenge = record_challenge_round(challenge.id, self.b.id, self.a.id, {"round": 2})
        self.a.refresh_from_db()
        self.assertEqual(challenge.status, FriendChallenge.Status.COMPLETED)
        self.assertEqual(self.a.chips, 1100)


class WeeklyMissionTests(TestCase):
    def test_matching_gameplay_advances_and_rewards_once(self):
        player = Player.objects.create(id=83001, name="Weekly", chips=100, xp=0)
        monday = timezone.localdate() - timedelta(days=timezone.localdate().weekday())
        mission = WeeklyMission.objects.create(
            quest_type="minigames", subtype="dice", description="Roll twice",
            target=2, reward_xp=10, reward_chips=25, week_start=monday,
        )
        self.assertEqual(advance_weekly_missions(player.id, "minigames", "dice"), [])
        completed = advance_weekly_missions(player.id, "minigames", "dice")
        self.assertEqual([x.id for x in completed], [mission.id])
        player.refresh_from_db()
        self.assertEqual((player.chips, player.xp), (125, 30))
        advance_weekly_missions(player.id, "minigames", "dice")
        self.assertEqual(PlayerWeeklyMissionProgress.objects.get().progress, 2)
        player.refresh_from_db()
        self.assertEqual(player.chips, 125)
