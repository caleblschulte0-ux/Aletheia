"""Her AgentSession runs and the requests they handed to him, in mission control.

A session answers by asking for tools; one that asks for something that
writes or reaches the world hands it to him (`aletheia.handoffs`). This
provider shows both on the home screen, goal-agnostically:

- a session running now is a RUNNING card: "looking things up to answer ..."
- a handed-off request waiting on his yes is a NEEDS YOU card naming what
  will happen, and its approval is claimed so it is counted once
- an approved request being run is RUNNING; one that finished today is DONE
  or STOPPED with what came of it (denied, expired, refused, failed)

Ribbon lines say what became of each request, with the handoff record one
click away. `read` is the only impure function; `build` is pure.
Read-only throughout: nothing here approves or runs anything.
"""
from __future__ import annotations

import datetime as dt
import json

from aletheia.mission_control import RECENT_S, Provider, _age_s, _words, mission_card

TYPE = "agent_request"
MAX_CARDS = 12

STATUS = {"AWAITING_APPROVAL": "NEEDS YOU", "RUNNING": "RUNNING", "DONE": "DONE", "FAILED": "STOPPED",
          "DENIED": "STOPPED", "EXPIRED": "STOPPED", "REFUSED": "STOPPED", "INTERRUPTED": "STOPPED"}


def handoff_card(record: dict, now: dt.datetime) -> dict | None:
    """One handed-off request as a card. Pure."""
    if not isinstance(record, dict) or not record.get("id"):
        return None
    state = str(record.get("state") or "")
    status = STATUS.get(state)
    if status is None:
        return None
    finished = record.get("finished_at")
    if status in ("DONE", "STOPPED"):
        age = _age_s(finished, now)
        if age is None or age > RECENT_S:
            return None
    what = _words(record.get("consequence") or record.get("tool"), 200)
    asked = _words(record.get("question"), 120)
    receipt = {"kind": "handoff", "id": record["id"]}
    needs, blockers = [], []
    if status == "NEEDS YOU":
        needs.append({"said": f"approve or deny: {what}", "blocking": True, "receipt": receipt})
        step, nxt = "", "It runs exactly as asked, once, when you approve it; nothing happens if you deny it."
    elif status == "RUNNING":
        step, nxt = f"doing what you approved: {what}", "Record what came of it."
    elif status == "DONE":
        step, nxt = "", "Nothing: it ran."
    else:
        blockers.append({"said": _words(record.get("outcome") or state.lower(), 200), "since": finished,
                         "source": "handoff record"})
        step, nxt = "", ("Ask again if you still want it." if state in ("EXPIRED", "INTERRUPTED", "FAILED")
                         else "Nothing: it did not run.")
    return mission_card(
        id=f"handoff:{record['id']}", type=TYPE, title=what or record["id"],
        goal=f"Asked for while answering “{asked}”" if asked else "", status=status, step=step, next=nxt,
        blockers=blockers, needs=needs,
        receipts=[{**receipt, "label": "request record"}]
        + ([{"kind": "session", "id": record["session"], "label": "the session that asked"}]
           if record.get("session") else []),
        updated=finished or record.get("started_at") or record.get("created_at"),
        in_browser=status == "RUNNING" and str(record.get("tool") or "").startswith("browser."),
        source="state/private/handoffs")


def session_card(session: dict) -> dict:
    """A session running now. Pure."""
    asked = _words(session.get("question"), 140)
    return mission_card(
        id=f"session:{session.get('id')}", type="agent_session", title=f"Answering “{asked}”",
        status="RUNNING", step="looking things up with her tools",
        next="Answer from what the tools show, or hand what only you can decide to you.",
        receipts=[{"kind": "session", "id": session.get("id"), "label": "session record"}],
        updated=session.get("saved_at"), source="state/private/agent-sessions")


def activity(records: list[dict]) -> list[dict]:
    items = []
    for record in records:
        if not isinstance(record, dict) or not record.get("id"):
            continue
        what = _words(record.get("consequence") or record.get("tool"), 140)
        receipt = {"kind": "handoff", "id": record["id"]}
        if record.get("created_at"):
            items.append({"at": record["created_at"], "tone": "info", "what": "Requests",
                          "said": f"Asked for your approval: {what}.", "receipt": receipt})
        state = record.get("state")
        if record.get("finished_at"):
            outcome = _words(record.get("outcome"), 140)
            said, tone = {
                "DONE": (f"Did what you approved: {what}.", "good"),
                "DENIED": (f"You said no, so it did not run: {what}.", "info"),
                "EXPIRED": (f"Expired before it ran: {what}.", "info"),
                "REFUSED": (f"Refused to run {what}: {outcome}.", "alert"),
                "FAILED": (f"What you approved did not work: {what} ({outcome}).", "alert"),
                "INTERRUPTED": (f"Interrupted while running: {what}.", "alert"),
            }.get(state, (f"{what}: {str(state).lower()}.", "info"))
            items.append({"at": record["finished_at"], "tone": tone, "what": "Requests", "said": said,
                          "receipt": receipt})
    return items


def build(reading: dict, ctx: dict) -> dict:
    now = ctx["now"]
    records = [r for r in reading.get("handoffs") or [] if isinstance(r, dict)]
    cards = [c for c in (handoff_card(r, now) for r in records) if c]
    cards += [session_card(s) for s in reading.get("running") or [] if isinstance(s, dict)]
    cards = sorted(cards, key=lambda c: str(c.get("updated") or ""), reverse=True)[:MAX_CARDS]
    claims = sorted({str(r.get("approval")) for r in records
                     if r.get("approval") and r.get("state") == "AWAITING_APPROVAL"})
    return {"missions": cards, "claims": claims, "activity": activity(records)}


def read(ctx: dict) -> dict:
    """The handoff records and the sessions running now. Never raises."""
    from aletheia import handoffs, proc, stateio
    from aletheia.agent_session import LIVE_S
    now = ctx["now"]
    notes = []
    try:
        records = handoffs.all_handoffs()
    except Exception as exc:  # noqa: BLE001
        records = []
        notes.append(f"the handed-off requests could not be read ({type(exc).__name__})")
    running = []
    try:
        folder = stateio.private_dir("agent-sessions")
        paths = sorted(folder.glob("agent-*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:20] \
            if folder.is_dir() else []
    except Exception:
        paths = []
    for path in paths:
        try:
            session = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if session.get("outcome") != "running":
            continue
        age = _age_s(session.get("started_at") or session.get("saved_at"), now)
        if age is None or age > LIVE_S or (session.get("pid") and proc.pid_alive(session["pid"]) is False):
            continue
        running.append(session)
    return {"handoffs": records, "running": running, "notes": notes}


def receipt(kind: str, ident: str) -> dict | None:
    from aletheia import handoffs
    if kind != "handoff":
        return None
    try:
        record = handoffs.load(ident)
    except (OSError, ValueError, KeyError):
        return None
    return {"kind": kind, "id": ident, "record": record,
            "provenance": {"model": "", "basis": "a tool request her session made, approved by you"}}


PROVIDER = Provider(type=TYPE, label="Requests", read=read, build=build,
                    journal_subjects=frozenset({"handoff"}), subject_labels={"handoff": "Requests"},
                    receipt_kinds=("handoff",), receipt=receipt)
