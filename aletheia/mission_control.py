"""Mission control: the one screen he reads after hours away.

The brief (docs/JARVIS_BRIEF.md section 5, milestone 5): *come back after
hours away and, from one screen in ten seconds, know: is she running, what
is she doing, what did she accomplish, what failed, what needs me, what
happens next.*

GENERIC FIRST. Operator direction, 2026-09-16: *"jobs should be the current
test case, not the architecture ... Specialized job code is fine as an
optimization, but the intelligence underneath it should stay fluid and
general."* So this module knows nothing about applications. It builds:

- `header`     the state word (IDLE, LISTENING, THINKING, LOOKING, ACTING,
               WAITING, NEEDS YOU, BLOCKED, HALTED), one "doing" sentence,
               one "next" sentence, today's done / problems, and whether it
               is stale - from `current_state.agent`, the approvals, the
               missions' own needs and the Core's heartbeat
- `missions`   one card per thing she is pursuing, whatever it is: a
               budgeted mission (`aletheia.mission`), a charter or plan
               (`plans/`), a durable task (`state/tasks/`), and whatever a
               registered provider adds. Every card has a status, the
               current step, blockers, what's next, receipts, and answers
               "why is this stuck?" from the blockers it recorded
- `needs_you`  approvals plus every mission's blocking needs, counted once
- `ribbon`     what she did, newest first, in sentences, each with the
               receipt it came from one click away (journal, AgentSession
               receipts, and provider lines)
- `eyes`       the browser's site, purpose and stage, and a screenshot
               already on the record (never a new one: reading must not act)
- `details`    per-mission detail views that a provider supplies

PROVIDERS. A mission TYPE that deserves more than the generic card (the job
hunt's pipeline and its "why this one?") plugs in through `registry()`, an
explicit, small table of `Provider`s. A provider reads its own stores once
(`read`) and contributes, purely (`build`), any of: mission cards, needs,
liveness signals, ribbon lines, screenshot candidates and a detail view. A
future mission type adds a provider here and a detail renderer in the page;
it does not fork the screen.

THE BUILDERS ARE PURE. Every builder takes plain dicts and a `now`, and
touches no store, so the tests hold the derivation rather than a fixture
directory. `gather` and the providers' `read` are the only functions that
read.

MODEL PROVENANCE IS A RECEIPT FIELD. A session answered by `ollama:qwen3`
says so inside its receipt; the sentence on the ribbon is hers. The model is
who she hired, not who she is.

Read-only throughout: nothing here approves, submits, halts or launches.
`mission.active()` finishes an expired mission as a side effect, so this
reads `mission.load()` and judges the clock itself.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable

#: The Core writes a heartbeat every sync beat (60s). Past this it is not
#: "running", whatever the page last said.
CORE_STALE_S = 300.0

#: Mission card statuses, in the order the home screen lists them: what
#: needs him, what is stuck, what is moving, then the rest.
STATUSES = ("NEEDS YOU", "BLOCKED", "RUNNING", "WAITING", "OPEN", "PROPOSED", "STOPPED", "DONE")
#: A finished budgeted mission stays on the home screen this long, so "it ran
#: out an hour ago having opened four pull requests" is still visible.
RECENT_S = 24 * 3600.0

RIBBON_LIMIT = 40
GATHER_CACHE_S = 5.0
_GATHERED: dict[str, Any] = {"at": 0.0, "value": None}

def _noise() -> tuple:
    """Journal subjects that are plumbing, not something she did for him.

    ONE list, in `recollection`, because the same journal is read twice —
    here for the screen and there for "what have you been doing" out loud
    — and a subject that is noise in one is noise in the other. Two copies
    drifted: the spoken answer read out "formfill: read 225 fields" and
    this one did not.
    """
    from aletheia import recollection
    return (frozenset(recollection.PLUMBING_HEADS),
            frozenset(recollection.PLUMBING_SUBJECTS))

#: What the ribbon calls each part of her, in words. Providers add theirs.
SUBJECT_LABELS = {
    "core": "Core", "core:sync": "Core", "supervisor": "Core", "access": "Access",
    "followup": "Conversation", "code": "Code", "project": "Projects", "mission": "Mission",
    "agenda": "Requests", "pursue": "Requests", "task": "Tasks", "plan": "Plans",
    "charter": "Projects",
}

_SLUG = re.compile(r"[a-z0-9][a-z0-9-]{0,80}")


# ---- small pure helpers ----------------------------------------------------------

def _parse(stamp: object) -> dt.datetime | None:
    if not stamp:
        return None
    try:
        parsed = dt.datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)


def _age_s(stamp: object, now: dt.datetime) -> float | None:
    when = _parse(stamp)
    return None if when is None else max(0.0, (now - when).total_seconds())


def _stamp(when: dt.datetime) -> str:
    return when.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _words(text: object, limit: int = 240) -> str:
    said = " ".join(str(text or "").split())
    if len(said) <= limit:
        return said
    cut = said[:limit].rsplit(" ", 1)[0]
    return (cut or said[:limit]).rstrip(",;:-") + "..."


def duration_words(seconds: float | None) -> str:
    """"40 seconds", "12 minutes", "3 hours", "2 days"."""
    if seconds is None:
        return "an unknown time"
    s = max(0, int(seconds))
    for size, unit in ((86400, "day"), (3600, "hour"), (60, "minute")):
        if s >= size * (2 if unit == "day" else 1):
            n = round(s / size)
            return f"{n} {unit}{'s' if n != 1 else ''}"
    return f"{s} second{'s' if s != 1 else ''}"


def _plural(n: int, word: str, plural: str | None = None) -> str:
    return f"{n} {word if n == 1 else (plural or word + 's')}"


def _sentence(text: object, limit: int = 220) -> str:
    said = _words(text, limit)
    return (said[:1].upper() + said[1:]) if said else ""


def no_ids(text: object) -> str:
    """A ribbon line with the machine taken out of it — `speech.for_reading`.

    The journal is written for the journal: `policy` records an approval as
    "Requested - browser.interact:9f3c1d2e…", and the ribbon put that on his
    screen verbatim, sha and all, beside a card whose whole point was that
    he never has to read one. It is `speech`'s door because the same lines
    reach him by ear through `needs_you`, and two cleaners drift.
    """
    from aletheia import speech
    return speech.for_reading(text)


# ---- the provider registry ----------------------------------------------------------

@dataclass(frozen=True)
class Provider:
    """One mission type's specialisation of the generic screen.

    `read(ctx)` reads the provider's stores once and returns plain data;
    `build(reading, ctx)` is pure and returns a contribution, any of:

        missions     list of `mission_card(...)` dicts
        claims       approval ids its needs already count (so each is counted once)
        signals      [{"what", "ok", "said", "banner"?}] liveness it can vouch for
        activity     ribbon lines [{"at", "tone", "what", "said", "receipt"}]
        screenshots  Eyes candidates, best first [{"id", "of", "title", "src", "at"}]
        details      {mission_id: {"type": ..., ...}} the detail view's data
        notes        what it could not read

    `ctx` carries `now`, `sections` (current_state), `entries` (journal),
    `halted`, `browser`, `say_time` and `today_floor`.
    """
    type: str
    label: str
    read: Callable[[dict], dict]
    build: Callable[[dict, dict], dict]
    journal_subjects: frozenset = frozenset()   # subjects whose ordinary lines it narrates better
    subject_labels: dict = field(default_factory=dict)
    receipt_kinds: tuple = ()
    receipt: Callable[[str, str], dict | None] | None = None
    screenshot: Callable[[str], Path | None] | None = None


def registry() -> dict[str, Provider]:
    """Every registered mission-type provider, by type. Explicit on purpose:
    adding a type is a visible line here, not a module discovered by name."""
    from aletheia import (mission_browser, mission_conversations, mission_jobs, mission_programs, mission_sessions,
                          mission_studies, mission_work)
    # The job hunt is one type among them, not the screen: any browser goal
    # and any request her sessions handed to him are cards of their own, and
    # the work inventory says what can run now and what waits on what.
    # Conversations she carries (awaiting a reply, a follow-up due, a message
    # waiting for his yes) and what she has pencilled into his calendar.
    providers = (mission_jobs.PROVIDER, mission_browser.PROVIDER, mission_sessions.PROVIDER,
                 mission_work.PROVIDER, mission_programs.PROVIDER, mission_studies.PROVIDER,
                 mission_conversations.PROVIDER)
    return {p.type: p for p in providers}


# ---- the generic mission card -------------------------------------------------------

def why_stuck(status: str, blockers: Iterable[dict], needs: Iterable[dict]) -> str:
    """"Why is this stuck?" from what the mission RECORDED. "" when it isn't."""
    said = [_words(b.get("said"), 200).rstrip(".") for b in blockers if isinstance(b, dict) and b.get("said")]
    if said:
        more = f"; and {len(said) - 3} more" if len(said) > 3 else ""
        return "Stuck because " + "; ".join(said[:3]) + more + "."
    blocking = [n for n in needs if isinstance(n, dict) and n.get("blocking") and n.get("said")]
    if status == "NEEDS YOU" and blocking:
        return "Waiting on you: " + _words(blocking[0]["said"], 200).rstrip(".") + "."
    if status == "BLOCKED":
        return "Marked blocked, but no blocker was recorded."
    return ""


