"""Job lifecycle transitions shared by the worker, the reaper, and the API.

State machine:
    SCHEDULED -> QUEUED -> CLAIMED -> RUNNING -> COMPLETED
                                          |-> FAILED -> QUEUED (retry, backoff)
                                          |-> FAILED -> DEAD_LETTER (attempts exhausted)
Any non-terminal state -> CANCELLED via the API.
DEAD_LETTER -> QUEUED via manual requeue (attempt counter reset).
"""
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models import (
    DeadLetterJob, ExecutionStatus, Job, JobExecution, JobLog, JobStatus,
    Queue, Worker,
)
from app.services.retry import compute_delay_ms


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def log(db: Session, job: Job, message: str, level: str = "INFO",
        execution_id: uuid.UUID | None = None) -> None:
    db.add(JobLog(job_id=job.id, execution_id=execution_id, level=level, message=message))


def start_execution(db: Session, job: Job, worker_id: uuid.UUID) -> JobExecution:
    job.status = JobStatus.RUNNING
    job.started_at = utcnow()
    execution = JobExecution(job_id=job.id, worker_id=worker_id, attempt=job.attempt)
    db.add(execution)
    db.flush()
    log(db, job, f"Attempt {job.attempt}/{job.max_attempts} started on worker {worker_id}",
        execution_id=execution.id)
    return execution


def complete_job(db: Session, job: Job, execution: JobExecution, result: dict | None) -> None:
    now = utcnow()
    execution.status = ExecutionStatus.SUCCESS
    execution.finished_at = now
    execution.duration_ms = (now - execution.started_at).total_seconds() * 1000
    job.status = JobStatus.COMPLETED
    job.finished_at = now
    job.result = result
    log(db, job, f"Completed in {execution.duration_ms:.0f}ms", execution_id=execution.id)


def fail_job(db: Session, job: Job, execution: JobExecution | None, error: str) -> None:
    """Record the failure, then either schedule a retry or dead-letter the job."""
    now = utcnow()
    if execution is not None:
        execution.status = ExecutionStatus.FAILED
        execution.finished_at = now
        execution.duration_ms = (now - execution.started_at).total_seconds() * 1000
        execution.error = error
    job.last_error = error

    if job.attempt < job.max_attempts:
        queue = db.get(Queue, job.queue_id)
        policy = queue.retry_policy if queue else None
        delay_ms = compute_delay_ms(policy, job.attempt)
        job.status = JobStatus.QUEUED
        job.run_at = now + timedelta(milliseconds=delay_ms)
        job.worker_id = None
        log(db, job,
            f"Attempt {job.attempt} failed: {error} — retrying in {delay_ms}ms",
            level="WARN", execution_id=execution.id if execution else None)
    else:
        job.status = JobStatus.DEAD_LETTER
        job.finished_at = now
        # A requeued job can die again — refresh its existing DLQ entry
        # instead of violating the unique job_id constraint.
        existing = db.query(DeadLetterJob).filter_by(job_id=job.id).first()
        if existing is not None:
            existing.error = error
            existing.attempts_made = job.attempt
            existing.created_at = now
            existing.requeued_at = None
        else:
            db.add(DeadLetterJob(job_id=job.id, queue_id=job.queue_id,
                                 error=error, attempts_made=job.attempt))
        log(db, job,
            f"All {job.max_attempts} attempts exhausted — moved to dead letter queue",
            level="ERROR", execution_id=execution.id if execution else None)


def requeue_dead_letter(db: Session, dlq_entry: DeadLetterJob) -> Job:
    job = db.get(Job, dlq_entry.job_id)
    job.status = JobStatus.QUEUED
    job.attempt = 0
    job.run_at = utcnow()
    job.last_error = None
    job.worker_id = None
    job.finished_at = None
    dlq_entry.requeued_at = utcnow()
    log(db, job, "Manually requeued from dead letter queue")
    return job


def reclaim_lost_jobs(db: Session, worker: Worker) -> int:
    """Return a dead/draining worker's in-flight jobs to the queue (at-least-once)."""
    lost = (
        db.query(Job)
        .filter(Job.worker_id == worker.id,
                Job.status.in_([JobStatus.CLAIMED, JobStatus.RUNNING]))
        .all()
    )
    for job in lost:
        open_exec = (
            db.query(JobExecution)
            .filter_by(job_id=job.id, attempt=job.attempt, status=ExecutionStatus.RUNNING)
            .first()
        )
        if open_exec is not None:
            open_exec.status = ExecutionStatus.LOST
            open_exec.finished_at = utcnow()
            open_exec.error = f"Worker {worker.name} died mid-execution"
        # The interrupted run consumed an attempt; route through normal
        # retry/DLQ handling so a crash-looping job can't spin forever.
        fail_job(db, job, None, f"Worker {worker.name} lost (missed heartbeats)")
    return len(lost)
