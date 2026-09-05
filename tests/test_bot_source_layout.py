import ast
from pathlib import Path
from unittest import TestCase


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SECTION_DIRECTORY = PROJECT_ROOT / "bot_sections"
SECTION_FILES = (
    "core_and_menus.py",
    "items_and_callbacks.py",
    "players_and_progression.py",
    "blackjack_game.py",
    "minigames_and_economy.py",
    "horse_racing_and_social.py",
    "poll_recovery.py",
    "application.py",
)


class BotSourceLayoutTests(TestCase):
    def test_every_section_is_valid_python(self):
        for filename in SECTION_FILES:
            path = SECTION_DIRECTORY / filename
            ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

    def test_sections_are_valid_in_runtime_order(self):
        combined_source = "".join(
            (SECTION_DIRECTORY / filename).read_text(encoding="utf-8")
            for filename in SECTION_FILES
        )
        tree = ast.parse(combined_source, filename="blackjack.py")

        top_level_names = {
            node.name
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        }

        self.assertIn("start_blackjack", top_level_names)
        self.assertIn("start_round", top_level_names)
        self.assertIn("end_game", top_level_names)
        self.assertIn("horserace", top_level_names)
        self.assertIn("handle_stale_polls_and_reschedule", top_level_names)

    def test_polling_remains_the_final_runtime_action(self):
        application = (SECTION_DIRECTORY / "application.py").read_text(encoding="utf-8")
        meaningful_lines = [
            line.strip()
            for line in application.splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
        self.assertEqual(meaningful_lines[-1], "app.run_polling()")

    def test_application_creates_an_event_loop_explicitly(self):
        application = (SECTION_DIRECTORY / "application.py").read_text(encoding="utf-8")
        self.assertIn("asyncio.new_event_loop()", application)
        self.assertIn("asyncio.set_event_loop(event_loop)", application)

    def test_recovery_runs_as_application_startup_hook(self):
        application = (SECTION_DIRECTORY / "application.py").read_text(encoding="utf-8")
        self.assertIn(".post_init(handle_stale_polls_and_reschedule)", application)
