"""Task handler registry.

A handler receives (payload, log) where log(message, level) appends to the
job's execution logs. Handlers must be idempotent: the platform guarantees
at-least-once execution, so a crash after side effects means a re-run.

Demo handlers exercise every lifecycle path: success, slow jobs, transient
failures (retries), and permanent failures (dead letter queue).
"""
import random
import time
from typing import Callable

HANDLERS: dict[str, Callable] = {}


def handler(name: str):
    def decorator(fn):
        HANDLERS[name] = fn
        return fn
    return decorator


@handler("echo")
def echo(payload: dict, log) -> dict:
    log(f"Echoing payload: {payload}")
    return {"echoed": payload}


@handler("sleep")
def sleep_task(payload: dict, log) -> dict:
    seconds = min(float(payload.get("seconds", 1)), 60)
    log(f"Sleeping for {seconds}s")
    time.sleep(seconds)
    return {"slept": seconds}


@handler("send_email")
def send_email(payload: dict, log) -> dict:
    """Simulated email send with realistic latency."""
    to = payload.get("to", "unknown@example.com")
    log(f"Rendering template for {to}")
    time.sleep(random.uniform(0.1, 0.5))
    log(f"Email dispatched to {to}")
    return {"delivered_to": to}


@handler("flaky")
def flaky(payload: dict, log) -> dict:
    """Fails with the given probability — demonstrates retry + backoff."""
    failure_rate = float(payload.get("failure_rate", 0.5))
    log(f"Running flaky task (failure_rate={failure_rate})")
    if random.random() < failure_rate:
        raise RuntimeError("Transient failure (simulated)")
    return {"succeeded": True}


@handler("always_fail")
def always_fail(payload: dict, log) -> dict:
    """Always fails — demonstrates the dead letter queue."""
    log("This task always fails", level="WARN")
    raise RuntimeError(payload.get("error", "Permanent failure (simulated)"))
