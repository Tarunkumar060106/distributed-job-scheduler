"""Scheduler behaviors: promotion, cron materialization, dead-worker reaping."""
import uuid
from datetime import datetime, timedelta, timezone

from app.models import (
    Job, JobStatus, ScheduledJob, Worker, WorkerStatus,
)
from app.scheduler import materialize_recurring, promote_due_jobs, reap_dead_workers
from tests.test_claiming import make_queue


def test_due_scheduled_jobs_are_promoted(db):
    queue = make_queue(db)
    past = Job(queue_id=queue.id, task="echo", status=JobStatus.SCHEDULED,
               run_at=datetime.now(timezone.utc) - timedelta(seconds=5))
    future = Job(queue_id=queue.id, task="echo", status=JobStatus.SCHEDULED,
                 run_at=datetime.now(timezone.utc) + timedelta(hours=1))
    db.add_all([past, future])
    db.commit()

    promote_due_jobs(db)
    db.commit()
    db.expire_all()
    assert db.get(Job, past.id).status == JobStatus.QUEUED
    assert db.get(Job, future.id).status == JobStatus.SCHEDULED


def test_cron_materialization_advances_next_run(db):
    queue = make_queue(db)
    template = ScheduledJob(
        queue_id=queue.id, task="echo", payload={"cron": True},
        cron_expr="*/5 * * * *",
        next_run_at=datetime.now(timezone.utc) - timedelta(minutes=1),
    )
    db.add(template)
    db.commit()

    created = materialize_recurring(db)
    db.commit()
    assert created == 1
    db.refresh(template)
    assert template.next_run_at > datetime.now(timezone.utc)
    job = db.query(Job).filter_by(scheduled_job_id=template.id).one()
    assert job.status == JobStatus.QUEUED

    # Not due any more — no duplicate materialization.
    assert materialize_recurring(db) == 0


def test_dead_worker_jobs_are_reclaimed(db):
    queue = make_queue(db)
    worker = Worker(name="dead-worker", hostname="h", pid=1,
                    last_heartbeat_at=datetime.now(timezone.utc) - timedelta(minutes=10))
    db.add(worker)
    db.flush()
    job = Job(queue_id=queue.id, task="echo", status=JobStatus.RUNNING,
              worker_id=worker.id, attempt=1, max_attempts=3)
    db.add(job)
    db.commit()

    reclaimed = reap_dead_workers(db)
    db.commit()
    assert reclaimed == 1
    db.refresh(worker)
    db.refresh(job)
    assert worker.status == WorkerStatus.DEAD
    assert job.status == JobStatus.QUEUED  # attempt 1 of 3 -> retried
    assert job.worker_id is None
