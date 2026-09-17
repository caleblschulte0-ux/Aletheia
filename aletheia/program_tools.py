"""Two read tools so "how is my big mission going / what are we waiting on" is LOOKED INTO.

`mission.status` and `mission.waiting` read `aletheia.programs` and nothing
else. Both only read, so the policy broker runs them without an approval and a
local model may see them. Each says which of the three situations the store is
in - full, empty or unreadable - because a model asked about a store nothing in
its context mentions denies the store exists (CLAUDE.md).
"""
from __future__ import annotations

from aletheia import tools

MAX_TASKS = 12


def _slim(mission: dict) -> dict:
    def rows(items, keys):
        return [{k: r.get(k) for k in keys if r.get(k) not in (None, "", [])} for r in items[:MAX_TASKS]]
    return {
        "id": mission["id"], "title": mission["title"], "state": mission["state"],
        "objective": mission.get("objective"), "horizon": mission.get("horizon"),
        "progress": f"{mission['done']} of {mission['total']} tasks done",
        "outcomes": rows(mission["outcomes"], ("text", "measure", "status", "tasks_done", "tasks")),
        "workstreams": [{"title": w["title"], "done": w["done"], "total": w["total"]} for w in mission["workstreams"]],
        "executing": rows(mission["executing"], ("title", "tools")),
        "ready": rows(mission["ready"], ("title", "tools")),
        "waiting": rows(mission["waiting"], ("title", "state", "reason", "next", "not_before")),
        "decisions_for_caleb": rows(mission["decisions"], ("question", "options")),
        "questions_for_caleb": mission["questions"],
        "needs_his_confirm": mission["needs_confirm"],
        "drafted_by": (mission.get("drafted_by") or {}).get("provider"),
        "recent_results": [r.get("text") for r in mission["results"]][-5:],
    }


def mission_status(args: dict, **_ignored) -> dict:
    from aletheia import programs
    said = programs.status(str(args.get("which") or ""))
    out = {"readable": said.get("readable", False), "total_on_record": said.get("total", 0),
           "missions": [_slim(m) for m in said.get("missions") or []]}
    if said.get("note"):
        out["note"] = said["note"]
    return out


def mission_waiting(args: dict, **_ignored) -> dict:
    from aletheia import programs
    return programs.waiting_view(str(args.get("which") or ""))


TOOLS = (
    tools.declare(
        "mission.status",
        description=("His LONG missions (weeks or months): each one's outcomes and how to tell they are met, "
                     "workstreams, what is running, what is waiting and why, decisions only he can make, and "
                     "whether a draft waits for his yes. which narrows to one mission by words of its title."),
        input_schema={"properties": {"which": {"type": "string"}}},
        handler=mission_status, capability="mission.long", reads=("programs", "waits"),
        provenance=tools.TRUSTED_LOCAL_STATE),
    tools.declare(
        "mission.waiting",
        description=("Everything his long missions are waiting on: a reply, a date, an approval, a model, his "
                     "decision - with why, what wakes it, when it may next move, the follow-up and what a "
                     "timeout would mean. which narrows to one mission."),
        input_schema={"properties": {"which": {"type": "string"}}},
        handler=mission_waiting, capability="mission.long", reads=("programs", "waits"),
        provenance=tools.TRUSTED_LOCAL_STATE),
)
