"""The core reliability guarantee: concurrent workers never double-claim."""
import threading
import uuid

from app.db import SessionLocal
from app.models import (
    Job, JobStatus, Organization, Project, Queue, User, Worker,
)
from app.services.claiming import claim_jobs


import pytest
from sqlalchemy import text


@pytest.fixture(autouse=True)
def clean_jobs(db):
    """Claiming is global across queues, so these tests need an empty job table."""
    db.execute(text("DELETE FROM jobs"))
    db.commit()
    yield


def make_worker(db) -> uuid.UUID:
    worker = Worker(name=f"w-{uuid.uuid4().hex[:6]}", hostname="test", pid=0)
    db.add(worker)
    db.commit()
    return worker.id


def make_queue(db, max_concurrency=100, paused=False) -> Queue:
    user = User(email=f"c-{uuid.uuid4().hex[:8]}@t.com", password_hash="x", name="c")
    org = Organization(name="claim-org")
    db.add_all([user, org])
    db.flush()
    project = Project(organization_id=org.id, name=f"p-{uuid.uuid4().hex[:6]}")
    db.add(project)
    db.flush()
    queue = Queue(project_id=project.id, name=f"q-{uuid.uuid4().hex[:6]}",
                  max_concurrency=max_concurrency, paused=paused)
    db.add(queue)
    db.commit()
    return queue


def enqueue(db, queue, n=1, priority=0):
    jobs = [Job(queue_id=queue.id, task="echo", priority=priority) for _ in range(n)]
    db.add_all(jobs)
    db.commit()
    return jobs


def test_no_double_claim_under_concurrency(db):
    """10 threads race to claim 50 jobs; every job must be claimed exactly once."""
    queue = make_queue(db)
    enqueue(db, queue, n=50)

    results: list[list] = []
    lock = threading.Lock()
    worker_id = make_worker(db)

    def worker_claims():
        session = SessionLocal()
        try:
            claimed = claim_jobs(session, worker_id, limit=10)
            with lock:
                results.append(claimed)
        finally:
            session.close()

    threads = [threading.Thread(target=worker_claims) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    all_claimed = [job_id for chunk in results for job_id in chunk]
    assert len(all_claimed) == 50
    assert len(set(all_claimed)) == 50, "a job was claimed by two workers!"


def test_paused_queue_is_not_claimed(db):
    queue = make_queue(db, paused=True)
    enqueue(db, queue, n=3)
    assert claim_jobs(db, make_worker(db), limit=10) == []


def test_max_concurrency_is_respected(db):
    queue = make_queue(db, max_concurrency=2)
    enqueue(db, queue, n=10)
    first = claim_jobs(db, make_worker(db), limit=10)
    assert len(first) == 2
    # With 2 jobs in CLAIMED, the queue is at its limit; nothing more.
    assert claim_jobs(db, make_worker(db), limit=10) == []


def test_priority_order(db):
    queue = make_queue(db)
    low = enqueue(db, queue, n=1, priority=0)[0]
    high = enqueue(db, queue, n=1, priority=10)[0]
    claimed = claim_jobs(db, make_worker(db), limit=1)
    assert claimed == [high.id]
    db.expire_all()
    assert db.get(Job, low.id).status == JobStatus.QUEUED


def test_future_jobs_are_not_claimed(db):
    from datetime import datetime, timedelta, timezone
    queue = make_queue(db)
    job = Job(queue_id=queue.id, task="echo",
              run_at=datetime.now(timezone.utc) + timedelta(hours=1))
    db.add(job)
    db.commit()
    assert claim_jobs(db, make_worker(db), limit=10) == []
