"""The intercom — ChatGPT is the operator's voice; this is what hears it.

The operator talks to ChatGPT (the app — voice mode, phone, unlimited,
no API keys). ChatGPT reads the fleet's truth straight from this repo and,
when the operator asks for an ACTION, relays it as one small JSON file in
`exchange/commands/`. `intercom.yml` fires on that push, validates the
command, executes it through the SAME gates the operator would use at a
keyboard, and writes a `<id>.result.json` receipt next to it. ChatGPT
reads the receipt and tells the operator what happened. Contract for the
ChatGPT side: `exchange/INTERCOM.md`.

What keeps this sane (the constitution holds):

- **ChatGPT still never writes code.** A command names a KIND and
  arguments — never a file path, never a script, never a diff. Unknown
  kinds and extra payload keys are refused.
- **The registry still gates the hands.** `dispatch` and `issue` run
  through `aletheia.act`, which checks `front_door` BEFORE any network
  call. A relayed command can do nothing a registry grant doesn't allow.
- **Every command must quote the operator** (`operator_quote`), every
  execution is journaled, and every receipt is committed. A hallucinated
  command is bounded by the allowlist (worst case today: a pulse re-run,
  an issue, a note, a plan edit, a re-rulable ruling) and leaves a paper
  trail the operator sees in the next brief.
- **Results are idempotent**: a command with a receipt is never run twice.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

from aletheia import act, gh, journal, plans, suggestions, tasks
from aletheia.fleet import REPO_ROOT, load_fleet

COMMANDS_DIR = REPO_ROOT / "exchange" / "commands"
MAX_BYTES = 8_192
ACTOR = "operator-via-intercom"

REQUIRED_KEYS = {"id", "filed", "by", "relayed_from", "operator_quote", "command"}

# kind -> exactly these argument keys (a set means required; OPTIONAL maps allow omission)
KIND_ARGS: dict[str, tuple[set[str], set[str]]] = {
    "note":          ({"text"}, set()),
    "dispatch":      ({"repo", "workflow"}, {"ref"}),
    "issue":         ({"repo", "title"}, {"body"}),
    "rule":          ({"id", "state", "because"}, set()),
    "plan_new":      ({"slug", "title", "goal"}, set()),
    "plan_add_step": ({"slug", "text"}, {"repo"}),
    "plan_step":     ({"slug", "n", "state"}, set()),
    "plan_set":      ({"slug", "state"}, {"because"}),
    "task_new":      ({"id", "description"}, {"goal", "worker", "deadline"}),
    "task_status":   ({"id", "state"}, {"note"}),
}


def validate_command(path: Path, fleet: dict) -> list[str]:
    """Every problem with one command file; empty list = valid."""
    problems: list[str] = []
    raw = path.read_bytes()
    if len(raw) > MAX_BYTES:
        problems.append(f"{len(raw)} bytes — over the {MAX_BYTES} cap")
    try:
        c = json.loads(raw.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        return problems + [f"not valid JSON: {exc}"]
    if not isinstance(c, dict):
        return problems + ["top level must be an object"]
    missing = REQUIRED_KEYS - set(c)
    if missing:
        problems.append(f"missing keys: {sorted(missing)}")
    if set(c) - REQUIRED_KEYS:
        problems.append(f"unexpected keys: {sorted(set(c) - REQUIRED_KEYS)}")
    if c.get("id") != path.stem:
        problems.append(f"id {c.get('id')!r} must match filename stem {path.stem!r}")
    if c.get("by") != "chatgpt" or c.get("relayed_from") != "operator":
        problems.append("by must be 'chatgpt' and relayed_from 'operator' — "
                        "the intercom relays the operator's words, nothing else")
    if not str(c.get("operator_quote", "")).strip():
        problems.append("operator_quote is required — the command must carry the operator's words")
    cmd = c.get("command")
    if not isinstance(cmd, dict) or "kind" not in cmd:
        return problems + ["command must be an object with a kind"]
    kind = cmd["kind"]
    if kind not in KIND_ARGS:
        return problems + [f"kind {kind!r} not in {sorted(KIND_ARGS)} — "
                           "the intercom executes named slots, never arbitrary asks"]
    required, optional = KIND_ARGS[kind]
    args = set(cmd) - {"kind"}
    if required - args:
        problems.append(f"{kind}: missing args {sorted(required - args)}")
    if args - required - optional:
        problems.append(f"{kind}: unexpected args {sorted(args - required - optional)}")
    repo = cmd.get("repo")
    if repo is not None and repo != "fleet" and repo not in fleet["repos"]:
        problems.append(f"repo {repo!r} is not 'fleet' or a fleet registry key")
    return problems


def execute_command(cmd: dict, fleet: dict, request=gh.request) -> str:
    """Run one validated command. Returns a human-readable detail line.
    Raises act.Refused / ValueError / KeyError — the caller records them."""
    kind = cmd["kind"]
    if kind == "note":
        journal.append("note", "operator", cmd["text"], actor=ACTOR)
        return "journaled"
    if kind == "dispatch":
        act.dispatch(fleet, cmd["repo"], cmd["workflow"], cmd.get("ref"), request=request)
        return f"dispatched {cmd['workflow']} on {cmd['repo']}"
    if kind == "issue":
        issue = act.file_issue(fleet, cmd["repo"], cmd["title"], cmd.get("body", ""), request=request)
        return f"filed issue #{(issue or {}).get('number', '?')} on {cmd['repo']}"
    if kind == "rule":
        suggestions.rule(cmd["id"], cmd["state"], cmd["because"], actor=ACTOR)
        return f"suggestion {cmd['id']} -> {cmd['state']}"
    if kind == "plan_new":
        plans.new_plan(cmd["slug"], cmd["title"], cmd["goal"])
        return f"plan {cmd['slug']} opened"
    if kind == "plan_add_step":
        plan = plans.add_step(cmd["slug"], cmd["text"], cmd.get("repo"))
        return f"plan {cmd['slug']} step {len(plan['steps'])} added"
    if kind == "plan_step":
        plans.set_step(cmd["slug"], int(cmd["n"]), cmd["state"])
        return f"plan {cmd['slug']} step {cmd['n']} -> {cmd['state']}"
    if kind == "plan_set":
        plans.set_plan(cmd["slug"], cmd["state"], cmd.get("because", ""))
        return f"plan {cmd['slug']} -> {cmd['state']}"
    if kind == "task_new":
        tasks.create(cmd["id"], cmd["description"], goal=cmd.get("goal"),
                     assigned_worker=cmd.get("worker"), deadline=cmd.get("deadline"))
        return f"task {cmd['id']} queued"
    if kind == "task_status":
        t = tasks.set_status(cmd["id"], cmd["state"], cmd.get("note", ""))
        return f"task {cmd['id']} -> {t['status']}"
    raise ValueError(f"unhandled kind {kind!r}")  # unreachable after validation


def _result_path(path: Path) -> Path:
    return path.with_name(path.stem + ".result.json")


def pending(commands_dir: Path | None = None) -> list[Path]:
    d = commands_dir or COMMANDS_DIR
    if not d.is_dir():
        return []
    return [p for p in sorted(d.glob("*.json"))
            if not p.name.endswith(".result.json") and not _result_path(p).exists()]


def run_pending(fleet: dict, request=gh.request, commands_dir: Path | None = None) -> list[dict]:
    """Validate + execute every command without a receipt; write receipts."""
    results = []
    for path in pending(commands_dir):
        result: dict = {
            "id": path.stem,
            "executed_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        problems = validate_command(path, fleet)
        if problems:
            result["outcome"] = "invalid"
            result["detail"] = "; ".join(problems)
        else:
            c = json.loads(path.read_text(encoding="utf-8"))
            try:
                result["outcome"] = "done"
                result["detail"] = execute_command(c["command"], fleet, request=request)
            except act.Refused as exc:
                result["outcome"] = "refused"
                result["detail"] = str(exc)
            except Exception as exc:
                result["outcome"] = "error"
                result["detail"] = f"{type(exc).__name__}: {exc}"
        _result_path(path).write_text(
            json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        journal.append("action", f"intercom:{path.stem}",
                       f"{result['outcome']} — {result['detail']}", actor=ACTOR)
        results.append(result)
    return results


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Execute relayed operator commands.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("validate")
    sub.add_parser("run")
    sub.add_parser("list")
    args = ap.parse_args(argv)

    fleet = load_fleet()
    COMMANDS_DIR.mkdir(parents=True, exist_ok=True)

    if args.cmd == "validate":
        bad = 0
        todo = pending()
        for path in todo:
            problems = validate_command(path, fleet)
            if problems:
                bad += 1
                print(f"INVALID {path.name}: " + "; ".join(problems))
            else:
                print(f"ok      {path.name}")
        print(f"{len(todo)} pending command(s), {bad} invalid")
        return 1 if bad else 0

    if args.cmd == "list":
        for path in sorted(COMMANDS_DIR.glob("*.json")):
            if path.name.endswith(".result.json"):
                continue
            rp = _result_path(path)
            if rp.exists():
                r = json.loads(rp.read_text(encoding="utf-8"))
                print(f"[{r['outcome']:7}] {path.stem}  {r['detail']}")
            else:
                print(f"[pending] {path.stem}")
        return 0

    results = run_pending(fleet)
    for r in results:
        print(f"{r['id']}: {r['outcome']} — {r['detail']}")
    if not results:
        print("no pending commands")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
