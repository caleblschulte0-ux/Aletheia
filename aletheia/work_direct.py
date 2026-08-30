"""Strict ChatGPT -> local Work Session plan envelope.

The existing exchange command files live in a public repository. This module is
therefore deliberately NOT a generic remote keyboard. It accepts only a small,
non-secret navigation/control subset and binds the generated envelope to the
operator_quote already required by the intercom contract.

Private text, credentials and API keys never belong in this transport. A future
local secret-acquisition capability stores them on the PC and returns metadata
only.
"""
from __future__ import annotations

import hashlib
import json
import re

from aletheia import work_session

PREFIX = "ALETHEIA_CHATGPT_WORK_V1:"
MAX_ENVELOPE_CHARS = 7_000
MAX_ACTIONS = 12
MAX_STEPS_PER_ACTION = 24
MAX_SUMMARY_CHARS = 240

# Public-bus plans may navigate and invoke already-labelled benign controls, but
# never carry arbitrary typed text. GitHub is the transport, so typed values
# would become repository history even if the destination UI were safe.
DIRECT_COMPUTER_ACTIONS = frozenset({
    "open_app", "list_windows", "wait_window", "focus_window",
    "inspect_controls", "invoke", "screenshot_window",
})
DIRECT_BROWSER_ACTIONS = frozenset({"click", "press", "wait_for"})
SAFE_TEXT = re.compile(r"^[\x20-\x7e]{1,500}$")


class DirectWorkRefused(PermissionError):
    pass


def quote_digest(quote: str) -> str:
    return hashlib.sha256(str(quote).strip().encode("utf-8")).hexdigest()


def encode(*, quote: str, summary: str, actions: list[dict]) -> str:
    """Helper for ChatGPT-side tooling/tests; produces no authority itself."""
    payload = {
        "version": 1,
        "quote_sha256": quote_digest(quote),
        "summary": str(summary)[:MAX_SUMMARY_CHARS],
        "actions": actions,
    }
    return PREFIX + json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def is_direct(text: str) -> bool:
    return isinstance(text, str) and text.startswith(PREFIX)


def _exact_keys(value: dict, allowed: set[str], label: str) -> None:
    extra = set(value) - allowed
    if extra:
        raise DirectWorkRefused(f"{label}: unexpected fields {sorted(extra)}")


def _validate_public_computer(steps: object) -> list[dict]:
    if not isinstance(steps, list) or not 1 <= len(steps) <= MAX_STEPS_PER_ACTION:
        raise DirectWorkRefused(
            f"computer steps must contain 1..{MAX_STEPS_PER_ACTION} entries"
        )
    for i, step in enumerate(steps):
        if not isinstance(step, dict):
            raise DirectWorkRefused(f"computer steps[{i}] must be an object")
        if step.get("action") not in DIRECT_COMPUTER_ACTIONS:
            raise DirectWorkRefused(
                f"computer steps[{i}] action {step.get('action')!r} is not allowed on the public command bus"
            )
        # Even app arguments are repository-visible. Permit only bounded plain
        # text that has already survived Work Session's sensitive-term filter.
        for arg in step.get("arguments", []):
            if not isinstance(arg, str) or not SAFE_TEXT.fullmatch(arg):
                raise DirectWorkRefused(f"computer steps[{i}] has a non-public-safe argument")
    problems = work_session.computer_problems(steps)
    if problems:
        raise DirectWorkRefused("; ".join(problems))
    return steps


def _validate_public_browser(url: object, steps: object) -> tuple[str, list[dict]]:
    if not isinstance(url, str) or not SAFE_TEXT.fullmatch(url):
        raise DirectWorkRefused("browser url must be bounded public-safe text")
    if not isinstance(steps, list) or not 1 <= len(steps) <= MAX_STEPS_PER_ACTION:
        raise DirectWorkRefused(
            f"browser steps must contain 1..{MAX_STEPS_PER_ACTION} entries"
        )
    for i, step in enumerate(steps):
        if not isinstance(step, dict):
            raise DirectWorkRefused(f"browser steps[{i}] must be an object")
        if step.get("action") not in DIRECT_BROWSER_ACTIONS:
            raise DirectWorkRefused(
                f"browser steps[{i}] action {step.get('action')!r} is not allowed on the public command bus"
            )
        for field in ("selector", "value"):
            value = step.get(field)
            if value is not None and (not isinstance(value, str) or not SAFE_TEXT.fullmatch(value)):
                raise DirectWorkRefused(f"browser steps[{i}].{field} is not public-safe text")
    problems = work_session.browser_problems(url, steps)
    if problems:
        raise DirectWorkRefused("; ".join(problems))
    return url, steps


