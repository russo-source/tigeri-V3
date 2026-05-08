# Tigeri Operations Runbook

Single-source operator guide for the Tigeri.ai stack on EC2. If you can only
read one page during an incident, this is the one.

## 1. Architecture at a glance

```
                ┌────────────────────────── EC2 (single host) ──────────────────────────┐
internet ─https─┤  nginx :443  →  /api/* → uvicorn :8000  (tigeri-api.service)           │
                │                                                                          │
                │                /        → static frontend at /var/www/tigeri-frontend    │
                │                                                                          │
                │  cron 02:15 UTC → /opt/tigeri/scripts/backup_postgres.sh                 │
                │                       └→ /var/backups/tigeri/tigeri-<ts>.sql.gz (7d)     │
                │                                                                          │
                │  docker container `tigeri-postgres` (postgres:16-alpine, persistent vol) │
                └──────────────────────────────────────────────────────────────────────────┘
```

- Public host: `https://100-48-88-95.sslip.io`
- SSH: `ssh ec2` (config in `~/.ssh/config`, key `~/Downloads/tigeri_global.pem`)
- App user: `tigeri`. App root: `/opt/tigeri`. Env file: `/etc/tigeri/tigeri.env` (root:tigeri 0640).
- Logs: `journalctl -u tigeri-api -f` (api), `journalctl -t tigeri-backup -f` (cron).

## 2. Routine deploy

From a clean local repo on `main`:

```bash
EC2_HOST=ec2-user@ec2-100-48-88-95.compute-1.amazonaws.com \
  SSH_KEY=~/Downloads/tigeri_global.pem \
  ./infra/aws/deploy/deploy.sh
```

The script syncs source → `/opt/tigeri`, installs deps, runs `alembic upgrade head`,
restarts `tigeri-api`, and reloads nginx with the canonical config from
`infra/aws/deploy/nginx-tigeri-https.conf`. To deploy the frontend:

```bash
cd frontend && npm run build
rsync -az --delete -e "ssh -i ~/Downloads/tigeri_global.pem" \
  --rsync-path="sudo rsync" \
  ./out/ ec2-user@ec2-100-48-88-95.compute-1.amazonaws.com:/var/www/tigeri-frontend/
```

Smoke after every deploy:

```bash
curl -sk https://100-48-88-95.sslip.io/api/healthz   # liveness
curl -sk https://100-48-88-95.sslip.io/api/readyz    # DB + crypto round-trip
```

## 3. Rollback

The deploy is rsync-based — there's no built-in tag. To roll back:

1. `git checkout <previous-good-sha>` locally.
2. Re-run `deploy.sh`. The migration step will run — if the previous SHA had
   fewer migrations, alembic is a no-op (alembic doesn't downgrade automatically).
3. If a destructive migration ran in the bad release, restore from the last
   known-good `pg_dump` (Section 5) BEFORE re-running deploy.

## 4. Postgres backup

A 02:15 UTC cron runs `/opt/tigeri/scripts/backup_postgres.sh`, which:

- `pg_dump -Fp --clean --if-exists` from inside the `tigeri-postgres` container,
- gzips to `/var/backups/tigeri/tigeri-<ts>.sql.gz`,
- runs `gzip -t` to validate the archive (deletes + exit 1 on corruption),
- prunes anything older than 7 days.

Verify backups exist:

```bash
ssh ec2 "ls -lh /var/backups/tigeri/ | tail -10"
ssh ec2 "journalctl -t tigeri-backup --since=yesterday | tail"
```

To force a backup right now: `ssh ec2 "sudo /opt/tigeri/scripts/backup_postgres.sh"`.

## 5. Restore from backup (drill + real)

**Drill (in a sandbox env, not prod):**

```bash
docker run --rm -d --name pg-drill -e POSTGRES_PASSWORD=test -p 5433:5432 postgres:16-alpine
sleep 5
zcat /var/backups/tigeri/tigeri-<ts>.sql.gz | \
  docker exec -i pg-drill psql -U postgres -d postgres -c 'CREATE DATABASE tigeri;'
zcat /var/backups/tigeri/tigeri-<ts>.sql.gz | \
  docker exec -i pg-drill psql -U postgres -d tigeri
docker exec pg-drill psql -U postgres -d tigeri -c 'SELECT count(*) FROM users;'
docker rm -f pg-drill
```

**Real restore (production data loss event):**

1. `sudo systemctl stop tigeri-api` — stop writes.
2. Take an emergency dump of whatever survives: `sudo /opt/tigeri/scripts/backup_postgres.sh`.
3. `sudo docker exec tigeri-postgres psql -U tigeri -d postgres -c 'DROP DATABASE tigeri; CREATE DATABASE tigeri;'`.
4. `sudo zcat /var/backups/tigeri/tigeri-<ts>.sql.gz | sudo docker exec -i tigeri-postgres psql -U tigeri -d tigeri`.
5. `sudo systemctl start tigeri-api`.
6. Smoke `/api/readyz`.

RPO: **24 hours** (one backup per day). RTO: **~30 min** (depends on dump
size; pilot is currently 50 KB and restores in seconds).

## 6. Rotate the admin password (force-change-on-first-sign-in)

The right flow when the operator and the user are different people:

1. **Operator** picks a *temporary* password and runs `seed_admin.py`. The
   script flips `users.must_change_password=true`.
2. **Operator** shares the temporary password out-of-band (1Password share,
   Signal, in-person — never email or chat).
3. **User** signs in. The sign-in response carries
   `must_change_password=true`; the frontend bounces them to
   `/change-password` and the API refuses every authed call other than
   `/auth/change-password` (a 403 with `code: password_change_required`).
4. **User** picks their own password. The flag clears, the operator never
   sees it.

```bash
TEMP_PW=$(python3 -c "import secrets; print('Init' + secrets.token_urlsafe(12))")
ssh ec2 "DBURL=\$(sudo grep '^TIGERI_DATABASE_URL=' /etc/tigeri/tigeri.env | cut -d= -f2-) && cd /opt/tigeri && sudo -u tigeri env TIGERI_DATABASE_URL=\"\$DBURL\" TIGERI_ADMIN_PASSWORD=\"$TEMP_PW\" /opt/tigeri/.venv/bin/python scripts/seed_admin.py"
echo "TEMPORARY PASSWORD (share OOB, then forget): $TEMP_PW"
```

Set `TIGERI_ADMIN_FORCE_CHANGE=0` only for the very first bootstrap when
the operator IS the user (no follow-up sign-in by anyone else).

## 7. Rotate `TIGERI_SECRET_ENCRYPTION_KEY` (Fernet)

**Heads up:** rotating this key invalidates every encrypted column already in
the DB (OAuth tokens, BYOA secrets, pending-action parameters, audit-chain
HMAC). Treat as a re-encryption event, not a rotation. Until proper key
versioning is in place:

1. Export every tenant's OAuth tokens (decrypt with the current key, hold in
   memory or temp file owned by tigeri:tigeri 0600).
