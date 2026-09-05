from django.test import TestCase, override_settings
from django.contrib.auth import get_user_model
from django.contrib import admin
from django.urls import reverse
from django.test import RequestFactory
from django.utils import timezone
import json
import logging

from game.models import (
    BotControl,
    ChipTransaction,
    CrashGame,
    Dealer,
    DailyQuest,
    Game,
    HorseBet,
    HorseRace,
    HorseSale,
    HorseUpgrade,
    JoinGame,
    OperationalEvent,
    OwnedHorse,
    Player,
    PlayerItem,
    PlayerActiveItem,
    PlayerDailyQuestProgress,
    ReferralEarning,
    UserSettings,
)
from game.services.blackjack import (
    ActiveInAnotherGame,
    AlreadyJoined,
    join_game_with_chips,
    refund_joined_player,
)
from game.services.economy import (
    InsufficientChips,
    InsufficientExperience,
    adjust_balance,
    issue_loan,
    purchase_item,
    repay_loan,
    reverse_chip_transaction,
    TransactionAlreadyReversed,
    transfer_chips,
)
from game.services.operations import BettingPaused, ensure_betting_open, is_player_admin
from game.services.racing import ActiveRaceBet, AlreadyBet, RaceAlreadyStarted, place_race_bet
from game.services.crash import (
    ActiveCrashGame,
    NoActiveCrashGame,
    cash_out_crash_game,
    mark_crash_game_crashed,
    start_crash_game,
)
from game.services.chance import settle_roulette, settle_spin
from game.services.recovery import (
    cancel_blackjack_game,
    cancel_crash_game,
    cancel_race,
    recover_interrupted_games,
)
from game.services.mystery import open_mystery_box
from game.services.horses import (
    HorseUnavailable,
    InvalidHorseSale,
    UpgradeAlreadyOwned,
    buy_horse,
    buy_horse_for_recipient,
    buy_horse_upgrade,
    customize_horse,
    gift_owned_horse,
    purchase_horse_sale,
)
from game.services.progression import award_xp, deduct_xp_amount
from game.services.referrals import award_referral_bonus
from game.services.rewards import (
    RewardAlreadyClaimed,
    claim_daily_box,
    claim_daily_chips,
    claim_daily_xp,
)
from game.services.analytics import build_economy_analytics
from game.services.quests import advance_daily_quest
from game.services.items import (
    ItemCategoryAlreadyActive,
    ItemUnavailable,
    activate_inventory_item,
    consume_xp_booster,
)
from game.services.turns import (
    apply_player_timeout,
    begin_player_turn,
    record_player_action,
)
from game.economy_config import (
    apply_potion_multiplier,
    horse_race_payout_pool,
    referral_share,
    standard_win_payout,
)
from game.logging import JsonFormatter
from game.telegram.update_guard import TelegramUpdateGuard, telegram_access_allowed


class EconomyServiceTests(TestCase):
    def setUp(self):
        self.player = Player.objects.create(id=1001, name="Ledger Tester", chips=1_000)

    def test_credit_updates_balance_and_writes_ledger(self):
        result = adjust_balance(
            self.player,
            250,
            category=ChipTransaction.Category.DAILY_REWARD,
            description="Test reward",
        )

        self.player.refresh_from_db()
        self.assertTrue(result.applied)
        self.assertEqual(self.player.chips, 1_250)
        self.assertEqual(result.transaction.balance_before, 1_000)
        self.assertEqual(result.transaction.balance_after, 1_250)

    def test_debit_updates_balance_and_writes_ledger(self):
        result = adjust_balance(
            self.player,
            -400,
            category=ChipTransaction.Category.BET,
        )

        self.player.refresh_from_db()
        self.assertEqual(self.player.chips, 600)
        self.assertEqual(result.transaction.amount, -400)

    def test_insufficient_balance_rolls_back_without_ledger_entry(self):
        with self.assertRaises(InsufficientChips):
            adjust_balance(
                self.player,
                -1_001,
                category=ChipTransaction.Category.BET,
            )

        self.player.refresh_from_db()
        self.assertEqual(self.player.chips, 1_000)
        self.assertFalse(ChipTransaction.objects.exists())

    def test_idempotency_key_prevents_duplicate_credit(self):
        first = adjust_balance(
            self.player,
            500,
            category=ChipTransaction.Category.BLACKJACK_PAYOUT,
            idempotency_key="blackjack:game-7:player-1001:payout",
        )
        retry = adjust_balance(
            self.player,
            500,
            category=ChipTransaction.Category.BLACKJACK_PAYOUT,
            idempotency_key="blackjack:game-7:player-1001:payout",
        )

        self.player.refresh_from_db()
        self.assertTrue(first.applied)
        self.assertFalse(retry.applied)
        self.assertEqual(self.player.chips, 1_500)
        self.assertEqual(ChipTransaction.objects.count(), 1)

    def test_transaction_can_be_reversed_exactly_once(self):
        original = adjust_balance(
            self.player, 250, category=ChipTransaction.Category.DAILY_REWARD
        ).transaction
        reversal = reverse_chip_transaction(original.id, operator="test-admin")
        with self.assertRaises(TransactionAlreadyReversed):
            reverse_chip_transaction(original.id, operator="test-admin")
        self.player.refresh_from_db()
        self.assertEqual(self.player.chips, 1_000)
        self.assertEqual(reversal.transaction.amount, -250)
        self.assertEqual(
            reversal.transaction.metadata["reverses_transaction_id"], original.id
        )

    def test_zero_changes_are_rejected(self):
        with self.assertRaises(ValueError):
            adjust_balance(
                self.player,
                0,
                category=ChipTransaction.Category.OTHER,
            )

    @override_settings(SUSPICIOUS_TRANSACTION_AMOUNT=500)
    def test_large_transaction_creates_suspicious_activity_incident(self):
        adjust_balance(
            self.player,
            500,
            category=ChipTransaction.Category.ADMIN_ADJUSTMENT,
        )
        event = OperationalEvent.objects.get(category="suspicious_economy")
        self.assertEqual(event.player_id, self.player.id)
        self.assertIn("large_amount", event.context["reasons"])


