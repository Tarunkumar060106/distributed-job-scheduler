"""Service registry — a lightweight Eureka equivalent.

Services POST themselves here on startup and renew with heartbeats (like
Eureka's 30s renewals). Instances whose lease expires are evicted lazily on
read, so a crashed service disappears from routing within `LEASE_TTL_S`.

State is in-memory by design: a registry must not depend on the database it
helps other services find. Run replicas behind DNS for HA (each instance
re-registers with every replica it can reach on heartbeat).

Run with:  uvicorn app.registry:app --port 8761
"""
import threading
import time

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

LEASE_TTL_S = 30.0

app = FastAPI(title="Service Registry", version="1.0.0")

_lock = threading.Lock()
# {service_name: {instance_id: {"host":…, "port":…, "meta":…, "last_renewed": epoch}}}
_services: dict[str, dict[str, dict]] = {}


class RegistrationIn(BaseModel):
    service: str
    instance_id: str
    host: str
    port: int
    meta: dict = {}


def _healthy(entry: dict) -> bool:
    return (time.time() - entry["last_renewed"]) < LEASE_TTL_S


@app.post("/registry/register", status_code=201)
def register(body: RegistrationIn):
    with _lock:
        _services.setdefault(body.service, {})[body.instance_id] = {
            "host": body.host, "port": body.port, "meta": body.meta,
            "last_renewed": time.time(),
        }
    return {"status": "registered", "lease_ttl_s": LEASE_TTL_S}


@app.put("/registry/heartbeat/{service}/{instance_id}")
def heartbeat(service: str, instance_id: str):
    with _lock:
        entry = _services.get(service, {}).get(instance_id)
        if entry is None:
            # Lease expired and was evicted — the client must re-register.
            raise HTTPException(404, "Unknown instance; re-register")
        entry["last_renewed"] = time.time()
    return {"status": "renewed"}


@app.delete("/registry/deregister/{service}/{instance_id}")
def deregister(service: str, instance_id: str):
    with _lock:
        _services.get(service, {}).pop(instance_id, None)
    return {"status": "deregistered"}


@app.get("/registry/services/{service}")
def instances(service: str):
    with _lock:
        entries = _services.get(service, {})
        healthy = {iid: e for iid, e in entries.items() if _healthy(e)}
        # Lazy eviction of expired leases.
        _services[service] = healthy
        return [
            {"instance_id": iid, "host": e["host"], "port": e["port"], "meta": e["meta"]}
            for iid, e in healthy.items()
        ]


@app.get("/registry/services")
def catalog():
    with _lock:
        return {
            service: [
                {"instance_id": iid, "host": e["host"], "port": e["port"],
                 "meta": e["meta"], "healthy": _healthy(e)}
                for iid, e in entries.items()
            ]
            for service, entries in _services.items()
        }


@app.get("/registry/health")
def health():
    return {"status": "ok"}
