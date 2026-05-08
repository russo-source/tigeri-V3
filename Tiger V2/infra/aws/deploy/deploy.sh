#!/usr/bin/env bash
# Sync source to EC2, install deps, run migrations, restart service.
# Usage:
#   EC2_HOST=ec2-user@1.2.3.4 SSH_KEY=~/.ssh/tigeri.pem ./deploy.sh
#
# First-time on a fresh box, also run setup_remote.sh first (uploaded by this
# script if missing).

set -euo pipefail

: "${EC2_HOST:?must be set, e.g. ec2-user@1.2.3.4}"
: "${SSH_KEY:?must be set, e.g. ~/.ssh/tigeri.pem}"

REPO_ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
SSH="ssh -i ${SSH_KEY} -o StrictHostKeyChecking=accept-new ${EC2_HOST}"
RSYNC="rsync -az --delete -e 'ssh -i ${SSH_KEY}'"

echo "→ syncing source to /opt/tigeri"
# .env / .env.local are dev-only convenience files. The production secrets
# live in /etc/tigeri/tigeri.env (systemd EnvironmentFile) and must NOT be
# overwritten by whatever the developer happens to have in their local .env.
# frontend/ is a separate static-export deploy; deliberately excluded here.
eval "$RSYNC --exclude '.git' --exclude 'node_modules' --exclude '__pycache__' \
    --exclude '.venv' --exclude '.next' --exclude 'frontend/node_modules' \
    --exclude '.env' --exclude '.env.local' --exclude '.pytest_cache' \
    --exclude '.mypy_cache' --exclude '*.egg-info' --exclude '.ruff_cache' \
    --exclude 'frontend.minimal.bak' \
    ${REPO_ROOT}/ ${EC2_HOST}:/tmp/tigeri-staged/"

# Stage → /opt/tigeri promotion. ``--delete`` would also wipe the venv (and
# any other long-lived state under /opt/tigeri) because they're excluded from
# the source-side rsync above. We exclude them on the destination side too so
# they survive the sync. .next/ is the Next.js build cache for the embedded
# frontend export — also kept untouched.
$SSH "sudo rsync -az --delete \
    --exclude '.venv' --exclude '.next' --exclude 'frontend/node_modules' \
    /tmp/tigeri-staged/ /opt/tigeri/ && sudo chown -R tigeri:tigeri /opt/tigeri"

echo "→ installing python deps"
$SSH "cd /opt/tigeri && sudo -u tigeri /opt/tigeri/.venv/bin/pip install -e . >/dev/null"

echo "→ running migrations"
# We deliberately don't ``source /etc/tigeri/tigeri.env`` because that file is
# a systemd EnvironmentFile (KEY=VALUE pairs, no shell escaping) and any value
# containing characters bash treats as syntax (``;``, ``(``, backticks, ``&&``,
# etc.) crashes the source. Alembic only needs TIGERI_DATABASE_URL, so extract
# just that line and pass it explicitly via ``env``.
$SSH "DBURL=\$(sudo grep '^TIGERI_DATABASE_URL=' /etc/tigeri/tigeri.env | cut -d= -f2-) && [ -n \"\$DBURL\" ] && cd /opt/tigeri && sudo -u tigeri env TIGERI_DATABASE_URL=\"\$DBURL\" /opt/tigeri/.venv/bin/alembic upgrade head"

echo "→ restarting service"
$SSH "sudo systemctl restart tigeri-api"
$SSH "sudo systemctl status tigeri-api --no-pager | head -20"

echo "→ syncing nginx config"
# Ship the canonical nginx config from the repo so security headers + the
# proxy block don't drift. ``nginx -t`` validates before reload; on failure
# the running config keeps serving traffic.
$SSH "sudo cp /tmp/tigeri-staged/infra/aws/deploy/nginx-tigeri-https.conf /etc/nginx/conf.d/tigeri.conf && sudo nginx -t && sudo systemctl reload nginx"