def mission_card(*, id: str, type: str, title: str, status: str, goal: str = "", step: str = "",
                 next: str = "", blockers: Iterable[dict] = (), needs: Iterable[dict] = (),
                 needs_count: int | None = None, progress: dict | None = None,
                 counts: Iterable[dict] = (), receipts: Iterable[dict] = (), updated: object = None,
                 detail: bool = False, in_browser: bool = False, source: str = "",
                 action: dict | None = None, actions: Iterable[dict] = ()) -> dict:
    """The one shape every mission takes on the home screen. Pure.

    `action` is the one command the card's own sentence asks of him
    ({"label", "kind", "args"}), for the page to put a button on
    (2026-09-23: "Nothing moves until you do this" carried no way to say
    he did)."""
    if status not in STATUSES:
        status = "OPEN"
    blockers = [dict(b) for b in blockers if isinstance(b, dict)]
    needs = [dict(n) for n in needs if isinstance(n, dict)]
    blocking = sum(1 for n in needs if n.get("blocking"))
    return {
        "id": str(id), "type": str(type), "title": _words(title, 120), "goal": _words(goal, 300),
        "status": status, "step": _words(step, 200), "next": _words(next, 240),
        "blockers": blockers, "stuck": why_stuck(status, blockers, needs),
        "needs": needs, "needs_count": max(blocking, int(needs_count or 0)),
        "progress": progress, "counts": [dict(c) for c in counts],
        "receipts": [dict(r) for r in receipts], "updated": updated, "detail": bool(detail),
        "in_browser": bool(in_browser), "source": source,
        "action": dict(action) if isinstance(action, dict) and action.get("kind") else {},
        # More than one click when a card honestly has more than one thing he
        # can do (Clear it; open it). `action` stays the first for anything
        # that reads one.
        "actions": [dict(a) for a in actions if isinstance(a, dict) and a.get("kind")],
    }


