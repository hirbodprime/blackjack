from datetime import timedelta
from decimal import Decimal
from unittest import mock

from django.test import TestCase
from django.utils import timezone

from game.models import ArcadeRound, ChipTransaction, Player
from game.services import arcade


class ArcadeMathTests(TestCase):
    def test_crash_point_distribution_matches_rtp(self):
        with mock.patch.object(arcade._rng, "random", return_value=0.5):
            self.assertEqual(arcade.crash_point(), Decimal("1.92"))
        with mock.patch.object(arcade._rng, "random", return_value=0.0):
            self.assertEqual(arcade.crash_point(), Decimal("1.00"))

    def test_mines_multiplier_grows_with_risk(self):
        self.assertEqual(arcade.mines_multiplier(3, 0), Decimal("1.00"))
        one = arcade.mines_multiplier(3, 1)
        self.assertEqual(one, Decimal("1.10"))  # 25/22 * 0.97
        self.assertGreater(arcade.mines_multiplier(10, 1), one)

    def test_hilo_odds_count_ties_for_the_guesser(self):
        self.assertEqual(arcade.hilo_odds("A♠", "higher"), Decimal(13) / 13)
        self.assertEqual(arcade.hilo_odds("K♠", "lower"), Decimal(13) / 13)
        self.assertEqual(arcade.hilo_odds("7♠", "higher"), Decimal(7) / 13)


class ArcadeRoundTests(TestCase):
    def setUp(self):
        self.player = Player.objects.create(id=8801, name="Arcade", chips=10_000)

    def balance(self):
        self.player.refresh_from_db()
        return self.player.chips

    def test_crash_cashout_before_point_pays_and_after_loses(self):
        with mock.patch.object(arcade, "crash_point", return_value=Decimal("3.00")):
            round_ = arcade.crash_start(self.player.pk, 100)
        start = timezone.now()
        safe = start + timedelta(seconds=arcade.crash_seconds_to(Decimal("2.00")) + 0.05)
        settled = arcade.crash_cashout(self.player.pk, now=safe)
        self.assertEqual(settled.status, ArcadeRound.Status.WON)
        self.assertEqual(self.balance(), 10_000 - 100 + settled.payout)
        self.assertGreaterEqual(settled.payout, 200)

        with mock.patch.object(arcade, "crash_point", return_value=Decimal("1.50")):
            arcade.crash_start(self.player.pk, 100)
        late = timezone.now() + timedelta(seconds=30)
        self.assertEqual(arcade.crash_cashout(self.player.pk, now=late).status, ArcadeRound.Status.LOST)

    def test_live_state_hides_secrets(self):
        with mock.patch.object(arcade, "crash_point", return_value=Decimal("50.00")):
            arcade.crash_start(self.player.pk, 50)
        state = arcade.public_state(arcade.current_round(self.player.pk))
        self.assertNotIn("point", state)

    def test_mines_reveal_safe_then_cash_out_or_boom(self):
        with mock.patch.object(arcade._rng, "sample", return_value=[0, 1, 2]):
            arcade.mines_start(self.player.pk, 100, 3)
        with self.assertRaises(arcade.ArcadeError):
            arcade.mines_cashout(self.player.pk)
        arcade.mines_reveal(self.player.pk, 10)
        self.assertNotIn("mines", arcade.public_state(arcade.current_round(self.player.pk)))
        won = arcade.mines_cashout(self.player.pk)
        self.assertEqual(won.payout, 110)

        with mock.patch.object(arcade._rng, "sample", return_value=[0, 1, 2]):
            arcade.mines_start(self.player.pk, 100, 3)
        lost = arcade.mines_reveal(self.player.pk, 1)
        self.assertEqual(lost.status, ArcadeRound.Status.LOST)
        self.assertEqual(arcade.public_state(lost)["boom"], 1)

    def test_hilo_streak_and_one_round_at_a_time(self):
        with mock.patch.object(arcade, "_draw", side_effect=["5♠", "9♥", "2♣"]):
            arcade.hilo_start(self.player.pk, 100)
            with self.assertRaises(arcade.ArcadeError):
                arcade.mines_start(self.player.pk, 100, 3)
            first = arcade.hilo_guess(self.player.pk, "higher")
            self.assertEqual(first.status, ArcadeRound.Status.ACTIVE)
            lost = arcade.hilo_guess(self.player.pk, "higher")
        self.assertEqual(lost.status, ArcadeRound.Status.LOST)
        self.assertEqual(self.balance(), 9_900)

    def test_bet_limits_and_ledger(self):
        with self.assertRaises(arcade.ArcadeError):
            arcade.hilo_start(self.player.pk, 5)
        arcade.hilo_start(self.player.pk, 100)
        self.assertTrue(ChipTransaction.objects.filter(reference_type="arcade", amount=-100).exists())


