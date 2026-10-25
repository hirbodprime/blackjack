from datetime import datetime, timedelta, timezone as dt_timezone
from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from game.models import (
    ChipTransaction, CompetitionPayout, DailyQuest, HorseAppliedUpgrade, HorseUpgrade,
    OwnedHorse, Player, PlayerAchievement, PlayerDailyQuestProgress, Season,
    SeasonProgress, Tournament,
)
from game.services import competitions
from game.services.achievements import sync_catalog, unlock
from game.services.challenges import ensure_daily_challenges, record_daily_completion
from game.services.economy import adjust_balance
from game.services.horses import (
    InvalidStarterChoice, StarterAlreadyClaimed, StarterHorseLocked,
    claim_starter_horse, gift_owned_horse, starter_powerup_offers,
)
from game.services.progression import award_xp
from game.services.ranks import level_reward, rank_label, xp_for_level
from game.services.seasons import settle_season, start_season


def bet(player, amount, ref="blackjack_game", when=None):
    change = adjust_balance(
        player, -amount, category=ChipTransaction.Category.BET, reference_type=ref
    )
    if when:
        ChipTransaction.objects.filter(pk=change.transaction.pk).update(created_at=when)


def win(player, amount, ref="blackjack_game", when=None):
    change = adjust_balance(
        player, amount, category=ChipTransaction.Category.BLACKJACK_PAYOUT, reference_type=ref
    )
    if when:
        ChipTransaction.objects.filter(pk=change.transaction.pk).update(created_at=when)


class RankTests(TestCase):
    def test_curve_grows_and_milestones_pay_more(self):
        self.assertEqual(xp_for_level(1), 100)
        self.assertLess(xp_for_level(10), xp_for_level(11))
        self.assertGreater(level_reward(10), level_reward(11) - 100)

    def test_rank_labels(self):
        self.assertEqual(rank_label(1), "🥉 Bronze I")
        self.assertEqual(rank_label(10), "🥇 Gold I")
        self.assertEqual(rank_label(19), "🥇 Gold III")
        self.assertEqual(rank_label(80), "🌟 Legend")

    def test_reaching_silver_unlocks_rank_achievement(self):
        sync_catalog()
        player = Player.objects.create(id=60001, name="Climber", level=4, xp=0)
        award_xp(player, xp_for_level(4))
        self.assertEqual(player.level, 5)
        self.assertTrue(PlayerAchievement.objects.filter(
            player=player, achievement__condition="rank_silver"
        ).exists())


class AchievementTests(TestCase):
    def setUp(self):
        sync_catalog()
        self.player = Player.objects.create(id=60010, name="Hunter", chips=0)

    def test_unlock_pays_once(self):
        first = unlock(self.player, "first_race_win")
        second = unlock(self.player, "first_race_win")
        self.assertIsNotNone(first)
        self.assertIsNone(second)
        self.assertEqual(self.player.chips, first.reward_chips)

    def test_unknown_condition_is_ignored(self):
        self.assertIsNone(unlock(self.player, "no_such_thing"))


class SeasonTests(TestCase):
    def test_reset_sets_everyone_to_same_balance_and_forgives_loans(self):
        rich = Player.objects.create(id=60020, name="Rich", chips=500_000, loan=1_000)
        poor = Player.objects.create(id=60021, name="Poor", chips=3)
        start_season(1, "Test", 10_000, reset_balances=True)
        rich.refresh_from_db()
        poor.refresh_from_db()
        self.assertEqual((rich.chips, rich.loan), (10_000, 0))
        self.assertEqual(poor.chips, 10_000)
        self.assertEqual(
            ChipTransaction.objects.filter(category=ChipTransaction.Category.SEASON_RESET).count(), 2
        )

    def test_xp_feeds_points_and_settlement_pays_once(self):
        season = start_season(1, "Test", 1_000, reset_balances=False)
        top = Player.objects.create(id=60022, name="Top")
        award_xp(top, 50)
        self.assertEqual(SeasonProgress.objects.get(season=season, player=top).points, 50)
        first = settle_season(season.pk)
        second = settle_season(season.pk)
        self.assertEqual(len(first), 1)
        self.assertEqual(second, [])
        season.refresh_from_db()
        self.assertFalse(season.is_active)


