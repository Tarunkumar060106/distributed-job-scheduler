"""Retry backoff computation: fixed, linear, exponential — all with optional jitter.

Jitter avoids the thundering-herd effect when many jobs fail at once (e.g. a
downstream outage) and would otherwise all retry at the same instant.
"""
import random

from app.models import RetryPolicy, RetryStrategy

DEFAULTS = dict(strategy=RetryStrategy.EXPONENTIAL, max_attempts=3,
                base_delay_ms=1000, max_delay_ms=60_000, jitter=True)


def compute_delay_ms(policy: RetryPolicy | None, attempt: int) -> int:
    """Delay before retry number `attempt` (1-based: attempt 1 already ran)."""
    strategy = policy.strategy if policy else DEFAULTS["strategy"]
    base = policy.base_delay_ms if policy else DEFAULTS["base_delay_ms"]
    cap = policy.max_delay_ms if policy else DEFAULTS["max_delay_ms"]
    jitter = policy.jitter if policy else DEFAULTS["jitter"]

    if strategy == RetryStrategy.FIXED:
        delay = base
    elif strategy == RetryStrategy.LINEAR:
        delay = base * attempt
    else:  # EXPONENTIAL
        delay = base * (2 ** (attempt - 1))

    delay = min(delay, cap)
    if jitter and delay > 0:
        # Full jitter over [delay/2, delay] keeps ordering roughly intact
        # while spreading retries out.
        delay = random.randint(delay // 2, delay)
    return delay
