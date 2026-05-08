## Tiger Scale Backend

This document explains how the backend works, where each major feature lives, which libraries are used, and how to run the system.

## What This Backend Does

The backend is a FastAPI + Celery system for multi-client business automation workflows:

- Invoice workflows
- Expense workflows
- Payment workflows
- Admin workflows
- Channel ingestion (Telegram, WhatsApp, Email)
- External integrations (Xero, QuickBooks, Stripe, PayPal, Google, Microsoft)
- Authentication and dashboard APIs
- Background jobs, monitoring, and health checks

## High-Level Architecture

Runtime components:

- API service: FastAPI app in webhooks/main.py
- Worker services: Celery workers in core/worker.py and task implementations in core/tasks.py
- Scheduler: Celery Beat periodic jobs from core/worker.py schedule
- Database: PostgreSQL with pgvector
- Cache + broker: Redis (also used for idempotency keys, token state, circuit-breaker flags, health heartbeats)

Core startup flow:

1. API boot starts via webhooks/main.py
2. Lifespan hook runs DB SQL migrations from migrations/runner.py
3. OAuth/channel tokens are restored from DB to Redis
4. Agents are registered into core/orchestrator.py registry
5. Routers are mounted (auth, dashboard, integrations, webhooks, admin)

## Request Processing Flow

For a channel message (example: Telegram):

1. webhooks/telegram.py receives payload
2. Message is normalized through channels classes and orchestration input
3. core/orchestrator.py classifies intent and checks confidence
4. Intent is mapped to queue and agent
5. core/tasks.py run_agent_task enqueues/executes work with retries + dead-letter handling
6. Agent logic in agents/a0x_*/agent.py processes business logic
7. Channel response is sent back (Telegram/WhatsApp/Email)
8. Logs, metrics, and audits are written

Background lifecycle:

- Periodic tasks (reminders, token refresh, health checks, insights) run through Celery Beat
- Operational status exposed via /health, /health/db, /health/redis, /health/celery, /health/beat, /health/dlq

## Backend File Structure And Ownership

Top-level structure:

```text
tigerscale-agents/
	agents/
	auth/
	channels/
	config/
	core/
	docker/
	integrations/
	memory/
	migrations/
	scripts/
	security/
	tests/
	webhooks/
	requirements.txt
	Dockerfile
```

Directory-by-directory explanation:

### webhooks/

HTTP API layer (FastAPI routers and app entrypoint).

- webhooks/main.py: Main FastAPI app, router wiring, startup/shutdown lifecycle, migrations and token restoration
- webhooks/health.py: Health checks for API, DB, Redis, Celery, Beat, DLQ
- webhooks/auth.py: Register/login/refresh/logout/password reset/Google OAuth endpoints
- webhooks/dashboard.py: Client and admin dashboard data APIs
- webhooks/integrations.py: Integration connect/callback/status/disconnect/admin utilities
- webhooks/telegram.py, webhooks/whatsapp.py, webhooks/email.py: Channel inbound webhooks
- webhooks/stripe.py, webhooks/paypal.py, webhooks/xero.py, webhooks/quickbooks.py, webhooks/google.py, webhooks/microsoft.py: Provider webhooks
- webhooks/admin_init.py: Admin bootstrap and access request approval flow
- webhooks/onboarding.py: Onboarding preview/submit APIs
- webhooks/channels.py: Connect/disconnect/status for channels
- webhooks/log_stream.py: Client log streaming endpoint
- webhooks/approval.py and webhooks/approver_config.py: Approval workflow and client approver config APIs

### core/

System orchestration, worker, queue, metrics, and intelligence logic.

- core/orchestrator.py: Intent routing, confidence gating, dedup/idempotency, queue selection
- core/worker.py: Celery app config, queue definitions, beat schedule
- core/tasks.py: Background task execution, retries, dead-letter handling, reminders, sweeps
- core/intent_classifier.py: Classification layer used by orchestrator
- core/intelligence_loop.py: Metrics collection, degradation detection, proactive insights
- core/conversation.py: Conversation/task result persistence
- core/context_builder.py: Prompt/context assembly
- core/alerting.py: Alert dispatching
- core/event_bus.py: Event broadcasting helpers
- core/prompts.py: Prompt composition helpers

### agents/

Domain-specific business agents.

- agents/base_agent.py: Shared agent base behavior
- agents/a01_invoice/: Invoice/Bill/PO agent logic
- agents/a02_expense/: Expense agent logic
- agents/a03_admin/: Admin agent logic
- agents/a04_payment/: Payment agent logic
- agents/a05_booking/: Booking-related logic (available in codebase)

Each agent package usually contains:

- agent.py: Main agent implementation
- tools.py: Tool/utility methods for the agent
- prompts.py: Prompt templates
- config.py: Agent-level constants/config

### integrations/

Provider SDK wrappers and integration abstraction layer.