def budget_mission(record: dict | None, now: dt.datetime) -> dict | None:
    """A budgeted mission (`aletheia.mission`) as a card. Pure.

    A finished one stays for `RECENT_S`; older ones are history."""
    if not isinstance(record, dict) or not record.get("id"):
        return None
    state = str(record.get("state") or "")
    used, ceiling = int(record.get("actions_used") or 0), int(record.get("max_actions") or 0)
    log = [e for e in record.get("log") or [] if isinstance(e, dict)]
    last = log[-1] if log else {}
    blockers: list[dict] = []
    expires = _parse(record.get("expires"))
    if state == "RUNNING":
        if expires is not None and expires <= now:
            status, nxt = "STOPPED", "Nothing: its time ran out."
            blockers.append({"said": f"its time ran out at {_stamp(expires)}", "since": record.get("expires"),
                             "source": "mission record"})
        elif ceiling and used >= ceiling:
            status, nxt = "DONE", "Nothing: its work budget is spent."
        else:
            status = "RUNNING"
            nxt = (f"Keep working until {_stamp(expires) if expires else 'its deadline'} "
                   f"or {max(0, ceiling - used)} more, whichever comes first.")
    else:
        ended = _age_s(record.get("ended_at"), now)
        if ended is None or ended > RECENT_S:
            return None
        status = "DONE" if state == "DONE" else "STOPPED"
        nxt = "Nothing: it has ended."
        if state in ("FAILED", "EXPIRED"):
            blockers.append({"said": str(record.get("ended_because") or state.lower()),
                             "since": record.get("ended_at"), "source": "mission record"})
    return mission_card(
        id=f"mission:{record['id']}", type="mission", title=str(record.get("kind") or "mission").replace("_", " ").capitalize(),
        goal=str(record.get("goal") or ""), status=status, step=_words(last.get("entry"), 200), next=nxt,
        blockers=blockers, progress={"done": used, "total": ceiling, "unit": "actions"},
        receipts=[{"kind": "mission", "id": record["id"], "label": "mission record"}],
        updated=record.get("ended_at") or last.get("at") or record.get("created_at"),
        source="state/private/mission" + (f" - {record.get('ended_because')}" if record.get("ended_because") else ""))


def plan_mission(plan: dict, tasks: Iterable[dict] = ()) -> dict | None:
    """A plan or charter (`plans/`) as a card, with the durable tasks filed
    under it. Pure. Done and dropped plans are not being pursued."""
    if not isinstance(plan, dict) or not plan.get("slug"):
        return None
    state = str(plan.get("state") or "")
    if state not in ("open", "proposed"):
        return None
    steps = [s for s in plan.get("steps") or [] if isinstance(s, dict)]
    done_ns = {s.get("n") for s in steps if s.get("state") == "done"}

    def whose(step: dict) -> str:
        return str(step.get("owner") or "thea")

    def doable(who: str) -> dict | None:
        for s in steps:
            if s.get("state") in ("done", "blocked") or whose(s) != who:
                continue
            if all(n in done_ns for n in s.get("needs") or []):
                return s
        return None

    blockers = [{"said": f"step {s.get('n')} is blocked: {_words(s.get('text'), 140)}", "since": None,
                 "source": "plan step"} for s in steps if s.get("state") == "blocked"]
    needs: list[dict] = []
    tasks = [t for t in tasks if isinstance(t, dict)]
    for t in tasks:
        status = str(t.get("status") or "")
        if status in ("BLOCKED", "FAILED_RETRYABLE"):
            blockers.append({"said": f"task {t.get('id')}: " + _words(t.get("error") or t.get("result")
                                                                    or t.get("description"), 160),
                             "since": t.get("updated_at"), "source": "task"})
        elif status == "WAITING_OPERATOR":
            needs.append({"said": _words(t.get("description"), 180), "blocking": True,
                          "receipt": {"kind": "task", "id": t.get("id")}})
    doing = next((s for s in steps if s.get("state") == "doing"), None)
    hers, his = doable("thea"), doable("caleb")
    running_task = any(str(t.get("status")) == "RUNNING" for t in tasks)
    action: dict = {}
    if his is not None:
        needs.append({"said": f"step {his.get('n')} is yours: {_words(his.get('text'), 160)}",
                      "blocking": hers is None and doing is None,
                      "receipt": {"kind": "plan", "id": plan["slug"]}})
    total, done = len(steps), len(done_ns)
    if state == "proposed":
        status = "PROPOSED"
        needs.insert(0, {"said": "it waits for your yes before anything works on it", "blocking": False,
                         "receipt": {"kind": "plan", "id": plan["slug"]}})
        step, nxt = "", "Nothing works on it until you say yes."
        action = {"label": "Yes, start it", "kind": "plan_set",
                  "args": {"slug": plan["slug"], "state": "open", "because": "he said yes on the Thea page"}}
    elif doing is not None or running_task:
        status = "RUNNING"
        step = _words((doing or {}).get("text"), 200) or "a task under it is running"
        after = hers or his
        nxt = f"Then step {after.get('n')}: {_words(after.get('text'), 160)}" if after and after is not doing \
            else "Finish this step."
    elif total and done == total:
        status, step, nxt = "DONE", "", "Every step is done."
    elif any(n.get("blocking") for n in needs):
        status = "NEEDS YOU"
        step = ""
        first = next(n for n in needs if n.get("blocking"))
        nxt = f"Nothing moves until you do this: {first['said']}."
        if his is not None and his.get("n") is not None:
            action = {"label": "I did it", "kind": "plan_step",
                      "args": {"slug": plan["slug"], "n": int(his["n"]), "state": "done"}}
    elif hers is not None:
        status = "OPEN"
        step = ""
        nxt = f"Her next step ({hers.get('n')}): {_words(hers.get('text'), 180)}"
    elif blockers:
        status, step, nxt = "BLOCKED", "", "Nothing moves until a blocker clears."
    else:
        status, step, nxt = "WAITING", "", "Every open step is waiting on another."
    is_charter = isinstance(plan.get("project"), dict)
    return mission_card(
        id=f"plan:{plan['slug']}", type="charter" if is_charter else "plan",
        title=str(plan.get("title") or plan["slug"]), goal=str(plan.get("goal") or ""), status=status,
        step=step, next=nxt, blockers=blockers, needs=needs,
        progress={"done": done, "total": total, "unit": "steps"} if total else None,
        receipts=[{"kind": "plan", "id": plan["slug"], "label": "plan"}]
        + [{"kind": "task", "id": t.get("id"), "label": f"task {t.get('id')}"} for t in tasks[:3]],
        updated=max([str(t.get("updated_at") or "") for t in tasks] + [str(plan.get("created") or "")]) or None,
        source=f"plans/{plan['slug']}.json", action=action)


