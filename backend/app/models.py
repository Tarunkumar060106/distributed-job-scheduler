"""Relational schema for the distributed job scheduler.

Design notes (expanded in docs/design-decisions.md):
- UUID primary keys so IDs can be generated client/worker-side without coordination.
- jobs carries a snapshot of retry settings (max_attempts) so editing a queue's
  policy never changes semantics of jobs already in flight.
- The claim path is served by a partial composite index on
  (queue_id, status, run_at, priority) WHERE status = 'QUEUED'.
- Cascades: org -> project -> queue -> job -> executions/logs delete as a tree.
"""
import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    JSON, BigInteger, Boolean, DateTime, Enum, Float, ForeignKey, Index,
    Integer, String, Text, UniqueConstraint, text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def uuid_pk():
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


class OrgRole(str, enum.Enum):
    OWNER = "OWNER"
    ADMIN = "ADMIN"
    MEMBER = "MEMBER"
    VIEWER = "VIEWER"


class JobStatus(str, enum.Enum):
    SCHEDULED = "SCHEDULED"   # future run_at; promoted to QUEUED by the scheduler
    QUEUED = "QUEUED"         # ready to be claimed
    CLAIMED = "CLAIMED"       # atomically claimed by a worker, not yet started
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"         # transient: will be retried (requeued) or dead-lettered
    DEAD_LETTER = "DEAD_LETTER"
    CANCELLED = "CANCELLED"


class JobType(str, enum.Enum):
    IMMEDIATE = "IMMEDIATE"
    DELAYED = "DELAYED"
    SCHEDULED = "SCHEDULED"
    RECURRING = "RECURRING"
    BATCH = "BATCH"


class RetryStrategy(str, enum.Enum):
    FIXED = "FIXED"
    LINEAR = "LINEAR"
    EXPONENTIAL = "EXPONENTIAL"


class ExecutionStatus(str, enum.Enum):
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    LOST = "LOST"  # worker died mid-execution; job was reclaimed by the reaper


class WorkerStatus(str, enum.Enum):
    ONLINE = "ONLINE"
    DRAINING = "DRAINING"  # graceful shutdown in progress
    OFFLINE = "OFFLINE"    # clean exit
    DEAD = "DEAD"          # missed heartbeats; marked by the reaper


class User(Base):
    __tablename__ = "users"
    id: Mapped[uuid.UUID] = uuid_pk()
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    name: Mapped[str] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    memberships: Mapped[list["OrganizationMember"]] = relationship(back_populates="user")


class Organization(Base):
    __tablename__ = "organizations"
    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    members: Mapped[list["OrganizationMember"]] = relationship(
        back_populates="organization", cascade="all, delete-orphan")
    projects: Mapped[list["Project"]] = relationship(
        back_populates="organization", cascade="all, delete-orphan")


class OrganizationMember(Base):
    """RBAC: a user's role within an organization."""
    __tablename__ = "organization_members"
    __table_args__ = (UniqueConstraint("organization_id", "user_id"),)
    id: Mapped[uuid.UUID] = uuid_pk()
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True)
    role: Mapped[OrgRole] = mapped_column(Enum(OrgRole), default=OrgRole.MEMBER)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    user: Mapped["User"] = relationship(back_populates="memberships")
    organization: Mapped["Organization"] = relationship(back_populates="members")


class Project(Base):
    __tablename__ = "projects"
    __table_args__ = (UniqueConstraint("organization_id", "name"),)
    id: Mapped[uuid.UUID] = uuid_pk()
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    organization: Mapped["Organization"] = relationship(back_populates="projects")
    queues: Mapped[list["Queue"]] = relationship(
        back_populates="project", cascade="all, delete-orphan")


class RetryPolicy(Base):
    __tablename__ = "retry_policies"
    id: Mapped[uuid.UUID] = uuid_pk()
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    strategy: Mapped[RetryStrategy] = mapped_column(
        Enum(RetryStrategy), default=RetryStrategy.EXPONENTIAL)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    base_delay_ms: Mapped[int] = mapped_column(Integer, default=1000)
    max_delay_ms: Mapped[int] = mapped_column(Integer, default=60_000)
    jitter: Mapped[bool] = mapped_column(Boolean, default=True)