class ProtectedOperationsTests(TestCase):
    def setUp(self):
        self.url = reverse("process-game-results")

    def test_xp_recalculation_requires_staff_authentication(self):
        response = self.client.post(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertIn("/admin/login/", response.url)

    def test_xp_recalculation_rejects_get_requests_for_staff(self):
        user = get_user_model().objects.create_user(
            username="operator",
            password="test-password",
            is_staff=True,
        )
        self.client.force_login(user)

        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 405)

    def test_rest_api_requires_admin_user(self):
        response = self.client.get("/game/api/players/")
        self.assertIn(response.status_code, (401, 403))

    def test_rest_api_is_read_only_even_for_admin(self):
        user = get_user_model().objects.create_superuser(
            username="api-operator", password="test-password"
        )
        player = Player.objects.create(id=1500, name="API Target", chips=100)
        self.client.force_login(user)
        response = self.client.patch(
            f"/game/api/players/{player.id}/",
            {"chips": 999},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 405)
        player.refresh_from_db()
        self.assertEqual(player.chips, 100)

    def test_admin_chip_edit_creates_adjustment_ledger_entry(self):
        operator = get_user_model().objects.create_superuser(
            username="ledger-operator", password="test-password"
        )
        player = Player.objects.create(id=1501, name="Admin Target", chips=100)
        edited = Player.objects.get(pk=player.pk)
        edited.chips = 175
        request = RequestFactory().post("/admin/game/player/")
        request.user = operator

        admin.site._registry[Player].save_model(request, edited, None, True)

        player.refresh_from_db()
        entry = ChipTransaction.objects.get(player=player)
        self.assertEqual(player.chips, 175)
        self.assertEqual(entry.amount, 75)
        self.assertEqual(entry.category, ChipTransaction.Category.ADMIN_ADJUSTMENT)

    def test_structured_log_includes_correlation_ids(self):
        record = logging.LogRecord(
            "game.test", logging.INFO, __file__, 1, "settled", (), None
        )
        record.game_id = 77
        record.chat_id = -1001
        record.player_id = 42
        payload = json.loads(JsonFormatter().format(record))
        self.assertEqual(payload["message"], "settled")
        self.assertEqual(payload["game_id"], 77)
        self.assertEqual(payload["chat_id"], -1001)
        self.assertEqual(payload["player_id"], 42)



class TelegramAccessGuardTests(TestCase):
    def test_global_guard_blocks_frozen_player_but_keeps_help_available(self):
        Player.objects.create(id=1502, name="Frozen", is_frozen=True)
        self.assertFalse(telegram_access_allowed(1502, command="/slot"))
        self.assertTrue(telegram_access_allowed(1502, command="/help"))

    def test_global_guard_maintenance_exempts_admin(self):
        Player.objects.create(id=1503, name="Regular")
        Player.objects.create(id=1504, name="Operator", admin=True)
        BotControl.objects.create(maintenance_mode=True)
        self.assertFalse(telegram_access_allowed(1503, command="/slot"))
        self.assertTrue(telegram_access_allowed(1504, command="/slot"))


class BlackjackPersistenceTests(TestCase):
    def setUp(self):
        self.player = Player.objects.create(id=2001, name="Blackjack Tester", chips=500)
        self.game = Game.objects.create(chat_id="-10001", bet_amount=100, join_time=True)

    def test_join_debits_and_creates_participation_atomically(self):
        joined = join_game_with_chips(self.player.id, self.game.id)

        self.player.refresh_from_db()
        self.assertEqual(self.player.chips, 400)
        self.assertTrue(joined.is_active)
        ledger = ChipTransaction.objects.get(player=self.player)
        self.assertEqual(ledger.category, ChipTransaction.Category.BET)
        self.assertEqual(ledger.reference_id, str(self.game.id))

    def test_duplicate_join_does_not_debit_twice(self):
        join_game_with_chips(self.player.id, self.game.id)

        with self.assertRaises(AlreadyJoined):
            join_game_with_chips(self.player.id, self.game.id)

        self.player.refresh_from_db()
        self.assertEqual(self.player.chips, 400)
        self.assertEqual(JoinGame.objects.count(), 1)
        self.assertEqual(ChipTransaction.objects.count(), 1)

    def test_player_cannot_join_two_active_tables(self):
        join_game_with_chips(self.player.id, self.game.id)
        other = Game.objects.create(chat_id="-10002", bet_amount=100, join_time=True)
        with self.assertRaises(ActiveInAnotherGame):
            join_game_with_chips(self.player.id, other.id)
        self.player.refresh_from_db()
        self.assertEqual(self.player.chips, 400)

    def test_failed_join_creates_neither_participation_nor_ledger(self):
        self.game.bet_amount = 501
        self.game.save(update_fields=("bet_amount",))
        with self.assertRaises(InsufficientChips):
            join_game_with_chips(self.player.id, self.game.id)
        self.assertFalse(JoinGame.objects.exists())
        self.assertFalse(ChipTransaction.objects.exists())

    def test_refund_restores_balance_and_removes_participation(self):
        joined = join_game_with_chips(self.player.id, self.game.id)
        self.assertTrue(refund_joined_player(joined.id, description="Test refund"))
        self.assertFalse(refund_joined_player(joined.id, description="Retry"))
        self.player.refresh_from_db()
        self.assertEqual(self.player.chips, 500)
        self.assertFalse(JoinGame.objects.exists())
        self.assertEqual(ChipTransaction.objects.count(), 2)

    def test_operator_can_pause_new_blackjack_bets(self):
        BotControl.objects.create(pk=1, betting_paused=True)
        with self.assertRaises(BettingPaused):
            join_game_with_chips(self.player.id, self.game.id)
        self.player.refresh_from_db()
        self.assertEqual(self.player.chips, 500)
        self.assertFalse(JoinGame.objects.exists())


