import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.db import Base, engine
from app.routers import auth, jobs, orgs, queues, stats, workers

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("scheduler.api")

app = FastAPI(
    title="Distributed Job Scheduler",
    description="Production-inspired distributed job scheduling platform. "
                "Auth via Bearer JWT from /api/auth/login.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # dashboard runs on a different port in dev/compose
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup():
    # Schema is created idempotently at startup; a real deployment would use
    # Alembic migrations (documented trade-off in docs/design-decisions.md).
    Base.metadata.create_all(bind=engine)
    logger.info("Schema ensured, API ready")


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={
        "error": "internal_server_error",
        "detail": "An unexpected error occurred",
    })


@app.get("/api/health")
def health():
    return {"status": "ok"}


for r in (auth.router, orgs.router, queues.router, jobs.router,
          workers.router, stats.router):
    app.include_router(r)