TASK_STATUS = {"RUNNING": "RUNNING", "WAITING_OPERATOR": "NEEDS YOU", "BLOCKED": "BLOCKED",
               "FAILED_RETRYABLE": "BLOCKED", "WAITING_EXTERNAL": "WAITING",
               "WAITING_DEPENDENCY": "WAITING", "RETRY_SCHEDULED": "WAITING",
               "QUEUED": "OPEN", "READY": "OPEN"}
TASK_TERMINAL = ("COMPLETED", "CANCELLED", "FAILED_TERMINAL")


def task_mission(task: dict, index: dict | None = None) -> dict | None:
    """A durable task that belongs to no plan, as its own card. Pure."""
    if not isinstance(task, dict) or not task.get("id") or task.get("status") in TASK_TERMINAL:
        return None
    index = index or {}
    raw = str(task.get("status") or "")
    status = TASK_STATUS.get(raw, "OPEN")
    blockers: list[dict] = []
    needs: list[dict] = []
    if raw in ("BLOCKED", "FAILED_RETRYABLE"):
        blockers.append({"said": _words(task.get("error") or task.get("result") or "no reason recorded", 200),
                         "since": task.get("updated_at"), "source": "task"})
    waiting_on = [d for d in task.get("dependencies") or [] if (index.get(d) or {}).get("status") != "COMPLETED"]
    if waiting_on:
        blockers.append({"said": "waiting on " + ", ".join(waiting_on[:3]), "since": None, "source": "dependencies"})
        if status == "OPEN":
            status = "WAITING"
    if raw == "WAITING_OPERATOR":
        # The description is the ask; `result` is the history of how it got here.
        needs.append({"said": _words(task.get("description") or task.get("result"), 200), "blocking": True,
                      "receipt": {"kind": "task", "id": task["id"]}})
    action = ({"label": "I did it", "kind": "task_done",
               "args": {"which": str(task.get("description") or task["id"])}}
              if raw == "WAITING_OPERATOR" else {})
    nxt = {"RUNNING": "Finish it.", "NEEDS YOU": "Nothing moves until you do your part.",
           "BLOCKED": "Nothing moves until the blocker clears.",
           "WAITING": "Pick it up when what it waits on arrives.",
           "OPEN": "Queued; nothing is working on it yet."}.get(status, "")
    if task.get("deadline"):
        nxt = (nxt + f" Due {task['deadline']}.").strip()
    return mission_card(
        id=f"task:{task['id']}", type="task", title=str(task.get("description") or task["id"]),
        goal=str(task.get("goal") or ""), status=status, step="", next=nxt, blockers=blockers, needs=needs,
        receipts=[{"kind": "task", "id": task["id"], "label": f"task {task['id']}"}],
        updated=task.get("updated_at"), source="state/tasks", action=action)


def generic_missions(*, mission_record: dict | None, plans: Iterable[dict], tasks: Iterable[dict],
                     now: dt.datetime) -> list[dict]:
    """Every mission the generic stores hold. Pure."""
    plans = [p for p in plans if isinstance(p, dict)]
    tasks = [t for t in tasks if isinstance(t, dict)]
    index = {t.get("id"): t for t in tasks}
    slugs = {p.get("slug") for p in plans}
    out: list[dict] = []
    card = budget_mission(mission_record, now)
    if card:
        out.append(card)
    for plan in plans:
        mine = [t for t in tasks if t.get("goal") == plan.get("slug") and t.get("status") not in TASK_TERMINAL]
        card = plan_mission(plan, mine)
        if card:
            out.append(card)
    for task in tasks:
        if task.get("goal") in slugs:
            continue
        card = task_mission(task, index)
        if card:
            out.append(card)
    return out


