"""Registry service and gateway routing rules."""
import time

from fastapi.testclient import TestClient

from app.gateway import route_for
from app.registry import app as registry_app


def make_client():
    return TestClient(registry_app)


def register(client, service="svc-a", instance_id="i-1", port=8000):
    return client.post("/registry/register", json={
        "service": service, "instance_id": instance_id,
        "host": "hostA", "port": port, "meta": {}})


def test_register_and_discover():
    client = make_client()
    assert register(client).status_code == 201
    found = client.get("/registry/services/svc-a").json()
    assert [i["instance_id"] for i in found] == ["i-1"]


def test_heartbeat_renews_and_unknown_instance_404s():
    client = make_client()
    register(client, service="svc-b", instance_id="i-2")
    assert client.put("/registry/heartbeat/svc-b/i-2").status_code == 200
    assert client.put("/registry/heartbeat/svc-b/ghost").status_code == 404


def test_expired_lease_is_evicted(monkeypatch):
    client = make_client()
    register(client, service="svc-c", instance_id="i-3")
    # Jump past the lease TTL instead of sleeping.
    import app.registry as registry_module
    real_time = time.time
    monkeypatch.setattr(registry_module.time, "time",
                        lambda: real_time() + registry_module.LEASE_TTL_S + 1)
    assert client.get("/registry/services/svc-c").json() == []


def test_deregister_removes_instance():
    client = make_client()
    register(client, service="svc-d", instance_id="i-4")
    client.delete("/registry/deregister/svc-d/i-4")
    assert client.get("/registry/services/svc-d").json() == []


def test_gateway_routing_table():
    assert route_for("/api/auth/login") == "identity-service"
    assert route_for("/api/orgs/123/projects") == "identity-service"
    assert route_for("/api/stats/overview") == "monitoring-service"
    assert route_for("/api/queues/1/jobs") == "job-service"
    assert route_for("/api/workers") == "job-service"
    assert route_for("/api/dlq/1/requeue") == "job-service"
    assert route_for("/not-api") is None
