"""Microservice entrypoint: builds a FastAPI app for one bounded context.

The domain code lives in one package (shared models/services) but deploys as
independent services — a "modular monolith, microservice deployment" layout.
Which service this process is comes from SERVICE_NAME:

    identity-service    auth, organizations, members, projects
    job-service         retry policies, queues, jobs, DLQ, workers listing
    monitoring-service  system stats + live WebSocket feed

Run with:  SERVICE_NAME=job-service uvicorn app.microservice:app --port 8002
"""
import logging
import os

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.db import Base, engine
from app.discovery import ServiceRegistration
from app.routers import auth, jobs, orgs, queues, stats, workers

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s %(message)s")

SERVICE_ROUTERS = {
    "identity-service": [auth.router, orgs.router],
    "job-service": [queues.router, jobs.router, workers.router],
    "monitoring-service": [stats.router],
}

service_name = os.environ.get("SERVICE_NAME", "job-service")
if service_name not in SERVICE_ROUTERS:
    raise RuntimeError(f"Unknown SERVICE_NAME '{service_name}'. "
                       f"Expected one of {sorted(SERVICE_ROUTERS)}")

logger = logging.getLogger(f"scheduler.{service_name}")

app = FastAPI(title=f"Job Scheduler — {service_name}", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"],
                   allow_methods=["*"], allow_headers=["*"])

registration = ServiceRegistration(
    service_name, port=int(os.environ.get("SERVICE_PORT", "8000")))


@app.on_event("startup")
def startup():
    Base.metadata.create_all(bind=engine)
    if service_name == "identity-service":
        from app.db import SessionLocal
        from app.seed import seed_demo_data
        db = SessionLocal()
        try:
            seed_demo_data(db)
        finally:
            db.close()
    registration.start()
    logger.info("%s ready", service_name)


@app.on_event("shutdown")
def shutdown():
    registration.stop()


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception):
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={
        "error": "internal_server_error", "detail": "An unexpected error occurred"})


@app.get("/api/health")
def health():
    return {"status": "ok", "component": service_name}


for router in SERVICE_ROUTERS[service_name]:
    app.include_router(router)
