"""Strict ChatGPT -> local Work Session plan envelope.

The exchange command files live in a public repository. This module is therefore
not a generic remote keyboard. It accepts only a small, non-secret control
subset and binds the generated envelope to the operator_quote required by the
intercom contract.

Private text, credentials and API keys never belong in this transport. Private
observations use an ephemeral public key and are returned only as ciphertext;
the corresponding private key never enters GitHub.
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
# never carry arbitrary typed text. GitHub is the transport, so typed values or
# process command-line arguments would become repository history.
DIRECT_COMPUTER_ACTIONS = frozenset({
    "open_app", "list_windows", "wait_window", "focus_window",
    "inspect_controls", "invoke", "screenshot_window",
})
DIRECT_BROWSER_ACTIONS = frozenset({"click", "press", "wait_for"})
SAFE_TEXT = re.compile(r"^[\x20-\x7e]{1,500}$")
SAFE_RESPONSE_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
SAFE_PUBLIC_KEY = re.compile(r"^[A-Za-z0-9+/=]{100,3000}$")


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
                f"computer steps[{i}] action {step.get('action')!r} "
                "is not allowed on the public command bus"
            )
        if step.get("action") == "open_app":
            app = step.get("app")
            if not isinstance(app, str) or not SAFE_TEXT.fullmatch(app):
                raise DirectWorkRefused(
                    f"computer steps[{i}].app is not public-safe text"
                )
            if step.get("arguments"):
                raise DirectWorkRefused(
                    f"computer steps[{i}] app arguments are not allowed "
                    "on the public command bus"
                )
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
                f"browser steps[{i}] action {step.get('action')!r} "
                "is not allowed on the public command bus"
            )
        for field in ("selector", "value"):
            value = step.get(field)
            if value is not None and (
                not isinstance(value, str) or not SAFE_TEXT.fullmatch(value)
            ):
                raise DirectWorkRefused(
                    f"browser steps[{i}].{field} is not public-safe text"
                )
    problems = work_session.browser_problems(url, steps)
    if problems:
        raise DirectWorkRefused("; ".join(problems))
    return url, steps


def _validate_public_observe(action: dict, label: str) -> dict:
    _exact_keys(
        action,
        {"type", "response_id", "public_key", "target", "url", "window"},
        label,
    )
    response_id = action.get("response_id")
    public_key = action.get("public_key")
    target = action.get("target")
    url = action.get("url")
    window = action.get("window")

    if not isinstance(response_id, str) or not SAFE_RESPONSE_ID.fullmatch(response_id):
        raise DirectWorkRefused(f"{label}.response_id is not public-safe")
    if not isinstance(public_key, str) or not SAFE_PUBLIC_KEY.fullmatch(public_key):
        raise DirectWorkRefused(f"{label}.public_key must be bounded base64 text")
    if target not in {"browser", "screen"}:
        raise DirectWorkRefused(f"{label}.target must be 'browser' or 'screen'")
    if target == "browser":
        if not isinstance(url, str) or not SAFE_TEXT.fullmatch(url):
            raise DirectWorkRefused(
                f"{label}: browser observation needs a public-safe url"
            )
        if window is not None:
            raise DirectWorkRefused(
                f"{label}: browser observation does not accept window"
            )
    else:
        if url is not None:
            raise DirectWorkRefused(
                f"{label}: screen observation does not accept url"
            )
        if window is not None and (
            not isinstance(window, str) or not SAFE_TEXT.fullmatch(window)
        ):
            raise DirectWorkRefused(f"{label}.window is not public-safe text")
    return {
        "type": "observe",
        "response_id": response_id,
        "public_key": public_key,
        "target": target,
        "url": url,
        "window": window,
    }


def parse(text: str, *, quote: str) -> dict:
    if not is_direct(text):
        raise DirectWorkRefused("not a direct-work envelope")
    if not str(quote).strip():
        raise DirectWorkRefused("direct work requires the original operator quote")
    if len(text) > MAX_ENVELOPE_CHARS:
        raise DirectWorkRefused(
            f"direct-work envelope exceeds {MAX_ENVELOPE_CHARS} characters"
        )
    try:
        payload = json.loads(text[len(PREFIX):])
    except json.JSONDecodeError as exc:
        raise DirectWorkRefused(
            f"direct-work envelope is not valid JSON ({exc.msg})"
        ) from exc
    if not isinstance(payload, dict):
        raise DirectWorkRefused("direct-work payload must be an object")
    _exact_keys(
        payload, {"version", "quote_sha256", "summary", "actions"}, "payload"
    )
    if payload.get("version") != 1:
        raise DirectWorkRefused("direct-work version must be 1")
    if payload.get("quote_sha256") != quote_digest(quote):
        raise DirectWorkRefused(
            "direct-work plan is not bound to this operator quote"
        )
    summary = payload.get("summary")
    if (
        not isinstance(summary, str)
        or not summary.strip()
        or len(summary) > MAX_SUMMARY_CHARS
    ):
        raise DirectWorkRefused(
            f"summary must be 1..{MAX_SUMMARY_CHARS} characters"
        )
    actions = payload.get("actions")
    if not isinstance(actions, list) or not 1 <= len(actions) <= MAX_ACTIONS:
        raise DirectWorkRefused(
            f"actions must contain 1..{MAX_ACTIONS} entries"
        )

    clean = []
    for i, action in enumerate(actions):
        if not isinstance(action, dict):
            raise DirectWorkRefused(f"actions[{i}] must be an object")
        kind = action.get("type")
        if kind == "computer":
            _exact_keys(action, {"type", "steps"}, f"actions[{i}]")
            clean.append({
                "type": kind,
                "steps": _validate_public_computer(action.get("steps")),
            })
        elif kind == "browser":
            _exact_keys(action, {"type", "url", "steps"}, f"actions[{i}]")
            url, steps = _validate_public_browser(
                action.get("url"), action.get("steps")
            )
            clean.append({"type": kind, "url": url, "steps": steps})
        elif kind == "observe":
            clean.append(_validate_public_observe(action, f"actions[{i}]"))
        else:
            raise DirectWorkRefused(
                f"actions[{i}].type must be 'computer', 'browser', or 'observe'"
            )
    return {"version": 1, "summary": summary.strip(), "actions": clean}


def _ready_session() -> dict | None:
    """Use a live session, or auto-open one only from a standing LOCAL grant."""
    current = work_session.active()
    if current:
        return current
    # Lazy import keeps work_trust -> work_session and work_direct imports acyclic.
    from aletheia import work_trust
    return work_trust.ensure_session()


def execute(text: str, *, quote: str) -> dict:
    """Execute a quote-bound direct plan through permitted local authority."""
    plan = parse(text, quote=quote)
    if not _ready_session():
        raise work_session.WorkSessionRequired(
            "direct ChatGPT work requires an active Work Session or a local "
            "standing work grant"
        )

    receipts = []
    for n, action in enumerate(plan["actions"], start=1):
        try:
            if action["type"] == "computer":
                result = work_session.run_computer(
                    action["steps"], requested_by="chatgpt-direct-work"
                )
                detail = (
                    f"computer run {result.get('run_id', '?')} completed "
                    f"{result.get('steps_done', 0)} step(s)"
                )
            elif action["type"] == "browser":
                result = work_session.run_browser(
                    action["url"], action["steps"]
                )
                detail = (
                    f"browser reached {result.get('url', action['url'])} after "
                    f"{len(result.get('steps_done', []))} step(s)"
                )
            else:
                from aletheia import sealed_observe
                result = sealed_observe.run(
                    response_id=action["response_id"],
                    public_key=action["public_key"],
                    target=action["target"],
                    url=action.get("url"),
                    window=action.get("window"),
                )
                detail = (
                    f"sealed {action['target']} observation ready at "
                    f"{result['sidecar']}"
                )
            receipts.append({
                "n": n,
                "type": action["type"],
                "outcome": "done",
                "detail": detail,
            })
        except Exception as exc:
            receipts.append({
                "n": n,
                "type": action["type"],
                "outcome": "failed",
                "detail": f"{type(exc).__name__}: {exc}",
            })
            break

    done = sum(1 for r in receipts if r["outcome"] == "done")
    return {
        "direct_work": True,
        "summary": plan["summary"],
        "state": (
            "EXECUTED" if done == len(plan["actions"]) else "FAILED"
        ),
        "receipts": receipts,
        "spoken": (
            f"{plan['summary']}. Completed {done} of "
            f"{len(plan['actions'])} work action(s)."
            + (
                f" {receipts[-1]['detail']}"
                if receipts and receipts[-1]["outcome"] == "failed"
                else ""
            )
        )[:600],
    }
