# VPS deployment

The Telegram poller runs as `blackjackbot.service` under a dedicated system
account. Application code lives in `/opt/blackjackbot`, production state lives
in `/var/lib/blackjackbot`, and secrets are loaded from
`/etc/blackjackbot.env`.

The service does not listen on a network port and does not require an Nginx
change. Logs are available with:

```bash
journalctl -u blackjackbot.service
```

The authenticated Telegram casino Mini App is exposed through
`casino.bigpapagames.com` using `nginx-casino.conf`. Only `/casino/` is routed
to Django; the administration site remains on its separate hostname.

Before each release, stop the service, back up the SQLite database, synchronize
the application, install dependencies, run migrations and `bot_audit`, then
start the service. Keep the database and environment file out of the application
directory so code deployments cannot overwrite them.