class BlackjackTurnTimeoutTests(TestCase):
    def setUp(self):
        self.player = Player.objects.create(id=2051, name="Slow Player", chips=500)
        self.game = Game.objects.create(
            chat_id="-2051", bet_amount=100, started=True,
            turn_order=[self.player.id]
        )
        self.joined = JoinGame.objects.create(
            player=self.player, game=self.game, is_active=True
        )

    def test_first_timeout_skips_and_second_consecutive_timeout_removes(self):
        first_token = begin_player_turn(self.game.id, self.player.id)
        first = apply_player_timeout(self.game.id, self.player.id, first_token)
        self.assertTrue(first.applied)
        self.assertFalse(first.removed)

        self.joined.refresh_from_db()
        self.joined.has_stood = False
        self.joined.save(update_fields=("has_stood",))
        second_token = begin_player_turn(self.game.id, self.player.id)
        second = apply_player_timeout(self.game.id, self.player.id, second_token)

        self.joined.refresh_from_db()
        self.assertTrue(second.removed)
        self.assertEqual(self.joined.consecutive_timeouts, 2)
        self.assertFalse(self.joined.is_active)
        self.assertTrue(
            OperationalEvent.objects.filter(
                category="player_inactivity", player_id=self.player.id
            ).exists()
        )

    def test_valid_action_resets_timeout_streak_and_invalidates_old_timer(self):
        old_token = begin_player_turn(self.game.id, self.player.id)
        apply_player_timeout(self.game.id, self.player.id, old_token)
        new_token = begin_player_turn(self.game.id, self.player.id)
        record_player_action(self.game.id, self.player.id)

        stale = apply_player_timeout(self.game.id, self.player.id, new_token)
        self.joined.refresh_from_db()
        self.assertFalse(stale.applied)
        self.assertEqual(self.joined.consecutive_timeouts, 0)
        self.assertTrue(self.joined.is_active)

class OperationalControlTests(TestCase):
    def test_betting_is_open_by_default(self):
        ensure_betting_open()
        self.assertTrue(BotControl.objects.filter(pk=1).exists())

    def test_betting_pause_raises_gate_exception(self):
        BotControl.objects.create(pk=1, betting_paused=True)
        with self.assertRaises(BettingPaused):
            ensure_betting_open()

    def test_admin_permission_comes_from_player_record(self):
        regular = Player.objects.create(id=8001, name="Regular", admin=False)
        operator = Player.objects.create(id=8002, name="Operator", admin=True)

        self.assertFalse(is_player_admin(regular.id))
        self.assertTrue(is_player_admin(operator.id))

        operator.is_frozen = True
        operator.save(update_fields=("is_frozen",))
        self.assertFalse(is_player_admin(operator.id))


class AdminDashboardTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser(
            username="dashboard-admin",
            password="test-password",
            email="admin@example.com",
        )
        self.factory = RequestFactory()

    def test_economy_dashboard_renders_ledger_metrics(self):
        request = self.factory.get(reverse("admin:game_chiptransaction_changelist"))
        request.user = self.admin
        model_admin = admin.site._registry[ChipTransaction]
        response = model_admin.changelist_view(request)

        self.assertEqual(response.status_code, 200)
        self.assertIn("economy", response.context_data)
        self.assertIn("total_supply", response.context_data["economy"])
        self.assertIn("net_24h", response.context_data["economy"])

    def test_operations_dashboard_renders_active_game_metrics(self):
        request = self.factory.get(reverse("admin:game_botcontrol_changelist"))
        request.user = self.admin
        model_admin = admin.site._registry[BotControl]
        response = model_admin.changelist_view(request)

        self.assertEqual(response.status_code, 200)
        self.assertIn("operations", response.context_data)
        self.assertIn("active_games", response.context_data["operations"])
        self.assertIn("active_crash_games", response.context_data["operations"])


class LoanServiceTests(TestCase):
    def setUp(self):
        self.player = Player.objects.create(
            id=3001,
            name="Loan Tester",
            chips=500,
            xp=100,
            level=2,
        )
        self.dealer = Dealer.objects.create(chips=10_000)

    def test_loan_moves_chips_and_records_player_ledger(self):
        issue_loan(self.player.id, 1_000, 50)

        self.player.refresh_from_db()
        self.dealer.refresh_from_db()
        self.assertEqual(self.player.chips, 1_500)
        self.assertEqual(self.player.loan, 1_000)
        self.assertEqual(self.player.xp, 50)
        self.assertEqual(self.dealer.chips, 9_000)
        self.assertEqual(
            ChipTransaction.objects.get().category,
            ChipTransaction.Category.LOAN,
        )

    def test_level_down_loan_deducts_xp_once(self):
        self.player.xp = 10
        self.player.save(update_fields=("xp",))

        issue_loan(self.player.id, 100, 25)

        self.player.refresh_from_db()
        self.assertEqual(self.player.level, 1)
        self.assertEqual(self.player.xp, 35)

    def test_unaffordable_xp_rolls_back_loan(self):
        self.player.level = 1
        self.player.xp = 0
        self.player.save(update_fields=("level", "xp"))

        with self.assertRaises(InsufficientExperience):
            issue_loan(self.player.id, 100, 25)

        self.player.refresh_from_db()
        self.dealer.refresh_from_db()
        self.assertEqual(self.player.chips, 500)
        self.assertEqual(self.dealer.chips, 10_000)
        self.assertFalse(ChipTransaction.objects.exists())

    def test_repayment_is_atomic_and_includes_interest(self):
        issue_loan(self.player.id, 1_000, 50)
        _, repayment = repay_loan(self.player.id)

        self.player.refresh_from_db()
        self.dealer.refresh_from_db()
        self.assertEqual(repayment, 1_030)
        self.assertEqual(self.player.chips, 470)
        self.assertEqual(self.player.loan, 0)
        self.assertEqual(self.dealer.chips, 10_030)
        self.assertEqual(ChipTransaction.objects.count(), 2)


