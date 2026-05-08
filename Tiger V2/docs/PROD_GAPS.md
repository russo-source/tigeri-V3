# Production Gaps — Deferred Cloud-Console Work

Code-only fixes from the 2026-04-28 production-readiness assessment have
landed on `main`. The items below cannot be closed from inside the repo —
they require AWS console, account-level, or vendor decisions. Each entry
states **what's missing**, **why it matters**, **what to do**, and the
**rough effort**.

## Status snapshot (last refreshed 2026-04-28, end-of-day)

**Code-side hardening shipped since the original assessment:**
- Cookie auth + admin gate + audit hash chain (alembic 0006-0008)
- Force-change-on-first-sign-in (alembic 0014, MustChangePasswordMiddleware)
- nginx security headers (HSTS / CSP / X-Frame-Options / Permissions-Policy)
  source-controlled and replayed by deploy.sh
- Per-tenant LLM token budget + prompt-injection guard + tool-arg scoping
  (covers BOTH Anthropic and OpenRouter chat paths)
- Cross-tenant isolation tests (negative tests for IDOR + role escalation)
- CSRF allow-list invariant tests (regression guard for new webhook routes)
- Postgres backup cron (daily 02:15 UTC, gzip-validated, 7-day retention)
- GitHub Actions CI (backend pytest + frontend type-check + build)
- Operations runbook (deploy / rollback / restore / rotate procedures)
- Google Workspace integrations: Gmail send, Calendar with Meet, Drive
  doc creation, Sheets read/append; Maps Geocoding, Places (New),
  Distance Matrix, Weather. All write paths route through the
  propose-confirm gate.
- Idempotency-key bug fix in pending_actions (per-propose nonce instead of
  content hash; prevents 500 on resubmit + duplicate side effect)
- Routing GL adapter surfaces real Xero rejections to chat instead of
  silently falling back to the stub
- Stub-mode banner on the chat invoice card (no longer pretends to be Live
  when no GL provider is connected)
- Chat session_id input validated before DB use (regex-bound length)
- Sign-up stamps `last_active_at` on creation; demo-seed failures log
  with tenant context

**98/98 unit + integration tests passing. Local main and EC2 in sync.**

**The gaps below are unchanged — they are the residual production debt.**

## P0 (close before any paying customer)

### 1. Secrets out of `/etc/tigeri/tigeri.env`
**Why:** A single read of that file leaks every tenant's OAuth tokens and
breaks the audit chain (HMAC key + Fernet key both live there in plaintext).
**What:** Move at minimum `TIGERI_SECRET_ENCRYPTION_KEY` and
`TIGERI_A2A_HMAC_SECRET` to AWS Secrets Manager (or Parameter Store
SecureString). Update `tigeri-api.service` to fetch with `aws secretsmanager
get-secret-value` at boot, write to a tmpfs path, and source. Rotate the
Fernet key immediately because it has been displayed in chat during the
build.
**Effort:** ½ day for Secrets Manager + service unit; +1 day for re-encrypting
existing rows during rotation. Versioned key column on encrypted rows is the
right end-state but a bigger lift.

### 2. RDS Postgres multi-AZ
**Why:** The DB lives in a docker container on one EC2 host. EBS volume loss
or AZ failure = total data loss beyond the last 02:15 UTC pg_dump.
**What:** Provision RDS Postgres 16, multi-AZ, encryption-at-rest enabled,
automated backups (7-day PITR). Switch `TIGERI_DATABASE_URL` to the RDS
endpoint. Run alembic against RDS, then dump-restore from the docker
container. Decommission the in-host container.
**Effort:** 1 day. ~$30/month for `db.t4g.micro` multi-AZ.

### 3. CloudWatch agent + alarms
**Why:** Right now we discover an outage when a customer pings us. There are
zero metrics and zero alerts.
**What:**
- Install `amazon-cloudwatch-agent` on the EC2 host.
- Ship `journalctl -u tigeri-api` and `journalctl -t tigeri-backup` to a
  CloudWatch log group with 30-day retention.
