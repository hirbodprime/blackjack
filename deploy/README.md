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

`/opt/blackjackbot` is a git checkout of `main`. To release, push to GitHub and
then run on the server:

```bash
cd /opt/blackjackbot && sudo deploy/deploy.sh
```

The script stops both services, backs up the database, fast-forwards to
`origin/main`, installs changed requirements, runs migrations, `collectstatic`
and `bot_audit`, and starts the services again. Never edit code on the server.
Keep the database and environment file out of the application directory so
code deployments cannot overwrite them.

The database runs in SQLite WAL mode, so recent commits can live in
`db.sqlite3-wal`. Back it up with the SQLite backup API rather than copying
`db.sqlite3` alone, and run Django commands as `blackjackbot` so the `-wal` and
`-shm` files stay owned by the service user:

```bash
sudo -u blackjackbot python3 -c 'import sqlite3; sqlite3.connect("/var/lib/blackjackbot/db.sqlite3").backup(sqlite3.connect("/var/lib/blackjackbot/manual-backup.sqlite3"))'
```
