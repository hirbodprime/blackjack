#!/usr/bin/env bash
# Deploy origin/main on the VPS. Run as root from /opt/blackjackbot:
#   sudo deploy/deploy.sh
#
# Stops both services, backs up the database, fast-forwards to origin/main,
# installs changed requirements, migrates, audits, and starts the services.
# Django commands run as the service user so SQLite's -wal/-shm files keep
# the right owner.
set -euo pipefail

APP=/opt/blackjackbot
STATE=/var/lib/blackjackbot
USER_NAME=blackjackbot
SERVICES=(blackjackbot.service blackjack-admin.service)

as_app() { runuser -u "$USER_NAME" -- "$@"; }
manage() { as_app "$APP/.venv/bin/python" "$APP/manage.py" "$@"; }

cd "$APP"
git fetch --quiet origin main
old_rev=$(git rev-parse HEAD)
new_rev=$(git rev-parse origin/main)
echo "Deploying ${old_rev:0:7} -> ${new_rev:0:7}"

systemctl stop "${SERVICES[@]}"
trap 'echo "Deploy failed; services are stopped. Database backup: $backup" >&2' ERR

# The backup API copies a consistent snapshot, including WAL contents.
backup="$STATE/db.sqlite3.pre-deploy-$(date -u +%Y%m%d%H%M%S)"
as_app python3 -c '
import sqlite3, sys
source, target = sqlite3.connect(sys.argv[1]), sqlite3.connect(sys.argv[2])
source.backup(target)
target.close()
' "$STATE/db.sqlite3" "$backup"
echo "Backed up database to $backup"

git merge --ff-only --quiet origin/main
chown -R "$USER_NAME:$USER_NAME" "$APP"

if ! git diff --quiet "$old_rev" "$new_rev" -- requirements.txt; then
    as_app "$APP/.venv/bin/pip" install --quiet --no-cache-dir -r requirements.txt
fi

manage migrate --noinput
manage collectstatic --noinput --verbosity 0
manage bot_audit

systemctl start "${SERVICES[@]}"
trap - ERR
sleep 5
systemctl is-active "${SERVICES[@]}"
