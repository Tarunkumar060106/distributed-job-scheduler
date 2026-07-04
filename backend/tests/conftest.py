"""Test fixtures. Tests run against a dedicated `scheduler_test` database so
they never interfere with dev data or a running worker."""
import os

import pytest
from sqlalchemy import create_engine, text

TEST_DB_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+psycopg2://scheduler:scheduler@localhost:5433/scheduler_test",
)
os.environ["DATABASE_URL"] = TEST_DB_URL

# Import AFTER the env override so the app engine points at the test DB.
from app.config import settings  # noqa: E402
from app.db import Base, SessionLocal, engine  # noqa: E402


def _ensure_test_database():
    admin_url = TEST_DB_URL.rsplit("/", 1)[0] + "/scheduler"
    admin = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        exists = conn.execute(text(
            "SELECT 1 FROM pg_database WHERE datname = 'scheduler_test'")).scalar()
        if not exists:
            conn.execute(text("CREATE DATABASE scheduler_test"))
    admin.dispose()


@pytest.fixture(scope="session", autouse=True)
def database():
    assert settings.database_url == TEST_DB_URL
    _ensure_test_database()
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield


@pytest.fixture()
def db(database):
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture()
def client(database):
    from fastapi.testclient import TestClient

    from app.main import app
    return TestClient(app)


@pytest.fixture()
def auth_client(client):
    """Client authenticated as a fresh user with an owned org + project + queue."""
    import uuid as _uuid
    email = f"user-{_uuid.uuid4().hex[:8]}@test.com"
    r = client.post("/api/auth/register", json={
        "email": email, "password": "password123", "name": "Test User"})
    assert r.status_code == 201, r.text
    client.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
    org = client.get("/api/orgs").json()[0]
    project = client.post(f"/api/orgs/{org['id']}/projects",
                          json={"name": f"proj-{_uuid.uuid4().hex[:6]}"}).json()
    queue = client.post(f"/api/projects/{project['id']}/queues",
                        json={"name": "default", "max_concurrency": 10}).json()
    client.ctx = {"org": org, "project": project, "queue": queue}  # type: ignore[attr-defined]
    return client
