"""Her work inventory on the mission screen: what can run now, what waits on what.

Continuity brief II.3 and rule 3: every unfinished item has a reason and a next
condition, and "work on my projects" with Claude out must show that she is still
working. This provider adds ONE card (the inventory) rather than a card per item,
because tasks, charter steps, handoffs and browser goals already have cards of their
own; the card's detail lists every blocked item with its reason and wake condition,
and its blockers are the few that matter most. Only the engine's own gap items (a
missing capability turned into a next action) get cards of their own.

Since C3 it also shows the WORK SESSION ("work on my projects", `project_work`):
one card with what is running now, what got done this session and what waits and
why, and ribbon lines that narrate each receipt in a plain sentence ("Drafted
handoff/STATUS.md ...", "Investigated Barkly's red CI and queued it for a stronger
model: ...").

`read` is the only impure function; `build` is pure. Read-only: nothing here runs,
approves or checkpoints anything (`work_engine.summary` probes nothing).
"""
from __future__ import annotations

from aletheia.mission_control import Provider, _plural, _words, mission_card

TYPE = "work"
CARD_ID = "work:inventory"
SESSION_CARD_ID = "work:session"
RIBBON_LINES = 12
MAX_BLOCKERS = 4


def read(ctx: dict) -> dict:
    sections = ctx.get("sections") or {}
    summary = sections.get("work")
    if not isinstance(summary, dict) or not summary.get("readable"):
        from aletheia import work_engine
        summary = work_engine.summary(ctx.get("now"))
    notes = [] if summary.get("readable") else [summary.get("note") or "the work inventory could not be read"]
    session = sections.get("work_session")
    if not isinstance(session, dict) or not session.get("readable"):
        try:
            from aletheia import project_work
            session = project_work.summary(ctx.get("now"))
        except Exception as exc:  # noqa: BLE001
            session = {"readable": False, "note": f"the work sessions could not be read ({type(exc).__name__})"}
    if not session.get("readable"):
        notes.append(session.get("note") or "the work sessions could not be read")
    return {"summary": summary, "session": session, "notes": notes}


#: How a receipt's kind is said on the ribbon, and its tone.
_RIBBON_KIND = {"completed": "good", "repaired": "good", "drafted": "good", "verified": "good", "started": "info",
                "investigated": "info", "asked": "info", "handed": "info", "refused": "alert", "failed": "alert",
                "waiting": "info"}


def session_card(session: dict | None) -> tuple[dict | None, list[dict], dict]:
    """The work session as (card, ribbon lines, detail). Pure."""
    if not isinstance(session, dict) or not session.get("id"):
        return None, [], {}
    done = [r for r in session.get("done") or [] if isinstance(r, dict)]
    waiting = [w for w in session.get("waiting") or [] if isinstance(w, dict)]
    running = session.get("running") or {}
    live = session.get("state") == "RUNNING"
    stopped = (session.get("stopped") or {}).get("why") or ""
    yours = [w for w in waiting if w.get("state") in ("BLOCKED_USER", "BLOCKED_LOGIN")]
    needs = [{"said": f"{_words(w.get('title'), 90)}: {_words(w.get('reason') or w.get('next'), 120)}",
              "blocking": False, "source": w.get("id")} for w in yours[:4]]
    card = mission_card(
        id=SESSION_CARD_ID, type=TYPE, title="Work session" + (" (rehearsal)" if session.get("rehearsal") else ""),
        status="RUNNING" if live else ("STOPPED" if stopped == "halted" else "DONE"),
        goal="Working on your projects on your say-so",
        step=(f"now: {_words(running.get('title'), 140)}" if live and running else
              f"{len(done)} done or investigated" + (f"; stopped: {stopped.replace('_', ' ')}" if stopped else "")),
        next=("the next thing she can carry" if live else
              (waiting[0].get("next") if waiting else "say work on my projects to start another")),
        needs=needs, needs_count=0,
        counts=[{"label": "done this session", "value": len(done)}, {"label": "waiting", "value": len(waiting)}],
        receipts=[{"kind": "work_session", "id": session["id"]}],
        updated=session.get("finished_at") or session.get("started_at"), detail=True, source="state/private/work/sessions")
    lines = []
    for r in done[-RIBBON_LINES:]:
        said = str(r.get("did") or "").strip() or f"{r.get('title')}: {r.get('state')}"
        lines.append({"at": r.get("at") or session.get("started_at"), "tone": _RIBBON_KIND.get(r.get("kind"), "info"),
                      "what": "Work", "said": (said[:1].upper() + said[1:]).rstrip(".") + ".",
                      "receipt": {"kind": "work_session", "id": session["id"]}})
    if live and running:
        lines.append({"at": running.get("since") or session.get("started_at"), "tone": "info", "what": "Work",
                      "said": f"Working on {_words(running.get('title'), 120)}.",
                      "receipt": {"kind": "work_session", "id": session["id"]}})
    detail = {"type": TYPE, "session": session["id"], "state": session.get("state"), "running": running,
              "done": done, "waiting": waiting, "stopped": session.get("stopped"), "said": session.get("said") or ""}
    return card, lines, detail


