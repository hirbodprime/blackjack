import asyncio
import runpy
from pathlib import Path
from unittest import mock

from django.test import SimpleTestCase, override_settings
from telegram.ext import CallbackQueryHandler, CommandHandler


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TEST_TOKEN ="123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijk"


@override_settings(TELEGRAM_BOT_TOKEN=TEST_TOKEN)
class BotApplicationTests(SimpleTestCase):
    def build(self):
        from bot_sections.application import build_application

        return build_application()

    def test_entry_point_imports_without_executing_the_bot(self):
        # ``blackjack/`` (Django settings) shadows ``blackjack.py`` on import,
        # so load the script by path the way systemd runs it.
        namespace = runpy.run_path(str(PROJECT_ROOT / "blackjack.py"), run_name="not_main")

        self.assertTrue(callable(namespace["main"]))

    def test_guards_run_before_regular_handlers(self):
        app = self.build()
        self.assertEqual(sorted(app.handlers), [-100, 0])
        self.assertEqual(len(app.handlers[-100]), 2)

    def test_core_commands_are_registered(self):
        app = self.build()
        commands = set()
        for handler in app.handlers[0]:
            if isinstance(handler, CommandHandler):
                commands |= set(handler.commands)
        for command in (
            "start", "play", "startblackjack", "join", "hit", "stand",
            "horserace", "joinrace", "startrace", "poker", "roulette", "help",
        ):
            self.assertIn(command, commands)

    def test_catch_all_callback_handler_is_registered_last(self):
        # The unfiltered menu handler claims every remaining callback and
        # dispatches internally, so any handler after it would never run.
        app = self.build()
        callbacks = [
            handler for handler in app.handlers[0]
            if isinstance(handler, CallbackQueryHandler)
        ]
        self.assertEqual(callbacks[-1].callback.__name__, "handle_menu_callback")
        self.assertIsNone(callbacks[-1].pattern)

    def test_recovery_runs_as_application_startup_hook(self):
        from bot_sections.poll_recovery import handle_stale_polls_and_reschedule

        app = self.build()
        self.assertIs(app.post_init, handle_stale_polls_and_reschedule)

    @override_settings(TELEGRAM_BOT_TOKEN="")
    def test_missing_token_fails_fast(self):
        with self.assertRaises(RuntimeError):
            self.build()

    def test_main_registers_an_event_loop_before_polling(self):
        from bot_sections import application

        with mock.patch.object(application, "build_application") as build:
            build.return_value.run_polling.side_effect = (
                lambda: self.assertIsInstance(asyncio.get_event_loop(), asyncio.AbstractEventLoop)
            )
            application.main()
        build.return_value.run_polling.assert_called_once()

    def test_photo_handler_ignores_edits_and_groups(self):
        from telegram import Chat, Message, PhotoSize, Update, User
        from datetime import datetime, timezone

        from bot_sections.blackjack_game import photo_handler

        user = User(1, "A", False)
        photo = (PhotoSize("f", "u", 1, 1),)
        when = datetime.now(timezone.utc)
        private = Message(1, when, Chat(1, Chat.PRIVATE), from_user=user, photo=photo)
        group = Message(2, when, Chat(-5, Chat.SUPERGROUP), from_user=user, photo=photo)

        self.assertTrue(photo_handler.check_update(Update(1, message=private)))
        self.assertFalse(photo_handler.check_update(Update(2, message=group)))
        self.assertFalse(photo_handler.check_update(Update(3, edited_message=private)))
