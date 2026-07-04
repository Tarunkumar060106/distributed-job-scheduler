# Architecture

Microservice deployment with an API gateway and Eureka-style service discovery.

```mermaid
flowchart LR
    subgraph Clients
        UI[React Dashboard]
        CLI[API Clients]
    end

    GW["API Gateway :8000<br/>routing · discovery LB · retry · WS relay"]
    REG["Service Registry :8761<br/>register · heartbeat · lease eviction"]

    subgraph Services["Domain services (scale each independently)"]
        IDS["identity-service<br/>auth · orgs · projects"]
        JS1["job-service ×N<br/>queues · jobs · DLQ"]
        MON["monitoring-service<br/>stats · WebSocket feed"]
    end

    subgraph Background
        W1["worker ×N<br/>claim → execute → heartbeat"]
        SCH["scheduler (active/standby)<br/>promote · cron · reaper"]
    end

    PG[(PostgreSQL<br/>single source of truth)]

    UI --> GW
    CLI --> GW
    GW -->|resolve| REG
    IDS -.->|register + renew| REG
    JS1 -.-> REG
    MON -.-> REG
    W1 -.-> REG
    SCH -.-> REG
    GW --> IDS
    GW --> JS1
    GW --> MON
    IDS --> PG
    JS1 --> PG
    MON --> PG
    W1 -->|FOR UPDATE SKIP LOCKED| PG
    SCH --> PG
    SCH -.->|pg_try_advisory_lock| PG
```

## Edge components

**Service registry** (`app/registry.py`, :8761) — the Eureka analogue.
Services register on startup, renew a 30s lease with heartbeats, and are
lazily evicted when the lease expires — so a crashed instance drops out of
routing automatically. State is deliberately in-memory: the registry must not
depend on the database it helps other services reach.

**API gateway** (`app/gateway.py`, :8000) — the single entry point.
Longest-prefix routing table maps paths to owning services; instances are
resolved through the registry with a 5s local cache and round-robined
(client-side load balancing, like Spring Cloud Gateway + Ribbon). Connect
failures invalidate the cache and retry the next healthy instance — verified:
10/10 requests succeed while a job-service replica is killed mid-traffic.
Also relays the dashboard's WebSocket to the monitoring service.

**Discovery client** (`app/discovery.py`) — shared by every service:
registration + lease renewal in a daemon thread (with re-registration if the
registry restarts and loses the lease), and consumer-side resolution with
stale-if-error fallback.

## Domain services

All three are built from the same codebase by `app/microservice.py`
(`SERVICE_NAME` selects the router set) — a modular monolith deployed as
microservices:

| Service | Owns |
|---|---|
| `identity-service` | auth, users, organizations, members, projects |
| `job-service` | retry policies, queues, jobs, DLQ, worker listing (replicated ×2) |
| `monitoring-service` | system stats, live WebSocket feed |

`app/main.py` still assembles all routers in one process — used by the test
suite and for quick local development.

**Worker service** (`app/worker.py`) — a separate deployable. Loop:

1. Compute spare capacity (`concurrency − in-flight`).
2. Atomically claim up to that many due jobs in **one UPDATE with a
   `FOR UPDATE SKIP LOCKED` subquery** — competing workers skip locked rows
   instead of blocking, so N workers drain queues in parallel with zero
   double-claims.
3. Execute each job in a thread pool; record a `job_executions` row per attempt
   and stream log lines to `job_logs`.
4. Heartbeat every 10s (updates `workers.last_heartbeat_at` + appends history).
5. On SIGTERM/SIGINT: stop claiming, finish in-flight jobs (DRAINING), mark
   OFFLINE, exit.

**Scheduler service** (`app/scheduler.py`) — the only singleton, made safe to
replicate via a **Postgres advisory lock**: every instance contends for
`pg_try_advisory_lock`; the winner runs, the rest idle as hot standbys and take
over if the winner's connection dies. Each 1s tick:

- promotes `SCHEDULED` jobs whose `run_at` arrived to `QUEUED`;
- materializes due cron templates into concrete jobs and advances `next_run_at`
  (`FOR UPDATE SKIP LOCKED` on templates for safety);
- **reaps dead workers**: any worker silent past the heartbeat deadline is
  marked `DEAD`, its open execution marked `LOST`, and its in-flight jobs sent
  through the normal retry/DLQ path (an interrupted run consumes an attempt so
  a crash-looping job cannot spin forever).

**Dashboard** — React SPA. Pages poll every 3–4s; the overview page receives
WebSocket pushes. Served by nginx in Docker, which also proxies `/api`.

## Job lifecycle

```mermaid
stateDiagram-v2
    [*] --> SCHEDULED: delayed / scheduled
    [*] --> QUEUED: immediate / batch / cron fire
    SCHEDULED --> QUEUED: scheduler promotes
    QUEUED --> CLAIMED: worker claims (atomic)
    CLAIMED --> RUNNING: execution starts
    RUNNING --> COMPLETED: handler returns
    RUNNING --> QUEUED: fails, attempts left (backoff delay)
    RUNNING --> DEAD_LETTER: attempts exhausted
    QUEUED --> CANCELLED: user cancels
    SCHEDULED --> CANCELLED: user cancels
    DEAD_LETTER --> QUEUED: manual requeue / retry
```

## Delivery semantics

The platform guarantees **at-least-once** execution: if a worker dies after
side effects but before recording completion, the job runs again. Exactly-once
is impossible without cooperation from the job's side effects, so instead:

- job **creation** is idempotent via `idempotency_key` (unique per queue);
- handlers are documented as needing to be idempotent;
- every attempt is recorded, so duplicates are visible and auditable.
