"""Scheduler service: promotes due jobs, materializes cron jobs, reaps dead workers.

Run with:  python -m app.scheduler

Multiple instances can run for high availability, but only one is active at a
time: each loop iteration first takes a Postgres *advisory lock*
(pg_try_advisory_lock). If another instance holds it, this one idles as a hot
standby — a simple, correct form of distributed locking with no extra
infrastructure (the lock dies with the holder's connection).
"""
import logging
import signal
import threading
import time
from datetime import datetime, timedelta, timezone

from croniter import croniter
from sqlalchemy import text

from app.config import settings
from app.db import Base, SessionLocal, engine
from app.models import (
    Job, JobStatus, JobType, ScheduledJob, Worker, WorkerHeartbeat, WorkerStatus,
)
from app.services.lifecycle import reclaim_lost_jobs

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("scheduler.scheduler")

shutdown = threading.Event()


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def promote_due_jobs(db) -> int:
    """SCHEDULED jobs whose run_at has arrived become QUEUED (claimable)."""
    result = db.execute(text("""
        UPDATE jobs SET status = 'QUEUED'
        WHERE status = 'SCHEDULED' AND run_at <= now()
    """))
    return result.rowcount


def materialize_recurring(db) -> int:
    """For each due cron template, enqueue a concrete Job and advance next_run_at."""
    due = (
        db.query(ScheduledJob)
        .filter(ScheduledJob.enabled.is_(True), ScheduledJob.next_run_at <= utcnow())
        .with_for_update(skip_locked=True)
        .all()
    )
    for template in due:
        db.add(Job(
            queue_id=template.queue_id, type=JobType.RECURRING, task=template.task,
            payload=template.payload, status=JobStatus.QUEUED, run_at=utcnow(),
            priority=template.priority, scheduled_job_id=template.id,
        ))
        template.last_enqueued_at = utcnow()
        template.next_run_at = croniter(template.cron_expr, utcnow()).get_next(datetime)
    return len(due)


def reap_dead_workers(db) -> int:
    """Mark workers with stale heartbeats DEAD and requeue their in-flight jobs."""
    cutoff = utcnow() - timedelta(seconds=settings.heartbeat_dead_after_s)
    stale = (
        db.query(Worker)
        .filter(Worker.status.in_([WorkerStatus.ONLINE, WorkerStatus.DRAINING]),
                Worker.last_heartbeat_at < cutoff)
        .all()
    )
    reclaimed = 0
    for worker in stale:
        worker.status = WorkerStatus.DEAD
        n = reclaim_lost_jobs(db, worker)
        reclaimed += n
        logger.warning("Worker %s marked DEAD, %d job(s) reclaimed", worker.name, n)
    return reclaimed


def prune_heartbeats(db) -> None:
    """Keep only the last 24h of heartbeat history."""
    db.execute(text(
        "DELETE FROM worker_heartbeats WHERE created_at < now() - interval '24 hours'"))


def run() -> None:
    Base.metadata.create_all(bind=engine)

    from app.discovery import ServiceRegistration
    ServiceRegistration("scheduler-service", port=0).start()

    def request_shutdown(signum, frame):
        shutdown.set()

    signal.signal(signal.SIGINT, request_shutdown)
    signal.signal(signal.SIGTERM, request_shutdown)

    # Dedicated connection: the advisory lock is held as long as it lives.
    lock_conn = engine.connect()
    have_lock = False
    last_prune = time.monotonic()
    logger.info("Scheduler started (lock key %d)", settings.scheduler_lock_key)

    while not shutdown.is_set():
        try:
            if not have_lock:
                have_lock = lock_conn.execute(
                    text("SELECT pg_try_advisory_lock(:key)"),
                    {"key": settings.scheduler_lock_key},
                ).scalar()
                if not have_lock:
                    logger.info("Standby: another scheduler instance holds the lock")
                    shutdown.wait(5)
                    continue
                logger.info("Acquired scheduler advisory lock — active")

            db = SessionLocal()
            try:
                promoted = promote_due_jobs(db)
                enqueued = materialize_recurring(db)
                reclaimed = reap_dead_workers(db)
                if time.monotonic() - last_prune > 3600:
                    prune_heartbeats(db)
                    last_prune = time.monotonic()
                db.commit()
                if promoted or enqueued or reclaimed:
                    logger.info("promoted=%d cron_enqueued=%d reclaimed=%d",
                                promoted, enqueued, reclaimed)
            except Exception:
                logger.exception("Scheduler tick failed")
                db.rollback()
            finally:
                db.close()
        except Exception:
            # Lock connection died; reconnect and re-contend for the lock.
            logger.exception("Lock connection lost, reconnecting")
            try:
                lock_conn.close()
            except Exception:
                pass
            lock_conn = engine.connect()
            have_lock = False

        shutdown.wait(settings.scheduler_interval_s)

    lock_conn.close()
    logger.info("Scheduler stopped")


if __name__ == "__main__":
    run()