def order_missions(missions: Iterable[dict]) -> list[dict]:
    """What needs him, what is stuck, what is moving; newest first within each."""
    rows = sorted(missions, key=lambda m: str(m.get("updated") or ""), reverse=True)
    return sorted(rows, key=lambda m: STATUSES.index(m["status"]) if m.get("status") in STATUSES else len(STATUSES))


def needs_list(missions: Iterable[dict], approvals: Iterable[dict]) -> list[dict]:
    """What needs him, flat: approvals first (they carry buttons elsewhere),
    then every mission's blocking needs. Pure."""
    out = [{"said": _words(a.get("label") or a.get("consequence") or a.get("requested_action") or a.get("id"), 200),
            "kind": "approval", "id": a.get("id"), "mission": None, "title": "Approval"}
           for a in approvals if isinstance(a, dict)]
    for m in missions:
        for n in m.get("needs") or []:
            if n.get("blocking"):
                out.append({"said": n.get("said"), "kind": "mission", "id": m["id"], "mission": m["id"],
                            "title": m.get("title"), "receipt": n.get("receipt"),
                            "approval": n.get("approval") or None})
    return out


# ---- the header ------------------------------------------------------------------------

def header(agent: dict, *, now: dt.datetime, core: dict, missions: Iterable[dict] = (),
           approvals: int = 0, signals: Iterable[dict] = (), today: dict | None = None,
           say_time: Callable | None = None, brains: str = "") -> dict:
    """"What is Thea doing right now?" - the state word, doing, next, stale.

    `agent` is `current_state.agent`'s block; `core` is {"heartbeat_age_s",
    "alive"}; `missions` are ordered cards; `approvals` counts the pending
    approvals no mission already counts; `signals` are the providers'
    liveness. Pure, and goal-agnostic: nothing here knows what a mission is
    about.
    """
    from aletheia.current_state import AGENT_STATES
    missions = list(missions)
    state = str(agent.get("state") or "IDLE")
    if state not in AGENT_STATES:
        state = "IDLE"
    step = _words(agent.get("step"), 180)
    mission = _words(agent.get("mission"), 80)
    mission_needs = sum(int(m.get("needs_count") or 0) for m in missions)
    needs_total = int(approvals or 0) + mission_needs
    if state in ("IDLE", "WAITING", "LISTENING") and needs_total:
        state = "NEEDS YOU"
    if state == "NEEDS YOU" and needs_total:
        parts = [_plural(int(m["needs_count"]), "thing") + f" for {_words(m['title'], 48)}"
                 for m in missions if m.get("needs_count")]
        if approvals:
            parts.insert(0, _plural(int(approvals), "approval"))
        step = " and ".join(parts[:3]) + (f" and {len(parts) - 3} more" if len(parts) > 3 else "")
        mission = "waiting on you"
    what = (step or mission).rstrip(". ")
    running = [m for m in missions if m.get("status") == "RUNNING"]

    doing = {
        "HALTED": "Halted" + (f": {step.rstrip('. ')}" if step else "") + ". Nothing acts until you resume her.",
        "IDLE": "Nothing in flight right now.",
        "ACTING": f"Working: {what}.",
        "LOOKING": f"Looking: {what}.",
        "THINKING": f"Thinking: {what}.",
        "BLOCKED": f"Stuck: {what}.",
        "NEEDS YOU": f"Waiting on you: {what}.",
        "WAITING": f"Waiting on the world: {what}.",
        "LISTENING": "Listening: the microphone is open.",
    }[state]
    if state == "IDLE" and running:
        first = running[0]
        doing = f"Between steps: {first['title']} is running" + (f" ({first['step']})" if first.get("step") else "") + "."

    def first_need() -> tuple[str, int]:
        for m in missions:
            for n in m.get("needs") or []:
                if n.get("blocking"):
                    said, title = _words(n["said"], 160), str(m["title"]).removesuffix("...")
                    # a task's need IS its title; say it once
                    return (said if said.startswith(title[:40]) else f"{_words(title, 48)}: {said}"), mission_needs
        return "", 0

    if state == "HALTED":
        nxt = "Nothing, until you resume her."
    elif state == "THINKING":
        nxt = "Your answer appears in the conversation when it is ready."
    elif state == "NEEDS YOU":
        said, _n = first_need()
        if said:
            more = needs_total - 1
            nxt = said.rstrip(". ") + (f" (and {more} more)" if more > 0 else "") + "."
        else:
            # Not the count again: "Waiting on you: 41 approvals. Next: 41
            # approvals waiting for your yes or no." said one thing twice
            # in two type sizes. What happens next is what his answer does.
            nxt = "Say yes or no to each one below. Nothing happens until you do."
    elif state == "BLOCKED":
        stuck = next((m for m in missions if m.get("status") == "BLOCKED"), None)
        nxt = (stuck.get("next") or stuck.get("stuck") or "") if stuck else ""
        nxt = nxt or "Nothing moves until what blocks her clears."
    elif state in ("ACTING", "LOOKING"):
        owner = next((m for m in missions if m.get("in_browser")), None) or (running[0] if running else None)
        nxt = (owner or {}).get("next") or "Finish this step."
    else:
        moving = running[0] if running else next((m for m in missions if m.get("status") in ("WAITING", "OPEN")
                                                  and m.get("next")), None)
        nxt = f"{moving['title']}: {moving['next']}" if moving else "Nothing is scheduled."

    age = core.get("heartbeat_age_s")
    core_ok = bool(core.get("alive")) and age is not None and age <= CORE_STALE_S
    all_signals = [{
        "what": "core", "ok": core_ok,
        "said": (f"Core heartbeat {duration_words(age)} old" if age is not None
                 else "the Core has never recorded a heartbeat"),
    }] + [dict(s) for s in signals if isinstance(s, dict)]
    banner = ""
    # A sentence that names a problem carries what to DO about it (his
    # words, 2026-09-23: "there should be like a link afterwards to like
    # restart stuff... Everything should be one click"). The page renders
    # the action as a button that sends this command; the words stay here.
    action: dict = {}
    if not core_ok:
        banner = ("The Core's heartbeat is " + (f"{duration_words(age)} old" if age is not None else "missing")
                  + ": this screen may be out of date and nothing may be running.")
        action = {"label": "Restart her", "kind": "restart"}
    else:
        loud = next((s for s in all_signals if s.get("banner")), None)
        banner = str(loud["banner"]) if loud else ""
        action = dict(loud.get("action") or {}) if loud else {}
    today = today or {}
    done, problems = int(today.get("done") or 0), int(today.get("problems") or 0)
    return {"state": state, "doing": doing, "next": nxt, "since": agent.get("since"),
            "mission": mission, "stale": not core_ok, "banner": banner, "action": action,
            # Who is thinking, and how that is going (current_state.brains_words).
            "brains": _words(brains, 240),
            "signals": [{k: v for k, v in s.items() if k != "banner"} for s in all_signals],
            "needs_you": needs_total, "needs_you_parts": {"approvals": int(approvals or 0), "missions": mission_needs},
            "today": {"done": done, "problems": problems,
                      "said": (f"Today: {_plural(done, 'thing')} done, {_plural(problems, 'problem')}."
                               if done or problems else "Today: nothing done or failed yet.")},
            "as_of": _stamp(now)}


