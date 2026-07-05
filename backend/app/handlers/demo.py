"""Demo handler pack — exercises every lifecycle path for evaluation/demos.

Kept separate from the builtin pack so a production deployment can drop it:
HANDLER_MODULES=app.handlers.builtin,yourteam.handlers
"""
import random
import time

from pydantic import BaseModel, Field

from app.handler_sdk import HandlerContext, handler


@handler("echo", idempotent=True,
         description="Return the payload unchanged (smoke testing)",
         example={"hello": "world"})
def echo(payload: dict, ctx: HandlerContext) -> dict:
    ctx.log(f"Echoing payload: {payload}")
    return {"echoed": payload}


class SleepPayload(BaseModel):
    seconds: float = Field(default=1, ge=0, le=60)


@handler("sleep", payload_model=SleepPayload, idempotent=True,
         description="Hold a worker slot for N seconds (load/timeout testing)",
         example={"seconds": 2})
def sleep_task(payload: SleepPayload, ctx: HandlerContext) -> dict:
    ctx.log(f"Sleeping for {payload.seconds}s")
    time.sleep(payload.seconds)
    return {"slept": payload.seconds}


class FlakyPayload(BaseModel):
    failure_rate: float = Field(default=0.5, ge=0, le=1)


@handler("flaky", payload_model=FlakyPayload,
         description="Fail randomly (demonstrates retry with backoff)",
         example={"failure_rate": 0.5})
def flaky(payload: FlakyPayload, ctx: HandlerContext) -> dict:
    ctx.log(f"Running flaky task (failure_rate={payload.failure_rate})")
    if random.random() < payload.failure_rate:
        raise RuntimeError("Transient failure (simulated)")
    return {"succeeded": True}


@handler("always_fail",
         description="Always fail (demonstrates the dead letter queue)",
         example={"error": "Permanent failure (simulated)"})
def always_fail(payload: dict, ctx: HandlerContext) -> dict:
    ctx.log("This task always fails", level="WARN")
    raise RuntimeError(payload.get("error", "Permanent failure (simulated)"))
