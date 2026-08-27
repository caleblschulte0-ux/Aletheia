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
  an issue, a note, a plan edit, a re-rulable ruling, or a read-only page
  visit / screenshot on the PC) and leaves a paper trail the operator
  sees in the next brief.
- **Results are idempotent**: a command with a receipt is never run twice.
- **Two runners, one directory, zero races**: LOCAL_KINDS (below) need
  the operator's PC and are executed only by the local Core's sync loop;
  everything else is executed only by the Actions runner. The partition
  is static, so no command ever has two possible executors. Browser
  INTERACTION is not a kind at all — it needs an approval bound to exact
  steps (`aletheia.browse.interact`), which a relayed voice command
  cannot carry.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path

from aletheia import act, gh, journal, plans, policy, suggestions, tasks
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
    "halt":          (set(), {"reason"}),
    "resume":        (set(), set()),
    "approve":       ({"id"}, set()),
    "deny":          ({"id"}, {"because"}),
    "remember":      ({"domain", "key", "value"}, {"memory_kind"}),
    "browse_read":   ({"url"}, set()),
    "browse_shot":   ({"url"}, set()),
    "email_check":   (set(), set()),
    "email_draft":   ({"to", "body"}, {"subject"}),
    # personal-OS verbs (2026-08-26): PC-private state, so all LOCAL_KINDS
    "remind_at":       ({"at", "text"}, set()),
    "remind_daily":    ({"time", "text"}, {"tz"}),
    "watch_email_from": ({"who"}, set()),
    "notify_operator": ({"text"}, {"priority"}),
    "notify_check":    (set(), set()),
    "notify_clear":    (set(), set()),
    "free_time":       ({"day"}, {"tz", "minutes"}),
    "contact_add":     ({"name", "email"}, {"alias"}),
    # The slot for everything that is not a slot (2026-08-27). `text` is
    # whatever the operator actually said; aletheia.planner compiles it
    # into steps expressed in the kinds ABOVE, and every one of those is
    # validated here like any other command. This kind widens what can be
    # SAID, never what may be DONE.
    "intent":          ({"text"}, set()),
    # Reading the screen (Phase §86). LOCAL: the accessibility tree only
    # exists on the PC, and the observation is redacted before it travels.
    "screen_ask":      ({"question"}, {"window"}),
}

# Kinds that need the operator's PC (a real browser, later the desktop).
# The partition is STATIC and disjoint on purpose: the Actions runner
# executes every kind NOT in this set; the local Core executes ONLY the
# kinds in it. Two runners share the commands directory, and receipts are
# the idempotency mechanism — a static partition is what guarantees no
# command can ever be executed by both sides in a race. A local kind with
# no receipt is honestly PENDING: the PC hasn't picked it up (Core off or
# offline), and ChatGPT should say exactly that, not invent an outcome.
LOCAL_KINDS = {"browse_read", "browse_shot", "email_check", "email_draft",
               "remind_at", "remind_daily", "watch_email_from", "notify_check",
               "notify_clear", "free_time", "contact_add", "notify_operator",
               "intent", "screen_ask"}  # both need the PC itself


def validate_kind_args(cmd, fleet: dict) -> list[str]:
    """Validate the inner command object (kind + args). Shared with the
    local Core's /api/command — one grammar, every channel."""
    problems: list[str] = []
    if not isinstance(cmd, dict) or "kind" not in cmd:
        return ["command must be an object with a kind"]
    kind = cmd["kind"]
    if kind not in KIND_ARGS:
        return [f"kind {kind!r} not in {sorted(KIND_ARGS)} — "
                "commands are named slots, never arbitrary asks"]
    required, optional = KIND_ARGS[kind]
    args = set(cmd) - {"kind"}
    if required - args:
        problems.append(f"{kind}: missing args {sorted(required - args)}")
    if args - required - optional:
        problems.append(f"{kind}: unexpected args {sorted(args - required - optional)}")
    repo = cmd.get("repo")
    if repo is not None and repo != "fleet" and repo not in fleet["repos"]:
        problems.append(f"repo {repo!r} is not 'fleet' or a fleet registry key")
    url = cmd.get("url")
    if url is not None and not (isinstance(url, str)
                                and url.startswith(("http://", "https://"))):
        problems.append(f"{kind}: url must be an http(s) URL")
    return problems


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
    return problems + validate_kind_args(c.get("command"), fleet)


