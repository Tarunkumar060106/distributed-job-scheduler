"""API contract tests: auth, validation, idempotency, pagination, RBAC."""
import uuid


def test_endpoints_require_auth(client):
    assert client.get("/api/orgs").status_code == 401
    assert client.get("/api/workers").status_code == 401


def test_register_validates_password_length(client):
    r = client.post("/api/auth/register", json={
        "email": "short@test.com", "password": "short", "name": "S"})
    assert r.status_code == 422


def test_login_rejects_wrong_password(auth_client):
    r = auth_client.post("/api/auth/login", json={
        "email": "nobody@test.com", "password": "wrongpassword"})
    assert r.status_code == 401


def test_job_creation_and_detail(auth_client):
    qid = auth_client.ctx["queue"]["id"]
    r = auth_client.post(f"/api/queues/{qid}/jobs",
                         json={"task": "echo", "payload": {"k": "v"}})
    assert r.status_code == 201
    job = r.json()
    assert job["status"] == "QUEUED"
    detail = auth_client.get(f"/api/jobs/{job['id']}").json()
    assert detail["payload"] == {"k": "v"}


def test_delayed_job_requires_delay(auth_client):
    qid = auth_client.ctx["queue"]["id"]
    r = auth_client.post(f"/api/queues/{qid}/jobs",
                         json={"task": "echo", "type": "DELAYED"})
    assert r.status_code == 422


def test_idempotency_key_dedupes(auth_client):
    qid = auth_client.ctx["queue"]["id"]
    body = {"task": "echo", "idempotency_key": "order-42"}
    first = auth_client.post(f"/api/queues/{qid}/jobs", json=body).json()
    second = auth_client.post(f"/api/queues/{qid}/jobs", json=body).json()
    assert first["id"] == second["id"]


def test_batch_creates_linked_jobs(auth_client):
    qid = auth_client.ctx["queue"]["id"]
    r = auth_client.post(f"/api/queues/{qid}/jobs/batch", json={
        "jobs": [{"task": "echo"} for _ in range(3)]})
    assert r.status_code == 201
    jobs = r.json()
    assert len({j["batch_id"] for j in jobs}) == 1


def test_recurring_requires_valid_cron(auth_client):
    qid = auth_client.ctx["queue"]["id"]
    bad = auth_client.post(f"/api/queues/{qid}/scheduled-jobs",
                           json={"task": "echo", "cron_expr": "not a cron"})
    assert bad.status_code == 422
    good = auth_client.post(f"/api/queues/{qid}/scheduled-jobs",
                            json={"task": "echo", "cron_expr": "*/5 * * * *"})
    assert good.status_code == 201


def test_pagination_and_filtering(auth_client):
    qid = auth_client.ctx["queue"]["id"]
    for _ in range(7):
        auth_client.post(f"/api/queues/{qid}/jobs", json={"task": "sleep"})
    page = auth_client.get(f"/api/queues/{qid}/jobs?page=1&page_size=5&task=sleep").json()
    assert page["total"] == 7
    assert len(page["items"]) == 5
    page2 = auth_client.get(f"/api/queues/{qid}/jobs?page=2&page_size=5&task=sleep").json()
    assert len(page2["items"]) == 2


def test_cancel_only_pending_jobs(auth_client):
    qid = auth_client.ctx["queue"]["id"]
    job = auth_client.post(f"/api/queues/{qid}/jobs", json={"task": "echo"}).json()
    assert auth_client.post(f"/api/jobs/{job['id']}/cancel").status_code == 200
    # Cancelling twice conflicts.
    assert auth_client.post(f"/api/jobs/{job['id']}/cancel").status_code == 409


def test_pause_blocks_and_resume_restores(auth_client):
    qid = auth_client.ctx["queue"]["id"]
    assert auth_client.post(f"/api/queues/{qid}/pause").json()["paused"] is True
    assert auth_client.post(f"/api/queues/{qid}/resume").json()["paused"] is False


def test_rbac_viewer_cannot_mutate(auth_client, client):
    """A VIEWER member can read but cannot create queues (403)."""
    org_id = auth_client.ctx["org"]["id"]
    project_id = auth_client.ctx["project"]["id"]

    viewer_email = f"viewer-{uuid.uuid4().hex[:8]}@test.com"
    r = client.post("/api/auth/register", json={
        "email": viewer_email, "password": "password123", "name": "Viewer"})
    viewer_token = r.json()["access_token"]
    auth_client.post(f"/api/orgs/{org_id}/members",
                     json={"email": viewer_email, "role": "VIEWER"})

    viewer_headers = {"Authorization": f"Bearer {viewer_token}"}
    read = client.get(f"/api/projects/{project_id}/queues", headers=viewer_headers)
    assert read.status_code == 200
    write = client.post(f"/api/projects/{project_id}/queues",
                        json={"name": "hacked"}, headers=viewer_headers)
    assert write.status_code == 403


def test_outsider_cannot_access_foreign_project(auth_client, client):
    project_id = auth_client.ctx["project"]["id"]
    r = client.post("/api/auth/register", json={
        "email": f"outsider-{uuid.uuid4().hex[:8]}@test.com",
        "password": "password123", "name": "Outsider"})
    headers = {"Authorization": f"Bearer {r.json()['access_token']}"}
    assert client.get(f"/api/projects/{project_id}/queues",
                      headers=headers).status_code == 403
