# Tigeri.ai frontend

Next.js 16 (App Router) + React 19 + TypeScript strict + Tailwind 4. Talks to the FastAPI backend in [../src/tigeri/api](../src/tigeri/api).

## Quickstart

```bash
cp .env.local.example .env.local   # set NEXT_PUBLIC_API_BASE_URL if not http://localhost:8000
npm install
npm run dev                         # http://localhost:3000
```

Pages:
- `/` — landing
- `/sign-in` — set tenant id (stored in localStorage; sent as `X-Tigeri-Tenant-Id` header)
- `/activation` — 4-step CRM connect → objectives → recommendations → deploy
- `/agents` — agent catalog (lists every Agent Card)
- `/agents/invoice` — Invoice Agent inbox; submit raw invoice text and see the run end-to-end
- `/audit` — append-only audit log viewer with trace_id filter

CORS is open to `http://localhost:3000` from the backend in [src/tigeri/api/app.py](../src/tigeri/api/app.py).
