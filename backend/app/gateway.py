"""API Gateway — the single entry point for all clients.

Responsibilities (mirrors Spring Cloud Gateway + Eureka client):
- route by path prefix to the owning microservice;
- discover healthy instances from the registry and round-robin across them;
- retry idempotent-safe failures (connect errors) on the next instance;
- proxy the WebSocket stream to the monitoring service;
- expose the service catalog for observability.

Run with:  uvicorn app.gateway:app --port 8000
"""
import logging

import httpx
import websockets
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response

from app.discovery import REGISTRY_URL, DiscoveryClient

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("scheduler.gateway")

app = FastAPI(title="Job Scheduler — API Gateway", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"],
                   allow_methods=["*"], allow_headers=["*"])

discovery = DiscoveryClient()

# Longest-prefix routing table: path prefix -> service name.
ROUTES: list[tuple[str, str]] = [
    ("/api/auth", "identity-service"),
    ("/api/orgs", "identity-service"),
    ("/api/stats", "monitoring-service"),
    ("/api/ws", "monitoring-service"),
    ("/api", "job-service"),  # queues, jobs, projects, workers, dlq
]

HOP_BY_HOP = {"host", "content-length", "connection", "keep-alive", "transfer-encoding"}


def route_for(path: str) -> str | None:
    for prefix, service in ROUTES:
        if path.startswith(prefix):
            return service
    return None


client = httpx.AsyncClient(timeout=30)


@app.get("/api/health")
async def health():
    return {"status": "ok", "component": "gateway"}


@app.get("/api/gateway/services")
async def catalog():
    """Live service catalog straight from the registry (for the dashboard)."""
    r = await client.get(f"{REGISTRY_URL}/registry/services")
    return r.json()


@app.websocket("/api/ws/overview")
async def ws_proxy(websocket: WebSocket):
    """Bidirectional relay to the monitoring service's WebSocket."""
    instance = discovery.pick("monitoring-service")
    if instance is None:
        await websocket.close(code=4503)
        return
    await websocket.accept()
    upstream_url = (f"ws://{instance['host']}:{instance['port']}"
                    f"/api/ws/overview?{websocket.url.query}")
    try:
        async with websockets.connect(upstream_url) as upstream:
            while True:
                message = await upstream.recv()
                await websocket.send_text(message)
    except (WebSocketDisconnect, websockets.ConnectionClosed):
        pass
    except Exception:
        logger.exception("WebSocket proxy error")
        await websocket.close(code=1011)


@app.api_route("/{path:path}",
               methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
async def proxy(request: Request, path: str):
    service = route_for(request.url.path)
    if service is None:
        return JSONResponse(status_code=404, content={"error": "no_route"})

    body = await request.body()
    headers = {k: v for k, v in request.headers.items() if k.lower() not in HOP_BY_HOP}

    # Try up to two healthy instances on connect failures.
    last_error: Exception | None = None
    for _ in range(2):
        instance = discovery.pick(service)
        if instance is None:
            return JSONResponse(status_code=503, content={
                "error": "service_unavailable",
                "detail": f"No healthy instances of {service} registered",
            })
        target = f"http://{instance['host']}:{instance['port']}{request.url.path}"
        try:
            upstream = await client.request(
                request.method, target, params=request.query_params,
                content=body, headers=headers)
            return Response(
                content=upstream.content, status_code=upstream.status_code,
                headers={k: v for k, v in upstream.headers.items()
                         if k.lower() not in HOP_BY_HOP},
            )
        except httpx.ConnectError as exc:
            logger.warning("Instance %s unreachable, trying next", instance["instance_id"])
            discovery.invalidate(service)
            last_error = exc
    return JSONResponse(status_code=502, content={
        "error": "bad_gateway", "detail": f"{service} unreachable: {last_error}"})
