"""The sentinel — Aletheia notices, and tells the operator (ROADMAP A5's
alert half). Runs right after the pulse in `pulse.yml`.

It manages exactly one rolling GitHub issue on THIS repo (its own front
door — `GITHUB_TOKEN` with issues:write, no cross-repo power needed):

  - faults appear and no alert issue is open  -> open one
  - faults change while the issue is open     -> update body + comment
    (comments are what push a notification to the operator's devices)
  - everything recovers                        -> comment + close

The sentinel never touches any other repo and never fixes anything — it
is the smoke detector, not the fire brigade. Every open/close is
journaled. Deciding what to DO about a fault stays with the operator and
interactive Claude sessions (front-door actions live in `aletheia.act`).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from aletheia import gh, journal
from aletheia.pulse import PULSE_DIR

ALERT_TITLE = "🚨 Fleet alert"


def _render_body(pulse: dict) -> str:
    lines = [
        f"The pulse at `{pulse['generated_at']}` sees trouble in the fleet:",
        "",
    ]
    for a in pulse.get("alerts", []):
        detail = []
        if a.get("failing"):
            detail.append("failing: " + ", ".join(f"`{w}`" for w in a["failing"]))
        if a.get("missing"):
            detail.append("missing: " + ", ".join(f"`{p}`" for p in a["missing"]))
        if a.get("error"):
            detail.append(f"unreachable: {a['error']}")
        lines.append(f"- **{a['github']}** — {a['health']}" + (" · " + " · ".join(detail) if detail else ""))
    lines += [
        "",
        "Source of truth: `state/pulse/latest.json` / the wall. "
        "This issue is managed by the sentinel — it will comment and close itself on recovery.",
    ]
    return "\n".join(lines)


def _find_open_alert(repo_full: str, request) -> dict | None:
    issues = request("GET", f"/repos/{repo_full}/issues?state=open&per_page=100") or []
    for issue in issues:
        if issue.get("title", "").startswith(ALERT_TITLE) and "pull_request" not in issue:
            return issue
    return None


def sync(pulse: dict, repo_full: str, request=gh.request) -> str:
    """Reconcile the alert issue with the pulse. Returns what happened:
    'opened' | 'updated' | 'closed' | 'quiet'."""
    alerts = pulse.get("alerts") or []
    names = ", ".join(a["github"] for a in alerts)
    existing = _find_open_alert(repo_full, request)

    if alerts and existing is None:
        request("POST", f"/repos/{repo_full}/issues", {
            "title": f"{ALERT_TITLE}: {names}",
            "body": _render_body(pulse),
        })
        journal.append("alert", "sentinel", f"alert issue opened — {names}")
        return "opened"

    if alerts and existing is not None:
        number = existing["number"]
        request("PATCH", f"/repos/{repo_full}/issues/{number}", {
            "title": f"{ALERT_TITLE}: {names}",
            "body": _render_body(pulse),
        })
        # a comment only when the fault set changed — updates shouldn't spam
        if names not in existing.get("title", ""):
            request("POST", f"/repos/{repo_full}/issues/{number}/comments", {
                "body": f"Fault set changed — now: {names}\n\n" + _render_body(pulse),
            })
            journal.append("alert", "sentinel", f"alert issue updated — {names}")
        return "updated"

    if not alerts and existing is not None:
        number = existing["number"]
        request("POST", f"/repos/{repo_full}/issues/{number}/comments", {
            "body": f"All clear — the pulse at `{pulse['generated_at']}` sees no faults. Closing.",
        })
        request("PATCH", f"/repos/{repo_full}/issues/{number}", {"state": "closed"})
        journal.append("recovery", "sentinel", "fleet recovered — alert issue closed")
        return "closed"

    return "quiet"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Reconcile the fleet-alert issue with the pulse.")
    ap.add_argument("--repo", required=True, help="owner/name of THIS repo (github.repository in Actions)")
    ap.add_argument("--pulse", default=str(PULSE_DIR / "latest.json"))
    args = ap.parse_args(argv)

    if not gh.token():
        print("no token — the sentinel cannot manage issues; skipping honestly", file=sys.stderr)
        return 0
    pulse = json.loads(Path(args.pulse).read_text(encoding="utf-8"))
    outcome = sync(pulse, args.repo)
    print(f"sentinel: {outcome} ({len(pulse.get('alerts') or [])} alert(s))")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
