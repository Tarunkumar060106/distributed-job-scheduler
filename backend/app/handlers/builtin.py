"""Builtin handler pack — real, production-usable executors.

http_request is the universal integration: webhooks (Discord, Slack, Zapier),
internal service calls, third-party APIs. send_email speaks real SMTP.
The platform's retry machinery wraps both: transient errors (network,
5xx, 429) retry with backoff; permanent errors (other 4xx) go straight to
the dead letter queue via PermanentFailure.
"""
import os
import smtplib
from email.message import EmailMessage
from typing import Any

import httpx
from pydantic import BaseModel, Field

from app.handler_sdk import HandlerContext, PermanentFailure, handler


class HttpRequestPayload(BaseModel):
    url: str = Field(pattern=r"^https?://")
    method: str = Field(default="POST", pattern=r"^(GET|POST|PUT|PATCH|DELETE)$")
    headers: dict[str, str] = {}
    json_body: Any = None
    timeout_s: float = Field(default=30, ge=1, le=120)


@handler(
    "http_request", payload_model=HttpRequestPayload,
    description="Call any HTTP endpoint — webhooks (Discord/Slack), APIs, services",
    example={"url": "https://postman-echo.com/post", "method": "POST",
             "json_body": {"event": "order.confirmed", "order_id": "ord_42"}},
)
def http_request(payload: HttpRequestPayload, ctx: HandlerContext) -> dict:
    ctx.log(f"{payload.method} {payload.url}")
    try:
        response = httpx.request(
            payload.method, payload.url, headers=payload.headers,
            json=payload.json_body, timeout=payload.timeout_s)
    except httpx.HTTPError as exc:
        # Network-level problems are transient: let the retry policy handle it.
        raise RuntimeError(f"HTTP transport error: {exc}") from exc

    ctx.log(f"Upstream responded {response.status_code}")
    if response.status_code >= 500 or response.status_code == 429:
        raise RuntimeError(f"Upstream returned {response.status_code} (transient)")
    if response.status_code >= 400:
        # A 4xx will fail identically on every retry — dead-letter now.
        raise PermanentFailure(
            f"Upstream returned {response.status_code}: {response.text[:300]}")
    return {"status_code": response.status_code, "body": response.text[:2000]}


class EmailPayload(BaseModel):
    to: str
    subject: str
    body: str
    from_addr: str | None = None


@handler(
    "send_email", payload_model=EmailPayload,
    description="Send a real email over SMTP (SMTP_HOST/PORT/USER/PASSWORD env)",
    example={"to": "customer@example.com", "subject": "Order confirmed",
             "body": "Thanks for your order!"},
)
def send_email(payload: EmailPayload, ctx: HandlerContext) -> dict:
    host = os.environ.get("SMTP_HOST")
    if not host:
        raise PermanentFailure(
            "SMTP is not configured on this worker (set SMTP_HOST, SMTP_PORT, "
            "SMTP_USER, SMTP_PASSWORD, SMTP_FROM)")
    port = int(os.environ.get("SMTP_PORT", "587"))
    user = os.environ.get("SMTP_USER", "")
    password = os.environ.get("SMTP_PASSWORD", "")
    sender = payload.from_addr or os.environ.get("SMTP_FROM", user)

    message = EmailMessage()
    message["From"] = sender
    message["To"] = payload.to
    message["Subject"] = payload.subject
    message.set_content(payload.body)

    ctx.log(f"Connecting to SMTP {host}:{port}")
    with smtplib.SMTP(host, port, timeout=30) as smtp:
        smtp.starttls()
        if user:
            smtp.login(user, password)
        smtp.send_message(message)
    ctx.log(f"Email delivered to {payload.to}")
    return {"delivered_to": payload.to}
