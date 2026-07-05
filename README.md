# Meridian — Distributed Job Scheduler

A production-inspired distributed job scheduling platform with a microservice
backend: API gateway, Eureka-style service discovery, independently scalable
domain services and workers, a standby-capable scheduler, and a live web
dashboard — built on FastAPI, PostgreSQL, and React.

![Architecture](docs/architecture.md) · [ER diagram](docs/er-diagram.md) ·
[Design decisions](docs/design-decisions.md) · [API docs](docs/api.md)

## Features

- **Auth & multi-tenancy** — JWT auth; Users → Organizations → Projects → Queues,
  with role-based access control (OWNER / ADMIN / MEMBER / VIEWER), a workspace
  switcher, and an organization admin page (members, roles, invites).
- **Real job execution via a Handler SDK** — the platform is completely
  generic; business logic lives in pluggable *handler packs* loaded from
  `HANDLER_MODULES`. Payloads are schema-validated before execution, workers
  advertise their capabilities to the registry, `GET /api/tasks` exposes the
  fleet catalog, and deterministic failures (bad payload, 4xx, unknown task)
  dead-letter immediately instead of retrying. Builtin handlers: `http_request`
  (webhooks/APIs — verified against a live external API) and `send_email` (SMTP).
- **Queues** — per-queue priority, fleet-wide concurrency limits, pause/resume,
  configurable retry policies, live statistics.
- **Job types** — immediate, delayed, scheduled, recurring (cron), and batch.
- **Workers** — poll queues, **atomically claim jobs** (`FOR UPDATE SKIP LOCKED`),
  execute concurrently in a thread pool, send heartbeats, drain gracefully on SIGTERM.
- **Full lifecycle** — `SCHEDULED → QUEUED → CLAIMED → RUNNING → COMPLETED /
  FAILED → retry (fixed / linear / exponential backoff + jitter) → DEAD_LETTER`.
- **Reliability** — dead workers are detected via missed heartbeats and their
  in-flight jobs are reclaimed; at-least-once semantics with idempotency keys.
- **Observability** — per-attempt execution history, structured job logs, worker
  assignment, timing metrics, throughput charts.
- **Dashboard** — queue health, worker status, job explorer with filters and
  pagination, execution logs, one-click retry/requeue, **live WebSocket updates**.
- **Distributed locking** — multiple scheduler instances coordinate through a
  Postgres advisory lock (active/standby high availability).
- **Microservice architecture** — an API gateway routes to identity / job /
  monitoring services discovered through a Eureka-style registry with lease
  heartbeats, client-side round-robin load balancing, and instance failover.

## Quick start (Docker)

```bash
docker compose up -d --build
```

| Service          | URL                                   |
|------------------|---------------------------------------|
| Dashboard        | http://localhost:5173                 |
| API Gateway      | http://localhost:8000                 |
| Service Registry | http://localhost:8761/registry/services |
| Service catalog  | http://localhost:8000/api/gateway/services |
| Postgres         | localhost:5433 (host port)            |

This starts: `postgres`, `registry`, `gateway`, `identity-service`,
`job-service` ×2, `monitoring-service`, `worker` ×2, `scheduler`, `frontend`.

Register an account in the dashboard, create a queue, and enqueue demo jobs
(`echo`, `sleep`, `send_email`, `flaky`, `always_fail`) straight from the Jobs page.

Things worth trying:

```bash
# Scale services independently
docker compose up -d --scale worker=4 --scale job-service=3

# Kill a worker mid-job — the reaper reclaims and retries its jobs
docker kill distributed-job-scheduler-worker-1

# Kill an API replica — the gateway fails over with zero dropped requests
docker kill distributed-job-scheduler-job-service-2
```

## Local development

```bash
# 1. Postgres
docker compose up -d postgres        # published on host port 5433

# 2. Backend (Python 3.12)
cd backend
python -m venv .venv && .venv/Scripts/activate   # Windows
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload        # API on :8000
python -m app.worker                 # worker (run several!)
python -m app.scheduler              # scheduler + reaper

# 3. Frontend
cd frontend
npm install
npm run dev                          # dashboard on :5173 (proxies /api)
```

## Tests

```bash
cd backend
pytest tests -q
```

32 tests cover the concurrency-critical paths: race-free claiming under 10
concurrent claimers, per-queue concurrency caps, priority ordering, retry
backoff strategies, dead-letter + requeue transitions, dead-worker reaping,
cron materialization, API validation, pagination, idempotency, RBAC, service
registry lease lifecycle, and gateway routing rules.
Tests run against a dedicated `scheduler_test` database (created automatically).

## Repository layout

```
backend/
  app/
    gateway.py         API gateway: routing, discovery LB, retry, WS relay
    registry.py        Eureka-style service registry
    discovery.py       registry client (register, renew lease, resolve)
    microservice.py    service entrypoint (SERVICE_NAME selects routers)
    main.py            all-in-one app (tests + local dev)
    worker.py          worker service entrypoint
    scheduler.py       scheduler/reaper service entrypoint
    models.py          SQLAlchemy schema (12 entities)
    handlers.py        task handler registry
    routers/           API endpoints
    services/          claiming, retry, lifecycle logic
  tests/
frontend/              React + Vite dashboard ("Meridian")
docs/                  architecture, ER diagram, design decisions, API guide
docker-compose.yml     postgres + registry + gateway + 3 domain services
                       + worker×2 + scheduler + dashboard
```
