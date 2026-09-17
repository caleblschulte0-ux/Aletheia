"""Conversations and calendar holds on the mission screen.

Continuity brief IV.14-16: waiting is a state, not a failure, so the screen
shows what each conversation is waiting ON - his approval, the other person, a
follow-up date - and what she does next. One card per open conversation (they
are the unit he thinks in: "the landlord", "the recruiter"), plus one calendar
card when she has holds pencilled in or sees a clash.

`read` is the only impure function; `build` is pure. Read-only.
"""
from __future__ import annotations

from aletheia.mission_control import Provider, _words, mission_card

TYPE = "conversation"
CALENDAR_CARD = "calendar:holds"

STATUS = {"AWAITING_APPROVAL": "NEEDS YOU", "REPLIED": "NEEDS YOU", "DRAFTED": "NEEDS YOU",
          "AWAITING_REPLY": "WAITING", "FOLLOW_UP_DUE": "RUNNING", "SENT": "WAITING", "CLOSED": "DONE"}


def read(ctx: dict) -> dict:
    sections = ctx.get("sections") or {}
    summary = sections.get("conversations")
    if not isinstance(summary, dict) or not summary.get("readable"):
        from aletheia import conversations
        summary = conversations.summary(ctx.get("now"))
    notes = [] if summary.get("readable") else [summary.get("note") or "the conversations could not be read"]
    return {"summary": summary, "notes": notes}


def _card(row: dict, status: str) -> dict:
    needs = []
    if status == "NEEDS YOU":
        needs.append({"said": row.get("reason") or "it needs you", "blocking": True,
                      "approval": row.get("approval")})
    return mission_card(
        id=f"conversation:{row['id']}", type=TYPE, title=f"{row.get('with')}: {row.get('subject') or ''}",
        status=status, goal=_words(row.get("subject"), 200), step=_words(row.get("reason"), 200),
        next=_words(row.get("next"), 200), needs=needs, updated=row.get("follow_up_due"),
        receipts=[{"kind": "conversation", "id": row["id"], "label": "conversation record"}],
        source="state/private/conversations")


def build(reading: dict, ctx: dict) -> dict:
    s = reading.get("summary") or {}
    if not s.get("readable"):
        return {}
    missions, claims, seen = [], [], set()
    for key, forced in (("needs_approval", "NEEDS YOU"), ("needs_caleb", "NEEDS YOU"),
                        ("follow_up_due", "RUNNING"), ("awaiting_reply", "WAITING"), ("recently_closed", "DONE")):
        for row in s.get(key) or []:
            if row["id"] in seen:
                continue
            seen.add(row["id"])
            missions.append(_card(row, forced))
            if row.get("approval"):
                claims.append(row["approval"])
    holds, conflicts = s.get("holds") or [], s.get("conflicts") or []
    signals = [{"what": "conversations", "ok": not (s.get("needs_approval") or s.get("needs_caleb")),
                "said": s.get("said") or ""}]
    if holds or conflicts:
        missions.append(mission_card(
            id=CALENDAR_CARD, type=TYPE, title="Calendar holds", status="BLOCKED" if conflicts else "OPEN",
            goal="What she has pencilled in, and what clashes",
            step=(f"{holds[0].get('title')} {holds[0].get('human')}" if holds else ""),
            next=("sort out the clash" if conflicts else "confirm or release the holds as replies come in"),
            blockers=[{"said": c.get("why"), "since": c.get("start"), "source": c.get("a_id")} for c in conflicts[:4]],
            counts=[{"label": "holds", "value": len(holds)}, {"label": "conflicts", "value": len(conflicts)}],
            detail=True, source="state/private/calendar"))
        if conflicts:
            signals.append({"what": "calendar", "ok": False,
                            "said": f"{len(conflicts)} calendar clash{'es' if len(conflicts) != 1 else ''}"})
    return {"missions": missions, "claims": claims, "signals": signals,
            "details": {CALENDAR_CARD: {"type": TYPE, "holds": holds, "conflicts": conflicts}}}


PROVIDER = Provider(type=TYPE, label="Conversations", read=read, build=build,
                    journal_subjects=frozenset(), subject_labels={"conversation": "Conversations"})