def parse(text: str, *, quote: str) -> dict:
    if not is_direct(text):
        raise DirectWorkRefused("not a direct-work envelope")
    if not str(quote).strip():
        raise DirectWorkRefused("direct work requires the original operator quote")
    if len(text) > MAX_ENVELOPE_CHARS:
        raise DirectWorkRefused(f"direct-work envelope exceeds {MAX_ENVELOPE_CHARS} characters")
    try:
        payload = json.loads(text[len(PREFIX):])
    except json.JSONDecodeError as exc:
        raise DirectWorkRefused(f"direct-work envelope is not valid JSON ({exc.msg})") from exc
    if not isinstance(payload, dict):
        raise DirectWorkRefused("direct-work payload must be an object")
    _exact_keys(payload, {"version", "quote_sha256", "summary", "actions"}, "payload")
    if payload.get("version") != 1:
        raise DirectWorkRefused("direct-work version must be 1")
    if payload.get("quote_sha256") != quote_digest(quote):
        raise DirectWorkRefused("direct-work plan is not bound to this operator quote")
    summary = payload.get("summary")
    if not isinstance(summary, str) or not summary.strip() or len(summary) > MAX_SUMMARY_CHARS:
        raise DirectWorkRefused(f"summary must be 1..{MAX_SUMMARY_CHARS} characters")
    actions = payload.get("actions")
    if not isinstance(actions, list) or not 1 <= len(actions) <= MAX_ACTIONS:
        raise DirectWorkRefused(f"actions must contain 1..{MAX_ACTIONS} entries")

    clean = []
    for i, action in enumerate(actions):
        if not isinstance(action, dict):
            raise DirectWorkRefused(f"actions[{i}] must be an object")
        kind = action.get("type")
        if kind == "computer":
            _exact_keys(action, {"type", "steps"}, f"actions[{i}]")
            clean.append({"type": kind, "steps": _validate_public_computer(action.get("steps"))})
        elif kind == "browser":
            _exact_keys(action, {"type", "url", "steps"}, f"actions[{i}]")
            url, steps = _validate_public_browser(action.get("url"), action.get("steps"))
            clean.append({"type": kind, "url": url, "steps": steps})
        else:
            raise DirectWorkRefused(f"actions[{i}].type must be 'computer' or 'browser'")
    return {"version": 1, "summary": summary.strip(), "actions": clean}


def execute(text: str, *, quote: str) -> dict:
    """Execute a quote-bound direct plan through an already-active Work Session."""
    plan = parse(text, quote=quote)
    # `active()` is checked again inside each Work Session action, but failing
    # before any action makes the receipt clearer and consumes no session slot.
    if not work_session.active():
        raise work_session.WorkSessionRequired(
            "direct ChatGPT computer/browser work requires an active local Work Session"
        )
    receipts = []
    for n, action in enumerate(plan["actions"], start=1):
        try:
            if action["type"] == "computer":
                result = work_session.run_computer(
                    action["steps"], requested_by="chatgpt-direct-work"
                )
                detail = f"computer run {result.get('run_id', '?')} completed {result.get('steps_done', 0)} step(s)"
            else:
                result = work_session.run_browser(action["url"], action["steps"])
                detail = f"browser reached {result.get('url', action['url'])} after {len(result.get('steps_done', []))} step(s)"
            receipts.append({"n": n, "type": action["type"], "outcome": "done", "detail": detail})
        except Exception as exc:
            receipts.append({
                "n": n, "type": action["type"], "outcome": "failed",
                "detail": f"{type(exc).__name__}: {exc}",
            })
            break
    done = sum(1 for r in receipts if r["outcome"] == "done")
    return {
        "direct_work": True,
        "summary": plan["summary"],
        "state": "EXECUTED" if done == len(plan["actions"]) else "FAILED",
        "receipts": receipts,
        "spoken": (
            f"{plan['summary']}. Completed {done} of {len(plan['actions'])} work action(s)."
            + (f" {receipts[-1]['detail']}" if receipts and receipts[-1]["outcome"] == "failed" else "")
        )[:600],
    }
