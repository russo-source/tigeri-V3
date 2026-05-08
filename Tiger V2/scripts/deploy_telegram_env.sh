#!/usr/bin/env bash
# Surgically update the three TELEGRAM_* lines on the deployed EC2 backend
# from the local .env, then restart the API service.
#
# Run this FROM THE MAC, not from inside the EC2 shell:
#
#     bash scripts/deploy_telegram_env.sh
#
# Assumes you have an SSH alias `ec2` that resolves to the deploy host (the
# `ssh ec2` you used earlier). Override with SSH_HOST=<alias>.

set -euo pipefail

SSH_HOST="${SSH_HOST:-ec2}"
# The deployed app reads env from /etc/tigeri/tigeri.env (per the systemd unit
# at /etc/systemd/system/tigeri-api.service). The /opt/tigeri/.env file does
# exist but is NOT what the running service reads — patching only that file
# silently does nothing.
REMOTE_ENV_PATH="${REMOTE_ENV_PATH:-/etc/tigeri/tigeri.env}"
LOCAL_ENV="${LOCAL_ENV:-$(dirname "$0")/../.env}"

if [[ ! -f "$LOCAL_ENV" ]]; then
  echo "missing $LOCAL_ENV" >&2
  exit 1
fi

# Pull the values from the local .env so the bot token never gets retyped.
# shellcheck disable=SC1090
set -a; source "$LOCAL_ENV"; set +a

: "${TELEGRAM_BOT_USERNAME:?not set in $LOCAL_ENV}"
: "${TELEGRAM_BOT_TOKEN:?not set in $LOCAL_ENV}"
: "${TELEGRAM_WEBHOOK_SECRET:?not set in $LOCAL_ENV}"

echo "→ Confirming remote .env exists at $REMOTE_ENV_PATH"
ssh "$SSH_HOST" "sudo test -f $REMOTE_ENV_PATH || (echo 'MISSING'; exit 1)"

echo "→ Backing up remote .env to ${REMOTE_ENV_PATH}.bak.\$(date +%s)"
ssh "$SSH_HOST" "sudo cp $REMOTE_ENV_PATH ${REMOTE_ENV_PATH}.bak.\$(date +%s)"

echo "→ Patching three TELEGRAM_* lines in place"
# We pipe the new values over stdin instead of embedding them in the
# command line so they don't show up in process listings or shell history.
ssh "$SSH_HOST" "sudo tee /tmp/_telegram_env >/dev/null && \
  sudo python3 - $REMOTE_ENV_PATH /tmp/_telegram_env <<'PY'
import sys, pathlib
env_path, src_path = sys.argv[1], sys.argv[2]
new = {}
for line in pathlib.Path(src_path).read_text().splitlines():
    if '=' in line:
        k, _, v = line.partition('=')
        new[k.strip()] = v
out = []
seen = set()
for line in pathlib.Path(env_path).read_text().splitlines():
    if '=' in line:
        k = line.split('=', 1)[0].strip()
        if k in new:
            out.append(f'{k}={new[k]}')
            seen.add(k)
            continue
    out.append(line)
for k, v in new.items():
    if k not in seen:
        out.append(f'{k}={v}')
pathlib.Path(env_path).write_text('\n'.join(out) + '\n')
print('patched', sorted(new.keys()))
PY
  sudo rm -f /tmp/_telegram_env" <<EOF
TELEGRAM_BOT_USERNAME=$TELEGRAM_BOT_USERNAME
TELEGRAM_BOT_TOKEN=$TELEGRAM_BOT_TOKEN
TELEGRAM_WEBHOOK_SECRET=$TELEGRAM_WEBHOOK_SECRET
EOF

echo "→ Confirming the three lines are now what we expect"
ssh "$SSH_HOST" "sudo grep -E '^TELEGRAM_BOT_USERNAME=|^TELEGRAM_WEBHOOK_SECRET=' $REMOTE_ENV_PATH; \
  sudo grep -c '^TELEGRAM_BOT_TOKEN=' $REMOTE_ENV_PATH | xargs -I{} echo 'TELEGRAM_BOT_TOKEN lines: {}'"

echo "→ Restarting tigeri-api"
ssh "$SSH_HOST" 'sudo systemctl restart tigeri-api && sleep 2 && sudo systemctl status tigeri-api --no-pager | head -20'

echo
echo "Done. Next: run scripts/telegram_setup.sh from this Mac to register the webhook."
