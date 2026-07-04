# Design Decisions & Trade-offs

## 0. Microservices as a modular monolith deployment

The backend deploys as six independent processes — gateway, registry,
identity-service, job-service (replicated), monitoring-service, plus the
worker fleet and scheduler — but the domain code lives in one package, and
`SERVICE_NAME` selects which routers a process serves.

**Why this shape:**
- Each concern scales independently (job-service ×2 and worker ×2 in the
  default compose) and fails independently (killing a job-service replica
  loses zero requests — the gateway retries the other instance).
- One codebase means shared models, shared tests, and no premature contract
  duplication. Extracting a service into its own repo later is a `git mv`,
  not a rewrite. This is the migration path Shopify/Stripe-style modular
  monoliths take, run in reverse order.

**Why a custom registry instead of Consul/Eureka:** the registry pattern
(register, renew lease, evict on expiry, client-side LB) fits in ~90 lines of
FastAPI, adds zero infrastructure, and demonstrates the mechanism rather than
a vendor dependency. In production I'd swap it for Consul (or platform-native
discovery — Kubernetes Services make a registry redundant); only
`app/discovery.py` would change.

**Deliberate trade-off — shared database:** the services share one Postgres
with code-enforced ownership boundaries rather than database-per-service.
Splitting the DB requires either cross-service APIs for membership checks on
every request or event-carried replication of identity data — real costs that
buy nothing at this scale. The boundary that *matters* for correctness
(atomic job claiming) is already a single-owner concern of the claim SQL.

## 1. PostgreSQL as the queue (no Redis/RabbitMQ)

**Decision:** jobs live in Postgres and workers claim them with
`SELECT … FOR UPDATE SKIP LOCKED`.

**Why:** this is the same design used by production systems like Oban (Elixir)
and pg-boss (Node). One datastore means job state, tenant data, execution
history, and stats are transactionally consistent — a job can never be "in
Redis but not in the database" after a crash. `SKIP LOCKED` (Postgres 9.5+)
was added specifically for this pattern: competing claimers skip rows another
transaction holds instead of serializing behind them.

**Trade-off:** a dedicated broker wins on raw throughput (100k+ jobs/s) and
push-based delivery. At that scale the claim path is already isolated behind
`services/claiming.py`, so a broker could be introduced without touching the
rest of the system. Polling adds up to `poll_interval` (1s) of latency;
`LISTEN/NOTIFY` would close that gap and is the first thing I'd add.

## 2. The atomic claim

```sql
WITH ranked AS (
  SELECT j.id, row_number() OVER (PARTITION BY j.queue_id ORDER BY …) AS rank_in_queue,
         q.max_concurrency - (count of CLAIMED/RUNNING in q) AS remaining_capacity
  FROM jobs j JOIN queues q ON q.id = j.queue_id
  WHERE j.status = 'QUEUED' AND j.run_at <= now() AND NOT q.paused
)
UPDATE jobs SET status='CLAIMED', worker_id=…, attempt=attempt+1
WHERE id IN (
  SELECT j.id FROM jobs j JOIN ranked ON ranked.id = j.id
  WHERE j.status = 'QUEUED' AND ranked.rank_in_queue <= ranked.remaining_capacity
  ORDER BY … LIMIT :n
  FOR UPDATE OF j SKIP LOCKED
) RETURNING id;
```

Three subtleties worth calling out:

1. **Select-then-update in one statement** — there is no window between
   "found a job" and "claimed it" for another worker to slip into.
2. **The window function caps a single batch** at the queue's remaining
   capacity. A naive `WHERE running < max_concurrency` filter passes *all*
   candidates when the count snapshot is below the limit, so one claim of 10
   jobs on a `max_concurrency=2` queue would admit all 10. (Caught by a test.)
3. **The re-checked `status='QUEUED'` predicate in the locking subquery** —
   under READ COMMITTED, `FOR UPDATE` re-evaluates predicates on the current
   row version after acquiring the lock, so a row claimed and committed by a
   competitor between the CTE snapshot and lock acquisition is dropped.

Remaining race: two *simultaneous* batches can each see the same
`remaining_capacity` and jointly overshoot a queue's limit briefly.
`max_concurrency` is therefore a soft limit under extreme contention. Strict
enforcement needs a per-queue lock on every claim, which serializes the hot
path — the wrong trade for a limit whose purpose is protecting downstream
resources from sustained, not instantaneous, overload.

## 3. At-least-once delivery + idempotency (not exactly-once)

A worker can die after performing a job's side effects but before committing
`COMPLETED`. On reap, the job re-runs. We choose at-least-once because
exactly-once is not achievable without the job's side effects participating in
the transaction. Mitigations: `idempotency_key` dedupes job *creation*;
handlers are documented as idempotent; every attempt is recorded in
`job_executions` so duplicates are auditable. The crash-consumed attempt counts
toward `max_attempts`, so a job that kills workers cannot crash-loop the fleet.

## 4. Heartbeats + reaper for failure detection

Workers update `last_heartbeat_at` every 10s; the scheduler marks a worker
DEAD after 30s of silence and routes its in-flight jobs through the normal
failure path. Trade-offs: a long GC pause or network blip can cause a false
positive — the job re-runs (safe under at-least-once) and the worker rejoins on
its next successful heartbeat. Timeouts are config, not code.

## 5. Scheduler as active/standby singleton (advisory lock)

Cron materialization and job promotion must not run twice concurrently.
Rather than a leader-election dependency (ZooKeeper/etcd) or "just run one"
(no HA), every scheduler instance contends for `pg_try_advisory_lock` on a
dedicated connection. The lock dies with the holder's connection, so failover
is automatic and there is nothing extra to deploy. This is the project's
distributed-locking implementation — it uses the database we already trust.

## 6. Retry policy snapshot on the job

`max_attempts` is copied from the queue's policy at enqueue time. Editing a
policy affects only future jobs. See er-diagram.md → "Normalization".

## 7. `create_all` at startup instead of Alembic migrations

For a reviewable assignment, `Base.metadata.create_all` (idempotent) keeps
setup to one command. In production this becomes Alembic on day one — the
models are already declarative SQLAlchemy, so autogenerate works unchanged.

## 8. Polling dashboard + WebSocket overview

Job/queue pages poll every 3–4s (simple, stateless, cache-friendly); the
overview receives WebSocket pushes every 2s for the "live" feel. Pushing
per-job events over WS requires a pub/sub channel between workers and the API
(Postgres `LISTEN/NOTIFY` or Redis) — listed as future work; the polling
fallback the assignment explicitly allows covers those pages.

## 9. Threads, not asyncio, in the worker

Handlers are arbitrary user code — blocking I/O, CPU work, `time.sleep`. A
thread pool executes them without requiring every handler to be async-aware,
and claim batching amortizes DB round-trips. At 10x, workers become processes
managed by a supervisor, or the executor grows a process pool for CPU-bound
tasks.

## What I would do next at 10x scale

1. `LISTEN/NOTIFY` to eliminate poll latency.
2. Partition `jobs`/`job_logs` by month; archive terminal jobs.
3. UUIDv7 keys for index locality.
4. Materialized per-queue counters for stats.
5. Rate limiting per queue (token bucket in the claim SQL).
6. Workflow dependencies (`depends_on_job_id`, BLOCKED status, unblock on
   parent completion — the schema already accommodates it).
