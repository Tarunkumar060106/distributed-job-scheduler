"""Handler SDK — the contract between the platform and business logic.

The scheduler is completely generic: it stores, schedules, claims, retries,
and audits jobs, but it never contains business logic. Work is performed by
*handlers* registered through this SDK:

    from app.handler_sdk import handler, HandlerContext, PermanentFailure

    class ChargePayload(BaseModel):
        order_id: str
        amount_cents: int

    @handler("charge_card", payload_model=ChargePayload, idempotent=True,
             description="Charge a saved card for an order",
             example={"order_id": "ord_42", "amount_cents": 1999})
    def charge_card(payload: ChargePayload, ctx: HandlerContext) -> dict:
        ctx.log(f"Charging order {payload.order_id}")
        ...
        return {"charge_id": "ch_123"}

Contract guarantees provided by the platform:
- payload is validated against `payload_model` BEFORE execution; invalid
  payloads never retry — they go straight to the dead letter queue;
- execution is bounded by the job's timeout;
- raising `PermanentFailure` skips remaining retries (for errors that will
  never succeed, e.g. a 4xx from a downstream API);
- any other exception is a transient failure -> retry policy applies;
- at-least-once semantics: handlers marked `idempotent=False` are flagged in
  the catalog so operators know a duplicate run has side effects.

Handler packs are plain Python modules importing this SDK. The platform loads
them from the HANDLER_MODULES environment variable (comma-separated import
paths), so teams ship their own pack without modifying platform code.
"""
from dataclasses import dataclass, field
from typing import Any, Callable

from pydantic import BaseModel


class PermanentFailure(Exception):
    """Raise from a handler to fail the job immediately, bypassing retries."""


class HandlerContext:
    """Execution context passed to every handler."""

    def __init__(self, job_id, attempt: int, max_attempts: int,
                 log_fn: Callable[[str, str], None]):
        self.job_id = job_id
        self.attempt = attempt
        self.max_attempts = max_attempts
        self._log_fn = log_fn

    @property
    def is_last_attempt(self) -> bool:
        return self.attempt >= self.max_attempts

    def log(self, message: str, level: str = "INFO") -> None:
        """Append a line to the job's execution log (visible in the dashboard)."""
        self._log_fn(message, level)


@dataclass
class HandlerSpec:
    name: str
    fn: Callable[[Any, HandlerContext], dict | None]
    description: str = ""
    payload_model: type[BaseModel] | None = None
    idempotent: bool = False
    example: dict = field(default_factory=dict)

    def catalog_entry(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "idempotent": self.idempotent,
            "example": self.example,
            "payload_schema": (self.payload_model.model_json_schema()
                               if self.payload_model else None),
        }


REGISTRY: dict[str, HandlerSpec] = {}


def handler(name: str, *, description: str = "",
            payload_model: type[BaseModel] | None = None,
            idempotent: bool = False, example: dict | None = None):
    """Register a function as a job handler."""
    def decorator(fn):
        if name in REGISTRY:
            raise ValueError(f"Duplicate handler name: {name}")
        REGISTRY[name] = HandlerSpec(
            name=name, fn=fn, description=description,
            payload_model=payload_model, idempotent=idempotent,
            example=example or {},
        )
        return fn
    return decorator


def get_handler(name: str) -> HandlerSpec | None:
    return REGISTRY.get(name)


def catalog() -> list[dict]:
    return [spec.catalog_entry() for spec in sorted(REGISTRY.values(),
                                                    key=lambda s: s.name)]