def build(reading: dict, ctx: dict) -> dict:
    s = reading.get("summary") or {}
    card, lines, detail = session_card((reading.get("session") or {}).get("session"))
    extra = {"missions": [card] if card else [], "activity": lines,
             "details": {SESSION_CARD_ID: detail} if card else {}}
    if not s.get("readable"):
        return extra if card else {}
    out = _inventory(s)
    out["missions"] = extra["missions"] + list(out.get("missions") or [])
    out["activity"] = list(out.get("activity") or []) + extra["activity"]
    out["details"] = {**(out.get("details") or {}), **extra["details"]}
    return out


def _inventory(s: dict) -> dict:
    run, blocked = int(s.get("executable_total") or 0), int(s.get("blocked_total") or 0)
    if not run and not blocked:
        return {"signals": [{"what": "work", "ok": True, "said": s.get("said") or ""}]}
    if s.get("halted"):
        status = "BLOCKED"
    elif run:
        status = "OPEN"
    else:
        status = "WAITING"
    blockers = [{"said": f"{_words(b.get('title'), 80)}: {b.get('reason') or b.get('state')}",
                 "since": b.get("not_before"), "source": b.get("id")}
                for b in (s.get("blocked") or [])[:MAX_BLOCKERS]] if not run else []
    ready = s.get("executable_now") or []
    if run and not blocked:
        # NO CARD FOR THE INVENTORY ITSELF when nothing is stuck. On his
        # phone this read "Work inventory - Everything unfinished across
        # her queues, read as one - can run now: call the plumber - the
        # next executable item", directly above the card for "call the
        # plumber". A queue that can run is the cards it contains.
        return {"signals": [{"what": "work", "ok": True, "said": s.get("said") or ""}],
                "details": {CARD_ID: {"type": TYPE, "counts": s.get("counts") or {},
                                      "executable_now": ready, "blocked": [],
                                      "executable_total": run, "blocked_total": 0}}}
    first_blocked = (s.get("blocked") or [{}])[0]
    card = mission_card(
        id=CARD_ID, type=TYPE, title="Waiting work" if not run else "Queued work", status=status,
        goal=(f"{_plural(blocked, 'thing')} can't move yet"
              + (f" and {_plural(run, 'thing')} can" if run else "")),
        step=(f"Next up: {_words(ready[0].get('title'), 120)}" if ready else ""),
        next=(first_blocked.get("next") or "whatever clears first") if not run else "",
        blockers=blockers,
        counts=[{"label": k.replace("_", " ").lower(), "value": v} for k, v in (s.get("counts") or {}).items()],
        updated=s.get("as_of"), detail=True, source="state/private/work")
    return {
        "missions": [card],
        "signals": [{"what": "work", "ok": bool(run) or not blocked, "said": s.get("said") or ""}],
        "details": {CARD_ID: {"type": TYPE, "counts": s.get("counts") or {},
                              "executable_now": ready, "blocked": s.get("blocked") or [],
                              "executable_total": run, "blocked_total": blocked}},
    }


def receipt(kind: str, ident: str) -> dict | None:
    """A work session's record, behind its card and its ribbon lines."""
    if kind != "work_session":
        return None
    from aletheia import project_work
    return {"kind": kind, "id": ident, "record": project_work.load(ident)}


PROVIDER = Provider(type=TYPE, label="Work", read=read, build=build,
                    journal_subjects=frozenset(), subject_labels={"work": "Work"},
                    receipt_kinds=("work_session",), receipt=receipt)
