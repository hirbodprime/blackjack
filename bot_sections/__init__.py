"""Telegram bot handlers.

Importing any submodule configures Django first, because the handlers import
models at module level.
"""

import os

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "blackjack.settings")
django.setup()
