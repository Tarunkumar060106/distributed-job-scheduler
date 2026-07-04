"""Retry strategies, lifecycle transitions, and dead-letter behavior."""
import uuid

from app.models import (
    DeadLetterJob, Job, JobStatus, RetryPolicy, RetryStrategy,
)
from app.services.lifecycle import fail_job, requeue_dead_letter, start_execution
from app.services.retry import compute_delay_ms
from tests.test_claiming import enqueue, make_queue, make_worker


def policy(strategy, base=1000, cap=60_000, jitter=False):
    return RetryPolicy(id=uuid.uuid4(), project_id=uuid.uuid4(), name="p",
                       strategy=strategy, max_attempts=3,
                       base_delay_ms=base, max_delay_ms=cap, jitter=jitter)


def test_fixed_backoff():
    p = policy(RetryStrategy.FIXED)
    assert [compute_delay_ms(p, a) for a in (1, 2, 3)] == [1000, 1000, 1000]


def test_linear_backoff():
    p = policy(RetryStrategy.LINEAR)
    assert [compute_delay_ms(p, a) for a in (1, 2, 3)] == [1000, 2000, 3000]


def test_exponential_backoff_with_cap():
    p = policy(RetryStrategy.EXPONENTIAL, base=1000, cap=3000)
    assert [compute_delay_ms(p, a) for a in (1, 2, 3, 4)] == [1000, 2000, 3000, 3000]


def test_jitter_stays_within_bounds():
    p = policy(RetryStrategy.EXPONENTIAL, jitter=True)
    for attempt in range(1, 5):
        expected = min(1000 * 2 ** (attempt - 1), 60_000)
        for _ in range(20):
            delay = compute_delay_ms(p, attempt)
            assert expected // 2 <= delay <= expected


def test_failed_job_is_requeued_then_dead_lettered(db):
    queue = make_queue(db)
    job = enqueue(db, queue, n=1)[0]
    job.max_attempts = 2
    worker_id = make_worker(db)

    # attempt 1: fails -> requeued with a future run_at
    job.attempt = 1
    execution = start_execution(db, job, worker_id)
    fail_job(db, job, execution, "boom")
    db.commit()
    db.refresh(job)
    assert job.status == JobStatus.QUEUED
    assert job.last_error == "boom"

    # attempt 2 (final): fails -> dead letter
    job.attempt = 2
    execution = start_execution(db, job, worker_id)
    fail_job(db, job, execution, "boom again")
    db.commit()
    db.refresh(job)
    assert job.status == JobStatus.DEAD_LETTER
    entry = db.query(DeadLetterJob).filter_by(job_id=job.id).one()
    assert entry.attempts_made == 2
    assert len(job.executions) == 2

    # manual requeue resets the attempt counter
    requeue_dead_letter(db, entry)
    db.commit()
    db.refresh(job)
    assert job.status == JobStatus.QUEUED
    assert job.attempt == 0
    assert entry.requeued_at is not None


def test_requeued_job_can_dead_letter_again(db):
    """Regression: DLQ -> requeue -> fail again must update the existing DLQ
    entry, not violate the unique job_id constraint."""
    queue = make_queue(db)
    job = enqueue(db, queue, n=1)[0]
    job.max_attempts = 1
    job.attempt = 1
    fail_job(db, job, None, "first death")
    db.commit()

    entry = db.query(DeadLetterJob).filter_by(job_id=job.id).one()
    requeue_dead_letter(db, entry)
    db.commit()

    job.attempt = 1
    fail_job(db, job, None, "second death")
    db.commit()

    entries = db.query(DeadLetterJob).filter_by(job_id=job.id).all()
    assert len(entries) == 1
    assert entries[0].error == "second death"
    assert entries[0].requeued_at is None
