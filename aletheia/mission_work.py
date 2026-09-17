"""Her work inventory on the mission screen: what can run now, what waits on what.

Continuity brief II.3 and rule 3: every unfinished item has a reason and a next
condition, and "work on my projects" with Claude out must show that she is still
working. This provider adds ONE card (the inventory) rather than a card per item,
because tasks, charter steps, handoffs and browser goals already have cards of their
own; the card's detail lists every blocked item with its reason and wake condition,
and its blockers are the few that matter most. Only the engine's own gap items (a
missing capability turned into a next action) get cards of their own.

`read` is the only impure function; `build` is pure. Read-only: nothing here runs,
approves or checkpoints anything (`work_engine.summary` probes nothing).
"""
from __future__ import annotations

from aletheia.mission_control import Provider, _words, mission_card

TYPE = "work"
CARD_ID = "work:inventory"
MAX_BLOCKERS = 4


def read(ctx: dict) -> dict:
    sections = ctx.get("sections") or {}
    summary = sections.get("work")
    if not isinstance(summary, dict) or not summary.get("readable"):
        from aletheia import work_engine
        summary = work_engine.summary(ctx.get("now"))
    notes = [] if summary.get("readable") else [summary.get("note") or "the work inventory could not be read"]
    return {"summary": summary, "notes": notes}


def build(reading: dict, ctx: dict) -> dict:
    s = reading.get("summary") or {}
    if not s.get("readable"):
        return {}
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
    card = mission_card(
        id=CARD_ID, type=TYPE, title="Work inventory", status=status,
        goal="Everything unfinished across her queues, read as one",
        step=(f"can run now: {_words(ready[0].get('title'), 120)}" if ready else ""),
        next=("the next executable item" if run else
              (s.get("blocked") or [{}])[0].get("next") or "whatever clears first"),
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


PROVIDER = Provider(type=TYPE, label="Work", read=read, build=build,
                    journal_subjects=frozenset(), subject_labels={"work": "Work"})