class PlayerPreferenceTests(TestCase):
    def test_language_and_compact_preferences_are_persistent(self):
        player = Player.objects.create(id=4001, name="Preference Tester")
        settings = UserSettings.objects.create(
            player=player,
            language=UserSettings.Language.PERSIAN,
            compact_mode=True,
        )

        settings.refresh_from_db()
        self.assertEqual(settings.language, "fa")
        self.assertTrue(settings.compact_mode)


class HorseRacePersistenceTests(TestCase):
    def setUp(self):
        self.player = Player.objects.create(id=5001, name="Race Tester", chips=1_000)
        self.race = HorseRace.objects.create(chat_id=-10002)

    def test_race_bet_is_atomic_and_audited(self):
        bet = place_race_bet(
            race_id=self.race.id,
            player_id=self.player.id,
            horse_number=2,
            amount=250,
            username="tester",
        )

        self.player.refresh_from_db()
        self.assertEqual(self.player.chips, 750)
        self.assertEqual(bet.bet_amount, 250)
        ledger = ChipTransaction.objects.get(player=self.player)
        self.assertEqual(ledger.category, ChipTransaction.Category.BET)
        self.assertEqual(ledger.reference_type, "horse_race")

    def test_duplicate_race_bet_cannot_charge_twice(self):
        kwargs = {
            "race_id": self.race.id,
            "player_id": self.player.id,
            "horse_number": 2,
            "amount": 250,
            "username": "tester",
        }
        place_race_bet(**kwargs)
        with self.assertRaises(AlreadyBet):
            place_race_bet(**kwargs)

        self.player.refresh_from_db()
        self.assertEqual(self.player.chips, 750)
        self.assertEqual(HorseBet.objects.count(), 1)
        self.assertEqual(ChipTransaction.objects.count(), 1)

    def test_player_cannot_bet_in_two_active_races(self):
        place_race_bet(
            race_id=self.race.id, player_id=self.player.id, horse_number=2,
            amount=250, username="tester"
        )
        other = HorseRace.objects.create(chat_id=-10003)
        with self.assertRaises(ActiveRaceBet):
            place_race_bet(
                race_id=other.id, player_id=self.player.id, horse_number=3,
                amount=250, username="tester"
            )
        self.player.refresh_from_db()
        self.assertEqual(self.player.chips, 750)

    def test_started_race_rejects_bet_without_debit(self):
        self.race.race_started = True
        self.race.save(update_fields=("race_started",))

        with self.assertRaises(RaceAlreadyStarted):
            place_race_bet(
                race_id=self.race.id,
                player_id=self.player.id,
                horse_number=2,
                amount=250,
                username="tester",
            )

        self.player.refresh_from_db()
        self.assertEqual(self.player.chips, 1_000)
        self.assertFalse(HorseBet.objects.exists())


class CrashGamePersistenceTests(TestCase):
    def setUp(self):
        self.player = Player.objects.create(id=6001, name="Crash Tester", chips=1_000)

    def test_start_is_atomic_and_prevents_parallel_game(self):
        game = start_crash_game(self.player.id, 200)
        with self.assertRaises(ActiveCrashGame):
            start_crash_game(self.player.id, 200)

        self.player.refresh_from_db()
        self.assertEqual(self.player.chips, 800)
        self.assertEqual(CrashGame.objects.count(), 1)
        self.assertEqual(game.bet, 200)
        self.assertEqual(ChipTransaction.objects.count(), 1)

    def test_cashout_pays_once_and_removes_active_game(self):
        game = start_crash_game(self.player.id, 200)
        game.multiplier = 2.5
        game.save(update_fields=("multiplier",))

        settlement = cash_out_crash_game(self.player.id)
        with self.assertRaises(NoActiveCrashGame):
            cash_out_crash_game(self.player.id)

        self.player.refresh_from_db()
        self.assertEqual(settlement.winnings, 500)
        self.assertEqual(self.player.chips, 1_300)
        self.assertFalse(CrashGame.objects.exists())
        self.assertEqual(ChipTransaction.objects.count(), 2)

    def test_crashed_game_cannot_cash_out(self):
        game = start_crash_game(self.player.id, 200)
        self.assertTrue(mark_crash_game_crashed(game.id))

        with self.assertRaises(NoActiveCrashGame):
            cash_out_crash_game(self.player.id)

        self.player.refresh_from_db()
        self.assertEqual(self.player.chips, 800)

    def test_missing_or_settled_game_is_not_marked_crashed(self):
        self.assertFalse(mark_crash_game_crashed(999999))


class TransferAndPurchaseTests(TestCase):
    def setUp(self):
        self.giver = Player.objects.create(id=7001, name="Giver", chips=1_000)
        self.receiver = Player.objects.create(id=7002, name="Receiver", chips=100)

    def test_transfer_updates_both_players_and_writes_two_ledger_entries(self):
        transfer_chips(
            self.giver.id,
            self.receiver.id,
            300,
            idempotency_key="transfer:test:1",
        )

        self.giver.refresh_from_db()
        self.receiver.refresh_from_db()
        self.assertEqual(self.giver.chips, 700)
        self.assertEqual(self.receiver.chips, 400)
        self.assertEqual(ChipTransaction.objects.count(), 2)

    def test_transfer_retry_does_not_move_money_twice(self):
        for _ in range(2):
            transfer_chips(
                self.giver.id,
                self.receiver.id,
                300,
                idempotency_key="transfer:test:retry",
            )

        self.giver.refresh_from_db()
        self.receiver.refresh_from_db()
        self.assertEqual(self.giver.chips, 700)
        self.assertEqual(self.receiver.chips, 400)

    def test_failed_transfer_rolls_back_both_sides(self):
        with self.assertRaises(InsufficientChips):
            transfer_chips(self.giver.id, self.receiver.id, 1_001)

        self.giver.refresh_from_db()
        self.receiver.refresh_from_db()
        self.assertEqual(self.giver.chips, 1_000)
        self.assertEqual(self.receiver.chips, 100)
        self.assertFalse(ChipTransaction.objects.exists())

    def test_item_purchase_debits_and_increments_inventory_atomically(self):
        purchase_item(self.giver.id, "insurance_pass", 200)
        purchase_item(self.giver.id, "insurance_pass", 200)

        self.giver.refresh_from_db()
        item = PlayerItem.objects.get(player=self.giver, item_type="insurance_pass")
        self.assertEqual(self.giver.chips, 600)
        self.assertEqual(item.quantity, 2)
        self.assertEqual(ChipTransaction.objects.count(), 2)

    def test_failed_item_purchase_does_not_create_inventory(self):
        with self.assertRaises(InsufficientChips):
            purchase_item(self.receiver.id, "insurance_pass", 200)

        self.receiver.refresh_from_db()
        self.assertEqual(self.receiver.chips, 100)
        self.assertFalse(PlayerItem.objects.exists())