class CompetitionTests(TestCase):
    def setUp(self):
        self.a = Player.objects.create(id=60030, name="A", chips=10_000)
        self.b = Player.objects.create(id=60031, name="B", chips=10_000)

    def test_leaderboard_ranks_net_winnings_by_game(self):
        bet(self.a, 100)
        win(self.a, 500)
        bet(self.b, 100, ref="horse_race")
        start = timezone.now() - timedelta(minutes=1)
        end = timezone.now() + timedelta(minutes=1)
        rows = competitions.leaderboard(start, end)
        self.assertEqual([(r.player_id, r.score) for r in rows], [(self.a.pk, 400)])
        self.assertEqual(competitions.leaderboard(start, end, Tournament.Kind.HORSES), [])

    def test_tournament_settles_once_with_split(self):
        now = timezone.now()
        tournament = Tournament.objects.create(
            title="T", kind=Tournament.Kind.BLACKJACK, prize_pool=1_000,
            starts_at=now - timedelta(hours=2), ends_at=now - timedelta(minutes=1),
        )
        bet(self.a, 100, when=now - timedelta(hours=1))
        win(self.a, 300, when=now - timedelta(hours=1))
        paid = competitions.settle_tournament(tournament.pk)
        self.assertEqual([(p.player_id, p.prize_chips) for p in paid], [(self.a.pk, 500)])
        self.assertEqual(competitions.settle_tournament(tournament.pk), [])

    def test_tick_needs_a_season_and_ignores_pre_season_week(self):
        self.assertEqual(competitions.tick().started, [])
        self.assertFalse(Tournament.objects.exists())
        monday = datetime(2026, 11, 2, tzinfo=dt_timezone.utc)
        last_week = monday - timedelta(days=3)
        win(self.a, 999, when=last_week)
        with mock.patch("django.utils.timezone.now", return_value=monday - timedelta(hours=1)):
            start_season(1, "S", 1_000, reset_balances=False)
        win(self.b, 50, when=monday - timedelta(minutes=30))
        report = competitions.tick(now=monday + timedelta(hours=1))
        self.assertEqual([p.player_id for p in report.weekly], [self.b.pk])
        self.assertTrue(Tournament.objects.exists())
        self.assertEqual(competitions.tick(now=monday + timedelta(hours=1)).weekly, [])


class ChallengeTests(TestCase):
    def test_three_unique_challenges_per_day_and_old_ones_retire(self):
        today = timezone.localdate()
        yesterday = ensure_daily_challenges(today - timedelta(days=1))
        todays = ensure_daily_challenges(today)
        self.assertEqual([q.difficulty for q in todays], ["easy", "medium", "hard"])
        self.assertEqual(ensure_daily_challenges(today), todays)
        self.assertFalse(DailyQuest.objects.filter(pk=yesterday[0].pk, available=True).exists())

    def test_streak_grows_on_consecutive_days(self):
        player = Player.objects.create(id=60040, name="Streaker")
        today = timezone.localdate()
        for day in (today - timedelta(days=1), today):
            for quest in ensure_daily_challenges(day):
                PlayerDailyQuestProgress.objects.create(
                    player=player, quest=quest, progress=quest.target, completed=True
                )
            result = record_daily_completion(player.pk, day)
        self.assertEqual(result.streak, 2)
        self.assertIsNone(record_daily_completion(player.pk, today))


class StarterHorseTests(TestCase):
    def setUp(self):
        sync_catalog()
        for i, name in enumerate(("Boost", "Freeze", "Dash", "Magnet")):
            HorseUpgrade.objects.create(name=name, description=name, cost=1_000 + i)
        self.player = Player.objects.create(id=60050, name="Rider")
        self.friend = Player.objects.create(id=60051, name="Friend", chips=10_000)

    def test_claim_once_with_offered_powerup(self):
        offer = starter_powerup_offers(self.player.pk)[0]
        horse = claim_starter_horse(self.player.pk, "  Lightning  Bolt ", offer.pk, 5)
        self.assertEqual(horse.name, "Lightning Bolt")
        self.assertEqual(horse.horse_number, 100)
        self.assertEqual(HorseAppliedUpgrade.objects.get(horse=horse).uses_remaining, 5)
        with self.assertRaises(StarterAlreadyClaimed):
            claim_starter_horse(self.player.pk, "Again", offer.pk, 5)

    def test_numbers_skip_owned_and_repeated_digits(self):
        OwnedHorse.objects.create(user=self.friend, horse_number=100)
        offer = starter_powerup_offers(self.player.pk)[0]
        self.assertEqual(claim_starter_horse(self.player.pk, "Nag", offer.pk, 5).horse_number, 101)

    def test_rejects_unoffered_powerup_and_bad_names(self):
        offered = {u.pk for u in starter_powerup_offers(self.player.pk)}
        other = HorseUpgrade.objects.exclude(pk__in=offered).first()
        with self.assertRaises(InvalidStarterChoice):
            claim_starter_horse(self.player.pk, "Nag", other.pk, 5)
        with self.assertRaises(InvalidStarterChoice):
            claim_starter_horse(self.player.pk, "x" * 21, next(iter(offered)), 5)

    def test_starter_cannot_be_gifted(self):
        offer = starter_powerup_offers(self.player.pk)[0]
        horse = claim_starter_horse(self.player.pk, "Mine", offer.pk, 5)
        with self.assertRaises(StarterHorseLocked):
            gift_owned_horse(self.player.pk, self.friend.pk, horse.horse_number, 0)


