"""Atomic job claiming.

The core correctness guarantee of the system: two workers polling the same
queue can never claim the same job. Achieved with a single UPDATE wrapping a
`SELECT ... FOR UPDATE SKIP LOCKED` subquery:

- FOR UPDATE locks candidate rows inside the transaction.
- SKIP LOCKED makes competing workers skip rows another transaction holds,
  instead of blocking — so N workers drain a queue in parallel without contention.
- The UPDATE flips status to CLAIMED in the same statement, so there is no
  window between "selected" and "claimed".

Queue-level max_concurrency is enforced by only considering queues whose
current CLAIMED+RUNNING count is below their limit.
"""
import uuid

from sqlalchemy import text
from sqlalchemy.orm import Session

CLAIM_SQL = text("""
WITH ranked AS (
    -- Rank claimable jobs within each queue and compute the queue's remaining
    -- capacity, so a single claim batch cannot exceed max_concurrency.
    SELECT j.id,
           j.priority, j.run_at, j.created_at,
           row_number() OVER (
               PARTITION BY j.queue_id
               ORDER BY j.priority DESC, j.run_at ASC, j.created_at ASC
           ) AS rank_in_queue,
           q.max_concurrency - (
               SELECT count(*) FROM jobs r
               WHERE r.queue_id = q.id AND r.status IN ('CLAIMED', 'RUNNING')
           ) AS remaining_capacity
    FROM jobs j
    JOIN queues q ON q.id = j.queue_id
    WHERE j.status = 'QUEUED'
      AND j.run_at <= now()
      AND q.paused = false
)
UPDATE jobs
SET status = 'CLAIMED',
    worker_id = :worker_id,
    claimed_at = now(),
    attempt = attempt + 1
WHERE id IN (
    SELECT j.id
    FROM jobs j
    JOIN ranked ON ranked.id = j.id
    -- Re-check status here: under READ COMMITTED, FOR UPDATE re-evaluates this
    -- predicate on the current row version, so a job claimed by a competing
    -- worker between the CTE snapshot and lock acquisition is dropped.
    WHERE j.status = 'QUEUED'
      AND j.run_at <= now()
      AND ranked.rank_in_queue <= ranked.remaining_capacity
    ORDER BY ranked.priority DESC, ranked.run_at ASC, ranked.created_at ASC
    LIMIT :limit
    FOR UPDATE OF j SKIP LOCKED
)
RETURNING id
""")


def claim_jobs(db: Session, worker_id: uuid.UUID, limit: int) -> list[uuid.UUID]:
    """Atomically claim up to `limit` due jobs. Commits the claim transaction."""
    if limit <= 0:
        return []
    rows = db.execute(CLAIM_SQL, {"worker_id": str(worker_id), "limit": limit}).fetchall()
    db.commit()
    return [row[0] for row in rows]