class RouletteSettlementTests(TestCase):
    def setUp(self):
        self.player = Player.objects.create(id=9001, name="Roulette Tester", chips=1_000)

    def test_loss_debits_one_bet(self):
        result = settle_roulette(self.player.id, 7, 100, 8, "loss-1")

        self.player.refresh_from_db()
        self.assertFalse(result.won)
        self.assertEqual(self.player.chips, 900)
        self.assertEqual(ChipTransaction.objects.count(), 1)

    def test_win_preserves_original_net_35x_behavior(self):
        result = settle_roulette(self.player.id, 7, 100, 7, "win-1")

        self.player.refresh_from_db()
        self.assertTrue(result.won)
        self.assertEqual(result.winnings, 3_500)
        self.assertEqual(self.player.chips, 4_500)
        self.assertEqual(ChipTransaction.objects.count(), 2)

    def test_replayed_update_uses_original_result_without_double_settlement(self):
        first = settle_roulette(self.player.id, 7, 100, 7, "retry-1")
        replay = settle_roulette(self.player.id, 12, 999, 2, "retry-1")

        self.player.refresh_from_db()
        self.assertFalse(first.replayed)
        self.assertTrue(replay.replayed)
        self.assertEqual(replay.selected_number, 7)
        self.assertEqual(replay.result_number, 7)
        self.assertEqual(self.player.chips, 4_500)
        self.assertEqual(ChipTransaction.objects.count(), 2)


class SpinSettlementTests(TestCase):
    def setUp(self):
        self.player = Player.objects.create(
            id=9101,
            name="Spin Tester",
            chips=1_000,
            xp=20,
            level=2,
        )

    def test_spin_cost_and_positive_reward_are_audited(self):
        result = settle_spin(
            self.player.id,
            "low",
            200,
            ("Win", 500, 50, 1),
            "spin-win",
        )

        self.player.refresh_from_db()
        self.assertEqual(self.player.chips, 1_300)
        self.assertEqual(self.player.xp, 70)
        self.assertEqual(self.player.level, 3)
        self.assertEqual(result.actual_chips_delta, 500)
        self.assertEqual(ChipTransaction.objects.count(), 2)

    def test_negative_reward_is_clamped_at_zero_balance(self):
        result = settle_spin(
            self.player.id,
            "low",
            200,
            ("Large loss", -5_000, -50, -5),
            "spin-loss",
        )

        self.player.refresh_from_db()
        self.assertEqual(self.player.chips, 0)
        self.assertEqual(self.player.xp, 0)
        self.assertEqual(self.player.level, 1)
        self.assertEqual(result.actual_chips_delta, -800)

    def test_spin_replay_does_not_apply_new_outcome(self):
        settle_spin(self.player.id, "low", 200, ("Win", 500, 50, 1), "same-spin")
        replay = settle_spin(
            self.player.id,
            "high",
            20_000,
            ("Different", -50_000, -500, -2),
            "same-spin",
        )

        self.player.refresh_from_db()
        self.assertTrue(replay.replayed)
        self.assertEqual(replay.label, "Win")
        self.assertEqual(self.player.chips, 1_300)
        self.assertEqual(self.player.xp, 70)
        self.assertEqual(self.player.level, 3)


class StartupRecoveryTests(TestCase):
    def test_active_crash_game_is_refunded(self):
        player = Player.objects.create(id=9201, name="Crash Recovery", chips=1_000)
        start_crash_game(player.id, 250)

        report = recover_interrupted_games()

        player.refresh_from_db()
        self.assertEqual(player.chips, 1_000)
        self.assertEqual(report.crash_games, 1)
        self.assertFalse(CrashGame.objects.exists())
        self.assertEqual(OperationalEvent.objects.filter(category="startup_recovery").count(), 1)

    def test_started_race_is_refunded(self):
        player = Player.objects.create(id=9202, name="Race Recovery", chips=1_000)
        race = HorseRace.objects.create(chat_id=-20001)
        place_race_bet(
            race_id=race.id,
            player_id=player.id,
            horse_number=2,
            amount=300,
            username="recovery",
        )
        race.race_started = True
        race.save(update_fields=("race_started",))

        report = recover_interrupted_games()

        player.refresh_from_db()
        self.assertEqual(player.chips, 1_000)
        self.assertEqual(report.races, 1)
        self.assertFalse(HorseRace.objects.exists())

    def test_started_blackjack_game_is_refunded(self):
        player = Player.objects.create(id=9203, name="Blackjack Recovery", chips=1_000)
        Dealer.objects.create(chips=900)
        game = Game.objects.create(
            chat_id="-20002",
            bet_amount=100,
            started=True,
            join_time=False,
        )
        join_game_with_chips(player.id, game.id)

        report = recover_interrupted_games()

        player.refresh_from_db()
        dealer = Dealer.objects.get()
        self.assertEqual(player.chips, 1_000)
        self.assertEqual(dealer.chips, 1_000)
        self.assertEqual(report.blackjack_games, 1)
        self.assertFalse(Game.objects.exists())