class ArcadeApiTests(TestCase):
    def init_data(self, user_id, **extra):
        import hashlib, hmac, json, time
        from urllib.parse import urlencode
        from django.conf import settings

        values = {"auth_date": str(int(time.time())), "user": json.dumps({"id": user_id}), **extra}
        check = "\n".join(f"{k}={values[k]}" for k in sorted(values))
        secret = hmac.new(b"WebAppData", settings.TELEGRAM_BOT_TOKEN.encode(), hashlib.sha256).digest()
        values["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
        return urlencode(values)

    def test_auth_play_and_reject_forged_token(self):
        from django.test import override_settings

        Player.objects.create(id=8811, name="Web", chips=1_000)
        with override_settings(TELEGRAM_BOT_TOKEN="123:test"):
            auth = self.client.post("/casino/api/arcade/auth/", {"init_data": self.init_data(8811)}, content_type="application/json")
            self.assertEqual(auth.status_code, 200, auth.content)
            token = auth.json()["token"]
            headers = {"HTTP_AUTHORIZATION": f"Bearer {token}"}
            started = self.client.post("/casino/api/arcade/hilo_start/", {"bet": 100}, content_type="application/json", **headers)
            self.assertEqual(started.json()["player"]["chips"], 900)
            self.assertEqual(len(started.json()["round"]["cards"]), 1)
            bad = self.client.get("/casino/api/arcade/state/", HTTP_AUTHORIZATION="Bearer forged")
            self.assertEqual(bad.status_code, 403)
        from django.template.loader import get_template

        self.assertIn("BIG PAPA ARCADE", get_template("casino/arcade.html").template.source)

    def test_group_launch_tags_rounds_and_ranks_by_group(self):
        from django.test import override_settings

        Player.objects.create(id=8821, name="Grouper", chips=1_000)
        Player.objects.create(id=8822, name="Elsewhere", chips=1_000)
        ArcadeRound.objects.create(player_id=8822, game="crash", bet=100, payout=900, status="won", multiplier=9, chat_id=-200)
        param = arcade.group_start_param(-100)
        with override_settings(TELEGRAM_BOT_TOKEN="123:test"), \
                mock.patch("game.casino_views._is_chat_member", return_value=True):
            forged = self.client.post("/casino/api/arcade/auth/", {"init_data": self.init_data(8821, start_param="ag_-200_0000000000000000")}, content_type="application/json")
            self.assertEqual(forged.status_code, 403)
            auth = self.client.post("/casino/api/arcade/auth/", {"init_data": self.init_data(8821, start_param=param)}, content_type="application/json")
            self.assertEqual(auth.status_code, 200, auth.content)
            self.assertIsNotNone(auth.json()["group"])
            headers = {"HTTP_AUTHORIZATION": f"Bearer {auth.json()['token']}"}
            with mock.patch.object(arcade, "_draw", side_effect=["5♠", "9♥"]):
                self.client.post("/casino/api/arcade/hilo_start/", {"bet": 100}, content_type="application/json", **headers)
                self.client.post("/casino/api/arcade/hilo_guess/", {"guess": "higher"}, content_type="application/json", **headers)
                self.client.post("/casino/api/arcade/hilo_cashout/", {}, content_type="application/json", **headers)
            self.assertEqual(ArcadeRound.objects.get(player_id=8821).chat_id, -100)

            group = self.client.get("/casino/api/arcade/ranks/?scope=group&period=all", **headers).json()
            self.assertEqual([r["name"] for r in group["top"]], ["Grouper"])
            self.assertTrue(group["me"]["me"])
            world = self.client.get("/casino/api/arcade/ranks/?scope=global&period=all", **headers).json()
            self.assertEqual([r["name"] for r in world["top"]], ["Elsewhere", "Grouper"])
            self.assertEqual(world["top"][0]["score"], 800)
            self.assertEqual(world["top"][0]["best"], "9.00")
            crash = self.client.get("/casino/api/arcade/ranks/?scope=global&game=hilo&period=all", **headers).json()
            self.assertEqual([r["name"] for r in crash["top"]], ["Grouper"])
            bad = self.client.get("/casino/api/arcade/ranks/?game=nope", **headers)
            self.assertEqual(bad.status_code, 400)


class ArcadeRankTests(TestCase):
    def test_roulette_counts_only_completed_tables_and_merges_into_all(self):
        from game.models import RouletteTable, RouletteTableBet
        from game.services import arcade_ranks

        p = Player.objects.create(id=8831, name="Wheel", chips=0)
        done = RouletteTable.objects.create(chat_id=-1, created_by=p, status="complete", closes_at=timezone.now(), seed_hash="x", access_token="a")
        void = RouletteTable.objects.create(chat_id=-1, created_by=p, status="cancelled", closes_at=timezone.now(), seed_hash="x", access_token="b")
        RouletteTableBet.objects.create(table=done, player=p, kind="red", selection="red", amount=100, payout=200, won=True, idempotency_key="k1")
        RouletteTableBet.objects.create(table=void, player=p, kind="red", selection="red", amount=500, idempotency_key="k2")
        ArcadeRound.objects.create(player=p, game="mines", bet=50, status="lost", chat_id=-1)
        roulette = arcade_ranks.leaderboard("roulette", chat_id=-1, period="all")
        self.assertEqual(roulette["top"][0]["score"], 100)
        everything = arcade_ranks.leaderboard("all", chat_id=-1, period="week", player_id=p.pk)
        self.assertEqual((everything["top"][0]["score"], everything["top"][0]["rounds"]), (50, 2))
        self.assertEqual(arcade_ranks.leaderboard("all", chat_id=-999, period="all")["top"], [])

    def test_group_start_param_round_trip(self):
        param = arcade.group_start_param(-1001234567890)
        self.assertLessEqual(len(param), 64)
        self.assertRegex(param, r"^[A-Za-z0-9_-]+$")
        self.assertEqual(arcade.parse_group_start_param(param), -1001234567890)
        self.assertIsNone(arcade.parse_group_start_param("rt_1_abc"))
        with self.assertRaises(arcade.ArcadeError):
            arcade.parse_group_start_param("ag_-5_deadbeefdeadbeef")
