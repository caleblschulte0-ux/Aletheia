"""Deterministic retry/recovery policy calculations.

This module never sleeps and never re-executes an action. It decides whether a
failure is eligible for retry, when the next attempt is due, and when the retry
budget is exhausted. The task/action engine remains responsible for execution.
"""
from __future__ import annotations

import datetime as dt
import hashlib

RETRYABLE = {"timeout", "rate_limit", "temporary_unavailable", "transport", "conflict"}
TERMINAL = {"permission_denied", "invalid_request", "policy_denied", "not_found", "unsafe"}


def classify(code: str) -> str:
    if code in RETRYABLE:
        return "RETRYABLE"
    if code in TERMINAL:
        return "TERMINAL"
    return "UNKNOWN"


def delay_seconds(attempt: int, *, base_seconds: int = 30, max_seconds: int = 3600,
                  jitter_key: str = "") -> int:
    if attempt < 1 or base_seconds < 1 or max_seconds < base_seconds:
        raise ValueError("invalid backoff parameters")
    raw = min(max_seconds, base_seconds * (2 ** (attempt - 1)))
    if not jitter_key:
        return raw
    digest = hashlib.sha256(f"{jitter_key}:{attempt}".encode()).digest()
    extra = int(raw * 0.20 * (int.from_bytes(digest[:2], "big") / 65535))
    return min(max_seconds, raw + extra)


def next_step(*, failure_code: str, attempts: int, max_attempts: int,
              now: dt.datetime | None = None, jitter_key: str = "") -> dict:
    if attempts < 0 or max_attempts < 1:
        raise ValueError("invalid attempts")
    category = classify(failure_code)
    if category != "RETRYABLE":
        return {"decision": "STOP", "reason": category.lower(), "failure_code": failure_code}
    if attempts >= max_attempts:
        return {"decision": "STOP", "reason": "retry_budget_exhausted", "failure_code": failure_code}
    now = now or dt.datetime.now(dt.timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    delay = delay_seconds(attempts + 1, jitter_key=jitter_key)
    due = now.astimezone(dt.timezone.utc) + dt.timedelta(seconds=delay)
    return {"decision": "RETRY", "failure_code": failure_code, "next_attempt": attempts + 1,
            "delay_seconds": delay, "due_at": due.strftime("%Y-%m-%dT%H:%M:%SZ")}
