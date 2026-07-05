import uuid
from datetime import datetime
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models import (
    ExecutionStatus, JobStatus, JobType, OrgRole, RetryStrategy, WorkerStatus,
)

T = TypeVar("T")


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    page_size: int


# ---- auth ----
class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    name: str = Field(min_length=1, max_length=120)


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserOut(ORMModel):
    id: uuid.UUID
    email: str
    name: str


# ---- orgs / projects ----
class OrgCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class OrgOut(ORMModel):
    id: uuid.UUID
    name: str
    created_at: datetime


class MemberAdd(BaseModel):
    email: EmailStr
    role: OrgRole = OrgRole.MEMBER


class MemberOut(ORMModel):
    id: uuid.UUID
    user_id: uuid.UUID
    role: OrgRole


class MemberDetailOut(MemberOut):
    email: str
    name: str


class OrgDetailOut(OrgOut):
    my_role: OrgRole
    member_count: int
    project_count: int


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = None


class ProjectOut(ORMModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    name: str
    description: str | None
    created_at: datetime


# ---- retry policies / queues ----
class RetryPolicyCreate(BaseModel):
    name: str
    strategy: RetryStrategy = RetryStrategy.EXPONENTIAL
    max_attempts: int = Field(default=3, ge=1, le=50)
    base_delay_ms: int = Field(default=1000, ge=0)
    max_delay_ms: int = Field(default=60_000, ge=0)
    jitter: bool = True


class RetryPolicyOut(ORMModel):
    id: uuid.UUID
    name: str
    strategy: RetryStrategy
    max_attempts: int
    base_delay_ms: int
    max_delay_ms: int
    jitter: bool


class QueueCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    default_priority: int = 0
    max_concurrency: int = Field(default=10, ge=1, le=1000)
    retry_policy_id: uuid.UUID | None = None


class QueueUpdate(BaseModel):
    default_priority: int | None = None
    max_concurrency: int | None = Field(default=None, ge=1, le=1000)
    retry_policy_id: uuid.UUID | None = None


class QueueOut(ORMModel):
    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    default_priority: int
    max_concurrency: int
    paused: bool
    retry_policy_id: uuid.UUID | None
    created_at: datetime


class QueueStats(BaseModel):
    queue_id: uuid.UUID
    counts: dict[str, int]
    throughput_last_hour: int
    avg_duration_ms: float | None
    failure_rate: float


# ---- jobs ----
class JobCreate(BaseModel):
    task: str = Field(min_length=1, max_length=120)
    payload: dict[str, Any] = {}
    type: JobType = JobType.IMMEDIATE
    priority: int | None = None
    run_at: datetime | None = None          # DELAYED / SCHEDULED
    delay_seconds: int | None = Field(default=None, ge=0)  # DELAYED convenience
    cron_expr: str | None = None            # RECURRING
    idempotency_key: str | None = None
    timeout_s: int = Field(default=300, ge=1, le=3600)


class BatchJobCreate(BaseModel):
    jobs: list[JobCreate] = Field(min_length=1, max_length=1000)


class JobOut(ORMModel):
    id: uuid.UUID
    queue_id: uuid.UUID
    type: JobType
    task: str
    payload: dict
    status: JobStatus
    priority: int
    run_at: datetime
    attempt: int
    max_attempts: int
    idempotency_key: str | None
    batch_id: uuid.UUID | None
    worker_id: uuid.UUID | None
    worker_name: str | None = None
    result: dict | None
    last_error: str | None
    created_at: datetime
    claimed_at: datetime | None
    started_at: datetime | None
    finished_at: datetime | None


class JobLogOut(ORMModel):
    id: int
    level: str
    message: str
    created_at: datetime


class ExecutionOut(ORMModel):
    id: uuid.UUID
    worker_id: uuid.UUID | None
    worker_name: str | None = None
    attempt: int
    status: ExecutionStatus
    started_at: datetime
    finished_at: datetime | None
    duration_ms: float | None
    error: str | None


class JobDetailOut(JobOut):
    executions: list[ExecutionOut] = []


class ScheduledJobOut(ORMModel):
    id: uuid.UUID
    queue_id: uuid.UUID
    task: str
    cron_expr: str
    enabled: bool
    next_run_at: datetime
    last_enqueued_at: datetime | None


# ---- workers / dlq ----
class CurrentJob(BaseModel):
    job_id: uuid.UUID
    task: str
    status: JobStatus
    started_at: datetime | None


class WorkerOut(ORMModel):
    id: uuid.UUID
    name: str
    hostname: str
    pid: int
    concurrency: int
    status: WorkerStatus
    started_at: datetime
    last_heartbeat_at: datetime
    jobs_processed: int
    jobs_failed: int
    current_jobs: list[CurrentJob] = []


class DeadLetterOut(ORMModel):
    id: uuid.UUID
    job_id: uuid.UUID
    queue_id: uuid.UUID
    error: str | None
    attempts_made: int
    created_at: datetime
    requeued_at: datetime | None
