# Tigeri.ai

Specification: [TIGERI_AGENT_CATALOG_v1.md](TIGERI_AGENT_CATALOG_v1.md). Slice 1 + Slice 2 are landed: scaffold, shared framework, **Phase 1 agents priorities 1–5** (Invoice, Expense, Admin, Staffing, Booking), Next.js frontend, AWS deploy kit, and LangGraph workflow with per-user session memory.

## Local quickstart

```bash
cp .env.example .env             # fill ANTHROPIC_API_KEY and TIGERI_A2A_HMAC_SECRET
make bootstrap                   # install backend deps
make up                          # Postgres in docker
make migrate                     # apply schema (0001 + 0002)
make run                         # http://localhost:8000
```

Frontend (separate terminal):

```bash
cd frontend
cp .env.local.example .env.local # NEXT_PUBLIC_API_BASE_URL defaults to http://localhost:8000
npm install
npm run dev                      # http://localhost:3000
```

Run backend tests: `make test`. Lint: `make lint`. Typecheck: `make typecheck`.

## Layout

- [src/tigeri/core/](src/tigeri/core/) — config, db, logging, ids
- [src/tigeri/agent_card/](src/tigeri/agent_card/) — A2A-style cards (catalog section 5.1) + registry; cards in [agent_card/cards/](src/tigeri/agent_card/cards/)
- [src/tigeri/a2a/](src/tigeri/a2a/) — envelope + HMAC signing, 30s replay window (catalog section 5.3)
- [src/tigeri/trust/](src/tigeri/trust/) — 4 trust tiers and policy evaluator (catalog section 5.2)
- [src/tigeri/audit/](src/tigeri/audit/) — append-only audit buffer with `chain_position` / `backfilled_at` placeholders for the future Compliance & Audit Agent (Priority 12)
- [src/tigeri/activation/](src/tigeri/activation/) — sign-up state machine (catalog section 4)
- [src/tigeri/graph/](src/tigeri/graph/) — LangGraph framework (BaseGraphAgent, checkpointer, LangSmith); see [graph/README.md](src/tigeri/graph/README.md)
- [src/tigeri/agents/](src/tigeri/agents/) — Priority 1 Invoice (imperative + LangGraph variants), 2 Expense, 3 Admin, 4 Staffing, 5 Booking
- [src/tigeri/api/](src/tigeri/api/) — FastAPI surface (CORS open to localhost:3000)
- [frontend/](frontend/) — Next.js 16 + React 19 + Tailwind 4 (sign-in, activation, agent catalog, invoice inbox, audit log)
- [infra/aws/deploy/](infra/aws/deploy/) — drop-in scripts to wire an existing S3 bucket + EC2 instance
- [infra/aws/cdk/](infra/aws/cdk/) — synth-only CDK skeleton for greenfield provisioning

## Endpoints

| Method | Path | Notes |
|---|---|---|
| GET | `/healthz` | liveness |
| POST | `/activation/start` | S0 → S4; MCP-first, API fallback |
| POST | `/activation/objectives` | S4 → S6; ranked recommendations |
| POST | `/activation/deploy` | S6 → S8 |
| GET | `/agents` | list every Agent Card |
| GET | `/agents/{agent_id}/card` | one card |
| POST | `/agents/invoice_agent/invoke` | LangGraph by default; `X-Tigeri-Engine: legacy` for the imperative variant |
| POST | `/agents/expense_agent/invoke` | imperative |
| POST | `/agents/admin_agent/invoke` | imperative |
| POST | `/agents/staffing_agent/invoke` | imperative |
| POST | `/agents/booking_agent/invoke` | imperative |
| GET | `/invoices/{id}` | invoice state |
| GET | `/audit/records` | filter by trace_id / actor |

Invoice invoke headers:
- `X-Tigeri-Tenant-Id` (required)
- `X-Tigeri-User-Id` (default `anonymous`) — drives session memory
- `X-Tigeri-Session-Id` (default `default`) — drives session memory
- `X-Tigeri-Engine: graph|legacy` — defaults to graph

## AWS deploy (existing bucket + EC2)

See [infra/aws/deploy/README.md](infra/aws/deploy/README.md). Two scripts on your laptop (`setup_iam.sh`, `attach_profile.sh`) plus one on the EC2 host (`setup_remote.sh`), then `deploy.sh` for every roll. The app uses the EC2 instance profile — no static AWS keys needed.

## LangChain / LangGraph / LangSmith

Agents are LangGraph `StateGraph` workflows. Per-user session memory persists between calls under `thread_id = tenant_id:user_id:session_id`. Default checkpointer is in-process `MemorySaver`; flip `TIGERI_SESSION_CHECKPOINTER=postgres` to persist. LangSmith tracing turns on with `LANGSMITH_TRACING=true` + `LANGSMITH_API_KEY=...`. Pattern docs and the migration plan for the other 19 agents live in [src/tigeri/graph/README.md](src/tigeri/graph/README.md).


russojossy@Russos-Mac-mini Trigerai % cd frontend
russojossy@Russos-Mac-mini frontend % npm run build
ussojossy@Russos-Mac-mini frontend % rsync -az --delete -e "ssh -i ~/Downloads/tigeri_global.pem" out/ \
  ec2-user@ec2-100-48-88-95.compute-1.amazonaws.com:/var/www/tigeri-frontend/