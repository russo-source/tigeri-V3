# Tigeri.ai EC2 Runbook

Active deployment as of 2026-04-26.

| Resource | Value |
|---|---|
| Public app URL | http://ec2-100-48-88-95.compute-1.amazonaws.com/ (frontend; backend via `/api/*`) |
| Public API (direct) | http://ec2-100-48-88-95.compute-1.amazonaws.com:8000 |
| Healthcheck | `curl http://ec2-100-48-88-95.compute-1.amazonaws.com/api/healthz` |
| EC2 instance | `i-0018214267e351749` (`t2.small`, AL2023, AZ `us-east-1c` / `use1-az4`) |
| SSH | `ssh -i ~/Downloads/tigeri_global.pem ec2-user@ec2-100-48-88-95.compute-1.amazonaws.com` |
| App user | `tigeri` |
| App dir | `/opt/tigeri` (venv at `/opt/tigeri/.venv`) |
| Env file | `/etc/tigeri/tigeri.env` (mode 600, `tigeri:tigeri`) |
| Service | `tigeri-api.service` (systemd) |
| Logs | `sudo journalctl -u tigeri-api -f` |
| Postgres | `tigeri-postgres` Docker container, bound to `127.0.0.1:5432`, volume `tigeri_pgdata` |
| S3 Express bucket | `trigeri--global--use1-az4--x-s3` (us-east-1, AZ `use1-az4`) |
| IAM role | `tigeri-app-role` → instance profile `tigeri-app-profile` |
| Security group | `sg-0b2977bdd43844b8d` (TCP 80 + 8000 open from `0.0.0.0/0`) |
| Frontend root | `/var/www/tigeri-frontend/` (static export, served by nginx) |
| nginx config | `/etc/nginx/nginx.conf` + `/etc/nginx/conf.d/tigeri.conf` |
| OCR backend | `TIGERI_OCR_BACKEND=claude` in `/etc/tigeri/tigeri.env` (uses Anthropic vision; falls back to heuristic if key missing) |
| Phase 1 agents live | invoice (1), expense (2), admin (3), staffing (4), booking (5), financial_reporting (6), contract_management (7), client_onboarding (8) |

## Day-to-day commands (SSH'd to the box)

```bash
# Service
sudo systemctl status tigeri-api
sudo systemctl restart tigeri-api
sudo systemctl stop tigeri-api

# Logs
sudo journalctl -u tigeri-api -f
sudo journalctl -u tigeri-api --since "10 min ago"

# Postgres (Docker container)
docker ps
docker logs tigeri-postgres --tail 50
docker exec -it tigeri-postgres psql -U tigeri tigeri

# Quick db query
docker exec tigeri-postgres psql -U tigeri tigeri -c "SELECT count(*) FROM audit_records;"

# Edit env then restart
sudo $EDITOR /etc/tigeri/tigeri.env
sudo systemctl restart tigeri-api

# Re-run migrations after pulling new code
cd /opt/tigeri
sudo -u tigeri bash -c 'set -a && source /etc/tigeri/tigeri.env && set +a && /opt/tigeri/.venv/bin/alembic upgrade head'
```

## Deploying backend code from your laptop

```bash
cd /Users/russojossy/Trigerai
EC2_HOST=ec2-user@ec2-100-48-88-95.compute-1.amazonaws.com \
SSH_KEY=~/Downloads/tigeri_global.pem \
infra/aws/deploy/deploy.sh
```

`deploy.sh` rsyncs the repo to `/tmp/tigeri-staged/`, then on the box: rsyncs into `/opt/tigeri/`, `pip install -e .`, `alembic upgrade head`, restarts `tigeri-api`.

## Deploying frontend updates from your laptop

```bash
cd /Users/russojossy/Trigerai/frontend
npm run build                   # static export → frontend/out/
rsync -az --delete -e "ssh -i ~/Downloads/tigeri_global.pem" out/ \
    ec2-user@ec2-100-48-88-95.compute-1.amazonaws.com:/var/www/tigeri-frontend/
```

