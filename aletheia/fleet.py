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
        for i, vital in enumerate(repo.get("vitals", [])):
            v_where = f"{where}.vitals[{i}]"
            for key in ("label", "file", "probe"):
                if not vital.get(key):
                    problems.append(f"{v_where}: needs {key}")
            if vital.get("probe") not in ("count", "field"):
                problems.append(f"{v_where}: probe {vital.get('probe')!r} not in ['count', 'field']")
            if vital.get("probe") == "field" and not vital.get("path"):
                problems.append(f"{v_where}: a field probe needs a path")
    if problems:
        raise FleetError("fleet registry invalid:\n  " + "\n  ".join(problems))


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