# ---- the activity ribbon -------------------------------------------------------------

def journal_id(entry: dict) -> str:
    raw = json.dumps([entry.get("ts"), entry.get("subject"), entry.get("text")], ensure_ascii=False)
    return "j-" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]


def session_lines(sessions: Iterable[dict]) -> list[dict]:
    """AgentSession receipts as ribbon lines. Pure. The model that answered
    is in the receipt, never in the sentence."""
    items = []
    for session in sessions:
        if not isinstance(session, dict) or not session.get("id") or not session.get("saved_at"):
            continue
        question = _words(session.get("question"), 120)
        looked = [s.get("tool") for s in (session.get("sources") or []) if isinstance(s, dict)]
        outcome = str(session.get("outcome") or "")
        if outcome == "running":
            continue            # still answering: its card says so, and it has done nothing yet
        if outcome == "answered":
            said = f"Answered “{question}”" + (f" after looking at {', '.join(looked[:3])}" if looked
                                                          else " without looking anything up")
        elif outcome == "handed_off":
            said = f"Handed “{question}” to you: it needs your decision"
        elif outcome == "refused_at_door":
            said = f"Refused “{question}”: it asks to spend money"
        else:
            said = f"Couldn't finish “{question}” ({outcome.replace('_', ' ') or 'no outcome'})"
        items.append({"at": session["saved_at"],
                      "tone": "info" if outcome in ("answered", "handed_off", "refused_at_door") else "alert",
                      "what": "Conversation", "said": said + ".",
                      "receipt": {"kind": "session", "id": session["id"]}})
    return items


def ribbon(*, journal_entries: Iterable[dict], sessions: Iterable[dict] = (), extra: Iterable[dict] = (),
           skip_subjects: Iterable[str] = (), labels: dict | None = None,
           limit: int | None = RIBBON_LIMIT) -> list[dict]:
    """What she did, newest first, one sentence each, receipt attached. Pure.

    `extra` is provider lines; `skip_subjects` are journal subjects whose
    ordinary lines a provider narrates better (alerts are always kept)."""
    names = dict(SUBJECT_LABELS)
    names.update(labels or {})
    skip = set(skip_subjects)
    noise_heads, noise_subjects = _noise()
    items: list[dict] = []
    for entry in journal_entries:
        subject = str(entry.get("subject") or "")
        head = subject.split(":")[0]
        kind = str(entry.get("kind") or "")
        if (head in noise_heads or subject in noise_subjects
                or (subject == "access" and kind != "alert")):
            continue
        if subject in skip and kind != "alert":
            continue
        said = _sentence(entry.get("text") or "")
        if not said or not entry.get("ts"):
            continue
        items.append({"at": entry["ts"], "tone": "alert" if kind == "alert" else "info",
                      "what": names.get(subject) or names.get(head) or (head.capitalize() or "Journal"),
                      "said": said, "receipt": {"kind": "journal", "id": journal_id(entry)}})
    items.extend(session_lines(sessions))
    items.extend(i for i in extra if isinstance(i, dict) and i.get("at") and i.get("receipt"))
    items.sort(key=lambda i: str(i.get("at") or ""), reverse=True)
    # ONE door for every line, whoever wrote it — the journal, a session
    # receipt or a provider. A digest on his screen is a digest on his
    # screen no matter which of the three put it there.
    for item in items:
        item["said"] = no_ids(item.get("said"))
    return items if limit is None else items[:max(0, int(limit))]


