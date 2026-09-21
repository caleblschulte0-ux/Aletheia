"""His long missions on the mission screen: one card each, with everything waiting and why.

A long mission (`aletheia.programs`) is the unit he thinks in for weeks at a
time, so its card answers the brief's questions directly: what the outcomes are
and how far along, the workstreams, what is executing, EVERYTHING waiting with
its reason and when it may wake, and the decisions that are his. A draft is
PROPOSED (it needs his answers and his yes); a mission with a decision or an
approval on him is NEEDS YOU; one with nothing runnable and things waiting is
WAITING.

`read` is the only impure function; `build` is pure. Read-only throughout.
"""
from __future__ import annotations

from aletheia.mission_control import Provider, _words, mission_card

TYPE = "program"
MAX_BLOCKERS = 6


def read(ctx: dict) -> dict:
    sections = ctx.get("sections") or {}
    from aletheia import programs
    said = programs.status(now=ctx.get("now"))
    notes = [] if said.get("readable") else [said.get("note") or "the long missions could not be read"]
    return {"status": said, "notes": notes, "section": sections.get("programs")}


def _status_word(m: dict) -> str:
    if m["state"] in ("DRAFTING", "DRAFT"):
        return "PROPOSED"
    if m["state"] == "PAUSED":
        return "STOPPED"
    if m["decisions"] or m["needs_confirm"] or any(w["state"] == "BLOCKED_USER" for w in m["waiting"]):
        return "NEEDS YOU"
    if m["executing"]:
        return "RUNNING"
    if m["ready"]:
        return "OPEN"
    if m["waiting"]:
        return "WAITING"
    return "DONE" if m["total"] and m["done"] == m["total"] else "OPEN"


def build(reading: dict, ctx: dict) -> dict:
    said = reading.get("status") or {}
    if not said.get("readable"):
        return {}
    cards, details = [], {}
    for m in said.get("missions") or []:
        cid = f"program:{m['id']}"
        status = _status_word(m)
        needs = [{"said": f"Decide: {d['question']}", "blocking": True, "source": d.get("wait")} for d in m["decisions"]]
        if m["needs_confirm"]:
            needs.append({"said": ("Answer: " + m["questions"][0]) if m["questions"]
                          else "Confirm the mission draft", "blocking": True, "source": cid})
        blockers = [{"said": f"{_words(w['title'], 80)}: {w['reason']}", "since": w.get("since"),
                     "wakes": w.get("next"), "at": w.get("not_before"), "source": w.get("wait") or w["key"]}
                    for w in m["waiting"][:MAX_BLOCKERS]] if status in ("WAITING", "NEEDS YOU") else []
        step = (f"working on {m['executing'][0]['title']}" if m["executing"]
                else f"next: {m['ready'][0]['title']}" if m["ready"] else "")
        nxt = (m["waiting"][0]["next"] if m["waiting"] and not m["ready"]
               else "confirm the draft" if m["needs_confirm"] else step)
        progress = {"done": m["done"], "total": m["total"]} if m["total"] else None
        counts = [{"label": k.replace("_", " ").lower(), "value": v} for k, v in m["counts"].items()]
        cards.append(mission_card(
            id=cid, type=TYPE, title=m["title"] or "Long mission", status=status, goal=m.get("objective") or "",
            step=step, next=nxt, blockers=blockers, needs=needs, progress=progress, counts=counts,
            receipts=[{"said": r.get("text"), "at": r.get("at")} for r in m["results"][-3:]],
            updated=m.get("updated_at"), detail=True, source="state/private/programs"))
        details[cid] = {"type": TYPE, "state": m["state"], "horizon": m.get("horizon"),
                        "drafted_by": m.get("drafted_by"), "outcomes": m["outcomes"],
                        "workstreams": m["workstreams"], "executing": m["executing"], "ready": m["ready"],
                        "waiting": m["waiting"], "decisions": m["decisions"], "questions": m["questions"],
                        "activities": m["activities"], "results": m["results"], "draft": m.get("draft"),
                        "next_wake_at": m["next_wake_at"]}
    signals = []
    if cards:
        waiting = sum(len(d["waiting"]) for d in details.values())
        signals.append({"what": "missions", "ok": True,
                        "said": f"{len(cards)} long mission{'s' if len(cards) != 1 else ''}, {waiting} waiting"})
    return {"missions": cards, "details": details, "signals": signals}


PROVIDER = Provider(type=TYPE, label="Long missions", read=read, build=build,
                    journal_subjects=frozenset(), subject_labels={"programs": "Long missions"})
