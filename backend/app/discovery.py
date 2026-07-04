"""Registry client: registration, lease renewal, and client-side discovery.

Mirrors the Netflix Eureka client model:
- register on startup, renew on an interval, deregister on clean shutdown;
- consumers resolve a service to its healthy instances and round-robin
  across them, with a short local cache so the registry isn't on the hot path.
"""
import atexit
import logging
import os
import socket
import threading
import time
import uuid

import httpx

logger = logging.getLogger("scheduler.discovery")

REGISTRY_URL = os.environ.get("REGISTRY_URL", "")
HEARTBEAT_INTERVAL_S = 10.0
CACHE_TTL_S = 5.0


def enabled() -> bool:
    return bool(REGISTRY_URL)


class ServiceRegistration:
    """Registers this process and keeps its lease alive in a daemon thread."""

    def __init__(self, service: str, port: int, meta: dict | None = None):
        self.service = service
        self.port = port
        self.meta = meta or {}
        self.host = os.environ.get("SERVICE_HOST", socket.gethostname())
        self.instance_id = f"{self.host}:{port}:{uuid.uuid4().hex[:6]}"
        self._stop = threading.Event()

    def start(self) -> None:
        if not enabled():
            logger.info("REGISTRY_URL not set — discovery disabled")
            return
        self._register()
        threading.Thread(target=self._renew_loop, daemon=True).start()
        atexit.register(self.stop)

    def _register(self) -> None:
        for attempt in range(10):
            try:
                httpx.post(f"{REGISTRY_URL}/registry/register", json={
                    "service": self.service, "instance_id": self.instance_id,
                    "host": self.host, "port": self.port, "meta": self.meta,
                }, timeout=5)
                logger.info("Registered %s as %s", self.service, self.instance_id)
                return
            except httpx.HTTPError:
                logger.warning("Registry unreachable (attempt %d), retrying", attempt + 1)
                time.sleep(min(2 ** attempt, 15))
        logger.error("Could not register with registry at %s", REGISTRY_URL)

    def _renew_loop(self) -> None:
        while not self._stop.wait(HEARTBEAT_INTERVAL_S):
            try:
                r = httpx.put(
                    f"{REGISTRY_URL}/registry/heartbeat/{self.service}/{self.instance_id}",
                    timeout=5)
                if r.status_code == 404:  # lease evicted (e.g. registry restarted)
                    self._register()
            except httpx.HTTPError:
                logger.warning("Heartbeat to registry failed")

    def stop(self) -> None:
        self._stop.set()
        if enabled():
            try:
                httpx.delete(
                    f"{REGISTRY_URL}/registry/deregister/{self.service}/{self.instance_id}",
                    timeout=5)
            except httpx.HTTPError:
                pass


class DiscoveryClient:
    """Resolve service names to instances; round-robin with a short cache."""

    def __init__(self):
        self._cache: dict[str, tuple[float, list[dict]]] = {}
        self._rr: dict[str, int] = {}
        self._lock = threading.Lock()

    def instances(self, service: str) -> list[dict]:
        with self._lock:
            cached = self._cache.get(service)
            if cached and time.time() - cached[0] < CACHE_TTL_S:
                return cached[1]
        try:
            r = httpx.get(f"{REGISTRY_URL}/registry/services/{service}", timeout=5)
            found = r.json() if r.status_code == 200 else []
        except httpx.HTTPError:
            found = cached[1] if cached else []  # stale-if-error
        with self._lock:
            self._cache[service] = (time.time(), found)
        return found

    def pick(self, service: str) -> dict | None:
        found = self.instances(service)
        if not found:
            return None
        with self._lock:
            index = self._rr.get(service, 0)
            self._rr[service] = index + 1
        return found[index % len(found)]

    def invalidate(self, service: str) -> None:
        with self._lock:
            self._cache.pop(service, None)
