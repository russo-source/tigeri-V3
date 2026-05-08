#!/usr/bin/env bash
# Telegram bot install + smoke-test runbook.
#
# Run this AFTER the new TELEGRAM_BOT_* values in .env have been pushed to
# the deployed backend (EC2) and the tigeri-api service has been restarted.
# It does three things, in order:
#
#   1. getMe   — confirms Telegram accepts the bot token (no auth needed
#                from our side; the token is the auth).
#   2. setWebhook via the deployed Tigeri API — admin-gated, so you'll need
#                a signed-in admin cookie. Pass it via TIGERI_COOKIE.
#   3. getWebhookInfo — confirms Telegram is now pointing at our URL.
#
# After this script passes, send "/start <linkcode>" to @Tigerimario_bot
# from your phone (mint a code via /v1/integrations/telegram/link-code in
# the web app first) to bind your tenant to the bot.
#
# Usage:
#   TIGERI_API_BASE_URL=https://api.tigeri.ai/api \
#   TIGERI_FRONTEND_ORIGIN=https://app.tigeri.ai \
#   TIGERI_COOKIE='tigeri_session=xxx' \
#   bash scripts/telegram_setup.sh

set -euo pipefail

# Pull token + secret from .env so we don't have to retype them. The token
# is read locally; we never send it anywhere except api.telegram.org and
# (for setup) our own backend.
ENV_FILE="${ENV_FILE:-$(dirname "$0")/../.env}"
if [[ ! -f "$ENV_FILE" ]]; then
  echo "missing $ENV_FILE — set ENV_FILE=/path/to/.env" >&2
  exit 1
fi

# shellcheck disable=SC1090
set -a; source "$ENV_FILE"; set +a

: "${TELEGRAM_BOT_TOKEN:?TELEGRAM_BOT_TOKEN not set in $ENV_FILE}"
: "${TELEGRAM_BOT_USERNAME:?TELEGRAM_BOT_USERNAME not set in $ENV_FILE}"
: "${TELEGRAM_WEBHOOK_SECRET:?TELEGRAM_WEBHOOK_SECRET not set in $ENV_FILE}"
: "${TIGERI_API_BASE_URL:?set TIGERI_API_BASE_URL (e.g. https://api.tigeri.ai/api)}"
: "${TIGERI_FRONTEND_ORIGIN:?set TIGERI_FRONTEND_ORIGIN (e.g. https://app.tigeri.ai)}"
: "${TIGERI_COOKIE:?set TIGERI_COOKIE (paste tigeri_session=... from your browser)}"

bar() { printf '\n%s\n%s\n%s\n' "────────────────────────────────────────" "$1" "────────────────────────────────────────"; }

bar "1. Telegram getMe — confirm token is live"
curl -sS --max-time 10 \
  "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/getMe" \
  | python3 -m json.tool

bar "2. Tigeri /telegram/setup — register webhook"
curl -sS --max-time 15 \
  -X POST \
  -H "Content-Type: application/json" \
  -H "Origin: ${TIGERI_FRONTEND_ORIGIN}" \
  -H "Cookie: ${TIGERI_COOKIE}" \
  --data '{}' \
  "${TIGERI_API_BASE_URL}/v1/integrations/telegram/setup" \
  | python3 -m json.tool

bar "3. Telegram getWebhookInfo — confirm registration"
curl -sS --max-time 10 \
  "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/getWebhookInfo" \
  | python3 -m json.tool

cat <<EOF

Next steps (manual, can't be scripted):
  • In the web app, go to Integrations → Telegram → "Generate link code".
  • Open Telegram → @${TELEGRAM_BOT_USERNAME} → tap Start.
  • Send: /connect <code>
  • The bot replies "Linked to <tenant>". From then on, free-form messages
    to the bot are forwarded into the orchestrator under that tenant.
EOF
