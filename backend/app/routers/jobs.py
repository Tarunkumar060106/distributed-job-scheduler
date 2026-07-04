import uuid
from datetime import datetime, timedelta, timezone

from croniter import croniter
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import (
    Job, JobLog, JobStatus, JobType, OrgRole, Queue, ScheduledJob, User,
)
from app.routers.deps import get_queue_checked
from app.schemas import (
    BatchJobCreate, JobCreate, JobDetailOut, JobLogOut, JobOut, Page,
    ScheduledJobOut,
)
from app.security import get_current_user

router = APIRouter(prefix="/api", tags=["jobs"])


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def build_job(queue: Queue, body: JobCreate, batch_id: uuid.UUID | None = None) -> Job:
    run_at = utcnow()
    status_ = JobStatus.QUEUED
    if body.type == JobType.DELAYED:
        if body.delay_seconds is None and body.run_at is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                "DELAYED jobs need delay_seconds or run_at")
        run_at = body.run_at or utcnow() + timedelta(seconds=body.delay_seconds)
        status_ = JobStatus.SCHEDULED
    elif body.type == JobType.SCHEDULED:
        if body.run_at is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                "SCHEDULED jobs need run_at")
        run_at = body.run_at
        status_ = JobStatus.SCHEDULED

    max_attempts = queue.retry_policy.max_attempts if queue.retry_policy else 3
    return Job(
        queue_id=queue.id, type=body.type, task=body.task, payload=body.payload,
        status=status_, run_at=run_at, timeout_s=body.timeout_s,
        priority=body.priority if body.priority is not None else queue.default_priority,
        max_attempts=max_attempts, idempotency_key=body.idempotency_key,
        batch_id=batch_id,
    )


