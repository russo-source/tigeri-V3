#!/usr/bin/env bash
# Run ON THE EC2 instance once, as root. Installs system deps, sets up
# Postgres in Docker, creates the tigeri user, venv, /etc/tigeri/tigeri.env,
# the systemd unit, and starts the service.
#
# Idempotent — safe to re-run.
#
# Expects this repo to already be staged at /tmp/tigeri-staged/ (deploy.sh
# does this).

set -euo pipefail

STAGE="/tmp/tigeri-staged"
APP_DIR="/opt/tigeri"
ENV_DIR="/etc/tigeri"
ENV_FILE="${ENV_DIR}/tigeri.env"

if [[ ! -d "$STAGE" ]]; then
  echo "ERROR: $STAGE missing — run deploy.sh from your laptop first" >&2
  exit 1
fi

echo "→ system packages (python3.12, docker, git, rsync)"
dnf -y install python3.12 python3.12-pip docker git rsync >/dev/null

echo "→ enable + start docker"
systemctl enable --now docker >/dev/null

echo "→ ensure tigeri user"
id -u tigeri >/dev/null 2>&1 || useradd -m -s /bin/bash tigeri
# usermod accepts only one user per invocation. The previous form
# "usermod -aG docker tigeri ec2-user" was a no-op masked by "|| true";
# audit-flagged. Issue two calls so both users actually get the group.
usermod -aG docker tigeri || true
usermod -aG docker ec2-user || true

echo "→ /opt/tigeri layout"
mkdir -p "$APP_DIR" "$ENV_DIR"
rsync -az --delete \
    --exclude '.git' --exclude 'node_modules' --exclude '__pycache__' \
    --exclude '.venv' --exclude '.next' --exclude 'frontend/node_modules' \
    "$STAGE/" "$APP_DIR/"
chown -R tigeri:tigeri "$APP_DIR"

echo "→ python venv + deps"
if [[ ! -d "$APP_DIR/.venv" ]]; then
  sudo -u tigeri python3.12 -m venv "$APP_DIR/.venv"
fi
sudo -u tigeri "$APP_DIR/.venv/bin/pip" install --upgrade pip wheel >/dev/null
sudo -u tigeri "$APP_DIR/.venv/bin/pip" install -e "$APP_DIR" >/dev/null

echo "→ env file (preserves existing values)"
if [[ ! -f "$ENV_FILE" ]]; then
  cat > "$ENV_FILE" <<'ENVEOF'
TIGERI_DATABASE_URL=postgresql+asyncpg://tigeri:tigeri_local@localhost:5432/tigeri
TIGERI_LOG_LEVEL=INFO
TIGERI_ENV=aws
TIGERI_A2A_HMAC_SECRET=CHANGE_ME_32_BYTES_HEX
ANTHROPIC_API_KEY=CHANGE_ME
TIGERI_LLM_AGENT_MODEL=claude-sonnet-4-6
TIGERI_LLM_REASONING_MODEL=claude-opus-4-7
AWS_REGION=us-east-1
TIGERI_S3_DOCUMENTS_BUCKET=trigeri--global--use1-az4--x-s3
LANGSMITH_API_KEY=
LANGSMITH_PROJECT=tigeri
LANGSMITH_TRACING=false
TIGERI_SESSION_CHECKPOINTER=memory
ENVEOF
  chmod 600 "$ENV_FILE"
  chown tigeri:tigeri "$ENV_FILE"
  echo "  (created — fill in ANTHROPIC_API_KEY, TIGERI_A2A_HMAC_SECRET)"
fi

echo "→ Postgres in docker (postgres:16-alpine on host:5432)"
if ! docker ps --format '{{.Names}}' | grep -q '^tigeri-postgres$'; then
  docker rm -f tigeri-postgres >/dev/null 2>&1 || true
  docker run -d --name tigeri-postgres --restart unless-stopped \
      -p 127.0.0.1:5432:5432 \
      -e POSTGRES_USER=tigeri \
      -e POSTGRES_PASSWORD=tigeri_local \
      -e POSTGRES_DB=tigeri \
      -v tigeri_pgdata:/var/lib/postgresql/data \
      postgres:16-alpine >/dev/null
  echo "  (waiting 10s for Postgres to accept connections)"
  sleep 10
fi

# Audit-flagged: previously seeded "CHANGE_ME" placeholders and continued the
# bootstrap silently. A box isn't "production ready" if the HMAC / Anthropic
# creds are placeholder strings, so fail fast.
echo "→ verify env file has real secrets"
if grep -qE '^(TIGERI_A2A_HMAC_SECRET|ANTHROPIC_API_KEY)=CHANGE_ME' "$ENV_FILE"; then
  echo "ERROR: $ENV_FILE still contains CHANGE_ME placeholders." >&2
  echo "       Set TIGERI_A2A_HMAC_SECRET (32 random hex bytes) and" >&2
  echo "       ANTHROPIC_API_KEY before re-running bootstrap." >&2
  exit 2
fi

echo "→ alembic migrations"
sudo -u tigeri bash -c "cd $APP_DIR && set -a && source $ENV_FILE && set +a && $APP_DIR/.venv/bin/alembic upgrade head"

echo "→ systemd unit"
cp "$APP_DIR/infra/aws/deploy/tigeri-api.service" /etc/systemd/system/tigeri-api.service
systemctl daemon-reload
systemctl enable tigeri-api >/dev/null
systemctl restart tigeri-api

sleep 3
echo "→ status:"
systemctl is-active tigeri-api && echo "  service: active"

echo "→ smoke test:"
curl -sS --max-time 5 http://127.0.0.1:8000/healthz && echo

echo "✓ bootstrap complete"