def execute_command(cmd: dict, fleet: dict, request=gh.request, quote: str = "") -> str:
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
    if kind == "halt":
        policy.halt(cmd.get("reason", ""), via=ACTOR)
        return "KILL SWITCH ON — nothing acts until resume"
    if kind == "resume":
        policy.resume(via=ACTOR)
        return "resumed"
    if kind == "approve":
        policy.decide(cmd["id"], "APPROVED", via=ACTOR)
        return f"approval {cmd['id']} -> APPROVED"
    if kind == "deny":
        policy.decide(cmd["id"], "DENIED", via=ACTOR, because=cmd.get("because", ""))
        return f"approval {cmd['id']} -> DENIED"
    if kind == "remember":
        from aletheia import memory
        memory.remember(cmd["domain"], cmd["key"], cmd["value"],
                        source=f"operator via intercom: {quote[:120]}",
                        kind=cmd.get("memory_kind", "explicit"))
        return f"remembered {cmd['domain']}.{cmd['key']}"
    if kind == "browse_read":
        from aletheia import browse
        page = browse.read_page(cmd["url"])
        excerpt = " ".join(page["text"].split())[:1200]
        return f"read {page['url']} — {page['title'][:100]} :: {excerpt}"
    if kind == "email_check":
        from aletheia import mail
        return mail.check_unread()
    if kind == "email_draft":
        from aletheia import mail
        d = mail.draft(cmd["to"], cmd.get("subject", ""), cmd["body"],
                       requested_via=f"intercom: {quote[:80]}")
        return (f"draft to {d['to_name']} ready — {d['subject']!r}. "
                f"Approval {d['id']} is pending; approving it sends the email.")
    if kind == "browse_shot":
        from aletheia import browse
        out = REPO_ROOT / "cache" / "browser-captures"
        out.mkdir(parents=True, exist_ok=True)
        stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        target = out / f"shot-{stamp}.png"
        browse.screenshot(cmd["url"], target)
        # media never enters git — the capture stays on the PC, named here
        return f"screenshot of {cmd['url']} saved on the PC at {target}"
    if kind == "remind_at":
        from aletheia import scheduler
        import re as _re, uuid as _uuid
        sid = "remind-" + _uuid.uuid4().hex[:8]
        scheduler.create(sid, {"kind": "notify_operator", "text": cmd["text"]},
                         kind="once", at=cmd["at"])
        return f"reminder {sid} set for {cmd['at']} — {cmd['text'][:80]!r}"
    if kind == "remind_daily":
        from aletheia import scheduler
        import uuid as _uuid
        sid = "remind-daily-" + _uuid.uuid4().hex[:8]
        scheduler.create(sid, {"kind": "notify_operator", "text": cmd["text"]},
                         kind="daily", timezone=cmd.get("tz", "America/Chicago"),
                         time=cmd["time"])
        return f"daily reminder {sid} set for {cmd['time']} — {cmd['text'][:80]!r}"
    if kind == "notify_operator":
        from aletheia import notifications
        notice = notifications.publish("Reminder", cmd["text"], priority="IMPORTANT",
                                       source="reminder")
        return f"reminder surfaced: {notice['id']}"
    if kind == "watch_email_from":
        from aletheia import events as bus, mail as mail_mod
        addr, name = mail_mod.resolve_address(cmd["who"])
        if addr is None:
            return (f"I don't know an address for {name!r} — say "
                    f"'remember person {name} <their address>' first")
        watcher = bus.create_watcher(
            {"kind": "mail.received", "attributes": {"sender": addr.casefold()}},
            note=f"operator asked: tell me when email arrives from {name}",
            created_by="operator-voice", once=True)
        return f"watching for email from {name} — I'll tell you once ({watcher['id']})"
    if kind == "notify_check":
        from aletheia import notifications
        unread = notifications.all_notifications(state="UNREAD")
        if not unread:
            return "Nothing new."
        parts = [f"{n['title']}: {n['body'][:80]}" for n in unread[:5]]
        head = f"{len(unread)} notification{'s' if len(unread) != 1 else ''}. "
        return head + " — ".join(parts)
    if kind == "screen_ask":
        from aletheia import perception
        window = ({"title_re": re.escape(cmd["window"])} if cmd.get("window")
                  else None)
        answer = perception.describe(cmd["question"], window=window)
        return answer["answer"]
    if kind == "intent":
        from aletheia import intents
        record = intents.propose(cmd["text"], quote=quote, fleet=fleet)
        return intents.spoken(record)
    if kind == "notify_clear":
        from aletheia import notifications
        unread = notifications.all_notifications(state="UNREAD")
        for n in unread:
            notifications.set_state(n["id"], "ACKNOWLEDGED")
        return f"cleared {len(unread)} notification{'s' if len(unread) != 1 else ''}"
    if kind == "free_time":
        import datetime as _dt
        from aletheia import calendar as cal
        tz = cmd.get("tz", "America/Chicago")
        minutes = int(cmd.get("minutes", 30))
        day = _dt.date.fromisoformat(cmd["day"])
        slots = cal.free_slots(day, duration_minutes=minutes, timezone=tz)
        if not slots:
            return f"no free {minutes}-minute slot on {cmd['day']} inside work hours"
        spoken = ", ".join(s0[0][11:16] for s0 in slots[:4])
        return f"free on {cmd['day']} at {spoken}" + (" and more" if len(slots) > 4 else "")
    if kind == "contact_add":
        from aletheia import contacts, mail as mail_mod
        import re as _re
        addr, _ = mail_mod.resolve_address(cmd["email"])
        if addr is None or "@" not in addr:
            return f"that didn't sound like an email address: {cmd['email']!r}"
        cid = _re.sub(r"[^a-z0-9]+", "-", cmd["name"].lower()).strip("-") or "person"
        aliases = [cmd["alias"]] if cmd.get("alias") else []
        try:
            contacts.create(cid, cmd["name"].strip(), emails=[addr], aliases=aliases,
                            provenance=f"operator via voice/intercom: {quote[:100]}")
        except FileExistsError:
            contacts.update(cid, emails=[addr])
        return f"remembered {cmd['name']} as {addr} — private contacts only, never the public repo"
    raise ValueError(f"unhandled kind {kind!r}")  # unreachable after validation


