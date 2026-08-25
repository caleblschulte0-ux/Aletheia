"""ChatGPT's seat at the table: a validated suggestion inbox with rulings.

ChatGPT reads the fleet briefing and files SUGGESTIONS — one JSON file per
suggestion in `exchange/suggestions/`. It never writes code; a suggestion
that carries a patch is refused by the validator, not merged politely.
Claude rules on each one in the operator's vocabulary (doing / not_doing /
later / in_progress / done), with a real `--because` that gets read back —
same lifecycle the Shorts-pipeline doctor proved out.

Verdicts are durable in `exchange/verdicts.json`, keyed by suggestion id,
so a re-filed idea meets its old ruling instead of a fresh argument.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

from aletheia.fleet import REPO_ROOT, load_fleet

SUGGESTIONS_DIR = REPO_ROOT / "exchange" / "suggestions"
VERDICTS_PATH = REPO_ROOT / "exchange" / "verdicts.json"

VALID_KINDS = {"bug", "fix", "idea", "plan"}
VALID_STATES = {"doing", "not_doing", "later", "in_progress", "done"}
REQUIRED_KEYS = {"id", "filed", "by", "repo", "kind", "title", "detail"}
# A suggestion is prose about the code, never the code itself.
FORBIDDEN_KEYS = {"patch", "diff", "code", "files", "content", "script"}
MAX_BYTES = 16_384


def validate_file(path: Path, fleet: dict) -> list[str]:
    """Return every problem with one suggestion file (empty list = valid)."""
    problems: list[str] = []
    raw = path.read_bytes()
    if len(raw) > MAX_BYTES:
        problems.append(f"{len(raw)} bytes — over the {MAX_BYTES} cap; file prose, not payloads")
    try:
        s = json.loads(raw.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        return problems + [f"not valid JSON: {exc}"]
    if not isinstance(s, dict):
        return problems + ["top level must be an object"]
    missing = REQUIRED_KEYS - set(s)
    if missing:
        problems.append(f"missing keys: {sorted(missing)}")
    forbidden = FORBIDDEN_KEYS & set(s)
    if forbidden:
        problems.append(
            f"forbidden keys {sorted(forbidden)} — suggestions are prose; "
            "code changes are Claude's to make"
        )
    if s.get("id") != path.stem:
        problems.append(f"id {s.get('id')!r} must match filename stem {path.stem!r}")
    if s.get("by") != "chatgpt":
        problems.append("by must be 'chatgpt' — this inbox is its seat, nobody else's")
    if s.get("kind") not in VALID_KINDS:
        problems.append(f"kind {s.get('kind')!r} not in {sorted(VALID_KINDS)}")
    repo = s.get("repo")
    if repo != "fleet" and repo not in fleet["repos"]:
        problems.append(f"repo {repo!r} is not 'fleet' or a fleet registry key")
    return problems


def load_verdicts() -> dict:
    if not VERDICTS_PATH.exists():
        return {}
    return json.loads(VERDICTS_PATH.read_text(encoding="utf-8"))


def save_verdicts(verdicts: dict) -> None:
    VERDICTS_PATH.write_text(json.dumps(verdicts, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def cmd_validate(fleet: dict) -> int:
    files = sorted(SUGGESTIONS_DIR.glob("*.json"))
    bad = 0
    for path in files:
        problems = validate_file(path, fleet)
        if problems:
            bad += 1
            print(f"INVALID {path.name}:")
            for p in problems:
                print(f"  - {p}")
        else:
            print(f"ok      {path.name}")
    print(f"{len(files)} suggestion(s), {bad} invalid")
    return 1 if bad else 0


def cmd_list(fleet: dict, state_filter: str | None) -> int:
    verdicts = load_verdicts()
    for path in sorted(SUGGESTIONS_DIR.glob("*.json")):
        try:
            s = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        v = verdicts.get(s.get("id", ""), {})
        state = v.get("state", "new")
        if state_filter and state != state_filter:
            continue
        print(f"[{state:11}] {s.get('id')}  ({s.get('repo')}/{s.get('kind')}) {s.get('title')}")
        if v.get("because"):
            print(f"              because: {v['because']}")
    return 0


def cmd_rule(sid: str, state: str, because: str) -> int:
    if state not in VALID_STATES:
        print(f"state must be one of {sorted(VALID_STATES)}", file=sys.stderr)
        return 1
    if not because.strip():
        print("a real --because is required — it is quoted back to the reviewer", file=sys.stderr)
        return 1
    if not (SUGGESTIONS_DIR / f"{sid}.json").exists():
        print(f"no suggestion {sid!r} in {SUGGESTIONS_DIR}", file=sys.stderr)
        return 1
    verdicts = load_verdicts()
    verdicts[sid] = {
        "state": state,
        "because": because,
        "ruled": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    save_verdicts(verdicts)
    from aletheia import journal
    journal.append("decision", f"suggestion:{sid}", f"{state} — {because}", actor="claude")
    print(f"{sid} -> {state}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="ChatGPT suggestion inbox.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("validate")
    p_list = sub.add_parser("list")
    p_list.add_argument("--state", choices=sorted(VALID_STATES | {"new"}))
    p_rule = sub.add_parser("rule")
    p_rule.add_argument("id")
    p_rule.add_argument("state")
    p_rule.add_argument("--because", required=True)
    args = ap.parse_args(argv)

    SUGGESTIONS_DIR.mkdir(parents=True, exist_ok=True)
    if args.cmd == "rule":
        return cmd_rule(args.id, args.state, args.because)
    fleet = load_fleet()
    if args.cmd == "validate":
        return cmd_validate(fleet)
    return cmd_list(fleet, args.state)


if __name__ == "__main__":
    raise SystemExit(main())
