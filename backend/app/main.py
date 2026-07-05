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
    title="Distributed Job Scheduler (all-in-one)",
    description="All routers in one process — used by the test suite and for "
                "quick local development. Production deployment splits these "
                "across identity/job/monitoring services behind the gateway "
                "(see app/microservice.py and app/gateway.py).",
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
    from app.db import SessionLocal
    from app.seed import seed_demo_data
    db = SessionLocal()
    try:
        seed_demo_data(db)
    finally:
        db.close()
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