def _result_path(path: Path) -> Path:
    return path.with_name(path.stem + ".result.json")


def _peek_kind(path: Path) -> str | None:
    """The command's kind, or None when unreadable (side: cloud receipts those)."""
    try:
        c = json.loads(path.read_text(encoding="utf-8"))
        kind = c.get("command", {}).get("kind")
        return kind if isinstance(kind, str) else None
    except (OSError, json.JSONDecodeError, UnicodeDecodeError, AttributeError):
        return None


def _on_side(path: Path, side: str) -> bool:
    kind = _peek_kind(path)
    if side == "local":
        return kind in LOCAL_KINDS
    # cloud takes everything else, including unreadable files (it owns the
    # invalid-receipt path so garbage never sits pending forever)
    return kind not in LOCAL_KINDS


def pending(commands_dir: Path | None = None, side: str | None = None) -> list[Path]:
    d = commands_dir or COMMANDS_DIR
    if not d.is_dir():
        return []
    paths = [p for p in sorted(d.glob("*.json"))
             if not p.name.endswith(".result.json") and not _result_path(p).exists()]
    if side is not None:
        paths = [p for p in paths if _on_side(p, side)]
    return paths


def run_pending(fleet: dict, request=gh.request, commands_dir: Path | None = None,
                side: str = "cloud") -> list[dict]:
    """Validate + execute every receipt-less command on this side; write receipts.

    side="cloud" (the Actions runner) executes every kind except
    LOCAL_KINDS, which it leaves untouched — no receipt, honestly pending
    for the PC. side="local" (the Core) executes only LOCAL_KINDS. The
    static partition means a command has exactly one possible executor.
    """
    results = []
    for path in pending(commands_dir, side=side):
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
            # the kill switch holds everything except the resume that lifts it
            if policy.halted() and c["command"]["kind"] != "resume":
                result["outcome"] = "halted"
                result["detail"] = "Aletheia is halted — only a resume command executes"
                _write_receipt_and_journal(path, result)
                results.append(result)
                continue
            try:
                result["outcome"] = "done"
                result["detail"] = execute_command(c["command"], fleet, request=request,
                                                   quote=c.get("operator_quote", ""))
            except act.Refused as exc:
                result["outcome"] = "refused"
                result["detail"] = str(exc)
            except Exception as exc:
                result["outcome"] = "error"
                result["detail"] = f"{type(exc).__name__}: {exc}"
        _write_receipt_and_journal(path, result)
        results.append(result)
    return results


def _write_receipt_and_journal(path: Path, result: dict) -> None:
    _result_path(path).write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    journal.append("action", f"intercom:{path.stem}",
                   f"{result['outcome']} — {result['detail']}", actor=ACTOR)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Execute relayed operator commands.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("validate")
    runp = sub.add_parser("run")
    runp.add_argument("--side", choices=["cloud", "local"], default="cloud",
                      help="cloud (Actions, default) or local (the PC Core)")
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
                side = "local" if _on_side(path, "local") else "cloud"
                print(f"[pending] {path.stem}  (waiting on {side})")
        return 0

    results = run_pending(fleet, side=args.side)
    for r in results:
        print(f"{r['id']}: {r['outcome']} — {r['detail']}")
    if not results:
        print("no pending commands")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
