import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import DeadLetterJob, Job, JobStatus, OrgRole, User, Worker
from app.routers.deps import get_queue_checked
from app.schemas import CurrentJob, DeadLetterOut, JobOut, WorkerOut
from app.security import get_current_user
from app.services.lifecycle import requeue_dead_letter

router = APIRouter(prefix="/api", tags=["workers"])


@router.get("/workers", response_model=list[WorkerOut])
def list_workers(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Worker fleet with each worker's currently claimed/running jobs."""
    workers = db.query(Worker).order_by(Worker.started_at.desc()).limit(100).all()
    in_flight = (
        db.query(Job)
        .filter(Job.worker_id.in_([w.id for w in workers]),
                Job.status.in_([JobStatus.CLAIMED, JobStatus.RUNNING]))
        .all()
    ) if workers else []
    by_worker: dict = {}
    for job in in_flight:
        by_worker.setdefault(job.worker_id, []).append(CurrentJob(
            job_id=job.id, task=job.task, status=job.status,
            started_at=job.started_at))
    result = []
    for w in workers:
        out = WorkerOut.model_validate(w)
        out.current_jobs = by_worker.get(w.id, [])
        result.append(out)
    return result


@router.get("/queues/{queue_id}/dlq", response_model=list[DeadLetterOut])
def list_dlq(queue_id: uuid.UUID, user: User = Depends(get_current_user),
             db: Session = Depends(get_db)):
    get_queue_checked(db, user, queue_id)
    return (db.query(DeadLetterJob).filter_by(queue_id=queue_id)
            .order_by(DeadLetterJob.created_at.desc()).limit(200).all())


@router.post("/dlq/{entry_id}/requeue", response_model=JobOut)
def requeue(entry_id: uuid.UUID, user: User = Depends(get_current_user),
            db: Session = Depends(get_db)):
    entry = db.get(DeadLetterJob, entry_id)
    if entry is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "DLQ entry not found")
    get_queue_checked(db, user, entry.queue_id, OrgRole.MEMBER)
    if entry.requeued_at is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Entry already requeued")
    job = requeue_dead_letter(db, entry)
    db.commit()
    return job
