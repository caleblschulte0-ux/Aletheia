"""Two read tools so "what did you get done / why didn't you finish X" is LOOKED INTO.

`work.receipts` reads the work sessions (`aletheia.project_work`): what each one
finished, investigated, queued for a stronger model and why, handed to Caleb,
and why it stopped. `work.inventory` reads the one work inventory
(`aletheia.work_engine`): what can run now and what waits on what. Both only
read, so the broker runs them without an approval and a local model may see
them. Each says which situation the store is in - full, empty or unreadable -
because a model asked about a store nothing in its context mentions denies the
store exists (CLAUDE.md).
"""
from __future__ import annotations

from aletheia import tools

MAX_RECEIPTS = 15


def receipts(args: dict, **_ignored) -> dict:
    from aletheia import project_work
    try:
        rows = project_work.all_sessions()
    except Exception as exc:  # noqa: BLE001
        return {"readable": False, "note": f"UNREADABLE: the work sessions could not be read ({type(exc).__name__})"}
    if not rows:
        return {"readable": True, "sessions": [],
                "note": "READ AND EMPTY: no work session has run yet (he starts one by saying work on my projects)"}
    latest = rows[-1]
    return {"readable": True, "sessions_on_record": len(rows),
            "latest": {"id": latest.get("id"), "state": latest.get("state"), "started_at": latest.get("started_at"),
                       "finished_at": latest.get("finished_at"), "stopped": latest.get("stopped"),
                       "rehearsal": latest.get("rehearsal"), "running": latest.get("running"),
                       "receipts": [{k: r.get(k) for k in ("title", "kind", "state", "did", "reason", "next", "evidence",
                                                           "seconds")}
                                    for r in (latest.get("receipts") or [])[-MAX_RECEIPTS:]],
                       "report": latest.get("report") or ""},
            "earlier": [{"id": r.get("id"), "started_at": r.get("started_at"), "done": len(r.get("receipts") or []),
                         "stopped": (r.get("stopped") or {}).get("why")} for r in rows[-4:-1]]}


def inventory(args: dict, **_ignored) -> dict:
    from aletheia import work_engine
    value = work_engine.summary()
    if not value.get("readable"):
        return {"readable": False, "note": "UNREADABLE: " + str(value.get("note") or "the inventory could not be read")}
    if not value.get("unfinished"):
        value["note"] = "READ AND EMPTY: nothing unfinished is on record"
    return value


TOOLS = (
    tools.declare(
        "work.receipts",
        description=("What her work sessions on his projects did (\"work on my projects\"): what each finished, "
                     "investigated and queued for Claude or Codex with the reason, handed to Caleb, what it was "
                     "doing, and why it stopped - from the session receipts."),
        input_schema={"properties": {}},
        handler=receipts, capability="work.projects", reads=("work",), provenance=tools.TRUSTED_LOCAL_STATE),
    tools.declare(
        "work.inventory",
        description=("Everything unfinished across her queues as one inventory: what she can run now, and every "
                     "blocked item with why and what wakes it (a model, Caleb, the world, a date)."),
        input_schema={"properties": {}},
        handler=inventory, capability="work.projects", reads=("work", "tasks", "plans"),
        provenance=tools.TRUSTED_LOCAL_STATE),
)
