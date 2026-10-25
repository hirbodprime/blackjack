import ast
from pathlib import Path
from unittest import mock

from django.test import SimpleTestCase
from telegram.error import BadRequest

from bot_sections import horse_racing_and_social as horses
from bot_sections import items_and_callbacks as callbacks
from bot_sections.routing import CallbackRouter


class CallbackRouterTests(SimpleTestCase):
    def test_first_registered_match_wins(self):
        router = CallbackRouter()

        @router.on_prefix("menu:")
        async def prefix(*args):
            pass

        @router.on("menu:main")
        async def exact(*args):
            pass

        self.assertIs(router.resolve("menu:main"), prefix)

    def test_exact_and_prefix_matching(self):
        router = CallbackRouter()

        @router.on("a", "b")
        async def exact(*args):
            pass

        @router.on_prefix("x:", "y:")
        async def prefix(*args):
            pass

        self.assertIs(router.resolve("b"), exact)
        self.assertIs(router.resolve("y:42"), prefix)
        self.assertIsNone(router.resolve("ab"))
        self.assertIsNone(router.resolve("x"))


class BotRouteTableTests(SimpleTestCase):
    def assertRoute(self, router, data, name):
        handler = router.resolve(data)
        self.assertIsNotNone(handler, data)
        self.assertEqual(handler.__name__, name)

    def test_horse_routes(self):
        self.assertRoute(horses.HORSE_MENU_ROUTES, "menu:buy_horse", "_horse_buy_horse")
        self.assertRoute(horses.HORSE_MENU_ROUTES, "menu:buy_sale:12", "_horse_buy_sale")
        self.assertRoute(horses.HORSE_MENU_ROUTES, "menu:gift_owned", "_horse_gift_owned")
        self.assertRoute(horses.HORSE_MENU_ROUTES, "menu:buy_and_gift", "_horse_buy_and_gift")

    def test_menu_shop_and_item_routes(self):
        self.assertRoute(callbacks.MENU_ROUTES, "menu:profile", "_menu_profile")
        self.assertRoute(callbacks.MENU_ROUTES, "toggle:notify_quests", "_menu_toggle")
        self.assertRoute(callbacks.SHOP_ROUTES, "menu:shop", "_shop_shop")
        self.assertRoute(callbacks.SHOP_ROUTES, "shop:xp_booster_2000", "_shop_xp_booster_500")
        self.assertRoute(callbacks.ITEMS_ROUTES, "items:activate:7", "_items_activate_item")

    def test_route_tables_do_not_overlap(self):
        samples = [
            "menu:main", "menu:shop", "menu:profile", "menu:quests", "menu:settings",
            "menu:mainhorse", "menu:buy_horse", "menu:gift_owned", "menu:buy_sale:1",
            "shop:bj_potions", "items:activate", "quest:1", "toggle:x",
        ]
        tables = [
            callbacks.MENU_ROUTES, callbacks.SHOP_ROUTES,
            callbacks.ITEMS_ROUTES, horses.HORSE_MENU_ROUTES,
        ]
        for data in samples:
            matches = [table for table in tables if table.resolve(data)]
            self.assertLessEqual(len(matches), 1, data)


class MenuCallbackDispatchTests(SimpleTestCase):
    def make_update(self, data):
        update = mock.Mock()
        update.callback_query.data = data
        update.callback_query.answer = mock.AsyncMock()
        return update

    async def dispatch(self, data, **patches):
        update = self.make_update(data)
        defaults = {
            "handle_items_callback": mock.AsyncMock(),
            "handle_shop_callback": mock.AsyncMock(return_value=False),
            "dispatch_horse_menu": mock.AsyncMock(),
        }
        defaults.update(patches)
        with mock.patch.multiple(callbacks, **defaults):
            await callbacks.handle_menu_callback(update, mock.Mock())
        return update, defaults

    async def test_items_callbacks_go_to_items_handler(self):
        update, mocks = await self.dispatch("items:activate")
        mocks["handle_items_callback"].assert_awaited_once()
        mocks["handle_shop_callback"].assert_not_awaited()
        update.callback_query.answer.assert_awaited_once_with()

    async def test_unlisted_horse_callbacks_reach_the_horse_menu(self):
        update, mocks = await self.dispatch("menu:gift_owned")
        mocks["dispatch_horse_menu"].assert_awaited_once()
        update.callback_query.answer.assert_awaited_once_with()

    async def test_handled_shop_callback_stops_dispatch(self):
        _, mocks = await self.dispatch(
            "shop:bj_potions",
            handle_shop_callback=mock.AsyncMock(return_value=True),
        )
        mocks["dispatch_horse_menu"].assert_not_awaited()

    async def test_already_answered_query_is_ignored(self):
        update = self.make_update("menu:gift_owned")
        update.callback_query.answer.side_effect = BadRequest("Query is too old")
        with mock.patch.multiple(
            callbacks,
            handle_shop_callback=mock.AsyncMock(return_value=False),
            dispatch_horse_menu=mock.AsyncMock(),
        ):
            await callbacks.handle_menu_callback(update, mock.Mock())

    async def test_query_is_answered_even_when_handler_fails(self):
        update = self.make_update("menu:gift_owned")
        with mock.patch.multiple(
            callbacks,
            handle_shop_callback=mock.AsyncMock(return_value=False),
            dispatch_horse_menu=mock.AsyncMock(side_effect=RuntimeError),
        ):
            with self.assertRaises(RuntimeError):
                await callbacks.handle_menu_callback(update, mock.Mock())
        update.callback_query.answer.assert_awaited_once_with()


class StaticButtonCoverageTests(SimpleTestCase):
    """Every literal callback_data in the bot must reach a handler."""

    HANDLER_PREFIXES = ("play:", "onboarding:", "poker:", "retention:")

    def callback_literals(self):
        source_dir = Path(callbacks.__file__).resolve().parent
        for path in sorted(source_dir.glob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.keyword) and node.arg == "callback_data":
                    value = node.value
                    if isinstance(value, ast.Constant):
                        yield path.name, value.lineno, value.value
                    elif isinstance(value, ast.JoinedStr) and isinstance(value.values[0], ast.Constant):
                        # f"menu:buy_sale:{id}" -> check the static prefix
                        yield path.name, value.lineno, value.values[0].value + "0"

    def is_routed(self, data):
        if data.startswith(self.HANDLER_PREFIXES) or data in callbacks.MYSTERY_BOXES:
            return True
        tables = (
            callbacks.ITEMS_ROUTES, callbacks.SHOP_ROUTES,
            callbacks.MENU_ROUTES, horses.HORSE_MENU_ROUTES,
        )
        return any(table.resolve(data) for table in tables)

    def test_every_button_is_routed(self):
        unrouted = [
            f"{name}:{line} {data}"
            for name, line, data in self.callback_literals()
            if not self.is_routed(data)
        ]
        self.assertEqual(unrouted, [])
