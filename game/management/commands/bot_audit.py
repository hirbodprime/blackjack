"""Production preflight checks without exposing any secret values."""

from pathlib import Path

from django.conf import settings
from django.core.management import BaseCommand, CommandError
from django.core.management import call_command


class Command(BaseCommand):
    help = "Run production safety checks for Django and the Telegram bot."

    def handle(self, *args, **options):
        failures = []
        if settings.DEBUG:
            failures.append("DEBUG must be False")
        if settings.APP_ENV != "production":
            failures.append("APP_ENV must be production")
        if not settings.TELEGRAM_BOT_TOKEN:
            failures.append("TELEGRAM_BOT_TOKEN is missing")
        database_name = str(settings.DATABASES["default"]["NAME"])
        if Path(database_name).name == "db.test.sqlite3":
            failures.append("production cannot use db.test.sqlite3")
        if not settings.SESSION_COOKIE_SECURE or not settings.CSRF_COOKIE_SECURE:
            failures.append("secure session and CSRF cookies must be enabled")
        if not settings.ALLOWED_HOSTS:
            failures.append("DJANGO_ALLOWED_HOSTS must not be empty")

        call_command("check", "--deploy", verbosity=0)
        call_command("migrate", "--check", verbosity=0)
        if failures:
            raise CommandError("Production audit failed: " + "; ".join(failures))
        self.stdout.write(self.style.SUCCESS("Production audit passed."))