def today_tally(items: Iterable[dict], floor: str) -> dict:
    """Done and problems since `floor`, from the ribbon's own lines. Pure."""
    rows = [i for i in items if floor and str(i.get("at") or "") >= floor]
    return {"done": sum(1 for i in rows if i.get("tone") == "good"),
            "problems": sum(1 for i in rows if i.get("tone") == "alert")}


# ---- eyes ------------------------------------------------------------------------------

def eyes(browser: dict, *, screenshots: Iterable[dict] = ()) -> dict:
    """The browser's site, purpose and stage, and the best screenshot on record. Pure."""
    browser = browser or {}
    out = {"active": bool(browser.get("active")), "site": browser.get("site") or "",
           "purpose": browser.get("purpose") or "", "stage": browser.get("stage") or "",
           "since": browser.get("since"), "readable": browser.get("readable", True),
           "screenshot": None, "last": None}
    last = browser.get("last") if isinstance(browser.get("last"), dict) else None
    if last:
        out["last"] = {"site": last.get("site") or "", "what": last.get("what") or "",
                       "title": last.get("what") or "", "state": last.get("state"), "at": last.get("at")}
    for shot in screenshots:
        if isinstance(shot, dict) and shot.get("src"):
            out["screenshot"] = dict(shot)
            break
    return out


# ---- reading the stores (the only impure part) ----------------------------------------