class OperatorCancellationTests(TestCase):
    def test_cancel_crash_refunds_once_and_logs_incident(self):
        player = Player.objects.create(id=9251, name="Crash Cancel", chips=1_000)
        crash = start_crash_game(player.id, 250)

        self.assertEqual(cancel_crash_game(crash.id), 1)
        self.assertEqual(cancel_crash_game(crash.id), 0)
        player.refresh_from_db()
        self.assertEqual(player.chips, 1_000)
        self.assertEqual(ChipTransaction.objects.count(), 2)
        self.assertTrue(
            OperationalEvent.objects.filter(category="operator_cancel").exists()
        )

    def test_cancel_race_refunds_every_bet(self):
        first = Player.objects.create(id=9252, name="Race One", chips=1_000)
        second = Player.objects.create(id=9253, name="Race Two", chips=1_000)
        race = HorseRace.objects.create(chat_id=-9252)
        place_race_bet(
            race_id=race.id, player_id=first.id, horse_number=1,
            amount=100, username="one"
        )
        place_race_bet(
            race_id=race.id, player_id=second.id, horse_number=2,
            amount=200, username="two"
        )

        self.assertEqual(cancel_race(race.id), 2)
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual((first.chips, second.chips), (1_000, 1_000))
        self.assertFalse(HorseRace.objects.exists())

    def test_cancel_started_blackjack_restores_players_and_dealer_stake(self):
        player = Player.objects.create(id=9254, name="Blackjack Cancel", chips=1_000)
        dealer = Dealer.objects.create(chips=1_000)
        game = Game.objects.create(
            chat_id="-9254", bet_amount=100, started=True, join_time=False
        )
        join_game_with_chips(player.id, game.id)
        dealer.chips -= game.bet_amount
        dealer.save(update_fields=("chips",))

        self.assertEqual(cancel_blackjack_game(game.id), 1)
        player.refresh_from_db()
        dealer.refresh_from_db()
        self.assertEqual(player.chips, 1_000)
        self.assertEqual(dealer.chips, 1_000)
        self.assertFalse(Game.objects.exists())


class MysteryBoxSettlementTests(TestCase):
    def setUp(self):
        self.player = Player.objects.create(
            id=9301,
            name="Mystery Tester",
            chips=1_000,
            xp=40,
            level=1,
        )

    def test_chip_box_cost_and_reward_are_atomic(self):
        result = open_mystery_box(
            self.player.id, "bronze", 200, "chips", 500, "box-chip"
        )

        self.player.refresh_from_db()
        self.assertEqual(result.chips, 500)
        self.assertEqual(self.player.chips, 1_300)
        self.assertEqual(ChipTransaction.objects.count(), 2)

    def test_xp_reward_levels_up_and_ledgers_level_chips(self):
        result = open_mystery_box(
            self.player.id, "bronze", 200, "xp", 20, "box-xp"
        )

        self.player.refresh_from_db()
        self.assertEqual(self.player.level, 2)
        self.assertEqual(self.player.xp, 10)
        self.assertEqual(self.player.chips, 900)
        self.assertEqual(result.level_rewards, ((2, 100),))
        self.assertEqual(ChipTransaction.objects.count(), 2)

    def test_item_reward_and_cost_commit_together(self):
        result = open_mystery_box(
            self.player.id,
            "gold",
            200,
            "item",
            "insurance_pass",
            "box-item",
        )

        self.player.refresh_from_db()
        self.assertEqual(self.player.chips, 800)
        self.assertEqual(result.item_type, "insurance_pass")
        self.assertEqual(
            PlayerItem.objects.get(player=self.player, item_type="insurance_pass").quantity,
            1,
        )

    def test_replayed_box_keeps_original_reward(self):
        open_mystery_box(self.player.id, "bronze", 200, "chips", 500, "same-box")
        replay = open_mystery_box(
            self.player.id, "gold", 900, "item", "insurance_pass", "same-box"
        )

        self.player.refresh_from_db()
        self.assertTrue(replay.replayed)
        self.assertEqual(replay.reward_type, "chips")
        self.assertEqual(self.player.chips, 1_300)
        self.assertFalse(PlayerItem.objects.exists())


