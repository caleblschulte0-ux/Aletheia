"""Front-door actions — Aletheia's hands (ROADMAP A7, built gated).

Aletheia may act on a fleet repo ONLY through that repo's own front door
(a workflow dispatch, an issue) and ONLY where the registry explicitly
grants it, per repo, in `front_door`:

    "front_door": {"dispatch": ["pulse.yml"], "issues": true}

The allowlist is the whole safety model, so it is deliberately stingy:
by default only Aletheia's own workflows are dispatchable and only
issue-filing is open on active repos. Widening it is a REGISTRY change —
one JSON edit, reviewed like any other — never a code path around it.
Every action is journaled before it is attempted, so the memory shows
intent even when the API call fails.

Cross-repo actions need FLEET_TOKEN with write scope; without it, calls
fail with GitHub's own error, honestly. Callers today: the operator and
interactive Claude sessions (this CLI). Nothing autonomous dispatches —
the sentinel observes and reports only.
"""
from __future__ import annotations

import argparse
import sys

from aletheia import gh, journal
from aletheia.fleet import load_fleet


class Refused(PermissionError):
    """The registry does not grant this action."""


def _repo(fleet: dict, rid: str) -> dict:
    if rid not in fleet["repos"]:
        raise KeyError(f"{rid!r} is not a fleet registry key")
    return fleet["repos"][rid]


def check_dispatch(fleet: dict, rid: str, workflow: str) -> None:
    allowed = _repo(fleet, rid).get("front_door", {}).get("dispatch", [])
    if workflow not in allowed:
        raise Refused(
            f"registry does not allow dispatching {workflow!r} on {rid!r} "
            f"(allowed: {allowed or 'nothing'}). Granting it is a config/fleet.json change."
        )


def check_issues(fleet: dict, rid: str) -> None:
    if not _repo(fleet, rid).get("front_door", {}).get("issues", False):
        raise Refused(
            f"registry does not allow filing issues on {rid!r}. "
            "Granting it is a config/fleet.json change."
        )


def dispatch(fleet: dict, rid: str, workflow: str, ref: str | None = None,
             request=gh.request) -> None:
    check_dispatch(fleet, rid, workflow)
    repo = _repo(fleet, rid)
    ref = ref or repo["default_branch"]
    journal.append("action", f"repo:{rid}", f"dispatching {workflow} on {ref}")
    request("POST",
            f"/repos/{fleet['owner']}/{repo['github']}/actions/workflows/{workflow}/dispatches",
            {"ref": ref})


def file_issue(fleet: dict, rid: str, title: str, body: str, request=gh.request) -> dict:
    check_issues(fleet, rid)
    repo = _repo(fleet, rid)
    journal.append("action", f"repo:{rid}", f"filing issue: {title}")
    return request("POST", f"/repos/{fleet['owner']}/{repo['github']}/issues",
                   {"title": title, "body": body})


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Act on a fleet repo through its front door.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_d = sub.add_parser("dispatch")
    p_d.add_argument("repo"); p_d.add_argument("workflow"); p_d.add_argument("--ref")
    p_i = sub.add_parser("issue")
    p_i.add_argument("repo"); p_i.add_argument("title"); p_i.add_argument("--body", default="")
    sub.add_parser("grants")
    args = ap.parse_args(argv)

    fleet = load_fleet()
    if args.cmd == "grants":
        for rid, repo in fleet["repos"].items():
            fd = repo.get("front_door", {})
            print(f"{rid:16} dispatch: {fd.get('dispatch', []) or '—'}  issues: {fd.get('issues', False)}")
        return 0
    if not gh.token():
        print("no FLEET_TOKEN/GITHUB_TOKEN — cannot act", file=sys.stderr)
        return 1
    try:
        if args.cmd == "dispatch":
            dispatch(fleet, args.repo, args.workflow, args.ref)
            print(f"dispatched {args.workflow} on {args.repo}")
        else:
            issue = file_issue(fleet, args.repo, args.title, args.body)
            print(f"filed issue #{issue.get('number')} on {args.repo}")
    except Refused as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