def _sessions(limit: int = 30) -> list[dict]:
    from aletheia import stateio
    try:
        directory = stateio.private_dir("agent-sessions")
        paths = sorted(directory.glob("agent-*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    except Exception:
        return []
    out = []
    for path in paths[:limit]:
        try:
            out.append(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            continue
    return out


def gather(now: dt.datetime | None = None, *, fresh: bool = False,
           providers: dict[str, Provider] | None = None) -> dict:
    """Everything the mission screen shows, read once. Never raises."""
    clock = time.monotonic()
    cacheable = providers is None
    if cacheable and not fresh and _GATHERED["value"] is not None and clock - _GATHERED["at"] < GATHER_CACHE_S:
        return json.loads(json.dumps(_GATHERED["value"]))
    from aletheia import current_state, journal, liveness, policy
    now = (now or dt.datetime.now(dt.timezone.utc)).astimezone(dt.timezone.utc)
    notes: list[str] = []

    def attempt(name: str, fn: Callable[[], Any], fallback: Any) -> Any:
        # One part that cannot be read or built must not blank the whole
        # screen: it says so in `notes` and the rest renders.
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001
            notes.append(f"{name} could not be read ({type(exc).__name__})")
            return fallback

    # FRESH means fresh all the way down: the sections cache is three seconds
    # long, and a screen asked to refresh that showed a three-second-old
    # answer is a screen that disagrees with the store it is rendering.
    derived = attempt("her current state", lambda: current_state.sections(now, fresh=fresh), {})
    hunt = derived.get("job_hunt") or {}
    browser = derived.get("browser") or {}
    entries = attempt("the journal", lambda: journal.entries()[-600:], [])
    pending = attempt("the approvals", lambda: [a for a in policy.all_approvals() if a.get("state") == "PENDING"], [])
    halt = attempt("the kill switch", policy.halted, None)

    def read_tasks() -> list[dict]:
        from aletheia import tasks
        return tasks.all_tasks()

    def read_plans() -> list[dict]:
        from aletheia import plans
        return plans.all_plans()

    def read_mission() -> dict | None:
        from aletheia import mission
        return mission.load()

    all_tasks = attempt("the tasks", read_tasks, [])
    waiting_operator = [t for t in all_tasks if t.get("status") == "WAITING_OPERATOR"]
    agent = derived.get("agent") or {}
    agent = attempt("her agent state", lambda: current_state.agent(
        now, hunt=hunt, browsing=browser, pending_approvals=pending, waiting_operator=waiting_operator), agent)
    age = attempt("the heartbeat", liveness.age_seconds, None)
    core = {"heartbeat_age_s": None if age is None else round(age, 1),
            "alive": bool(age is not None and age <= CORE_STALE_S)}
    try:
        from aletheia import reasoner
        say_time = reasoner.spoken_time
    except Exception:
        say_time = None
    ctx = {"now": now, "sections": derived, "entries": entries, "halted": bool(halt), "browser": browser,
           "say_time": say_time, "today_floor": attempt("the day", lambda: current_state.today_started(now), "")}

    missions = attempt("the generic missions", lambda: generic_missions(
        mission_record=read_mission(), plans=read_plans(), tasks=all_tasks, now=now), [])
    claims: set[str] = set()
    signals: list[dict] = []
    extra: list[dict] = []
    shots: list[dict] = []
    details: dict[str, Any] = {}
    skip: set[str] = set()
    labels: dict[str, str] = {}
    registered = providers if providers is not None else attempt("the provider registry", registry, {})
    for provider in registered.values():
        skip |= set(provider.journal_subjects)
        labels.update(provider.subject_labels)
        reading = attempt(f"the {provider.label} stores", lambda p=provider: p.read(ctx), None)
        if reading is None:
            continue
        notes.extend(str(n) for n in (reading.get("notes") or []))
        part = attempt(f"the {provider.label} view", lambda p=provider, r=reading: p.build(r, ctx), {})
        missions.extend(m for m in part.get("missions") or [] if isinstance(m, dict))
        claims |= {str(c) for c in part.get("claims") or []}
        signals.extend(part.get("signals") or [])
        extra.extend(part.get("activity") or [])
        shots.extend(part.get("screenshots") or [])
        details.update(part.get("details") or {})

    # POWER, for every kind of work: a laptop that sleeps on battery silences
    # all of it, so the header says so whatever is running.
    working = bool(browser.get("active")) or any(m.get("status") == "RUNNING" for m in missions)
    try:
        from aletheia import power
        power_signal = power.signal(derived.get("power"), working=working)
    except Exception:
        power_signal = None
    if power_signal:
        signals.append(power_signal)
    missions = order_missions(missions)
    unclaimed = [a for a in pending if str(a.get("id")) not in claims]
    lines = attempt("the activity ribbon", lambda: ribbon(
        journal_entries=entries, sessions=_sessions(), extra=extra, skip_subjects=skip, labels=labels,
        limit=None), [])
    today = today_tally(lines, ctx["today_floor"])
    value = {
        "version": 2,
        "as_of": _stamp(now),
        "header": attempt("the header", lambda: header(
            agent, now=now, core=core, missions=missions, approvals=len(unclaimed), signals=signals,
            today=today, say_time=say_time,
            brains=str((derived.get("brains") or {}).get("said") or "")),
            {"state": "IDLE", "doing": "Her state could not be read.", "next": "", "stale": True,
             "banner": "The header could not be built from her state.", "signals": [], "needs_you": 0}),
        "missions": missions,
        "needs_you": needs_list(missions, unclaimed),
        "ribbon": lines[:RIBBON_LIMIT],
        "eyes": attempt("eyes", lambda: eyes(browser, screenshots=shots),
                        {"active": False, "site": "", "purpose": "", "stage": "", "readable": False,
                         "screenshot": None, "last": None}),
        "details": details,
        "providers": [{"type": p.type, "label": p.label} for p in registered.values()],
        "code": derived.get("code"),
        # WHAT SHE DID WITHOUT ASKING, on the screen he already looks at. Not a
        # mission card: none of it is waiting on him, and putting it in the
        # needs-you column would teach him to ignore that column. A short list
        # with the command that undoes each one (continuity brief item 10).
        "unattended": derived.get("unattended") or attempt(
            "what ran unattended", lambda: current_state.unattended(now),
            {"readable": False, "note": "the unattended ledger could not be read"}),
        "notes": notes,
    }
    value = json.loads(json.dumps(value, default=str))
    if cacheable:
        _GATHERED.update({"at": clock, "value": value})
    return json.loads(json.dumps(value))


def forget_cache() -> None:
    _GATHERED.update({"at": 0.0, "value": None})


def receipt(kind: str, ident: str, *, providers: dict[str, Provider] | None = None) -> dict | None:
    """The record a ribbon line or a card came from. None when there is none."""
    from aletheia import stateio
    kind = str(kind or "")
    ident = str(ident or "")
    try:
        if kind == "session":
            path = stateio.private_dir("agent-sessions") / f"{stateio.safe_id(ident, name='session id')}.json"
            record = json.loads(path.read_text(encoding="utf-8"))
            return {"kind": kind, "id": ident, "record": record,
                    # who she hired to think, said as what it is
                    "provenance": {"model": record.get("model") or "", "basis": record.get("basis") or "",
                                   "sources": record.get("sources") or []}}
        if kind == "journal":
            from aletheia import journal
            for entry in reversed(journal.entries()[-3000:]):
                if journal_id(entry) == ident:
                    return {"kind": kind, "id": ident, "record": entry}
            return None
        if kind == "mission":
            from aletheia import mission
            record = mission.load()
            if not record or record.get("id") != ident:
                return None
            return {"kind": kind, "id": ident,
                    "record": {k: v for k, v in record.items() if k != "machine_binding"}}
        if kind == "plan":
            if not _SLUG.fullmatch(ident):
                return None
            from aletheia import plans
            return {"kind": kind, "id": ident, "record": plans.load(ident)}
        if kind == "task":
            if not _SLUG.fullmatch(ident):
                return None
            from aletheia import tasks
            return {"kind": kind, "id": ident, "record": tasks.load(ident)}
    except (OSError, ValueError, KeyError):
        return None
    registered = providers if providers is not None else registry()
    for provider in registered.values():
        if kind in provider.receipt_kinds and provider.receipt is not None:
            try:
                return provider.receipt(kind, ident)
            except (OSError, ValueError, KeyError):
                return None
    return None


def screenshot_for(ident: str, *, providers: dict[str, Provider] | None = None) -> Path | None:
    """A screenshot a provider already has on record. Never takes one."""
    registered = providers if providers is not None else registry()
    for provider in registered.values():
        if provider.screenshot is None:
            continue
        try:
            found = provider.screenshot(str(ident or ""))
        except (OSError, ValueError, KeyError):
            found = None
        if found is not None:
            return found
    return None


def main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="What the mission screen shows, as JSON.")
    ap.add_argument("part", nargs="?", help="header, missions, needs_you, ribbon, eyes, details; omit for all")
    args = ap.parse_args(argv)
    value = gather(fresh=True)
    if args.part:
        value = value.get(args.part, {"error": f"no part {args.part!r}"})
    print(json.dumps(value, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
