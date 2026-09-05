from django.test import TestCase

from game.models import Group, Player, UserSettings
from game.services.language import language_for_context, set_group_language_sync


class GroupLanguageTests(TestCase):
    def setUp(self):
        self.player = Player.objects.create(id=84001, name="Bilingual", chips=100)
        UserSettings.objects.create(player=self.player, language="fa")

    def test_private_chat_uses_player_language(self):
        self.assertEqual(
            language_for_context(
                chat_id=self.player.id, chat_type="private", player_id=self.player.id
            ),
            "fa",
        )

    def test_each_group_has_independent_language(self):
        Group.objects.create(group_chat_id="-1001", group_name="Persian", language="fa")
        Group.objects.create(group_chat_id="-1002", group_name="English", language="en")
        self.assertEqual(
            language_for_context(chat_id=-1001, chat_type="supergroup", player_id=self.player.id),
            "fa",
        )
        self.assertEqual(
            language_for_context(chat_id=-1002, chat_type="supergroup", player_id=self.player.id),
            "en",
        )

    def test_unknown_group_defaults_to_english(self):
        self.assertEqual(
            language_for_context(chat_id=-9999, chat_type="group", player_id=self.player.id),
            "en",
        )

    def test_group_language_update_does_not_change_private_preference(self):
        settings = UserSettings.objects.get(player=self.player)
        settings.language = "en"
        settings.save(update_fields=("language",))
        set_group_language_sync(-1003, "New Group", "fa")
        settings = UserSettings.objects.get(player=self.player)
        self.assertEqual(settings.language, "en")
        group = Group.objects.get(group_chat_id="-1003")
        self.assertEqual(group.language, "fa")
