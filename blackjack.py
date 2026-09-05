"""Compatibility entry point for the Telegram blackjack bot.

The application is divided into domain-oriented source sections under
``bot_sections``. They intentionally execute in this module's shared global
namespace so handler ordering and cross-section global lookups remain identical
to the original single-file implementation.
"""

from pathlib import Path


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


def _load_sections() -> None:
    section_directory = Path(__file__).resolve().parent / "bot_sections"
    namespace = globals()

    for filename in SECTION_FILES:
        path = section_directory / filename
        source = path.read_text(encoding="utf-8")
        exec(compile(source, str(path), "exec"), namespace, namespace)


_load_sections()
