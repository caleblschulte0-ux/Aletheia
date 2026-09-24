"""What is wrong with a project, in words - and "handled", on his word.

His words, 2026-09-23 evening: *"it's saying Schwab Trader is broken. Yes,
it was broken today, but I've had a different Claude chat fix it ... I
don't need that being read all night ... when I go to it, it just says
Schwab Trader, guardrail, paper trading system, etc. It's like the readme
essentially. I want it to tell me what the fault is, so I can know what
needs to get fixed."*

Two things, both pure over the pulse the fleet cron writes:

- **`said(alert, repo)`** is the fault in one sentence a person can act on:
  which workflow failed and when; which file the pulse expected and did
  not find (a renamed file is a REGISTRY fix, not a fault in the project -
  the trader's `signals/paper_account.json` became `sim_account.json` in
  a rebuild, and the fleet read red for a day over it); or why the
  repository could not be read. The page leads its card with it; the
  README summary comes after.
- **`ack(repo)`** is his "handled": the fault's fingerprint (what is
  failing, what is missing) is kept in private state, and while the pulse
  keeps reporting the SAME fault it is shown as handled - waiting for the
  next reading to confirm - rather than shouted. A different failure on
  the same repository is a new fault and is shouted again. Nothing here
  changes the pulse itself; an ack is a fact about him, beside it.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json

from aletheia import journal, stateio

ACTOR = "aletheia-fleet"


def _path():
    return stateio.private_dir("fleet") / "handled.json"


def _load() -> dict:
    try:
        rows = json.loads(_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return rows if isinstance(rows, dict) else {}


def fingerprint(alert: dict) -> str:
    """The fault's identity: what is failing, what is missing, what error."""
    material = {"failing": sorted(str(f) for f in alert.get("failing") or []),
                "missing": sorted(str(m) for m in alert.get("missing") or []),
                "error": str(alert.get("error") or "")[:200]}
    return hashlib.sha256(json.dumps(material, sort_keys=True).encode("utf-8")).hexdigest()[:16]


def _ago(stamp: str, now: dt.datetime | None = None) -> str:
    try:
        when = dt.datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except ValueError:
        return ""
    now = now or dt.datetime.now(dt.timezone.utc)
    seconds = max(0.0, (now - when).total_seconds())
    if seconds < 3600:
        return f"{max(1, int(seconds // 60))} minutes ago"
    if seconds < 48 * 3600:
        hours = int(seconds // 3600)
        return "an hour ago" if hours == 1 else f"{hours} hours ago"
    return f"{int(seconds // 86400)} days ago"


def said(alert: dict, repo: dict | None = None, *, now: dt.datetime | None = None) -> str:
    """The fault in one sentence. Pure."""
    repo = repo or {}
    parts: list[str] = []
    workflows = repo.get("workflows") if isinstance(repo.get("workflows"), dict) else {}
    failing = [str(f) for f in alert.get("failing") or []]
    if failing:
        bits = []
        for name in failing:
            short = name[:-4] if name.endswith(".yml") else name
            wf = workflows.get(name) if isinstance(workflows.get(name), dict) else {}
            verdict = str(wf.get("conclusion") or "failed").replace("_", " ")
            when = _ago(str(wf.get("updated_at") or ""), now)
            bits.append(f"{short} {verdict if verdict != 'failure' else 'failed'}" + (f" {when}" if when else ""))
        parts.append("; ".join(bits))
    missing = [str(m) for m in alert.get("missing") or []]
    if missing:
        listed = ", ".join(missing)
        parts.append(f"the pulse expects {listed} and the repository does not have it"
                     + (" - if it was renamed, that is a fix to the fleet registry, not to the project"
                        if not failing else ""))
    if alert.get("error"):
        parts.append(f"it could not be read: {str(alert['error'])[:160]}")
    if not parts:
        parts.append("the pulse marks it red and does not say why")
    return ". ".join(p[0].upper() + p[1:] for p in parts) + "."


def is_handled(alert: dict) -> dict | None:
    """His ack for THIS fault, or None. A changed fault is a new fault."""
    row = _load().get(str(alert.get("repo") or ""))
    if not isinstance(row, dict) or row.get("fingerprint") != fingerprint(alert):
        return None
    return row


def ack(repo: str, *, alerts: list[dict] | None = None, quote: str = "") -> str:
    """Mark the current fault on `repo` handled. Says what that means."""
    repo = str(repo or "").strip()
    if not repo:
        raise ValueError("say which project")
    if alerts is None:
        alerts = current_alerts()
    hit = next((a for a in alerts if str(a.get("repo") or "") == repo or str(a.get("github") or "") == repo
                or str(a.get("github") or "").casefold() == repo.casefold()
                or str(a.get("repo") or "").casefold() == repo.casefold()), None)
    if hit is None:
        raise ValueError(f"nothing is red on {repo!r} right now")
    rows = _load()
    rows[str(hit.get("repo"))] = {"fingerprint": fingerprint(hit), "at": stateio.utcnow(),
                                  "quote": quote[:120], "said": said(hit)}
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    stateio.write_json_atomic(path, rows)
    name = str(hit.get("github") or hit.get("repo"))
    journal.append("decision", "fleet",
                   f"{name}: fault marked handled by him - quiet until the next reading says otherwise",
                   actor=ACTOR)
    return (f"Noted - I'll stop calling {name} broken. If the next reading shows the same fault it stays "
            "quiet; a different one and I'll say so.")


def current_alerts() -> list[dict]:
    from aletheia import pulse
    try:
        latest = json.loads((pulse.PULSE_DIR / "latest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [a for a in (latest.get("alerts") or []) if isinstance(a, dict)]


def decorate(pulse: dict, *, now: dt.datetime | None = None) -> dict:
    """Every alert given its sentence and his ack, in place. Never raises."""
    try:
        repos = pulse.get("repos") if isinstance(pulse.get("repos"), dict) else {}
        for alert in pulse.get("alerts") or []:
            if not isinstance(alert, dict):
                continue
            repo = repos.get(str(alert.get("repo") or "")) or {}
            alert["said"] = said(alert, repo, now=now)
            handled = is_handled(alert)
            alert["handled"] = bool(handled)
            if handled:
                alert["handled_at"] = handled.get("at", "")
    except Exception:
        pass
    return pulse


def loud(alerts: list[dict]) -> list[dict]:
    """The alerts he has not marked handled."""
    return [a for a in alerts or [] if isinstance(a, dict) and not is_handled(a)]
