"""The fleet registry resolver.

`config/fleet.json` is the ONLY place the fleet's composition lives — which
repos exist, what they are for, who acts inside them, and what the pulse
should watch. Everything else (the pulse, the briefing, the interface, the
README table) resolves through here. Never write the fleet's shape anywhere
else; `tests/test_fleet.py` holds the generated README table against this
file so a second copy cannot drift.

A missing or invalid registry fails CLOSED: callers get an exception, not a
guessed fleet.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PATH = REPO_ROOT / "config" / "fleet.json"

VALID_STATUSES = {"active", "stub", "retired"}
VALID_AGENT_KINDS = {"claude", "chatgpt", "ci"}
#: Every key a front door may grant, and the capability it gates. One table:
#: the validator refuses any other key and tests/test_contracts.py holds each
#: registry_grant capability to a real grant here.
FRONT_DOOR_CAPABILITIES = {
    "dispatch": "github.workflow.dispatch",
    "issues": "github.issue.create",
    "answers": "shorts.mailbox.answer",
}
#: His words, beside the grant they made. Not a capability; required with it.
ANSWERS_RULING = "answers_ruling"
#: The answers door reaches a repo's own mailbox and nowhere else.
ANSWERS_ROOT = "exchange/"


class FleetError(ValueError):
    """The registry is missing or structurally invalid."""


def load_fleet(path: Path | str = DEFAULT_PATH) -> dict:
    """Load and validate the registry. Raises FleetError on any problem."""
    path = Path(path)
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise FleetError(f"fleet registry unreadable at {path}: {exc}") from exc
    try:
        fleet = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise FleetError(f"fleet registry is not valid JSON: {exc}") from exc
    validate(fleet)
    return fleet


def validate(fleet: dict) -> None:
    """Structural validation. Raises FleetError with every problem found."""
    problems: list[str] = []
    for key in ("revision", "fleet", "owner", "repos"):
        if key not in fleet:
            problems.append(f"missing top-level key: {key}")
    repos = fleet.get("repos", {})
    if not isinstance(repos, dict) or not repos:
        problems.append("repos must be a non-empty object")
        repos = {}
    seen_github: dict[str, str] = {}
    for rid, repo in repos.items():
        where = f"repos.{rid}"
        for key in ("github", "role", "status", "summary", "default_branch", "agents", "watch"):
            if key not in repo:
                problems.append(f"{where}: missing key {key}")
        status = repo.get("status")
        if status not in VALID_STATUSES:
            problems.append(f"{where}: status {status!r} not in {sorted(VALID_STATUSES)}")
        gh = repo.get("github", "")
        low = gh.lower()
        if low in seen_github:
            problems.append(f"{where}: github name {gh!r} duplicates repos.{seen_github[low]}")
        seen_github[low] = rid
        for i, agent in enumerate(repo.get("agents", [])):
            if agent.get("kind") not in VALID_AGENT_KINDS:
                problems.append(f"{where}.agents[{i}]: kind {agent.get('kind')!r} not in {sorted(VALID_AGENT_KINDS)}")
            if not agent.get("name") or not agent.get("writes"):
                problems.append(f"{where}.agents[{i}]: needs name and writes")
        watch = repo.get("watch", {})
        if not isinstance(watch, dict) or set(watch) != {"workflows", "state_files"}:
            problems.append(f"{where}.watch: must have exactly workflows + state_files")
        if status == "stub" and (watch.get("workflows") or watch.get("state_files")):
            problems.append(f"{where}: a stub has nothing to watch — clear watch or change status")
        fd = repo.get("front_door")
        if fd is not None:
            if not isinstance(fd, dict) or set(fd) - set(FRONT_DOOR_CAPABILITIES) - {ANSWERS_RULING}:
                problems.append(f"{where}.front_door: only {', '.join(FRONT_DOOR_CAPABILITIES)} "
                                "are grantable")
            elif not isinstance(fd.get("dispatch", []), list) or not isinstance(fd.get("issues", False), bool):
                problems.append(f"{where}.front_door: dispatch is a list of workflows, issues a bool")
            else:
                problems += _answers_problems(where, fd)
        for i, vital in enumerate(repo.get("vitals", [])):
            v_where = f"{where}.vitals[{i}]"
            for key in ("label", "file", "probe"):
                if not vital.get(key):
                    problems.append(f"{v_where}: needs {key}")
            if vital.get("probe") not in ("count", "field"):
                problems.append(f"{v_where}: probe {vital.get('probe')!r} not in ['count', 'field']")
            if vital.get("probe") == "field" and not vital.get("path"):
                problems.append(f"{v_where}: a field probe needs a path")
            # PRIVATE means the NUMBER never reaches a committed file. The
            # repo is public; his account balance is not, and which vitals
            # are which is a registry decision rather than something a
            # collector hardcodes about one repo.
            if "private" in vital and not isinstance(vital["private"], bool):
                problems.append(f"{v_where}: private is true or false")
    if problems:
        raise FleetError("fleet registry invalid:\n  " + "\n  ".join(problems))


def _answers_problems(where: str, fd: dict) -> list[str]:
    """`answers` is a list of mailbox prefixes under exchange/, and a grant
    with no words of his beside it is not a grant (as config/rulings.json)."""
    problems: list[str] = []
    answers = fd.get("answers", [])
    if not isinstance(answers, list):
        return [f"{where}.front_door.answers: a list of path prefixes"]
    for prefix in answers:
        parts = prefix.split("/") if isinstance(prefix, str) else []
        if (not isinstance(prefix, str) or not prefix.startswith(ANSWERS_ROOT)
                or not prefix.endswith("/") or prefix == ANSWERS_ROOT
                or ".." in parts or "\\" in prefix or "" in parts[:-1]):
            problems.append(f"{where}.front_door.answers: {prefix!r} is not a mailbox "
                            f"folder under {ANSWERS_ROOT} (e.g. exchange/reviews/)")
    ruling = fd.get(ANSWERS_RULING)
    if answers:
        if not isinstance(ruling, dict) or not str(ruling.get("said") or "").strip() \
                or not str(ruling.get("on") or "").strip():
            problems.append(f"{where}.front_door: an answers grant needs {ANSWERS_RULING} "
                            "with his words (said) and when (on)")
    elif ruling is not None:
        problems.append(f"{where}.front_door: {ANSWERS_RULING} without an answers grant")
    return problems


def markdown_table(fleet: dict) -> str:
    """The table README.md embeds. Generated, never hand-edited."""
    lines = [
        "| Repo | Role | Status | Summary |",
        "|---|---|---|---|",
    ]
    for repo in fleet["repos"].values():
        lines.append(
            f"| `{repo['github']}` | {repo['role']} | {repo['status']} | {repo['summary']} |"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    try:
        fleet = load_fleet()
    except FleetError as exc:
        print(exc, file=sys.stderr)
        return 1
    if "--validate" in argv:
        print(f"fleet registry OK — rev {fleet['revision']}, {len(fleet['repos'])} repos")
        return 0
    if "--markdown" in argv:
        print(markdown_table(fleet))
        return 0
    if "--json" in argv:
        print(json.dumps(fleet, indent=2))
        return 0
    for rid, repo in fleet["repos"].items():
        watch = repo["watch"]
        print(
            f"{rid:16} {repo['status']:7} {repo['role']:20} "
            f"{len(repo['agents'])} agents, watching {len(watch['workflows'])} workflows / "
            f"{len(watch['state_files'])} state files"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