@router.post("/queues/{queue_id}/jobs", response_model=JobOut, status_code=201)
def create_job(queue_id: uuid.UUID, body: JobCreate,
               user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    queue = get_queue_checked(db, user, queue_id, OrgRole.MEMBER)

    if body.type == JobType.RECURRING:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Use POST /queues/{id}/scheduled-jobs for recurring jobs")
    if body.type == JobType.BATCH:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Use POST /queues/{id}/jobs/batch for batch jobs")

    # Idempotent creation: same key on the same queue returns the existing job.
    if body.idempotency_key:
        existing = db.query(Job).filter_by(
            queue_id=queue_id, idempotency_key=body.idempotency_key).first()
        if existing is not None:
            return existing

    job = build_job(queue, body)
    db.add(job)
    db.commit()
    return job


@router.post("/queues/{queue_id}/jobs/batch", response_model=list[JobOut], status_code=201)
def create_batch(queue_id: uuid.UUID, body: BatchJobCreate,
                 user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    queue = get_queue_checked(db, user, queue_id, OrgRole.MEMBER)
    batch_id = uuid.uuid4()
    jobs = []
    for item in body.jobs:
        if item.type in (JobType.RECURRING, JobType.BATCH):
            item.type = JobType.IMMEDIATE
        job = build_job(queue, item, batch_id=batch_id)
        job.type = JobType.BATCH
        db.add(job)
        jobs.append(job)
    db.commit()
    return jobs


@router.post("/queues/{queue_id}/scheduled-jobs", response_model=ScheduledJobOut,
             status_code=201)
def create_recurring(queue_id: uuid.UUID, body: JobCreate,
                     user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    queue = get_queue_checked(db, user, queue_id, OrgRole.MEMBER)
    if not body.cron_expr or not croniter.is_valid(body.cron_expr):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "A valid cron_expr is required for recurring jobs")
    next_run = croniter(body.cron_expr, utcnow()).get_next(datetime)
    scheduled = ScheduledJob(
        queue_id=queue.id, task=body.task, payload=body.payload,
        cron_expr=body.cron_expr, next_run_at=next_run,
        priority=body.priority if body.priority is not None else queue.default_priority,
    )
    db.add(scheduled)
    db.commit()
    return scheduled


@router.get("/queues/{queue_id}/scheduled-jobs", response_model=list[ScheduledJobOut])
def list_recurring(queue_id: uuid.UUID, user: User = Depends(get_current_user),
                   db: Session = Depends(get_db)):
    get_queue_checked(db, user, queue_id)
    return db.query(ScheduledJob).filter_by(queue_id=queue_id).all()


@router.patch("/scheduled-jobs/{scheduled_id}/toggle", response_model=ScheduledJobOut)
def toggle_recurring(scheduled_id: uuid.UUID, user: User = Depends(get_current_user),
                     db: Session = Depends(get_db)):
    scheduled = db.get(ScheduledJob, scheduled_id)
    if scheduled is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Scheduled job not found")
    get_queue_checked(db, user, scheduled.queue_id, OrgRole.MEMBER)
    scheduled.enabled = not scheduled.enabled
    db.commit()
    return scheduled


@router.get("/queues/{queue_id}/jobs", response_model=Page[JobOut])
def list_jobs(queue_id: uuid.UUID,
              status_filter: JobStatus | None = Query(default=None, alias="status"),
              task: str | None = None,
              page: int = Query(default=1, ge=1),
              page_size: int = Query(default=25, ge=1, le=200),
              user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    get_queue_checked(db, user, queue_id)
    q = db.query(Job).filter(Job.queue_id == queue_id)
    if status_filter is not None:
        q = q.filter(Job.status == status_filter)
    if task:
        q = q.filter(Job.task == task)
    total = q.count()
    items = (q.order_by(Job.created_at.desc())
             .offset((page - 1) * page_size).limit(page_size).all())
    return Page(items=items, total=total, page=page, page_size=page_size)


@router.get("/jobs/{job_id}", response_model=JobDetailOut)
def get_job(job_id: uuid.UUID, user: User = Depends(get_current_user),
            db: Session = Depends(get_db)):
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found")
    get_queue_checked(db, user, job.queue_id)
    return job


@router.get("/jobs/{job_id}/logs", response_model=list[JobLogOut])
def job_logs(job_id: uuid.UUID, user: User = Depends(get_current_user),
             db: Session = Depends(get_db)):
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found")
    get_queue_checked(db, user, job.queue_id)
    return (db.query(JobLog).filter_by(job_id=job_id)
            .order_by(JobLog.created_at).limit(500).all())


@router.post("/jobs/{job_id}/retry", response_model=JobOut)
def retry_job(job_id: uuid.UUID, user: User = Depends(get_current_user),
              db: Session = Depends(get_db)):
    """Manually retry a FAILED or DEAD_LETTER job (resets the attempt counter)."""
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found")
    get_queue_checked(db, user, job.queue_id, OrgRole.MEMBER)
    if job.status not in (JobStatus.FAILED, JobStatus.DEAD_LETTER, JobStatus.CANCELLED):
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"Cannot retry a job in status {job.status.value}")
    job.status = JobStatus.QUEUED
    job.attempt = 0
    job.run_at = utcnow()
    job.last_error = None
    job.worker_id = None
    job.finished_at = None
    db.add(JobLog(job_id=job.id, level="INFO", message=f"Manually retried by {user.email}"))
    db.commit()
    return job


@router.post("/jobs/{job_id}/cancel", response_model=JobOut)
def cancel_job(job_id: uuid.UUID, user: User = Depends(get_current_user),
               db: Session = Depends(get_db)):
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found")
    get_queue_checked(db, user, job.queue_id, OrgRole.MEMBER)
    if job.status not in (JobStatus.QUEUED, JobStatus.SCHEDULED):
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Only QUEUED or SCHEDULED jobs can be cancelled")
    job.status = JobStatus.CANCELLED
    job.finished_at = utcnow()
    db.add(JobLog(job_id=job.id, level="INFO", message=f"Cancelled by {user.email}"))
    db.commit()
    return job