class HorseEconomyTests(TestCase):
    def setUp(self):
        self.buyer = Player.objects.create(id=9401, name="Horse Buyer", chips=1_000)
        self.seller = Player.objects.create(id=9402, name="Horse Seller", chips=100)

    def test_horse_purchase_is_atomic_and_audited(self):
        horse = buy_horse(self.buyer.id, 42, 300)

        self.buyer.refresh_from_db()
        self.assertEqual(self.buyer.chips, 700)
        self.assertEqual(horse.user_id, self.buyer.id)
        self.assertEqual(ChipTransaction.objects.count(), 1)
        with self.assertRaises(HorseUnavailable):
            buy_horse(self.seller.id, 42, 300)

    def test_upgrade_purchase_cannot_duplicate_or_double_charge(self):
        upgrade = HorseUpgrade.objects.create(name="Fast", description="Fast", cost=250)
        buy_horse_upgrade(self.buyer.id, upgrade.id)
        with self.assertRaises(UpgradeAlreadyOwned):
            buy_horse_upgrade(self.buyer.id, upgrade.id)

        self.buyer.refresh_from_db()
        self.assertEqual(self.buyer.chips, 750)
        self.assertEqual(ChipTransaction.objects.count(), 1)

    def test_customization_updates_horse_with_same_debit(self):
        horse = OwnedHorse.objects.create(user=self.buyer, horse_number=43)
        customize_horse(self.buyer.id, horse.horse_number, 100, name="Comet")

        self.buyer.refresh_from_db()
        horse.refresh_from_db()
        self.assertEqual(self.buyer.chips, 900)
        self.assertEqual(horse.name, "Comet")

    def test_gift_fee_and_ownership_transfer_are_atomic(self):
        horse = OwnedHorse.objects.create(user=self.buyer, horse_number=44)
        gift_owned_horse(self.buyer.id, self.seller.id, horse.horse_number, 100)

        self.buyer.refresh_from_db()
        horse.refresh_from_db()
        self.assertEqual(self.buyer.chips, 900)
        self.assertEqual(horse.user_id, self.seller.id)

    def test_purchase_for_recipient_charges_payer_and_assigns_recipient(self):
        horse = buy_horse_for_recipient(
            self.buyer.id,
            self.seller.id,
            47,
            300,
        )

        self.buyer.refresh_from_db()
        self.seller.refresh_from_db()
        self.assertEqual(self.buyer.chips, 700)
        self.assertEqual(self.seller.chips, 100)
        self.assertEqual(horse.user_id, self.seller.id)

    def test_market_sale_moves_money_horse_and_listing_together(self):
        horse = OwnedHorse.objects.create(user=self.seller, horse_number=45)
        HorseSale.objects.create(horse=horse, price=400)

        result = purchase_horse_sale(self.buyer.id, horse.horse_number)

        self.buyer.refresh_from_db()
        self.seller.refresh_from_db()
        horse.refresh_from_db()
        self.assertEqual(result.price, 400)
        self.assertEqual(self.buyer.chips, 600)
        self.assertEqual(self.seller.chips, 500)
        self.assertEqual(horse.user_id, self.buyer.id)
        self.assertFalse(HorseSale.objects.exists())
        self.assertEqual(ChipTransaction.objects.count(), 2)

    def test_failed_market_sale_leaves_everything_unchanged(self):
        horse = OwnedHorse.objects.create(user=self.seller, horse_number=46)
        HorseSale.objects.create(horse=horse, price=1_001)

        with self.assertRaises(InsufficientChips):
            purchase_horse_sale(self.buyer.id, horse.horse_number)

        horse.refresh_from_db()
        self.assertEqual(horse.user_id, self.seller.id)
        self.assertTrue(HorseSale.objects.exists())
        self.assertFalse(ChipTransaction.objects.exists())


class ItemConsumptionTests(TestCase):
    def setUp(self):
        self.player = Player.objects.create(
            id=9451, name="Item Tester", chips=100, xp=40
        )

    def test_booster_consumption_and_rewards_are_atomic(self):
        item = PlayerItem.objects.create(
            player=self.player, item_type="xp_booster_500", quantity=1
        )
        result = consume_xp_booster(self.player.id, item.item_type, 20)
        item.refresh_from_db()
        self.player.refresh_from_db()
        self.assertEqual(item.quantity, 0)
        self.assertEqual((result.level, result.xp), (2, 10))
        self.assertEqual(self.player.chips, 200)
        with self.assertRaises(ItemUnavailable):
            consume_xp_booster(self.player.id, item.item_type, 20)

    def test_item_activation_decrements_inventory_once(self):
        item = PlayerItem.objects.create(
            player=self.player, item_type="insurance_pass", quantity=1
        )
        activate_inventory_item(
            self.player.id, item.item_type, ["insurance_pass", "first_hand_20"]
        )
        item.refresh_from_db()
        self.assertEqual(item.quantity, 0)
        self.assertTrue(PlayerActiveItem.objects.filter(player=self.player).exists())

    def test_category_exclusivity_does_not_consume_second_item(self):
        PlayerActiveItem.objects.create(
            player=self.player, item_type="insurance_pass", is_active=True
        )
        item = PlayerItem.objects.create(
            player=self.player, item_type="first_hand_20", quantity=1
        )
        with self.assertRaises(ItemCategoryAlreadyActive):
            activate_inventory_item(
                self.player.id, item.item_type,
                ["insurance_pass", "first_hand_20"]
            )
        item.refresh_from_db()
        self.assertEqual(item.quantity, 1)


class ProgressionServiceTests(TestCase):
    def setUp(self):
        self.player = Player.objects.create(
            id=9501, name="Progression Tester", chips=1_000, xp=10, level=1
        )

    def test_award_without_level_does_not_change_chips(self):
        result = award_xp(self.player, 20)
        self.player.refresh_from_db()
        self.assertEqual((result.level, result.xp), (1, 30))
        self.assertEqual(self.player.chips, 1_000)
        self.assertFalse(ChipTransaction.objects.exists())

    def test_multiple_levels_create_one_audited_reward(self):
        result = award_xp(self.player, 200)
        self.player.refresh_from_db()
        self.assertEqual((self.player.level, self.player.xp), (3, 60))
        self.assertEqual(result.level_rewards, ((2, 100), (3, 150)))
        self.assertEqual(self.player.chips, 1_250)
        transaction = ChipTransaction.objects.get()
        self.assertEqual(transaction.category, ChipTransaction.Category.LEVEL_REWARD)
        self.assertEqual(transaction.amount, 250)

    def test_deduction_can_cross_multiple_levels(self):
        self.player.level = 3
        self.player.xp = 20
        self.player.save(update_fields=("level", "xp"))
        result = deduct_xp_amount(self.player, 100)
        self.assertEqual((result.level, result.xp), (2, 20))
        self.assertTrue(result.level_changed)

    def test_deduction_clamps_at_level_one(self):
        result = deduct_xp_amount(self.player, 500)
        self.assertEqual((result.level, result.xp), (1, 0))


class ReferralServiceTests(TestCase):
    def test_bonus_updates_balance_total_and_history_atomically(self):
        referrer = Player.objects.create(id=9601, name="Referrer", chips=100)
        referred = Player.objects.create(id=9602, name="Friend")

        award_referral_bonus(
            referrer.id,
            referred.id,
            500,
            description="Test referral",
            idempotency_key="referral-test",
        )
        replay = award_referral_bonus(
            referrer.id,
            referred.id,
            500,
            description="Test referral",
            idempotency_key="referral-test",
        )

        referrer.refresh_from_db()
        self.assertFalse(replay.applied)
        self.assertEqual(referrer.chips, 600)
        self.assertEqual(referrer.total_referral_bonus, 500)
        self.assertEqual(ReferralEarning.objects.count(), 1)
        self.assertEqual(ChipTransaction.objects.count(), 1)


