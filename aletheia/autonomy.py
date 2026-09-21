"""Unattended reversible work: the budget, the ledger and the undo.

His continuity brief, Part III item 10, in his words: *"Move from 'reads
autonomous, writes ask Caleb' toward consequence-based authority: temporary
local workspaces, fixing a project in a branch, drafts, tasks, internal project
state, rescheduling its own queued work, notes, running tests, preparing PRs and
other reversible actions may run under standing or bounded authority. Money,
binding commitments, destructive operations, outward communications and
authority changes keep their approval rules. Do not weaken existing safety."*

`tools.consequence` says WHAT an action costs. This module says what may be done
with that, and it is deliberately three small things:

- **A budget.** Reversible is not free: a loop that drafts the same note four
  hundred times costs him a disk and a day of her attention. Every unattended
  action is counted, per session and per day, and past the cap the action stops
  being unattended and becomes an ordinary handoff. The caps are the only
  numbers here that are a judgement rather than a rule.
- **A ledger.** One line per unattended action, in private state, with what it
  was, when, which session asked, and HOW TO UNDO IT - the branch name, the
  file path, the record id. It is what `current_state`, `mission_control` and
  "what did you do without asking me" read; it is not a second journal, because
  the journal already has the line and this has the undo.
- **An undo.** `python -m aletheia.autonomy undo <id>` reverses one. She may
  undo HER OWN reversible actions and nothing else: a decision of his, an
  approval, a handoff and anything outward are all refused here, by name, and
  the refusal is the point of the module rather than an afterthought.

WHAT THIS CANNOT DO, and no flag changes:

- spend. The consequence model marks every spending kind outward
  (`tools.OUTWARD_ALWAYS`), so the budget is never even consulted for one, and
  `webtask.would_spend` still runs at the broker and at execution.
- lift the kill switch. `allow()` refuses while she is halted, before the
  budget is looked at, and fails CLOSED when the switch cannot be read.
- widen itself. The caps are constants; nothing here writes a grant, and
  `authority` is not imported.
- undo him. `undo()` refuses any record it did not write, and it only ever
  writes records of her own unattended actions.

    python -m aletheia.autonomy list
    python -m aletheia.autonomy undo un-3f9c1a2b4d5e
    python -m aletheia.autonomy budget
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import secrets
from typing import Any

from aletheia import stateio

ACTOR = "aletheia-unattended"

#: How much unattended reversible work one session may do before the rest of it
#: goes back to asking him. A session that wants a twenty-fifth reversible write
#: is looping, not working.
SESSION_LIMIT = 24
#: And across every session in a day. Measured against nothing: it is a
#: judgement, set where a busy day of real work fits comfortably under it and a
#: runaway loop hits it in minutes.
DAY_LIMIT = 120
#: How long a ledger day file is kept. The journal keeps the account of what she
#: did forever; this keeps the undo, which goes stale.
KEEP_DAYS = 30
MAX_SAID = 300


class UndoRefused(RuntimeError):
    """This is not hers to undo (and says why)."""


def ledger_dir():
    return stateio.private_dir("unattended")


def _now(now: dt.datetime | None = None) -> dt.datetime:
    return (now or dt.datetime.now(dt.timezone.utc)).astimezone(dt.timezone.utc)


def _stamp(when: dt.datetime) -> str:
    return when.strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse(stamp: object) -> dt.datetime | None:
    try:
        return dt.datetime.strptime(str(stamp), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)
    except (TypeError, ValueError):
        return None


def _day_path(day: str):
    return ledger_dir() / f"{day}.json"


def _read_day(day: str) -> list[dict]:
    """One day's actions. An unreadable day is an EMPTY day here, never an
    error: the ledger must not be able to stop her working, and a day that
    cannot be read is reported by `summary` rather than raised at a caller."""
    try:
        value = stateio.read_json(_day_path(day))
    except (OSError, ValueError):
        return []
    rows = value.get("actions") if isinstance(value, dict) else None
    return [r for r in (rows or []) if isinstance(r, dict)]


def _write_day(day: str, rows: list[dict]) -> None:
    ledger_dir().mkdir(parents=True, exist_ok=True)
    # An OBJECT, not a bare list: `stateio.read_json` refuses anything else, and
    # the version is what lets this shape change later without losing a day.
    stateio.write_json_atomic(_day_path(day), {"version": 1, "day": day, "actions": list(rows)})


def _days(back: int = 7, now: dt.datetime | None = None) -> list[str]:
    today = _now(now).date()
    return [(today - dt.timedelta(days=n)).isoformat() for n in range(back)]


# ---- the ledger ------------------------------------------------------------

def record(*, tool: str, args: dict | None = None, consequence: str, session: str = "",
           said: str = "", undo: dict | None = None, route: str = "",
           now: dt.datetime | None = None) -> dict:
    """One thing she did on her own, written down with how to reverse it.

    Not only the reversible ones. The live pass, 2026-09-18: the ledger said
    "Nothing in the last 48 hours" while a work session had run two test suites,
    made three mirror checkouts, drafted a document and opened a real pull
    request on his repository. A ledger holding only the harmless half of what
    she did cannot answer "what did you do without asking me" - and the half it
    was missing is the half he would want to hear about first. So an OUTWARD act
    belongs in here too: marked outward, said first, never undoable by her, and
    never counted against the unattended budget (it was authorised by its own
    gate, not by that budget).

    Never raises: an action that ran must not become an error because the ledger
    could not be written - but it says so in the returned record."""
    from aletheia import tools as tools_mod
    when = _now(now)
    # FAIL CLOSED on a consequence nobody recognises: unknown means outward,
    # which means not undoable and never described as having stayed here.
    named = str(consequence)
    if named not in tools_mod.CONSEQUENCES:
        named = tools_mod.OUTWARD
    entry = {
        "id": "un-" + secrets.token_hex(6),
        "at": _stamp(when),
        "tool": str(tool),
        "args": _clean(args or {}),
        "consequence": named,
        "session": str(session or ""),
        "route": str(route or ""),
        "said": " ".join(str(said or "").split())[:MAX_SAID],
        "undo": dict(undo or {"how": NONE, "why": "nothing recorded how to reverse it"}),
        "undone": False,
    }
    try:
        day = entry["at"][:10]
        rows = _read_day(day)
        rows.append(entry)
        _write_day(day, rows)
        _prune(when)
    except Exception as exc:                                       # noqa: BLE001
        entry["not_recorded_because"] = f"{type(exc).__name__}: {str(exc)[:120]}"
    return entry


def _clean(args: dict) -> dict:
    from aletheia import sensitivity
    try:
        return json.loads(sensitivity.clean(json.dumps(args, default=str)))
    except Exception:                                              # noqa: BLE001
        return {}


def _prune(now: dt.datetime) -> None:
    keep = set(_days(KEEP_DAYS, now))
    folder = ledger_dir()
    if not folder.is_dir():
        return
    for path in folder.glob("*.json"):
        if path.stem not in keep:
            try:
                path.unlink()
            except OSError:
                pass


def recent(*, hours: float = 48.0, limit: int = 20, session: str = "",
           now: dt.datetime | None = None) -> list[dict]:
    """What she did unattended, newest first."""
    when = _now(now)
    floor = when - dt.timedelta(hours=max(0.0, float(hours)))
    rows: list[dict] = []
    for day in _days(min(KEEP_DAYS, int(hours // 24) + 2), when):
        rows.extend(_read_day(day))
    out = []
    for row in rows:
        at = _parse(row.get("at"))
        if at is None or at < floor:
            continue
        if session and row.get("session") != session:
            continue
        out.append(row)
    out.sort(key=lambda r: str(r.get("at")), reverse=True)
    return out[:max(1, int(limit))]


def load(record_id: str, *, now: dt.datetime | None = None) -> tuple[str, dict]:
    """(day, record) for one id. Raises KeyError when there is none."""
    for day in _days(KEEP_DAYS, now):
        for row in _read_day(day):
            if row.get("id") == str(record_id):
                return day, row
    raise KeyError(f"no unattended action {record_id!r}")


def is_outward(row: dict) -> bool:
    """Did this one reach somebody else, or can it not be taken back?

    Fails CLOSED: a row whose consequence is missing or unrecognised is outward,
    because the only thing worse than an unreversible act is one described as
    reversible."""
    from aletheia import tools as tools_mod
    return str((row or {}).get("consequence") or "") not in tools_mod.UNATTENDED


def counts(*, session: str = "", now: dt.datetime | None = None) -> dict:
    """The unattended budget. OUTWARD rows are in the ledger and NOT in here: an
    outward act passed its own approval or trust gate, so counting it would
    quietly shrink the budget for the reversible work the budget is about - and
    would have changed what she may do the day outward acts began to be
    recorded. Recording something must never change what is permitted."""
    when = _now(now)
    today = [r for r in _read_day(_stamp(when)[:10]) if not is_outward(r)]
    return {"day": len(today), "day_limit": DAY_LIMIT,
            "session": sum(1 for r in today if session and r.get("session") == session),
            "session_limit": SESSION_LIMIT}


# ---- may it run without asking him -----------------------------------------

def _halted(halted=None) -> bool:
    """The kill switch, checked before EVERY unattended action rather than once
    at the top of a session. Fails closed."""
    try:
        if halted is not None:
            return bool(halted())
        from aletheia import policy
        return policy.halted() is not None
    except Exception:                                              # noqa: BLE001
        return True


def allow(tool, *, session: str = "", halted=None, now: dt.datetime | None = None) -> tuple[bool, str]:
    """May this run unattended right now? (ok, why not).

    The order is the safety argument: the consequence first (an outward action
    is never a budget question), then the kill switch, then the budget.
    """
    from aletheia import tools as tools_mod
    if not tools_mod.runs_unattended(tool):
        return False, (f"{getattr(tool, 'name', tool)} is not something I do without asking: "
                       f"its consequence is {getattr(tool, 'consequence', 'unknown')}")
    if _halted(halted):
        return False, "I am halted; only a resume from Caleb lifts that"
    seen = counts(session=session, now=now)
    if session and seen["session"] >= SESSION_LIMIT:
        return False, (f"I have already done {seen['session']} reversible things without asking in this "
                       "session, which is my limit for one session")
    if seen["day"] >= DAY_LIMIT:
        return False, (f"I have already done {seen['day']} reversible things without asking today, "
                       "which is my limit for a day")
    return True, ""


# ---- how to take it back ----------------------------------------------------

#: The ways an unattended action is reversed. Each is DATA on the record, so
#: the undo does not have to re-derive anything from a tool that has since
#: changed. `NONE` is honest rather than absent: the journal is append-only and
#: says so, and a record that cannot be reversed still says what it was.
TASK_CANCEL = "task_cancel"
MEMORY_FORGET = "memory_forget"
FILE_VERSION = "file_version"
SHOPPING_OFF = "shopping_off"
BRANCH = "branch"
NONE = "none"
HOWS = (TASK_CANCEL, MEMORY_FORGET, FILE_VERSION, SHOPPING_OFF, BRANCH, NONE)


def undo_plan(tool, args: dict, result: Any = None) -> dict:
    """How to reverse this action, from the descriptor and the arguments.

    Deliberately narrow. Where there is a real reverse it names the one thing
    that identifies what was made (a task id, a file path, a branch); where
    there is not, it says so in words he can hear, and the ledger line is still
    written - "I cannot take this one back" is the honest answer, and hiding it
    is how a store gets a writer and no reader.
    """
    name = str(getattr(tool, "name", tool) or "")
    args = dict(args or {})
    if name == "task_new" and args.get("id"):
        return {"how": TASK_CANCEL, "task": str(args["id"])}
    if name == "remember" and args.get("domain") and args.get("key"):
        return {"how": MEMORY_FORGET, "domain": str(args["domain"]), "key": str(args["key"])}
    if name in ("file_write", "file_edit", "file_move", "file_delete", "compose", "doc_make"):
        path = str(args.get("path") or args.get("to") or "")
        if path:
            return {"how": FILE_VERSION, "path": path}
    if name == "shopping_add" and args.get("item"):
        return {"how": SHOPPING_OFF, "item": str(args["item"])}
    if name == "notify_operator":
        return {"how": NONE, "why": "a notice I raised stays on your list until you clear it; "
                                    "say clear my notifications"}
    if name == "note":
        return {"how": NONE, "why": "my journal is append-only, so I can add a correction but never "
                                    "remove the line"}
    return {"how": NONE, "why": f"I did not record a way to take {name} back"}


def tools_consequence_local() -> str:
    """`tools.REVERSIBLE_LOCAL`, for callers that record something that is not
    a tool (a branch she prepared) and should not have to import the catalog."""
    from aletheia import tools
    return tools.REVERSIBLE_LOCAL


#: How each unattended action READS OUT. A receipt is not a sentence
#: (CLAUDE.md: "Say it OUT LOUD before you believe the receipt"), and the
#: intercom's own detail for `note` is the single word "journaled" - which, in
#: a list of things she did without asking, tells him nothing at all. The value
#: is a format string over the tool's arguments; anything not named here falls
#: back to the receipt, then to the tool's name.
SAID_AS = {
    "note": "noted: {text}",
    "task_new": "added a task: {description}",
    "task_status": "set the task {id} to {state}",
    "task_done": "ticked off {which}",
    "remember": "remembered your {domain}: {key}",
    "file_write": "wrote {path} in my workspace",
    "file_edit": "edited {path} in my workspace",
    "compose": "wrote {path} in my workspace",
    "doc_make": "made the document {path}",
    "thread_draft": "drafted a message to {to} (nothing sent)",
    "calendar_hold": "pencilled in {title} (a tentative hold in my own calendar, nothing sent)",
    "shopping_add": "put {item} on your list",
    "plan_step": "moved a step of {slug}",
    "notify_operator": "raised a notice: {text}",
    "remind_at": "set a reminder: {text}",
}


def said_for(tool, args: dict, result: Any = None) -> str:
    """One unattended action in a sentence he can hear. Never an identifier on
    its own, never a bare receipt word."""
    name = str(getattr(tool, "name", tool) or "")
    shape = SAID_AS.get(name)
    if shape:
        try:
            said = shape.format_map({k: " ".join(str(v).split()) for k, v in (args or {}).items()})
            return " ".join(said.split())[:MAX_SAID]
        except (KeyError, IndexError, ValueError):
            pass
    try:
        from aletheia import handoffs
        receipt = handoffs._said_result(result)
    except Exception:                                              # noqa: BLE001
        receipt = ""
    receipt = " ".join(str(receipt or "").split())
    if len(receipt) >= 12:
        return receipt[:MAX_SAID]
    return f"ran {name}" + (f" ({receipt})" if receipt else "")


def branch_undo(*, path: str, branch: str, repo: str = "") -> dict:
    """The undo for a branch she prepared in a throwaway checkout: delete the
    branch and drop the workspace. Nothing was pushed, so nothing is un-pushed."""
    return {"how": BRANCH, "path": str(path or ""), "branch": str(branch or ""), "repo": str(repo or "")}


def undo(record_id: str, *, via: str = "operator-cli", now: dt.datetime | None = None) -> dict:
    """Reverse one unattended action of hers. Returns {"undone", "said", ...}.

    Raises `UndoRefused` for anything that is not hers to take back.
    """
    from aletheia import journal, tools as tools_mod
    day, row = load(record_id, now=now)
    if row.get("undone"):
        return {"undone": False, "said": "I already took that one back.", "record": row}
    if row.get("consequence") not in tools_mod.UNATTENDED:
        raise UndoRefused("that one reached the world, so taking it back is not something I can do")
    if str(row.get("decided_by") or "").strip():
        raise UndoRefused("that was your decision, not mine, and I do not undo your decisions")
    plan = dict(row.get("undo") or {})
    how = str(plan.get("how") or NONE)
    if how not in HOWS:
        raise UndoRefused(f"I do not know how to reverse that ({how})")
    if how == NONE:
        raise UndoRefused(str(plan.get("why") or "I did not record a way to take that back"))
    said = _reverse(how, plan)
    row["undone"] = True
    row["undone_at"] = _stamp(_now(now))
    row["undone_via"] = str(via)[:120]
    row["undone_said"] = said[:MAX_SAID]
    rows = [r if r.get("id") != row["id"] else row for r in _read_day(day)]
    _write_day(day, rows)
    try:
        journal.append("action", "unattended", f"{row['id']}: undid {row.get('tool')} - {said[:160]}",
                       actor=ACTOR)
    except Exception:                                              # noqa: BLE001
        pass
    return {"undone": True, "said": said, "record": row}


def _reverse(how: str, plan: dict) -> str:
    if how == TASK_CANCEL:
        from aletheia import tasks
        tasks.set_status(str(plan["task"]), "CANCELLED", "undone: I added this without asking")
        return f"cancelled the task I added ({plan['task']})"
    if how == MEMORY_FORGET:
        from aletheia import memory
        gone = memory.forget(str(plan["domain"]), str(plan["key"]), via=ACTOR)
        return ("forgot what I noted" if gone else "it was already gone")
    if how == FILE_VERSION:
        from aletheia import workspace
        path = str(plan["path"])
        kept = workspace.versions(path)
        if kept:
            workspace.restore(kept[-1])
            return f"put back the version of {path} from before I changed it"
        # Nothing was there before: the file was NEW, so taking it back means
        # removing it - and `workspace.remove` keeps a version first, so even
        # the undo is undoable.
        workspace.remove(path, why="undone: I wrote this without asking")
        return f"removed {path}, which I had made; the copy is kept if you want it back"
    if how == SHOPPING_OFF:
        _run_kind("shopping_off", {"item": str(plan["item"])})
        return f"took {plan['item']} back off the list"
    if how == BRANCH:
        return _drop_branch(plan)
    raise UndoRefused(f"I do not know how to reverse that ({how})")


def _run_kind(kind: str, args: dict) -> str:
    """Reverse something through the one door every channel uses, so the undo
    passes the same gates as the act did."""
    from aletheia import intercom
    from aletheia.fleet import load_fleet
    return str(intercom.execute_command({"kind": kind, **args}, load_fleet(),
                                        quote="undoing something I did without asking"))


def _drop_branch(plan: dict) -> str:
    """Delete a branch she prepared, and drop the throwaway checkout it is in."""
    import shutil
    from pathlib import Path
    from aletheia import investigation as inv
    path, branch = Path(str(plan.get("path") or "")), str(plan.get("branch") or "")
    if not path.is_dir():
        return f"the workspace for {branch or 'that branch'} is already gone"
    if branch:
        inv.git(["switch", "--detach"], path)
        code, said = inv.git(["branch", "-D", branch], path)
        if code != 0:
            return f"the branch {branch} could not be deleted ({inv.clean(said, 120)})"
    try:
        shutil.rmtree(path, ignore_errors=True)
    except OSError:
        pass
    return f"deleted the branch {branch or '(unnamed)'} and threw away the copy of the project I made it in"


# ---- said out loud ----------------------------------------------------------

#: How many are named out loud. A list of everything is a list of nothing
#: (CLAUDE.md: he stops listening at the fourth item).
SPOKEN_LIMIT = 3


def said_line(row: dict) -> str:
    """One unattended action, in a sentence.

    NO IDENTIFIER. This is read out in a room, and `un-3af32fc6a8a4` is not a
    thing a person can say back (CLAUDE.md: "Everything a model writes is going
    to be read out in a room"). The id lives in the ledger and on the screen,
    where the undo command is one click; out loud he says "undo the task you
    added" and the sentence has to be enough to name it.
    """
    what = str(row.get("said") or "").strip() or f"ran {row.get('tool')}"
    what = what.rstrip(".")
    if row.get("undone"):
        return f"{what} - and I took that back"
    return what


def spoken(rows: list[dict] | None = None, *, hours: float = 24.0, limit: int = SPOKEN_LIMIT) -> str:
    """"What did you do without asking me", answered from the ledger.

    The wording used to do its second job - making plain what these cost him -
    by asserting something that is not always true any more: that every one was
    reversible and stayed on this machine. Now the work session's own routes
    record here, some of them REACHED THE WORLD (a pull request on his
    repository is the one that found this), and a sentence claiming otherwise is
    the worst kind of lie: wrong exactly where he is trusting it. The outward
    ones are said FIRST, by name, as the ones that cannot be taken back; the
    reversible ones keep their old sentence, now about themselves only.
    """
    from aletheia import speech
    rows = recent(hours=hours, limit=max(limit, 20)) if rows is None else rows
    if not rows:
        return (f"Nothing in the last {int(hours)} hours. Everything I did either you asked for, "
                "or it is still waiting for your yes.")
    outward = [r for r in rows if is_outward(r)]
    local = [r for r in rows if not is_outward(r)]
    parts: list[str] = []
    if outward:
        shown = outward[:max(1, limit)]
        rest = len(outward) - len(shown)
        parts.append(
            f"{speech.count_phrase(len(outward), 'thing')} in the last {int(hours)} hours reached beyond "
            "this machine, and I cannot take " + ("those" if len(outward) > 1 else "that") + " back: "
            + "; ".join(said_line(r) for r in shown)
            + (f"; and {rest} more" if rest > 0 else "") + ".")
    if local:
        shown = local[:max(1, limit)]
        rest = len(local) - len(shown)
        lead = (("Also, " if outward else "")
                + f"{speech.count_phrase(len(local), 'thing')} in the last {int(hours)} hours, and every "
                  "one of those was reversible and stayed on this machine - nothing was sent, published "
                  "or spent: ")
        tail = f"; and {rest} more." if rest > 0 else "."
        undoable = [r for r in local if not r.get("undone")
                    and (r.get("undo") or {}).get("how") not in (None, NONE)]
        if undoable:
            tail += " Tell me which one to undo and I will take it back."
        parts.append(lead + "; ".join(said_line(r) for r in shown) + tail)
    return " ".join(parts)


def summary(*, hours: float = 24.0, limit: int = 8, now: dt.datetime | None = None) -> dict:
    """The block `current_state` and `mission_control` show. Never raises."""
    try:
        rows = recent(hours=hours, limit=limit, now=now)
        seen = counts(now=now)
    except Exception as exc:                                       # noqa: BLE001
        return {"readable": False, "note": f"the unattended ledger could not be read ({type(exc).__name__})"}
    return {
        "readable": True,
        "hours": hours,
        "count": len(rows),
        "outward": sum(1 for r in rows if is_outward(r)),
        "budget": seen,
        "actions": [{"id": r.get("id"), "at": r.get("at"), "tool": r.get("tool"),
                     "consequence": r.get("consequence"), "said": r.get("said"),
                     "session": r.get("session"), "undone": bool(r.get("undone")),
                     "route": r.get("route", ""), "outward": is_outward(r),
                     "undo": "" if is_outward(r) else
                             (f"python -m aletheia.autonomy undo {r.get('id')}"
                              if (r.get("undo") or {}).get("how") not in (None, NONE)
                              and not r.get("undone") else ""),
                     "why_not_undoable":
                         "it reached beyond this machine, so taking it back is not mine to do"
                         if is_outward(r) else
                         ((r.get("undo") or {}).get("why", "")
                          if (r.get("undo") or {}).get("how") == NONE else "")}
                    for r in rows],
        # The LIST may be long (it is rendered); the SENTENCE names three and
        # counts the rest, because it is read out loud.
        "said": spoken(rows, hours=hours, limit=SPOKEN_LIMIT),
        "note": "" if rows else "nothing has run unattended in this window",
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="What she did without asking, and how to take it back.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_l = sub.add_parser("list", help="the recent unattended actions")
    p_l.add_argument("--hours", type=float, default=48.0)
    p_l.add_argument("--limit", type=int, default=20)
    p_l.add_argument("--json", action="store_true")
    p_u = sub.add_parser("undo", help="reverse one of them")
    p_u.add_argument("id")
    sub.add_parser("budget", help="how much unattended work is left today")
    args = ap.parse_args(argv)
    if args.cmd == "budget":
        print(json.dumps(counts(), indent=1))
        return 0
    if args.cmd == "undo":
        try:
            out = undo(args.id)
        except (KeyError, UndoRefused) as exc:
            # A KeyError prints its argument in quotes, which reads as a bug
            # rather than an answer.
            print(exc.args[0] if isinstance(exc, KeyError) and exc.args else exc)
            return 1
        print(out["said"])
        return 0
    rows = recent(hours=args.hours, limit=args.limit)
    if args.json:
        print(json.dumps(rows, indent=1, ensure_ascii=False))
        return 0
    for row in rows:
        mark = "undone" if row.get("undone") else row.get("consequence")
        print(f"{row.get('at')}  {row.get('id')}  [{mark}]  {row.get('tool')}: {row.get('said')}")
    print(f"\n{spoken(rows, hours=args.hours, limit=len(rows) or 1)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
