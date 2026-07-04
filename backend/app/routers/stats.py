"""System-wide stats for the dashboard overview, plus WebSocket live updates."""
import asyncio
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import settings
from app.db import SessionLocal, get_db
from app.models import Job, JobStatus, User, Worker, WorkerStatus
from app.security import get_current_user

router = APIRouter(prefix="/api", tags=["stats"])


def collect_overview(db: Session) -> dict:
    now = datetime.now(timezone.utc)
    counts = dict(db.query(Job.status, func.count(Job.id)).group_by(Job.status).all())
    counts = {s.value: counts.get(s, 0) for s in JobStatus}

    workers = dict(
        db.query(Worker.status, func.count(Worker.id)).group_by(Worker.status).all())
    workers = {s.value: workers.get(s, 0) for s in WorkerStatus}

    # Per-minute completions for the last 30 minutes (throughput chart).
    window_start = now - timedelta(minutes=30)
    per_minute_rows = (
        db.query(func.date_trunc("minute", Job.finished_at).label("minute"),
                 func.count(Job.id))
        .filter(Job.status == JobStatus.COMPLETED, Job.finished_at >= window_start)
        .group_by("minute").order_by("minute").all()
    )
    throughput = [
        {"minute": row[0].isoformat(), "completed": row[1]} for row in per_minute_rows
    ]
    return {
        "generated_at": now.isoformat(),
        "job_counts": counts,
        "worker_counts": workers,
        "throughput": throughput,
    }


@router.get("/stats/overview")
def overview(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return collect_overview(db)


@router.websocket("/ws/overview")
async def overview_ws(websocket: WebSocket):
    """Pushes the overview snapshot every 2s. Auth via ?token= query param."""
    from app.security import jwt  # local import to avoid cycle at module load

    token = websocket.query_params.get("token")
    try:
        jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except Exception:
        await websocket.close(code=4401)
        return

    await websocket.accept()
    try:
        while True:
            snapshot = await asyncio.to_thread(_snapshot)
            await websocket.send_json(snapshot)
            await asyncio.sleep(2)
    except WebSocketDisconnect:
        pass


def _snapshot() -> dict:
    db = SessionLocal()
    try:
        return collect_overview(db)
    finally:
        db.close()