- integrations/accounting_factory.py: Accounting provider abstraction (Xero/QuickBooks)
- integrations/payment_factory.py: Payment gateway abstraction (Stripe/PayPal)
- integrations/email_factory.py: Email provider abstraction
- integrations/calendar_factory.py: Calendar abstraction
- integrations/storage_factory.py: Storage abstraction
- integrations/token_manager.py: OAuth token storage/refresh helpers
- integrations/resilience.py: Retry + circuit breaker utilities
- Provider implementations: xero.py, quickbooks.py, stripe_integration.py, paypal_integration.py, google_calendar.py, gmail.py, outlook.py, sharepoint.py, onedrive.py, google_drive.py

### channels/

Channel adapters and payload normalization.

- channels/base_channel.py: Shared channel contract and message model
- channels/telegram.py: Telegram parsing and send logic
- channels/whatsapp.py: WhatsApp parsing and send logic
- channels/email.py: Email channel logic
- channels/document_router.py: Text/document route detection helpers
- channels/file_processor.py: File extraction/processing helpers

### auth/

Authentication and user/session lifecycle.

- auth/service.py: Register/login/token rotate/forgot-reset password/business logic
- auth/security.py: Password hashing, JWT generation/validation, token helpers
- auth/repository.py: DB reads/writes for auth entities
- auth/deps.py: FastAPI auth dependencies

### config/

Centralized settings and infra adapters.

- config/settings.py: Environment-backed settings model
- config/db_pool.py: PostgreSQL threaded connection pool
- config/channel_registry.py: Channel token registration/restore to Redis
- config/client_config.py: Client configuration retrieval/storage
- config/clients/: Per-client configuration files

### security/

Cross-cutting security controls.

- security/audit.py: Audit logging and fallback drain
- security/encryption.py: Secret encryption/decryption utilities
- security/rate_limiter.py: Request throttling helpers
- security/validator.py and security/sanitiser.py: Input validation and sanitization
- security/authorization.py: Authorization checks
- security/approval_token.py: Approval token helpers

### memory/

Knowledge and memory layer.

- memory/agent_memory.py: Agent memory persistence
- memory/rag.py: Retrieval-augmented knowledge store/retrieve flow
- memory/vector_store.py: Vector storage operations
- memory/entity_graph.py: Entity relationship memory graph

### migrations/

Database SQL migrations + migration runner.

- migrations/runner.py: Applies numbered SQL migrations exactly once

### scripts/

Operational scripts.

- scripts/init_db.py: Initial schema bootstrap script
- scripts/xero_setup.py and scripts/quickbooks_setup.py: OAuth setup helpers

### tests/

- tests/load_test.py: Locust load testing scenarios

### docker/

- docker/docker-compose.dev.yml: Main backend compose stack (API, workers, beat, postgres, redis)

## Libraries Used

Declared in requirements.txt and used in code:

- fastapi: HTTP API framework
- uvicorn and gunicorn: ASGI serving
- celery: Async background jobs and scheduling
- redis: Cache, Celery broker/backend, locks, health keys, idempotency
- psycopg2-binary and sqlalchemy: PostgreSQL access (psycopg2 is primary in many modules)
- pgvector: Vector support in PostgreSQL
- pydantic and pydantic-settings: Config and schema typing
- httpx: External HTTP/OAuth/provider calls
- PyJWT and bcrypt: Auth token and password security
- cryptography: Secret encryption/decryption
- email-validator: User input/email validation
- doclink and reportlab: Document parsing and PDF generation
- pytz and dateparser: Timezone and natural-language date parsing utilities
- locust: Load testing
- anthropic: LLM integration layer
- python-dotenv and pyyaml: Environment and YAML support

## How To Run (Docker Recommended)

### 1) Prerequisites

- Docker + Docker Compose
- Backend environment file at tigerscale-agents/.env

### 2) Start Stack

From repository root:

```bash
cd tigerscale-agents/docker
docker compose -f docker-compose.dev.yml up --build
```

This brings up:

- PostgreSQL (pgvector)
- Redis
- FastAPI API service
- Celery workers (high, normal, dead_letter)
- Celery beat scheduler

### 3) Verify Health

```bash
curl http://localhost:8000/health
curl http://localhost:8000/health/db
curl http://localhost:8000/health/redis
curl http://localhost:8000/health/celery
curl http://localhost:8000/health/beat
curl http://localhost:8000/health/dlq
```

## How To Run (Local Python Processes)

### 1) Start infra (postgres + redis)

```bash
cd tigerscale-agents/docker
docker compose -f docker-compose.dev.yml up -d postgres redis
```

### 2) Install dependencies

