# API Guide

All traffic enters through the **API gateway** on http://localhost:8000; it
routes each path to the owning microservice (identity / job / monitoring)
via the service registry. Interactive Swagger docs are served per service —
the gateway proxies `/docs` of the job-service; each service also exposes its
own `/docs` when run directly.

Gateway-specific endpoints:

| Method | Path | Notes |
|---|---|---|
| GET | `/api/health` | gateway liveness |
| GET | `/api/gateway/services` | live service catalog from the registry |

## Conventions

- **Auth:** `Authorization: Bearer <token>` from `/api/auth/register` or `/api/auth/login`.
- **Errors:** structured JSON — `422` validation (field-level details), `401`
  unauthenticated, `403` insufficient role, `404` missing, `409` conflict
  (duplicate name, illegal state transition).
- **Pagination:** `?page=1&page_size=25` → `{items, total, page, page_size}`.
- **RBAC:** VIEWER reads; MEMBER manages jobs and pause/resume; ADMIN manages
  queues/projects/members; OWNER everything.

## Endpoints

### Auth
| Method | Path | Notes |
|---|---|---|
| POST | `/api/auth/register` | creates user + personal org (OWNER) |
| POST | `/api/auth/login` | returns JWT |
| GET  | `/api/auth/me` | current user |

### Organizations & projects
| Method | Path | Role |
|---|---|---|
| POST/GET | `/api/orgs` | any |
| POST/GET | `/api/orgs/{id}/members` | ADMIN / VIEWER |
| POST/GET | `/api/orgs/{id}/projects` | ADMIN / VIEWER |

### Queues & retry policies
| Method | Path | Notes |
|---|---|---|
| POST/GET | `/api/projects/{id}/queues` | name unique per project |
| POST/GET | `/api/projects/{id}/retry-policies` | FIXED / LINEAR / EXPONENTIAL |
| GET/PATCH | `/api/queues/{id}` | update concurrency, priority, policy |
| POST | `/api/queues/{id}/pause` · `/resume` | claiming stops instantly |
| GET | `/api/queues/{id}/stats` | counts, throughput, avg duration, failure rate |

### Jobs
| Method | Path | Notes |
|---|---|---|
| POST | `/api/queues/{id}/jobs` | immediate; `type=DELAYED` + `delay_seconds` / `run_at`; `type=SCHEDULED` + `run_at`; optional `idempotency_key`, `priority` |
| POST | `/api/queues/{id}/jobs/batch` | up to 1000, share a `batch_id` |
| POST | `/api/queues/{id}/scheduled-jobs` | recurring: `cron_expr` (validated) |
| GET | `/api/queues/{id}/jobs?status=&task=&page=` | filtered, paginated |
| GET | `/api/jobs/{id}` | includes per-attempt execution history |
| GET | `/api/jobs/{id}/logs` | structured log lines |
| POST | `/api/jobs/{id}/retry` | FAILED/DEAD_LETTER/CANCELLED → QUEUED |
| POST | `/api/jobs/{id}/cancel` | QUEUED/SCHEDULED only |

### Workers, DLQ, stats
| Method | Path | Notes |
|---|---|---|
| GET | `/api/workers` | fleet status, heartbeats, counters |
| GET | `/api/queues/{id}/dlq` | dead letter entries |
| POST | `/api/dlq/{id}/requeue` | resets attempts, requeues |
| GET | `/api/stats/overview` | global counts + throughput series |
| WS | `/api/ws/overview?token=JWT` | same snapshot pushed every 2s |

## Example: create and watch a retrying job

```bash
TOKEN=$(curl -s -X POST localhost:8000/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"you@example.com","password":"password123"}' | jq -r .access_token)

curl -s -X POST "localhost:8000/api/queues/$QUEUE/jobs" \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"task":"flaky","payload":{"failure_rate":0.7}}'

curl -s "localhost:8000/api/jobs/$JOB" -H "Authorization: Bearer $TOKEN" | jq .executions
```