class DailyRewardServiceTests(TestCase):
    def setUp(self):
        self.player = Player.objects.create(id=9701, name="Daily Tester", chips=100, xp=45)

    def test_daily_chips_are_audited_and_cannot_be_reclaimed(self):
        now = timezone.now()
        self.assertEqual(claim_daily_chips(self.player.id, 200, now), 300)
        with self.assertRaises(RewardAlreadyClaimed):
            claim_daily_chips(self.player.id, 200, now)
        self.player.refresh_from_db()
        self.assertEqual(self.player.chips, 300)
        self.assertEqual(ChipTransaction.objects.count(), 1)

    def test_daily_box_commits_chips_xp_level_and_item(self):
        result = claim_daily_box(
            self.player.id,
            timezone.localdate(),
            250,
            10,
            "double_chip_potion",
        )
        self.player.refresh_from_db()
        self.assertEqual(result.balance, 350)
        self.assertEqual((self.player.level, self.player.xp), (2, 5))
        self.assertEqual(self.player.chips, 450)
        self.assertEqual(PlayerItem.objects.get(player=self.player).quantity, 1)
        self.assertEqual(ChipTransaction.objects.count(), 2)

    def test_daily_xp_claim_and_level_reward_are_atomic(self):
        result = claim_daily_xp(self.player.id, 10, timezone.now())
        self.player.refresh_from_db()
        self.assertEqual((result.level, result.xp), (2, 5))
        self.assertEqual(self.player.chips, 200)
        self.assertEqual(ChipTransaction.objects.count(), 1)
        with self.assertRaises(RewardAlreadyClaimed):
            claim_daily_xp(self.player.id, 10, timezone.now())


class DailyQuestServiceTests(TestCase):
    def setUp(self):
        self.player = Player.objects.create(id=9751, name="Quest Tester", chips=100, xp=45)
        self.quest = DailyQuest.objects.create(
            quest_type="minigames",
            subtype="dart",
            description="Hit two targets",
            target=2,
            reward_xp=10,
            reward_chips=75,
            available=True,
        )

    def test_completion_progress_xp_and_chip_rewards_commit_together(self):
        first = advance_daily_quest(self.player.id, self.quest.id)
        second = advance_daily_quest(self.player.id, self.quest.id)

        self.player.refresh_from_db()
        progress = PlayerDailyQuestProgress.objects.get(
            player=self.player, quest=self.quest
        )
        self.assertFalse(first.completed_now)
        self.assertTrue(second.completed_now)
        self.assertTrue(progress.completed)
        self.assertEqual(progress.progress, 2)
        self.assertEqual((self.player.level, self.player.xp), (2, 5))
        self.assertEqual(self.player.chips, 275)
        self.assertEqual(ChipTransaction.objects.count(), 2)

    def test_completed_quest_cannot_pay_twice(self):
        advance_daily_quest(self.player.id, self.quest.id, amount=2)
        replay = advance_daily_quest(self.player.id, self.quest.id, amount=2)
        self.player.refresh_from_db()
        self.assertFalse(replay.completed_now)
        self.assertEqual(self.player.chips, 275)
        self.assertEqual(ChipTransaction.objects.count(), 2)


class EconomyAnalyticsTests(TestCase):
    def test_dashboard_reports_median_flows_extremes_items_and_dealer_rate(self):
        first = Player.objects.create(id=9801, name="Low", chips=100)
        second = Player.objects.create(id=9802, name="High", chips=300)
        Dealer.objects.create(wins=3, loses=1)
        adjust_balance(
            first, -50, category=ChipTransaction.Category.BET,
            reference_type="test_game"
        )
        adjust_balance(
            second, 200, category=ChipTransaction.Category.MINIGAME_PAYOUT,
            reference_type="test_game"
        )
        PlayerItem.objects.create(player=first, item_type="insurance_pass", quantity=2)

        report = build_economy_analytics()

        self.assertEqual(report.median_balance, 275)
        self.assertEqual(report.dealer_win_rate, 75)
        self.assertEqual(report.largest_wins[0]["amount"], 200)
        self.assertEqual(report.largest_losses[0]["amount"], -50)
        self.assertEqual(report.game_flows[0]["net_player_change"], 150)
        self.assertEqual(report.game_flows[0]["casino_profit"], -150)
        self.assertEqual(report.game_flows[0]["actual_payout_rate"], 400)
        self.assertEqual(report.item_inventory[0]["quantity"], 2)


class EconomyPolicyTests(TestCase):
    def test_standard_games_have_small_house_edge(self):
        self.assertEqual(standard_win_payout(1_000), 1_900)
        coin_return = 0.5 * standard_win_payout(10_000) / 10_000
        rps_return = (
            (1 / 3) * standard_win_payout(10_000) / 10_000 + (1 / 3)
        )
        draw_return = (
            (6 / 13) * standard_win_payout(10_000) / 10_000 + (1 / 13)
        )
        slot_return = (1 / 36) * 10 + (10 / 36) * 2
        self.assertAlmostEqual(coin_return, 0.95)
        self.assertLess(rps_return, 1)
        self.assertLess(draw_return, 1)
        self.assertLess(slot_return, 1)

    def test_referral_share_no_longer_overwhelms_house_edge(self):
        self.assertEqual(referral_share(100_000), 1_000)
        self.assertEqual(referral_share(99), 0)

    def test_race_payout_never_exceeds_stakes(self):
        self.assertEqual(horse_race_payout_pool(100_000), 95_000)
        self.assertLessEqual(horse_race_payout_pool(100_000), 100_000)

    def test_potion_bonus_is_capped(self):
        self.assertEqual(apply_potion_multiplier(10_000, 2), 20_000)
        self.assertEqual(apply_potion_multiplier(1_000_000, 10), 1_800_000)