class SeasonLaunchCommandTests(TestCase):
    def test_dry_run_changes_nothing_and_confirm_resets(self):
        veteran = Player.objects.create(id=60060, name="Old", chips=77_777, games=3)
        out = StringIO()
        call_command("season_launch", stdout=out)
        self.assertIn("Dry run", out.getvalue())
        self.assertFalse(Season.objects.exists())

        with mock.patch(
            "game.management.commands.season_launch.Command._backup", return_value=None
        ):
            call_command("season_launch", "--confirm", "--starting-chips", "5000", stdout=out)
        veteran.refresh_from_db()
        self.assertEqual(veteran.chips, 5_000)
        self.assertTrue(Season.objects.get(number=1).is_active)
        conditions = set(PlayerAchievement.objects.filter(player=veteran).values_list(
            "achievement__condition", flat=True
        ))
        self.assertEqual(conditions, {"season0_veteran", "season0_founder"})
        self.assertEqual(DailyQuest.objects.filter(auto_generated=True).count(), 3)


class HubRenderTests(TestCase):
    def test_every_section_renders_in_both_languages(self):
        from game.telegram import hub

        sync_catalog()
        start_season(1, "The Comeback", 10_000, reset_balances=False)
        competitions.schedule_tournaments()
        player = Player.objects.create(id=60070, name="<b>Tag</b>", chips=10_000)
        win(player, 100)
        for lang in ("en", "fa"):
            text, keyboard = hub.render_home(hub.load_dashboard(player.pk), lang)
            self.assertIn("&lt;b&gt;Tag", text)
            self.assertEqual(keyboard.inline_keyboard[0][0].callback_data, "hub:claim")
            for render in (
                lambda: hub.render_play(lang, "bot"),
                lambda: hub.render_daily(player.pk, lang),
                lambda: hub.render_compete(lang),
                lambda: hub.render_season(player.pk, lang),
                lambda: hub.render_weekly(player.pk, lang),
                lambda: hub.render_tournament(player.pk, lang),
                lambda: hub.render_profile(player.pk, lang),
                lambda: hub.render_achievements(player.pk, lang, "blackjack"),
            ):
                text, keyboard = render()
                self.assertTrue(text)


class ShopTests(TestCase):
    def setUp(self):
        from game.services import shop

        self.shop = shop
        self.player = Player.objects.create(id=60080, name="Buyer", chips=200_000)

    def test_buy_charges_catalog_or_deal_price(self):
        key = "streak_freeze"
        self.shop.buy(self.player.pk, key)
        self.player.refresh_from_db()
        self.assertEqual(self.player.chips, 200_000 - self.shop.price_for(key))
        self.assertEqual(dict(self.shop.inventory(self.player.pk))[key], 1)

    def test_deal_of_the_day_is_discounted(self):
        deal = self.shop.deal_of_the_day()
        self.assertLess(self.shop.price_for(deal.key), deal.price)

    def test_titles_are_bought_once_and_equipped(self):
        self.shop.buy(self.player.pk, "title_shark")
        with self.assertRaises(self.shop.ShopError):
            self.shop.buy(self.player.pk, "title_shark")
        with self.assertRaises(self.shop.ShopError):
            self.shop.equip_title(self.player.pk, "title_ghost")
        self.assertEqual(self.shop.equip_title(self.player.pk, "title_shark"), "🦈 Card Shark")

    def test_lucky_charm_boosts_xp_and_stacks_duration(self):
        self.shop.buy(self.player.pk, "xp_charm")
        self.shop.buy(self.player.pk, "xp_charm")
        first = self.shop.activate_timed(self.player.pk, "xp_charm")
        expiry = self.shop.boost_expires_at(first)
        second = self.shop.activate_timed(self.player.pk, "xp_charm")
        self.assertEqual(self.shop.boost_expires_at(second) - expiry, timedelta(hours=24))
        result = award_xp(self.player, 40)
        self.assertEqual(result.xp, 50)

    def test_streak_freeze_bridges_one_missed_day(self):
        self.shop.buy(self.player.pk, "streak_freeze")
        today = timezone.localdate()
        for day in (today - timedelta(days=2), today):
            for quest in ensure_daily_challenges(day):
                PlayerDailyQuestProgress.objects.create(
                    player=self.player, quest=quest, progress=quest.target, completed=True
                )
            result = record_daily_completion(self.player.pk, day)
        self.assertEqual(result.streak, 2)
        self.assertNotIn("streak_freeze", dict(self.shop.inventory(self.player.pk)))

    def test_shop_screens_render(self):
        from game.telegram import shop as screens

        self.shop.buy(self.player.pk, "xp_charm")
        self.shop.buy(self.player.pk, "title_lucky")
        self.shop.buy(self.player.pk, "double_chip_potion")
        for text, _ in (
            screens.render_home(self.player),
            screens.render_category(self.player, "titles"),
            screens.render_bag(self.player),
        ):
            self.assertTrue(text)
