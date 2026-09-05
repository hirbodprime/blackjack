from unittest import TestCase

from game.telegram.update_guard import TelegramUpdateGuard


class TelegramUpdateGuardTests(TestCase):
    def test_repeated_command_is_throttled_per_user_and_command(self):
        guard = TelegramUpdateGuard(command_cooldown=2)

        self.assertTrue(guard.allow_command(1, "/slot", now=10))
        self.assertFalse(guard.allow_command(1, "/slot", now=11))
        self.assertTrue(guard.allow_command(1, "/slot", now=12))

    def test_different_commands_and_users_do_not_block_each_other(self):
        guard = TelegramUpdateGuard(command_cooldown=10)

        self.assertTrue(guard.allow_command(1, "/slot", now=10))
        self.assertTrue(guard.allow_command(1, "/coin", now=10))
        self.assertTrue(guard.allow_command(2, "/slot", now=10))

    def test_duplicate_callback_is_rejected_for_ttl(self):
        guard = TelegramUpdateGuard(callback_ttl=30)

        self.assertTrue(guard.allow_callback("callback-1", now=10))
        self.assertFalse(guard.allow_callback("callback-1", now=20))
        self.assertTrue(guard.allow_callback("callback-1", now=50))
