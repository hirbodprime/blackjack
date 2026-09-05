"""Backward-compatible translation entry point.

New code should import :func:`game.i18n.translate` directly.
"""

from game.i18n import translate


def t(key, lang="en", **values):
    return translate(key, lang, **values)
