#!/usr/bin/env bash
# Run ON THE EC2 instance once, as root, to prepare it for tigeri-api.
# After this, your local deploy.sh handles all subsequent rolls.
#
#   sudo bash setup_remote.sh

set -euo pipefail

dnf -y install python3.12 python3.12-pip git rsync || \
  apt-get update && apt-get -y install python3.12 python3.12-venv git rsync

id -u tigeri >/dev/null 2>&1 || useradd -m -s /bin/bash tigeri
mkdir -p /opt/tigeri /etc/tigeri
chown -R tigeri:tigeri /opt/tigeri

if [[ ! -d /opt/tigeri/.venv ]]; then
  sudo -u tigeri python3.12 -m venv /opt/tigeri/.venv
fi

if [[ ! -f /etc/tigeri/tigeri.env ]]; then
  cat > /etc/tigeri/tigeri.env <<'ENVEOF'
TIGERI_DATABASE_URL=postgresql+asyncpg://tigeri:CHANGE_ME@localhost:5432/tigeri
TIGERI_LOG_LEVEL=INFO
TIGERI_ENV=aws
TIGERI_A2A_HMAC_SECRET=CHANGE_ME_32_BYTES
ANTHROPIC_API_KEY=CHANGE_ME
TIGERI_S3_DOCUMENTS_BUCKET=CHANGE_ME
AWS_REGION=ap-southeast-2
ENVEOF
  chmod 600 /etc/tigeri/tigeri.env
  chown tigeri:tigeri /etc/tigeri/tigeri.env
fi

cp /tmp/tigeri-staged/infra/aws/deploy/tigeri-api.service /etc/systemd/system/tigeri-api.service
systemctl daemon-reload
systemctl enable tigeri-api

# Daily Postgres backup. The script lives in /opt/tigeri/scripts/backup_postgres.sh
# and is rsync-shipped by deploy.sh. We register the crontab entry here once
# so the backup runs even if deploy.sh hasn't been touched.
mkdir -p /var/backups/tigeri
chown tigeri:tigeri /var/backups/tigeri
cat > /etc/cron.d/tigeri-backup <<'CRONEOF'
# Tigeri daily Postgres dump — runs at 02:15 UTC.
# Logs to journald; review with: journalctl -t tigeri-backup --since today
SHELL=/bin/bash
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
15 2 * * * root /opt/tigeri/scripts/backup_postgres.sh 2>&1 | logger -t tigeri-backup
CRONEOF
chmod 644 /etc/cron.d/tigeri-backup

echo "✓ remote prepared. Edit /etc/tigeri/tigeri.env then run deploy.sh from your laptop."