class Queue(Base):
    __tablename__ = "queues"
    __table_args__ = (UniqueConstraint("project_id", "name"),)
    id: Mapped[uuid.UUID] = uuid_pk()
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    default_priority: Mapped[int] = mapped_column(Integer, default=0)
    # Max jobs from this queue in CLAIMED/RUNNING across the whole worker fleet.
    max_concurrency: Mapped[int] = mapped_column(Integer, default=10)
    paused: Mapped[bool] = mapped_column(Boolean, default=False)
    retry_policy_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("retry_policies.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    project: Mapped["Project"] = relationship(back_populates="queues")
    retry_policy: Mapped["RetryPolicy | None"] = relationship()


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        # The hot path: workers claim QUEUED jobs ordered by priority then age.
        Index("ix_jobs_claim", "queue_id", "run_at", "priority",
              postgresql_where=text("status = 'QUEUED'")),
        Index("ix_jobs_status", "status"),
        Index("ix_jobs_batch", "batch_id"),
        # Idempotent job creation: same key on the same queue returns the original.
        UniqueConstraint("queue_id", "idempotency_key", name="uq_jobs_idempotency"),
    )
    id: Mapped[uuid.UUID] = uuid_pk()
    queue_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("queues.id", ondelete="CASCADE"), index=True)
    type: Mapped[JobType] = mapped_column(Enum(JobType), default=JobType.IMMEDIATE)
    task: Mapped[str] = mapped_column(String(120))  # handler name in the worker registry
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[JobStatus] = mapped_column(Enum(JobStatus), default=JobStatus.QUEUED)
    priority: Mapped[int] = mapped_column(Integer, default=0)
    run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    timeout_s: Mapped[int] = mapped_column(Integer, default=300)

    attempt: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)  # snapshot from policy

    idempotency_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    batch_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    scheduled_job_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("scheduled_jobs.id", ondelete="SET NULL"), nullable=True)
    worker_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("workers.id", ondelete="SET NULL"), nullable=True)

    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    executions: Mapped[list["JobExecution"]] = relationship(
        back_populates="job", cascade="all, delete-orphan", order_by="JobExecution.attempt")


class ScheduledJob(Base):
    """Template for recurring (cron) jobs; the scheduler materializes Job rows."""
    __tablename__ = "scheduled_jobs"
    __table_args__ = (Index("ix_scheduled_next_run", "next_run_at", "enabled"),)
    id: Mapped[uuid.UUID] = uuid_pk()
    queue_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("queues.id", ondelete="CASCADE"), index=True)
    task: Mapped[str] = mapped_column(String(120))
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    cron_expr: Mapped[str] = mapped_column(String(120))
    priority: Mapped[int] = mapped_column(Integer, default=0)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    next_run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_enqueued_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Worker(Base):
    __tablename__ = "workers"
    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(String(120))
    hostname: Mapped[str] = mapped_column(String(255))
    pid: Mapped[int] = mapped_column(Integer)
    concurrency: Mapped[int] = mapped_column(Integer, default=4)
    status: Mapped[WorkerStatus] = mapped_column(Enum(WorkerStatus), default=WorkerStatus.ONLINE)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_heartbeat_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True)
    jobs_processed: Mapped[int] = mapped_column(BigInteger, default=0)
    jobs_failed: Mapped[int] = mapped_column(BigInteger, default=0)


class WorkerHeartbeat(Base):
    """Append-only heartbeat history (recent window; pruned by the reaper)."""
    __tablename__ = "worker_heartbeats"
    __table_args__ = (Index("ix_heartbeats_worker_ts", "worker_id", "created_at"),)
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    worker_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workers.id", ondelete="CASCADE"))
    running_jobs: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class JobExecution(Base):
    """One row per attempt: full retry history with timings and worker assignment."""
    __tablename__ = "job_executions"
    __table_args__ = (Index("ix_executions_job", "job_id", "attempt"),)
    id: Mapped[uuid.UUID] = uuid_pk()
    job_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    worker_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("workers.id", ondelete="SET NULL"), nullable=True)
    attempt: Mapped[int] = mapped_column(Integer)
    status: Mapped[ExecutionStatus] = mapped_column(
        Enum(ExecutionStatus), default=ExecutionStatus.RUNNING)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    job: Mapped["Job"] = relationship(back_populates="executions")
    logs: Mapped[list["JobLog"]] = relationship(
        back_populates="execution", cascade="all, delete-orphan", order_by="JobLog.created_at")


class JobLog(Base):
    __tablename__ = "job_logs"
    __table_args__ = (Index("ix_job_logs_job", "job_id", "created_at"),)
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    job_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    execution_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("job_executions.id", ondelete="CASCADE"), nullable=True)
    level: Mapped[str] = mapped_column(String(10), default="INFO")
    message: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    execution: Mapped["JobExecution | None"] = relationship(back_populates="logs")


class DeadLetterJob(Base):
    __tablename__ = "dead_letter_jobs"
    id: Mapped[uuid.UUID] = uuid_pk()
    job_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), unique=True)
    queue_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("queues.id", ondelete="CASCADE"), index=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempts_made: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    requeued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