- Alarms: 5xx rate > 1% for 5 min; CPU > 80% for 10 min; memory free
  < 256 MB; disk free < 1 GB; `tigeri-backup` log absent for > 30 hours
  (i.e. cron didn't fire).
- Pipe alarms to an SNS topic with email + a real on-call channel.
**Effort:** ½ day. Free tier covers the metric/log volume at this scale.

### 4. EBS daily snapshot via DLM
**Why:** `pg_dump` is logical and lives on the same EBS volume it's protecting.
A volume failure during the backup window = no recovery point.
**What:** Tag the EBS volume `Backup=true` and create a Data Lifecycle
Manager policy that snapshots daily, retains 7 copies. Cross-region copy is
a stretch goal.
**Effort:** 30 minutes in the console.

## P1 (close before public sign-ups)

### 5. AWS WAF in front of nginx
**Why:** No bot mitigation, no rate rules at the edge, no managed-rules
protection against common L7 attacks.
**What:** Put CloudFront in front of the EC2 origin, attach AWS WAF with
the AWS managed-rules core set + the known-bad-inputs ruleset + a rate-based
rule on `/api/auth/sign-in` (already protected at the app layer, but
defense-in-depth at the edge offloads the in-memory limiter).
**Effort:** 1 day. CloudFront also fixes the static-asset caching story
properly.

### 6. TOTP MFA for the admin role
**Why:** Cookie-only auth + bcrypt is the right floor, not the right ceiling.
A single-factor compromise gives full admin access.
**What:** Add `mfa_secret`, `mfa_recovery_codes` columns to `users`. Enrollment
flow at first sign-in for any `role IN ('owner','admin')`. Verify a TOTP at
sign-in for those users when `mfa_enrolled = true`.
**Effort:** 2–3 days. Use `pyotp` + `qrcode` for the enrollment QR.

### 7. Real domain + ACM cert
**Why:** sslip.io is public DNS controlled by a third party. SOC2 evidence
will not accept a cert chained to a domain we don't own. Phishing risk too
(anyone can `<garbage>.sslip.io`).
**What:** Buy a real domain (`tigeri.ai` already owned per `userEmail`). Move
DNS to Route53. Issue an ACM cert for `app.tigeri.ai`. Switch the nginx
server_name + Let's Encrypt → ACM (or keep certbot if not using CloudFront).
Update `TIGERI_PUBLIC_API_BASE_URL` so cookie SameSite stays correct.
**Effort:** ½ day.

### 8. Sentry + OpenTelemetry traces
**Why:** Right now exception triage is `journalctl` archaeology. No latency
breakdown across DB, LLM, external API.
**What:** Add `sentry-sdk[fastapi]` (free tier) to capture exceptions with
tenant_id + user_id tags. OTEL the FastAPI app + asyncpg + httpx, ship to
Grafana Cloud or self-hosted Tempo.
**Effort:** ½ day for Sentry, +1 day for OTEL.

### 9. External pen test
**Why:** No third-party assurance. We've reviewed our own code, which is the
weakest possible form of review for security.
**What:** Engage an OWASP-Top-10 + auth/session/multi-tenant focused engagement.
Around USD 5–10k for a one-week pilot-grade engagement.
**Effort:** Calendar time only, ~2 weeks elapsed.

## P2 (nice-to-have, not blocking)

### 10. Versioned Fernet key with rotation worker
Add `key_id` column to every encrypted row (`oauth_tokens`,
`tenant_integration_credentials`, `pending_actions.parameters_encrypted`,
audit-chain HMAC inputs). Rotation job re-encrypts in batches without
downtime.

### 11. Per-tenant Anthropic API key
Today there's a single platform key. A noisy tenant can exhaust the org
quota. Either add per-tenant keys (BYOA-style) or budget gating at the
provider level.

### 12. Data residency
Tenants are global; the EC2 + (future) RDS lives in one region. EU tenants
need an EU region or AWS regional pinning before GDPR Article 44 becomes
relevant.

### 13. SOC2 readiness assessment
Once items 1–8 are closed, engage a SOC2 auditor for a Type 1 readiness
review. The audit-chain, RBAC, and per-tenant scoping are already in good
shape; the gap is in policies (acceptable-use, change-management,
incident-response) and evidence (CI logs, deploy logs, alarm history).
