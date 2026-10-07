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

ANSWERS are the third door, and the narrowest: `"answers"` lists path
prefixes in a repo's own mailbox where Aletheia may write an ANSWER FILE
and nothing else (`check_answer_path`: a granted prefix AND a name ending
.verdict.json, .answer.json or .answers.json). Granted on Shorts-pipeline
by his ruling of 2026-10-07, whose words sit beside the grant; its one
caller is `aletheia.shorts_mailbox`.
"""
from __future__ import annotations

import argparse
import base64
import re
import sys
import urllib.error

from aletheia import gh, journal
from aletheia.fleet import load_fleet

#: The only files the answers door writes: an answer, never a request, an
#: index, a settlement or code.
ANSWER_SUFFIXES = (".verdict.json", ".answer.json", ".answers.json")
_SAFE_PATH = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]*")
#: The push IS the point: it runs the repo's own claim step.
_SKIP_CI = re.compile(r"\[(?:skip|no)[ -]?ci\]|\[ci[ -]?skip\]|\*\*\*NO_CI\*\*\*", re.I)


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
    from aletheia import policy
    policy.ensure_not_halted()
    check_dispatch(fleet, rid, workflow)
    repo = _repo(fleet, rid)
    ref = ref or repo["default_branch"]
    journal.append("action", f"repo:{rid}", f"dispatching {workflow} on {ref}")
    request("POST",
            f"/repos/{fleet['owner']}/{repo['github']}/actions/workflows/{workflow}/dispatches",
            {"ref": ref})


def file_issue(fleet: dict, rid: str, title: str, body: str, request=gh.request) -> dict:
    from aletheia import policy
    policy.ensure_not_halted()
    check_issues(fleet, rid)
    repo = _repo(fleet, rid)
    journal.append("action", f"repo:{rid}", f"filing issue: {title}")
    return request("POST", f"/repos/{fleet['owner']}/{repo['github']}/issues",
                   {"title": title, "body": body})


def answer_prefixes(fleet: dict, rid: str) -> list[str]:
    """The mailbox prefixes granted on `rid`, or [] - no grant, no door."""
    granted = _repo(fleet, rid).get("front_door", {}).get("answers", []) or []
    return [p for p in granted if isinstance(p, str) and p]


def check_answer_path(fleet: dict, rid: str, path: str) -> str:
    """The path, if the registry lets Aletheia write an answer there. Raises
    Refused otherwise - and is called before any network call."""
    p = str(path or "")
    parts = p.split("/")
    if (not _SAFE_PATH.fullmatch(p) or ".." in parts or "" in parts or p.startswith("/")):
        raise Refused(f"{p!r} is not a plain repository path")
    granted = answer_prefixes(fleet, rid)
    if not any(p.startswith(prefix) for prefix in granted):
        raise Refused(f"registry does not allow writing {p!r} on {rid!r} "
                      f"(answers granted under: {granted or 'nothing'}). "
                      "Granting it is a config/fleet.json change.")
    if not p.endswith(ANSWER_SUFFIXES):
        raise Refused(f"{p!r} is not an answer file; only {', '.join(ANSWER_SUFFIXES)} "
                      "may be written through the answers door")
    return p


def _contents_url(fleet: dict, rid: str, path: str) -> str:
    repo = _repo(fleet, rid)
    return f"/repos/{fleet['owner']}/{repo['github']}/contents/{path}"


def read_answer(fleet: dict, rid: str, path: str, request=gh.request) -> tuple[str | None, str | None]:
    """(blob sha, text) of an answer file on the default branch, or (None,
    None) when it does not exist. Grant-checked like a write."""
    check_answer_path(fleet, rid, path)
    branch = _repo(fleet, rid)["default_branch"]
    try:
        got = request("GET", f"{_contents_url(fleet, rid, path)}?ref={branch}")
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None, None
        raise
    if not isinstance(got, dict) or not got.get("sha"):
        return None, None
    text = None
    if got.get("encoding") == "base64" and isinstance(got.get("content"), str):
        text = base64.b64decode(got["content"]).decode("utf-8", "replace")
    return str(got["sha"]), text


def put_answer(fleet: dict, rid: str, path: str, text: str, *, message: str,
               request=gh.request, merge=None) -> dict:
    """Write ONE answer file to the repo's default branch (the Contents API).

    The grant is checked before anything else touches the network. An answer
    already there is never overwritten - a request is answered once - unless
    `merge(existing_text_or_None) -> text` is given, which ADDS to the file
    (the asks mailbox keeps one answers file per day). A sha conflict (409,
    422: someone else wrote in between) is re-read and tried once more."""
    from aletheia import closed, policy
    policy.ensure_not_halted()
    if closed.is_closed():
        raise Refused("Aletheia is closed")
    check_answer_path(fleet, rid, path)
    if _SKIP_CI.search(str(message or "")):
        raise Refused("an answer commit never skips CI: the push is what runs the claim step")
    branch = _repo(fleet, rid)["default_branch"]
    for attempt in range(2):
        sha, existing = read_answer(fleet, rid, path, request=request)
        if sha and merge is None:
            return {"written": False, "path": path, "why": "already answered"}
        body_text = merge(existing) if merge is not None else text
        body = {"message": message, "branch": branch,
                "content": base64.b64encode(body_text.encode("utf-8")).decode("ascii")}
        if sha:
            body["sha"] = sha
        if attempt == 0:
            # Before the attempt, so the memory shows intent even when it fails.
            journal.append("action", f"repo:{rid}", f"answering {path} on {branch}")
        try:
            made = request("PUT", _contents_url(fleet, rid, path), body)
        except urllib.error.HTTPError as exc:
            if exc.code in (409, 422) and attempt == 0:
                continue
            raise
        commit = ((made or {}).get("commit") or {}).get("sha") if isinstance(made, dict) else None
        return {"written": True, "path": path, "commit": commit or ""}
    raise Refused(f"{path} kept changing underneath the write")  # pragma: no cover


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
            print(f"{rid:16} dispatch: {fd.get('dispatch', []) or '—'}  issues: {fd.get('issues', False)}"
                  + (f"  answers: {fd['answers']}" if fd.get("answers") else ""))
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
