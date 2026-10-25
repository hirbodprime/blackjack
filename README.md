# Blackjack Telegram Bot

A Telegram casino bot backed by Django. It includes multiplayer blackjack,
horse racing, minigames, player progression, quests, inventory, referrals, and
an administrative control panel.

## Project layout

- `blackjack.py` starts the Telegram bot (`bot_sections.application.main`).
- `bot_sections/` contains the Telegram command and callback handlers.
- `game/models.py` contains the persistent game state.
- `game/services/` contains independently testable game rules.
- `blackjack/` contains Django configuration and deployment entry points.
- `tests/` contains fast tests that do not connect to Telegram.

## Local setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env
```

Set real values in `.env`, then initialize and validate Django:

```bash
.venv/bin/python manage.py migrate
.venv/bin/python manage.py check
.venv/bin/python manage.py test game tests
```

Run the Telegram bot with:

```bash
.venv/bin/python blackjack.py
```

The process runs until stopped. It performs interrupted-game recovery during
startup and closes through the Telegram application's graceful shutdown hook.

Run Django separately with its WSGI/ASGI server or, for local development:

```bash
.venv/bin/python manage.py runserver
```

## Safe development workflow

1. Add or update tests for the rule being changed.
2. Run the unit suite and `manage.py check`.
3. Run `manage.py makemigrations --check --dry-run` to catch model drift.
4. Test with `DEBUG=True` and the dedicated test bot token.
5. Deploy only after testing Telegram interactions in a private test group.

`APP_ENV=test` uses `db.test.sqlite3` by default, while production continues to
use the existing `db.sqlite3`. Set `DJANGO_DB_PATH` explicitly in deployment.
This prevents the test bot from touching production players or balances. Django's
automated test runner continues to create an isolated temporary database.
Set `EXPECTED_PAYOUT_RATES` to a JSON object of intended return percentages for
each ledger game type; the economy dashboard compares those targets with actual
results. Defaults cover slots, coin, draw, RPS, double, dice, roulette, and races.

## Test-bot acceptance checklist

Use `DEBUG=True`, `APP_ENV=test`, and the dedicated test token, then migrate and
start both processes:

```bash
.venv/bin/python manage.py migrate
.venv/bin/python manage.py check
.venv/bin/python blackjack.py
```

In a private test group, verify `/start`, `/play`, `/language fa`, one blackjack
round, one race, one minigame, `/history`, daily rewards, an item purchase, and a
loan/repayment. Restart during an active game once and confirm the bet is refunded.
Use Django admin to pause betting, enable maintenance, freeze a test player, and
emergency-cancel a game. Confirm each action appears in the ledger or incident log.

Blackjack turns have a 30-second action timer. A timeout automatically stands the
player for that round; two consecutive timeouts remove that seat from the game.
Any valid `/hit` or `/stand` resets the streak and starts a fresh timer.

Economy policy is centralized in `game/economy_config.py`. Standard minigames now
have a small documented house edge, referrals pay 1%, horse-race payouts stay
within the collected pool, and blackjack potion bonuses are capped. Mystery boxes
use reduced chip ranges and rare-item odds with a 30-second reopening cooldown.

Before production, run this with the production environment loaded:

```bash
.venv/bin/python manage.py bot_audit
.venv/bin/python manage.py test game tests
.venv/bin/python manage.py makemigrations --check --dry-run
```

## Security migration

The deployed Telegram tokens have existed in source history. Create replacement
tokens with BotFather, set the new values through environment variables, replace
the Django secret key, and then remove the temporary legacy fallbacks from
`blackjack/settings.py`. Never commit `.env`, session files, databases, logs, or
repository archives.