2. Generate the new key: `python3 -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'`.
3. Update `/etc/tigeri/tigeri.env`, restart `tigeri-api`.
4. Re-encrypt and re-save tokens with the new key.
5. Audit-chain hashes from the old key window become unverifiable; record
   the rotation timestamp in the audit ledger so future verifications stop at
   the boundary instead of failing mysteriously.

This is fragile — proper key versioning (with a `key_id` column on every
encrypted row) is on the 30-day plan and should land before scaling beyond
the pilot.

## 8. Common incidents

### tigeri-api won't start
```bash
sudo journalctl -u tigeri-api -n 100 --no-pager
sudo systemctl status tigeri-api
```
Most common: missing dep after a `pip install -e .` (run that), or a
malformed line in `/etc/tigeri/tigeri.env`. Note: deploy.sh extracts only
`TIGERI_DATABASE_URL` from the env file because line 53 has historically had
syntax bash refuses to source — don't try to `source` it.

### Postgres container down
```bash
sudo docker ps -a | grep tigeri-postgres
sudo docker logs --tail 50 tigeri-postgres
sudo docker start tigeri-postgres
```
Restart policy is `unless-stopped`, so a host reboot brings it back. If the
volume is gone, restore from backup (Section 5).

### nginx 502
The api process is dead or wedged. `sudo systemctl restart tigeri-api`,
then `journalctl -u tigeri-api`.

### Xero invoices stop posting
Check `/api/v1/integrations/health` (admin-authed). If `xero.healthy=false`
with a `refresh failed` error, the BYOA refresh token is invalid or the
client_id/secret in `tenant_integration_credentials` is wrong — reconnect
from the admin Integrations page.

### Token-budget false alarms
If a tenant claims "daily budget reached" but should have headroom, check
`audit_records` for the `llm_token_usage` action and confirm the sum.
Disable the gate temporarily by setting
`TIGERI_CHAT_TENANT_DAILY_TOKEN_BUDGET=0` in the env file and restarting.

## 9. What still needs cloud-console action

The following are not in code/scripts because they require AWS-console or
account-level changes. See `docs/PROD_GAPS.md` for context and the
recommended end state.

- AWS Secrets Manager / Parameter Store for `TIGERI_SECRET_ENCRYPTION_KEY`
  and `TIGERI_A2A_HMAC_SECRET` (currently in `/etc/tigeri/tigeri.env` plain-text).
- CloudWatch agent for log shipping + 4xx/5xx alarms + CPU/memory alarms.
- EBS DLM lifecycle policy for daily snapshots (defense in depth alongside pg_dump).
- AWS WAF in front of nginx (CloudFront distribution prerequisite).
- RDS Postgres multi-AZ migration (currently single-host docker container).
- TOTP MFA for admin role (schema + UI work, not just config).
- Real domain + ACM cert (currently sslip.io with Let's Encrypt — fine for
  pilot, blocks SOC2 evidence).

## 10. Contact / escalation

- Engineering on-call: see internal directory.
- AWS account: see `MEMORY.md` → `aws_resources.md` for account id and region.
- Anthropic API key owner: `russo@tigeri.ai` (rotate via console.anthropic.com).
