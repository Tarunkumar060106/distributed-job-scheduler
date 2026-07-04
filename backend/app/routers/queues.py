import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import (
    Job, JobExecution, JobStatus, OrgRole, Queue, RetryPolicy, User,
)
from app.routers.deps import get_project_checked, get_queue_checked
from app.schemas import (
    QueueCreate, QueueOut, QueueStats, QueueUpdate, RetryPolicyCreate, RetryPolicyOut,
)
from app.security import get_current_user

router = APIRouter(prefix="/api", tags=["queues"])


@router.post("/projects/{project_id}/retry-policies", response_model=RetryPolicyOut,
             status_code=201)
def create_retry_policy(project_id: uuid.UUID, body: RetryPolicyCreate,
                        user: User = Depends(get_current_user),
                        db: Session = Depends(get_db)):
    get_project_checked(db, user, project_id, OrgRole.ADMIN)
    policy = RetryPolicy(project_id=project_id, **body.model_dump())
    db.add(policy)
    db.commit()
    return policy


@router.get("/projects/{project_id}/retry-policies", response_model=list[RetryPolicyOut])
def list_retry_policies(project_id: uuid.UUID, user: User = Depends(get_current_user),
                        db: Session = Depends(get_db)):
    get_project_checked(db, user, project_id)
    return db.query(RetryPolicy).filter_by(project_id=project_id).all()


@router.post("/projects/{project_id}/queues", response_model=QueueOut, status_code=201)
def create_queue(project_id: uuid.UUID, body: QueueCreate,
                 user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    get_project_checked(db, user, project_id, OrgRole.ADMIN)
    if db.query(Queue).filter_by(project_id=project_id, name=body.name).first():
        raise HTTPException(status.HTTP_409_CONFLICT, "Queue name already exists in project")
    queue = Queue(project_id=project_id, **body.model_dump())
    db.add(queue)
    db.commit()
    return queue


@router.get("/projects/{project_id}/queues", response_model=list[QueueOut])
def list_queues(project_id: uuid.UUID, user: User = Depends(get_current_user),
                db: Session = Depends(get_db)):
    get_project_checked(db, user, project_id)
    return db.query(Queue).filter_by(project_id=project_id).all()


@router.get("/queues/{queue_id}", response_model=QueueOut)
def get_queue(queue_id: uuid.UUID, user: User = Depends(get_current_user),
              db: Session = Depends(get_db)):
    return get_queue_checked(db, user, queue_id)


@router.patch("/queues/{queue_id}", response_model=QueueOut)
def update_queue(queue_id: uuid.UUID, body: QueueUpdate,
                 user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    queue = get_queue_checked(db, user, queue_id, OrgRole.ADMIN)
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(queue, field, value)
    db.commit()
    return queue


@router.post("/queues/{queue_id}/pause", response_model=QueueOut)
def pause_queue(queue_id: uuid.UUID, user: User = Depends(get_current_user),
                db: Session = Depends(get_db)):
    queue = get_queue_checked(db, user, queue_id, OrgRole.MEMBER)
    queue.paused = True
    db.commit()
    return queue


@router.post("/queues/{queue_id}/resume", response_model=QueueOut)
def resume_queue(queue_id: uuid.UUID, user: User = Depends(get_current_user),
                 db: Session = Depends(get_db)):
    queue = get_queue_checked(db, user, queue_id, OrgRole.MEMBER)
    queue.paused = False
    db.commit()
    return queue


@router.get("/queues/{queue_id}/stats", response_model=QueueStats)
def queue_stats(queue_id: uuid.UUID, user: User = Depends(get_current_user),
                db: Session = Depends(get_db)):
    get_queue_checked(db, user, queue_id)
    counts = dict(
        db.query(Job.status, func.count(Job.id))
        .filter(Job.queue_id == queue_id)
        .group_by(Job.status)
        .all()
    )
    counts = {s.value: counts.get(s, 0) for s in JobStatus}

    hour_ago = datetime.now(timezone.utc) - timedelta(hours=1)
    completed_last_hour = (
        db.query(func.count(Job.id))
        .filter(Job.queue_id == queue_id, Job.status == JobStatus.COMPLETED,
                Job.finished_at >= hour_ago)
        .scalar()
    )
    avg_duration = (
        db.query(func.avg(JobExecution.duration_ms))
        .join(Job, Job.id == JobExecution.job_id)
        .filter(Job.queue_id == queue_id, JobExecution.duration_ms.isnot(None))
        .scalar()
    )
    finished = counts["COMPLETED"] + counts["DEAD_LETTER"]
    failure_rate = counts["DEAD_LETTER"] / finished if finished else 0.0
    return QueueStats(
        queue_id=queue_id, counts=counts, throughput_last_hour=completed_last_hour,
        avg_duration_ms=float(avg_duration) if avg_duration is not None else None,
        failure_rate=round(failure_rate, 4),
    )
