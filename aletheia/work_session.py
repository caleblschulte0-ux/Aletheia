"""Bounded operator work sessions for routine desktop/browser autonomy.

The operator explicitly opens a short-lived session. During it, Aletheia may
auto-authorize only a hard-coded safe subset of the existing browser/computer
adapters. The adapters and their normal approval gates remain unchanged: this
module creates one exact approval per accepted plan.

Authentication/credentials, API keys/secrets, payments, destructive actions,
account-security changes, external messages/publication, and shell/admin
execution are refused. They remain explicit operator handoffs.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import secrets
import sys
from pathlib import Path
from urllib.parse import urlparse

from aletheia import browse, computer, journal, policy, stateio

ACTOR = "aletheia-work-session"
SESSION_PATH = stateio.private_dir("work-session") / "active.json"
CLAIMS_DIR = stateio.private_dir("work-session") / "claims"
DEFAULT_HOURS = 8
DEFAULT_ACTIONS = 250
MAX_HOURS = 24
MAX_ACTIONS = 2_000

SENSITIVE_TERMS = frozenset({
    "password", "passcode", "pin", "2fa", "mfa", "authenticator", "otp",
    "security key", "recovery code", "backup code", "sign out all",
    "api key", "apikey", "access key", "secret", "token", "credential",
    "billing", "payment", "credit card", "debit card", "card number", "cvv",
    "checkout", "purchase", "buy now", "place order", "order now", "pay now",
    "wire transfer", "bank transfer", "send money", "withdraw", "deposit",
    "delete", "erase", "remove account", "close account", "terminate",
    "uninstall", "factory reset", "format", "wipe", "revoke", "rotate key",
    "change password", "reset password", "account security",
})
CONSEQUENTIAL_ACTION_TERMS = frozenset({
    "send", "submit", "publish", "post", "confirm", "approve", "accept", "book",
    "reserve", "purchase", "buy", "pay", "transfer", "delete", "remove", "revoke",
    "uninstall", "install", "create key", "generate key", "rotate key", "close account",
})
BLOCKED_EXECUTABLES = frozenset({
    "cmd", "cmd.exe", "powershell", "powershell.exe", "pwsh", "pwsh.exe",
    "wscript", "wscript.exe", "cscript", "cscript.exe", "regedit", "regedit.exe",
    "msiexec", "msiexec.exe", "diskpart", "diskpart.exe", "shutdown", "shutdown.exe",
    "taskkill", "taskkill.exe", "rundll32", "rundll32.exe", "wmic", "wmic.exe",
    "bash", "bash.exe", "wsl", "wsl.exe", "python", "python.exe", "py", "py.exe",
    "node", "node.exe", "ssh", "ssh.exe", "scp", "scp.exe",
})
SAFE_BROWSER_KEYS = frozenset({
    "Tab", "Shift+Tab", "Escape", "ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight",
    "PageUp", "PageDown", "Home", "End",
})
KNOWN_SECRET = re.compile(
    r"(?i)(?:\bsk-[a-z0-9_-]{12,}|\bgh[pousr]_[a-z0-9]{20,}|\bAIza[a-z0-9_-]{20,})"
)


class WorkSessionRequired(PermissionError):
    pass


class WorkSessionRefused(PermissionError):
    pass


def _parse_time(value: str) -> dt.datetime:
    parsed = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("session timestamp must be timezone-aware")
    return parsed.astimezone(dt.timezone.utc)


def _now(now: dt.datetime | None = None) -> dt.datetime:
    value = now or dt.datetime.now(dt.timezone.utc)
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    return value.astimezone(dt.timezone.utc)


def _claims(session_id: str) -> list[Path]:
    root = CLAIMS_DIR / stateio.safe_id(session_id, name="session id")
    return sorted(root.glob("*.json")) if root.is_dir() else []


def load() -> dict | None:
    if not SESSION_PATH.is_file():
        return None
    try:
        value = stateio.read_json(SESSION_PATH)
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


def active(*, now: dt.datetime | None = None) -> dict | None:
    session = load()
    if not session or not session.get("enabled"):
        return None
    try:
        if _parse_time(session["expires"]) <= _now(now):
            return None
        if not policy.is_approved(session["approval_id"]):
            return None
        if len(_claims(session["id"])) >= int(session["max_actions"]):
            return None
    except (KeyError, TypeError, ValueError):
        return None
    return session


def open_session(*, hours: int = DEFAULT_HOURS, max_actions: int = DEFAULT_ACTIONS,
                 via: str = "operator", now: dt.datetime | None = None) -> dict:
    if type(hours) is not int or not 1 <= hours <= MAX_HOURS:
        raise ValueError(f"hours must be 1..{MAX_HOURS}")
    if type(max_actions) is not int or not 1 <= max_actions <= MAX_ACTIONS:
        raise ValueError(f"max_actions must be 1..{MAX_ACTIONS}")
    current = active(now=now)
    if current:
        return current
    stamp = _now(now)
    session_id = f"ws-{stamp.strftime('%Y%m%d-%H%M')}-{secrets.token_hex(3)}"
    approval_id = f"{session_id}-operator"
    expires = stamp + dt.timedelta(hours=hours)
    policy.request(
        approval_id,
        requested_action=f"work.session:{session_id}",
        reason="bounded routine browser/desktop work without click-by-click approval",
        consequence=(
            f"for {hours} hour(s) / {max_actions} safe plans, Aletheia may auto-approve only "
            "the work-session subset; sensitive actions still require a separate decision"
        ),
        reversible=True,
    )
    policy.decide(
        approval_id, "APPROVED", via=via,
        because="operator explicitly opened a bounded local work session",
    )
    record = {
        "version": 1, "id": session_id, "enabled": True, "approval_id": approval_id,
        "created_at": stamp.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "expires": expires.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "max_actions": max_actions,
        "scope": "routine authenticated browser + ordinary Windows UI; no secrets/auth/payment/destructive/world-touching actions",
    }
    stateio.write_json_atomic(SESSION_PATH, record)
    journal.append(
        "decision", "work:session",
        f"OPEN {session_id} until {record['expires']} / {max_actions} actions",
        actor=ACTOR, refs=[f"approval:{approval_id}"],
    )
    return record


def close_session(*, via: str = "operator") -> bool:
    session = load()
    if not session or not session.get("enabled"):
        return False
    session["enabled"] = False
    session["closed_at"] = stateio.utcnow()
    stateio.write_json_atomic(SESSION_PATH, session)
    journal.append("decision", "work:session", f"CLOSED {session.get('id', '?')}", actor=via)
    return True


def status(*, now: dt.datetime | None = None) -> dict:
    session = load()
    live = active(now=now)
    used = len(_claims(session["id"])) if session and session.get("id") else 0
    maximum = int(session.get("max_actions", 0)) if session else 0
    return {
        "active": bool(live), "id": session.get("id") if session else None,
        "expires": session.get("expires") if session else None,
        "used": used, "max_actions": maximum, "actions_left": max(0, maximum - used),
        "scope": session.get("scope") if session else None,
    }


def _flatten(value: object) -> str:
    if isinstance(value, dict):
        return " ".join(_flatten(v) for v in value.values())
    if isinstance(value, (list, tuple)):
        return " ".join(_flatten(v) for v in value)
    return str(value or "")


def _normalized(value: object) -> str:
    return " ".join(_flatten(value).casefold().replace("_", " ").replace("-", " ").split())


def _sensitive(value: object) -> str | None:
    text = _normalized(value)
    return next((term for term in SENSITIVE_TERMS if term in text), None)


def _consequential(value: object) -> str | None:
    text = _normalized(value)
    return next((term for term in CONSEQUENTIAL_ACTION_TERMS if term in text), None)


def _looks_like_secret(value: object) -> bool:
    return bool(KNOWN_SECRET.search(str(value or "").strip()))


def computer_problems(steps: object) -> list[str]:
    problems = list(computer.validate_steps(steps))
    if problems or not isinstance(steps, list):
        return problems
    for i, step in enumerate(steps):
        action = step.get("action")
        label = f"steps[{i}]"
        if action == "close_window":
            problems.append(f"{label}: closing a window may discard unsaved work")
            continue
        if action == "open_app":
            name = Path(str(step.get("app", ""))).name.casefold()
            if name in BLOCKED_EXECUTABLES:
                problems.append(f"{label}: shell/admin executable {name!r} is outside work-session scope")
            risky = _sensitive([step.get("app"), step.get("arguments", [])])
            if risky:
                problems.append(f"{label}: app/arguments look sensitive ({risky})")
            continue
        risky = _sensitive(step.get("window"))
        if risky:
            problems.append(f"{label}: sensitive window target ({risky})")
        if action in {"invoke", "set_text"}:
            risky = _sensitive(step.get("control"))
            if risky:
                problems.append(f"{label}: sensitive control target ({risky})")
        if action == "invoke":
            risky = _sensitive(step) or _consequential(step.get("control"))
            if risky:
                problems.append(f"{label}: potentially consequential control ({risky})")
        if action == "set_text" and _looks_like_secret(step.get("text")):
            problems.append(f"{label}: text looks like a credential/secret")
    return list(dict.fromkeys(problems))


def browser_problems(url: str, steps: object) -> list[str]:
    problems = list(browse.validate_steps(steps if isinstance(steps, list) else []))
    parsed = urlparse(str(url or ""))
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        problems.append("url must be an absolute http(s) URL")
    risky = _sensitive(f"{parsed.netloc} {parsed.path} {parsed.query}")
    if risky:
        problems.append(f"url targets a sensitive surface ({risky})")
    if not isinstance(steps, list):
        return problems + ["steps must be a list"]
    if not steps:
        problems.append("steps must be non-empty")
    for i, step in enumerate(steps):
        label = f"steps[{i}]"
        action = step.get("action")
        selector = step.get("selector")
        risky = _sensitive(selector)
        if risky:
            problems.append(f"{label}: sensitive selector ({risky})")
        if action == "click":
            risky = _sensitive(step) or _consequential(selector)
            if risky:
                problems.append(f"{label}: consequential click ({risky})")
        if action in {"type", "select"}:
            if _looks_like_secret(step.get("value")):
                problems.append(f"{label}: value looks like a credential/secret")
            risky = _sensitive(step.get("value"))
            if risky:
                problems.append(f"{label}: sensitive form value ({risky})")
        if action == "press" and str(step.get("value")) not in SAFE_BROWSER_KEYS:
            problems.append(
                f"{label}: key {step.get('value')!r} can submit/trigger an unknown action; "
                "work sessions only auto-press navigation keys"
            )
    return list(dict.fromkeys(problems))


def _require_active() -> dict:
    session = active()
    if not session:
        raise WorkSessionRequired(
            "no active work session — run `python -m aletheia.work_session on` locally first"
        )
    policy.ensure_not_halted()
    return session


def _claim(session: dict, kind: str, digest: str) -> dict:
    root = CLAIMS_DIR / stateio.safe_id(session["id"], name="session id")
    root.mkdir(parents=True, exist_ok=True)
    for slot in range(1, int(session["max_actions"]) + 1):
        receipt = {
            "version": 1, "session_id": session["id"], "slot": slot,
            "kind": kind, "digest": digest, "claimed_at": stateio.utcnow(),
        }
        try:
            stateio.create_json_exclusive(root / f"{slot:05d}.json", receipt)
        except FileExistsError:
            continue
        return receipt
    raise WorkSessionRequired("work session action budget is exhausted")


def _digest_browser(url: str, steps: list[dict]) -> str:
    raw = json.dumps({"url": url, "steps": steps}, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def authorize_computer(steps: list[dict]) -> str:
    session = _require_active()
    problems = computer_problems(steps)
    if problems:
        raise WorkSessionRefused("; ".join(problems))
    digest = computer.plan_digest(steps)
    claim = _claim(session, "computer", digest)
    approval_id = f"{session['id']}-pc-{claim['slot']:05d}"
    policy.request(
        approval_id, requested_action=computer.approval_action(steps),
        reason=f"safe desktop plan under active work session {session['id']}",
        consequence="ordinary local UI only; exact plan remains hash-bound and one-shot",
        reversible=True,
    )
    policy.decide(
        approval_id, "APPROVED", via=f"work-session:{session['id']}",
        because="plan passed the hard-coded work-session desktop classifier",
    )
    return approval_id


def authorize_browser(url: str, steps: list[dict]) -> str:
    session = _require_active()
    problems = browser_problems(url, steps)
    if problems:
        raise WorkSessionRefused("; ".join(problems))
    digest = _digest_browser(url, steps)
    claim = _claim(session, "browser", digest)
    approval_id = f"{session['id']}-web-{claim['slot']:05d}"
    policy.request(
        approval_id, requested_action=f"browser.interact:{digest}",
        reason=f"safe browser plan under active work session {session['id']}",
        consequence="ordinary authenticated-site navigation only; no auth/secrets/payments/destructive/world-touching action",
        reversible=True,
    )
    policy.decide(
        approval_id, "APPROVED", via=f"work-session:{session['id']}",
        because="plan passed the hard-coded work-session browser classifier",
    )
    return approval_id


def run_computer(steps: list[dict], *, backend=None, backend_factory=None,
                 requested_by: str = "work-session") -> dict:
    approval_id = authorize_computer(steps)
    return computer.execute(
        steps, approval_id, backend=backend, backend_factory=backend_factory,
        requested_by=requested_by,
    )


def run_browser(url: str, steps: list[dict], *, profile: Path | None = None) -> dict:
    approval_id = authorize_browser(url, steps)
    return browse.interact(url, steps, approval_id=approval_id, profile=profile)


def _read_steps(path: str) -> list[dict]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, list):
        raise ValueError("steps JSON must be a list")
    return value


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Bounded routine desktop/browser work sessions.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    on = sub.add_parser("on", help="open a bounded work session")
    on.add_argument("--hours", type=int, default=DEFAULT_HOURS)
    on.add_argument("--actions", type=int, default=DEFAULT_ACTIONS)
    sub.add_parser("off", help="close the active work session")
    sub.add_parser("status", help="show current work-session scope and budget")
    pc = sub.add_parser("computer", help="run a safe computer steps JSON under the session")
    pc.add_argument("steps")
    web = sub.add_parser("browser", help="run safe browser steps JSON under the session")
    web.add_argument("url")
    web.add_argument("steps")
    args = ap.parse_args(argv)
    try:
        if args.cmd == "on":
            open_session(hours=args.hours, max_actions=args.actions)
            print(json.dumps(status(), indent=2))
            print("Work session open. Sensitive/auth/payment/destructive actions still require a handoff.")
            return 0
        if args.cmd == "off":
            print("Work session closed." if close_session() else "No active work session.")
            return 0
        if args.cmd == "status":
            print(json.dumps(status(), indent=2))
            return 0
        if args.cmd == "computer":
            print(json.dumps(run_computer(_read_steps(args.steps)), indent=2))
            return 0
        print(json.dumps(run_browser(args.url, _read_steps(args.steps)), indent=2))
        return 0
    except Exception as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