No service restart required — nginx serves the new static files immediately. The browser will pick them up on next reload (Cache-Control headers on `/_next/*` assets are immutable, so the file hashes change automatically when the build changes).

## Updating nginx config

```bash
scp -i ~/Downloads/tigeri_global.pem infra/aws/deploy/nginx-tigeri.conf \
    ec2-user@ec2-100-48-88-95.compute-1.amazonaws.com:/tmp/nginx-tigeri.conf
ssh -i ~/Downloads/tigeri_global.pem ec2-user@ec2-100-48-88-95.compute-1.amazonaws.com \
    'sudo mv /tmp/nginx-tigeri.conf /etc/nginx/conf.d/tigeri.conf && sudo nginx -t && sudo systemctl reload nginx'
```

## Smoke tests

```bash
# liveness
curl http://ec2-100-48-88-95.compute-1.amazonaws.com:8000/healthz

# agent catalog
curl -H 'X-Tigeri-Tenant-Id: tnt_smoke' http://ec2-100-48-88-95.compute-1.amazonaws.com:8000/agents

# Invoice Agent end-to-end (LangGraph engine)
curl -sS -H 'Content-Type: application/json' \
     -H 'X-Tigeri-Tenant-Id: tnt_smoke' \
     -H 'X-Tigeri-User-Id: usr_test' \
     -H 'X-Tigeri-Session-Id: s_first' \
     -X POST \
     -d '{"tenant_id":"tnt_smoke","source":"UPLOAD","document":{"media_type":"text/plain","content_ref":"inline:vendor: Acme\ncurrency: USD\ntotal: 100.00\ntax: 10.00\ninvoice: INV-1"},"received_at":"2026-04-26T00:00:00Z"}' \
     http://ec2-100-48-88-95.compute-1.amazonaws.com:8000/agents/invoice_agent/invoke

# audit trail
curl -H 'X-Tigeri-Tenant-Id: tnt_smoke' \
     http://ec2-100-48-88-95.compute-1.amazonaws.com:8000/audit/records?limit=10

# S3 Express read/write from inside the box
ssh -i ~/Downloads/tigeri_global.pem ec2-user@ec2-100-48-88-95.compute-1.amazonaws.com \
  'sudo -u tigeri /opt/tigeri/.venv/bin/python -c "import boto3;print(boto3.client(\"s3\",region_name=\"us-east-1\").list_objects_v2(Bucket=\"trigeri--global--use1-az4--x-s3\",MaxKeys=5).get(\"KeyCount\",0))"'
```

## Common failures

| Symptom | Fix |
|---|---|
| `/healthz` connect timeout | EC2 SG missing TCP 8000 inbound — re-run the CloudShell snippet's part 3, or add the rule in the console. |
| `NoCredentialsError` on S3 calls | IAM instance profile detached — re-run `attach_profile.sh i-0018214267e351749`, then `sudo systemctl restart tigeri-api`. |
| Service inactive after deploy | `sudo journalctl -u tigeri-api -n 50` — usually a missing env var or migration failure. |
| OOM-killed | `t2.small` has 1.9 GB RAM. Bump to `t3.small` or `t3.medium` from the EC2 console (stop instance, change type, start). The IAM role and SG persist. |
| Postgres container gone | `docker start tigeri-postgres`, then restart the api. Data is on the named volume `tigeri_pgdata`. |

## Rotating secrets

- Anthropic key: edit `ANTHROPIC_API_KEY` in `/etc/tigeri/tigeri.env`, restart.
- A2A HMAC: `openssl rand -hex 32` → write to `TIGERI_A2A_HMAC_SECRET`, restart.
- Postgres password: not currently rotated (single-tenant; stored in `TIGERI_DATABASE_URL`).

## Scheduled health check

A one-time CCR routine runs at **2026-04-26 20:15 UTC** (24h after first deploy) and posts a punch list to https://claude.ai/code/routines/trig_018tpMWWuCx7mHU7zejgHhdW. Re-arm by editing `run_once_at` from the same URL.