```bash
cd tigerscale-agents
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 3) Run API

```bash
cd tigerscale-agents
uvicorn webhooks.main:app --host 0.0.0.0 --port 8000 --reload
```

### 3.1) Expose Backend With ngrok (Webhook Testing)

Use ngrok when Telegram/WhatsApp/provider webhooks must reach your local backend.

1. Install ngrok and authenticate once:

```bash
ngrok config add-authtoken <YOUR_NGROK_AUTHTOKEN>
```

2. Keep backend running on port 8000.

3. Start ngrok in a new terminal:

```bash
ngrok http 8000
```

4. Copy the HTTPS forwarding URL from ngrok, for example:

```text
https://abcd-1234.ngrok-free.app
```

5. Update backend and frontend URLs to this new ngrok URL.

Backend env (`tigerscale-agents/.env`):
- Set `backend_url` to your new ngrok URL
- Set `frontend_url` if your local frontend callback flow depends on it
- Update any provider callback/webhook URLs that currently point to an old URL

Frontend env (`frontend/.env`):
- Set `NEXT_PUBLIC_API_BASE_URL` to your new ngrok URL

6. Restart API, workers, and frontend after URL changes.

### 4) Run workers (separate terminals)

```bash
cd tigerscale-agents
celery -A core.worker worker --loglevel=info --concurrency=16 -Q high
```

```bash
cd tigerscale-agents
celery -A core.worker worker --loglevel=info --concurrency=8 -Q normal,low
```

```bash
cd tigerscale-agents
celery -A core.worker worker --loglevel=info --concurrency=4 -Q dead_letter
```

```bash
cd tigerscale-agents
celery -A core.worker beat --loglevel=info
```

## Frontend Setup (Next.js)

Frontend directory: `../frontend/` (sibling folder from `tigerscale-agents/`)

### 1) Prerequisites

- Node.js 18+ (recommended)
- npm (or pnpm/yarn if your team standardizes on those)

### 2) Install Dependencies

```bash
cd ../frontend
npm install
```

### 3) Configure Environment

Create or update `../frontend/.env`:

```dotenv
NEXT_PUBLIC_API_BASE_URL=https://<your-backend-host-or-ngrok-url>
GOOGLE_SHEETS_WEBHOOK_URL=<your-google-sheets-webhook-url>
```

If you restart ngrok and get a new URL, replace `NEXT_PUBLIC_API_BASE_URL` with the new ngrok HTTPS URL.

### 4) Run Frontend

```bash
cd ../frontend
npm run dev
```

Default local app URL is usually:

```text
http://localhost:3000
```

### 5) Verify Frontend-Backend Connectivity

- Open the frontend in browser
- Trigger any API-backed screen (auth, dashboard, onboarding)
- Confirm requests hit the expected backend/ngrok URL
- If requests fail after ngrok restart, update `frontend/.env` and restart frontend

## Environment Variables

Main settings are loaded through config/settings.py from .env.

Critical variables for startup:

- Database: db_host, db_port, db_user, db_password, db_name
- Redis: redis_url
- Auth: jwt_secret_key, frontend_url, backend_url
- Provider secrets: xero_*, quickbooks_*, stripe_*, paypal_*, google_*, microsoft_*
- Security/admin: admin_api_key, admin_init_secret, secret_encryption_key
- Alerts: telegram_alert_chat_id

Note:

- config/db_pool.py currently uses sslmode=require in DB pool creation. Ensure your Postgres endpoint supports SSL, or adjust this for local non-SSL environments.

## Migrations And Schema

- Startup automatically executes migrations/runner.py from webhooks/main.py lifespan
- SQL files in migrations/ are applied once and tracked in schema_migrations
- scripts/init_db.py provides schema bootstrap helpers for initial setup scenarios

## Main API Groups

Representative endpoint groups:

- Auth: /api/v1/auth/*
- Integrations: /api/v1/integrations/*
- Channel webhooks: /webhooks/telegram, /webhooks/whatsapp, /webhooks/email
- Provider webhooks: /webhooks/stripe/{client_id}, /webhooks/paypal/{client_id}, /webhooks/xero, /webhooks/quickbooks
- Dashboard: /client/* and /admin/* APIs in webhooks/dashboard.py
- Health: /health and detailed /health/* checks

## Testing And Load Testing

Load testing script:

```bash
cd tigerscale-agents
locust -f tests/load_test.py --host http://localhost:8000
```

## Operational Notes

- Redis is used heavily for idempotency, locks, paused-agent flags, heartbeat, and token caches
- Task failures can be routed to dead_letter queue and monitored via /health/dlq
- Circuit breaker and retry behavior are implemented in integrations/resilience.py
- Agent enable/disable and maintenance-mode checks are enforced during orchestration

## Quick File Lookup Cheat Sheet

- App entrypoint: webhooks/main.py
- Routing/orchestration: core/orchestrator.py
- Task execution: core/tasks.py
- Celery config: core/worker.py
- Settings: config/settings.py
- DB pool: config/db_pool.py
- Auth logic: auth/service.py
- Integration abstraction: integrations/*_factory.py
- Migration runner: migrations/runner.py
- Health endpoints: webhooks/health.py

## Additional Documentation

- WhatsApp connector guide: ../WHATSAPP_PERSONAL_BOT_GUIDE.md


