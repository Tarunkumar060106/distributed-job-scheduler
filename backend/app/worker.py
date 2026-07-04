"""Worker service: polls queues, atomically claims jobs, executes them
concurrently in a thread pool, heartbeats, and drains gracefully on SIGTERM.

Run with:  python -m app.worker
Scale out by running more processes — claiming is race-free (SKIP LOCKED).
"""
import concurrent.futures
import logging
import os
import signal
import socket
import threading
import time
import uuid

from app.config import settings
from app.db import Base, SessionLocal, engine
from app.handlers import HANDLERS
from app.models import Job, Worker, WorkerHeartbeat, WorkerStatus
from app.services.claiming import claim_jobs
from app.services.lifecycle import complete_job, fail_job, start_execution

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("scheduler.worker")


class WorkerService:
    def __init__(self, concurrency: int | None = None):
        self.concurrency = concurrency or settings.worker_concurrency
        self.worker_id: uuid.UUID | None = None
        self.name = f"worker-{socket.gethostname()}-{os.getpid()}"
        self.shutdown_event = threading.Event()
        self.inflight: set[uuid.UUID] = set()
        self.inflight_lock = threading.Lock()

    # ---- registration & heartbeats ----

    def register(self) -> None:
        db = SessionLocal()
        try:
            worker = Worker(name=self.name, hostname=socket.gethostname(),
                            pid=os.getpid(), concurrency=self.concurrency)
            db.add(worker)
            db.commit()
            self.worker_id = worker.id
            logger.info("Registered as %s (%s)", self.name, worker.id)
        finally:
            db.close()

    def heartbeat_loop(self) -> None:
        while not self.shutdown_event.wait(settings.heartbeat_interval_s):
            self.send_heartbeat()

    def send_heartbeat(self) -> None:
        db = SessionLocal()
        try:
            worker = db.get(Worker, self.worker_id)
            if worker is None:
                return
            from app.services.lifecycle import utcnow
            worker.last_heartbeat_at = utcnow()
            if worker.status == WorkerStatus.DEAD:
                # We were presumed dead (e.g. long GC pause / network blip) but
                # we're alive — our jobs were already reclaimed, so just rejoin.
                worker.status = WorkerStatus.ONLINE
            with self.inflight_lock:
                running = len(self.inflight)
            db.add(WorkerHeartbeat(worker_id=self.worker_id, running_jobs=running))
            db.commit()
        except Exception:
            logger.exception("Heartbeat failed")
            db.rollback()
        finally:
            db.close()

    # ---- execution ----

    def execute(self, job_id: uuid.UUID) -> None:
        db = SessionLocal()
        try:
            job = db.get(Job, job_id)
            execution = start_execution(db, job, self.worker_id)
            db.commit()

            def log_fn(message: str, level: str = "INFO"):
                from app.services.lifecycle import log as log_line
                log_line(db, job, message, level=level, execution_id=execution.id)
                db.commit()

            handler = HANDLERS.get(job.task)
            try:
                if handler is None:
                    raise LookupError(f"No handler registered for task '{job.task}'")
                result = handler(job.payload or {}, log_fn)
                complete_job(db, job, execution, result)
                self._bump_counters(db, failed=False)
            except Exception as exc:  # noqa: BLE001 — any handler error is a job failure
                fail_job(db, job, execution, f"{type(exc).__name__}: {exc}")
                self._bump_counters(db, failed=True)
            db.commit()
        except Exception:
            logger.exception("Executor error for job %s", job_id)
            db.rollback()
        finally:
            db.close()
            with self.inflight_lock:
                self.inflight.discard(job_id)

    def _bump_counters(self, db, failed: bool) -> None:
        worker = db.get(Worker, self.worker_id)
        if worker is not None:
            worker.jobs_processed += 1
            if failed:
                worker.jobs_failed += 1

    # ---- main loop ----

    def run(self) -> None:
        Base.metadata.create_all(bind=engine)
        self.register()

        # Announce ourselves in the service registry (observability; workers
        # take no inbound traffic, so port is informational only).
        from app.discovery import ServiceRegistration
        registry_reg = ServiceRegistration(
            "worker-service", port=0,
            meta={"name": self.name, "concurrency": self.concurrency})
        registry_reg.start()

        heartbeat = threading.Thread(target=self.heartbeat_loop, daemon=True)
        heartbeat.start()

        def request_shutdown(signum, frame):
            logger.info("Signal %s received — draining (no new claims)...", signum)
            self.shutdown_event.set()

        signal.signal(signal.SIGINT, request_shutdown)
        signal.signal(signal.SIGTERM, request_shutdown)

        pool = concurrent.futures.ThreadPoolExecutor(max_workers=self.concurrency)
        logger.info("Polling with concurrency=%d", self.concurrency)

        while not self.shutdown_event.is_set():
            with self.inflight_lock:
                capacity = self.concurrency - len(self.inflight)
            claimed: list[uuid.UUID] = []
            if capacity > 0:
                db = SessionLocal()
                try:
                    claimed = claim_jobs(db, self.worker_id, capacity)
                except Exception:
                    logger.exception("Claim failed")
                    db.rollback()
                finally:
                    db.close()
            for job_id in claimed:
                with self.inflight_lock:
                    self.inflight.add(job_id)
                pool.submit(self.execute, job_id)
            if not claimed:
                time.sleep(settings.worker_poll_interval_s)

        # Graceful shutdown: stop claiming, finish in-flight jobs, deregister.
        self._set_status(WorkerStatus.DRAINING)
        logger.info("Waiting for %d in-flight job(s)...", len(self.inflight))
        pool.shutdown(wait=True)
        self._set_status(WorkerStatus.OFFLINE)
        logger.info("Shutdown complete")

    def _set_status(self, status: WorkerStatus) -> None:
        db = SessionLocal()
        try:
            worker = db.get(Worker, self.worker_id)
            if worker is not None:
                worker.status = status
                db.commit()
        finally:
            db.close()


if __name__ == "__main__":
    WorkerService().run()
