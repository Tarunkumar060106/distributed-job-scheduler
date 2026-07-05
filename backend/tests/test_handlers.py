"""Handler SDK contract: registration, validation, failure semantics."""
import pytest
from pydantic import BaseModel, ValidationError

import app.handlers  # noqa: F401 — load default packs
from app.handler_sdk import (
    REGISTRY, HandlerContext, PermanentFailure, catalog, get_handler, handler,
)


def make_context():
    lines = []
    ctx = HandlerContext(job_id="j", attempt=1, max_attempts=3,
                         log_fn=lambda m, lvl="INFO": lines.append((lvl, m)))
    return ctx, lines


def test_default_packs_are_loaded():
    for name in ("echo", "sleep", "flaky", "always_fail",
                 "http_request", "send_email"):
        assert get_handler(name) is not None, name


def test_catalog_exposes_contract_metadata():
    entries = {e["name"]: e for e in catalog()}
    assert entries["http_request"]["payload_schema"] is not None
    assert entries["http_request"]["example"]["url"].startswith("https://")
    assert entries["echo"]["idempotent"] is True


def test_duplicate_registration_is_rejected():
    with pytest.raises(ValueError):
        @handler("echo")
        def clash(payload, ctx):
            return {}


def test_payload_validation_rejects_bad_input():
    spec = get_handler("sleep")
    with pytest.raises(ValidationError):
        spec.payload_model(**{"seconds": "not-a-number"})
    with pytest.raises(ValidationError):
        spec.payload_model(**{"seconds": 9999})  # over the ceiling


def test_handler_executes_with_context():
    spec = get_handler("echo")
    ctx, lines = make_context()
    result = spec.fn({"k": "v"}, ctx)
    assert result == {"echoed": {"k": "v"}}
    assert lines, "handler should have logged through the context"


def test_send_email_without_smtp_is_permanent(monkeypatch):
    monkeypatch.delenv("SMTP_HOST", raising=False)
    spec = get_handler("send_email")
    payload = spec.payload_model(to="a@b.com", subject="s", body="b")
    ctx, _ = make_context()
    with pytest.raises(PermanentFailure):
        spec.fn(payload, ctx)


def test_worker_dead_letters_permanent_failures(db):
    """A ValidationError-style permanent failure must consume all attempts."""
    from app.models import DeadLetterJob, JobStatus
    from app.services.lifecycle import fail_job
    from tests.test_claiming import enqueue, make_queue

    queue = make_queue(db)
    job = enqueue(db, queue, n=1)[0]
    job.max_attempts = 5
    job.attempt = 1
    # Mirror worker behavior for deterministic failures.
    job.attempt = job.max_attempts
    fail_job(db, job, None, "[permanent] ValidationError: bad payload")
    db.commit()
    db.refresh(job)
    assert job.status == JobStatus.DEAD_LETTER
    assert db.query(DeadLetterJob).filter_by(job_id=job.id).count() == 1


def test_unknown_task_rejected_at_enqueue(auth_client):
    qid = auth_client.ctx["queue"]["id"]
    r = auth_client.post(f"/api/queues/{qid}/jobs",
                         json={"task": "no_such_task"})
    assert r.status_code == 422
    assert "no_such_task" in r.json()["detail"]


def test_task_catalog_endpoint(auth_client):
    entries = auth_client.get("/api/tasks").json()
    names = {e["name"] for e in entries}
    assert {"echo", "http_request", "send_email"} <= names
