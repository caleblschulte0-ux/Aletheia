"""Workers Aletheia owns, rather than chat windows she borrows.

The problem this solves is not "she should have more bots". It is that
the useful part of keeping five Claude and ChatGPT windows open — one
per concern, each holding its own context, arguing with each other — is
currently held by the VENDORS. Close the tab and the worker is gone.
Here the identity, the mission, the context and the history belong to
Aletheia, and the model underneath is a replaceable detail: a project
agent can be answered by Claude today and a local Qwen tomorrow without
becoming a different agent.

**An agent is not a model.** `reasoning_gateway` picks the provider from
a policy (routine / standard / critical); an agent says what KIND of
thinking its work needs and never names a vendor. That is why
`model_policy` here is one of the gateway's own words and not "sonnet".

THE HIERARCHY IS THE POINT, and it is the thing to protect:

    Caleb -> Aletheia -> the runtime -> an agent -> a model or tool

never

    an agent -> "I need more permission" -> an agent with more permission

Four rules enforce that, and each is a test:

**A capability an agent may hold is one the registry says may be
delegated at all.** `authority.delegable` — the same predicate that gates
standing grants — refuses anything high-risk or `operator_always`. So no
agent, ever, at any depth, holds `message.send`, `purchase.execute`,
`email.send` or `computer.control`. Those stop for him every time. An
agent may still ASK: `intercom` will write the draft and the approval,
and he decides. Asking is not authority.

**A child is a subset of its parent.** `spawn` refuses a capability the
parent does not hold, so delegation can only ever narrow. Permission
laundering — parent creates child, child creates grandchild with more —
is arithmetically impossible rather than watched for.

**Permission is checked when the work runs, not when the agent was
made.** `require()` re-reads the record and the registry every time. An
agent created last week under a registry that has since tightened does
not keep yesterday's authority.

**The kill switch is above all of it.** `require()` re-reads
`policy.halted()`, so "stop everything" stops every agent at its next
step, including ones that were mid-assignment. Nothing here can clear
that, and no agent may hold the capability to.

WHAT IS DELIBERATELY SMALL IN V1. The concurrency ceiling is TWO, from
measurement rather than taste: on 2026-09-02 a sixteen-way parallel
`claude -p` burst on this machine had half its calls refused by the CLI,
which surfaces as `ReasonerUnavailable` and reads like a model outage
rather than a self-inflicted wound. The same laptop killed a test suite
for memory today. "Five frontier workers in parallel" is not hardware
this operator has, so the runtime is honest about it instead of
discovering it under load.

States are `contracts.TASK_STATES` — not a new vocabulary. The existing
twelve already separate WAITING_EXTERNAL from WAITING_OPERATOR from
WAITING_DEPENDENCY, and FAILED_RETRYABLE from FAILED_TERMINAL, which is
finer than anything a second list would have said. Receipts are
`outcomes.py` for the same reason: two audit trails is one audit trail
and one liability.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from aletheia import authority, contracts, journal, policy
from aletheia.stateio import private_dir, read_json, safe_id, utcnow, write_json_atomic

ACTOR = "agents"

# The supervisor. Not an agent record: Aletheia is above the runtime, and
# giving her a row in the same table is the first step toward her being
# one of the things it manages.
ROOT = "aletheia"

AGENT_TYPES = {
    # one bounded assignment, then gone
    "temporary",
    # attached to a real project, survives restarts and model changes
    "project",
    # a standing responsibility rather than one project. NOT new autonomy:
    # `project_loop`, the pulse and the watchers already run unattended
    # forever. What this adds is a NAME and a capability scope for work
    # that currently runs without either, which makes it a tightening.
    "standing",
}

# How deep delegation may go. Three is a parent, a child and a grandchild
# — enough for "Barkly agent asks for a QA worker", short enough that a
# runaway is bounded by arithmetic rather than by noticing.
MAX_DEPTH = 3
MAX_CHILDREN = 4

# Measured, not chosen. See the module docstring.
MAX_PARALLEL = 2

# Terminal states an agent does not come back from.
FINISHED = {"COMPLETED", "FAILED_TERMINAL", "CANCELLED"}


class AgentError(RuntimeError):
    """The runtime refused. Never raised for a thing that merely failed."""


class NotPermitted(AgentError):
    """An agent reached for authority it does not have."""


def agents_dir() -> Path:
    return private_dir("agents")


def _path(agent_id: str) -> Path:
    return agents_dir() / f"{safe_id(agent_id, name='agent id')}.json"


def exists(agent_id: str) -> bool:
    return _path(agent_id).exists()


def load(agent_id: str) -> dict:
    if agent_id == ROOT:
        return root_record()
    return read_json(_path(agent_id))


def all_agents() -> list[dict]:
    directory = agents_dir()
    if not directory.is_dir():
        return []
    out = []
    for path in sorted(directory.glob("*.json")):
        try:
            out.append(read_json(path))
        except (OSError, ValueError):
            continue
    return out


# ---- what may be held at all ---------------------------------------------

def grantable(capability_ids) -> list[str]:
    """The subset of these that any agent may ever hold.

    Unknown ids are dropped rather than raised on, because this is also
    used to describe the root's own reach and a registry that loses an
    entry must not take the runtime down with it. An UNREADABLE registry
    grants nothing at all, which is the fail-closed direction.

    The registry is read ONCE here and passed down. Asking `delegable`
    per id re-parses the whole file per id, which is 130 parses for one
    call and was most of a minute across these tests.
    """
    from aletheia import capabilities
    try:
        reg = capabilities.load_registry()
    except Exception:
        return []                    # an unreadable registry grants nothing
    out = []
    for cid in capability_ids or []:
        try:
            if authority.delegable(cid, reg):
                out.append(cid)
        except Exception:
            continue
    return out


def root_record() -> dict:
    """Aletheia's own reach: everything the registry says may be delegated.

    Computed from the registry every time rather than stored, so a
    capability that becomes high-risk tomorrow leaves the root's set
    tomorrow — and therefore leaves every agent's set, since a child can
    only ever be a subset.
    """
    from aletheia import capabilities
    ids = [c["id"] for c in capabilities.load_registry().get("capabilities", [])]
    return {"version": 1, "id": ROOT, "name": "Aletheia", "type": "root",
            "parent": None, "mission": "the operator's interface",
            "status": "READY", "capabilities": grantable(ids)}


def holds(agent_id: str) -> set[str]:
    """What this agent may exercise right now, registry re-read."""
    record = load(agent_id)
    return set(grantable(record.get("capabilities") or []))


def depth(agent_id: str) -> int:
    """How far below Aletheia this agent sits. Root is 0."""
    seen = set()
    steps = 0
    current = agent_id
    while current and current != ROOT:
        if current in seen:                      # a cycle on disk is not a chain
            raise AgentError(f"agent {agent_id!r} has a cyclic parent chain")
        seen.add(current)
        steps += 1
        if steps > MAX_DEPTH + 2:
            raise AgentError(f"agent {agent_id!r} is deeper than the runtime allows")
        current = (load(current).get("parent") or ROOT)
    return steps


def children(agent_id: str) -> list[dict]:
    return [a for a in all_agents() if (a.get("parent") or ROOT) == agent_id]


# ---- making one -----------------------------------------------------------

def spawn(agent_id: str, *, name: str, mission: str, capabilities: list[str],
          agent_type: str = "temporary", parent: str = ROOT,
          project: str = "", model_policy: str = "standard",
          limits: dict | None = None) -> dict:
    """Create a worker that is strictly weaker than the thing that made it.

    Every refusal here is a rule from the brief, enforced rather than
    remembered. Nothing is created if anything is refused.
    """
    if agent_type not in AGENT_TYPES:
        raise AgentError(f"agent type must be one of {sorted(AGENT_TYPES)}")
    if model_policy not in {"routine", "standard", "critical"}:
        raise AgentError("model_policy is the gateway's: routine, standard or critical")
    if not str(mission or "").strip():
        raise AgentError("an agent without a mission is a process, not a worker")
    if exists(agent_id):
        raise AgentError(f"agent {agent_id!r} already exists")

    if parent != ROOT and not exists(parent):
        raise AgentError(f"parent {parent!r} does not exist")
    if depth(parent) + 1 > MAX_DEPTH:
        raise AgentError(
            f"delegation stops at depth {MAX_DEPTH}; {parent!r} is already at "
            f"{depth(parent)}")
    if len(children(parent)) >= MAX_CHILDREN:
        raise AgentError(
            f"{parent!r} already has {MAX_CHILDREN} children, which is the limit")

    wanted = list(dict.fromkeys(capabilities or []))
    # 1. the registry's own floor: nothing high-risk or operator_always
    refused = [c for c in wanted if c not in grantable(wanted)]
    if refused:
        raise NotPermitted(
            f"no agent may hold {', '.join(sorted(refused))} — the registry "
            "keeps those for him every time. An agent may still ask, and the "
            "approval goes to him.")
    # 2. and never more than the thing that made it
    parent_holds = holds(parent)
    escalation = [c for c in wanted if c not in parent_holds]
    if escalation:
        raise NotPermitted(
            f"{parent!r} does not hold {', '.join(sorted(escalation))}, so it "
            "cannot give it away; a child is a subset of its parent")

    now = utcnow()
    record = {
        "version": 1, "id": safe_id(agent_id, name="agent id"),
        "name": str(name or agent_id)[:120],
        "type": agent_type, "parent": parent,
        "mission": str(mission).strip()[:2000], "project": str(project or "")[:80],
        "status": "READY", "capabilities": wanted,
        "model_policy": model_policy,
        "limits": dict(limits or {}),
        "created_at": now, "last_active_at": now,
    }
    agents_dir().mkdir(parents=True, exist_ok=True)
    write_json_atomic(_path(agent_id), record)
    journal.append("action", f"agent:{agent_id}",
                   f"{agent_type} agent created under {parent} — {record['name']}",
                   actor=ACTOR)
    return record


# ---- using one ------------------------------------------------------------

def permits(agent_id: str, capability_id: str) -> bool:
    """Read-only: may this agent exercise this, right now?"""
    try:
        return capability_id in holds(agent_id)
    except Exception:
        return False                              # unreadable is not permitted


def require(agent_id: str, capability_id: str) -> None:
    """The gate every agent action passes through. Raises, or returns None.

    Checked HERE rather than at spawn time on purpose: an agent made last
    week under a registry that has since tightened does not keep last
    week's authority, and a record edited on disk buys nothing.
    """
    halt = policy.halted()
    if halt:
        raise NotPermitted(
            "everything is halted; no agent acts until he resumes her")
    record = load(agent_id)
    status = str(record.get("status") or "")
    if status in FINISHED:
        raise NotPermitted(f"agent {agent_id!r} is {status} and does no more work")
    if status == "BLOCKED":
        raise NotPermitted(f"agent {agent_id!r} is paused")
    if capability_id not in holds(agent_id):
        raise NotPermitted(
            f"agent {agent_id!r} does not hold {capability_id}. It may ask; "
            "asking is not authority.")


def set_status(agent_id: str, status: str, *, note: str = "") -> dict:
    if status not in contracts.TASK_STATES:
        raise AgentError(f"status must be one of {sorted(contracts.TASK_STATES)}")
    record = load(agent_id)
    was = record.get("status")
    record["status"] = status
    record["last_active_at"] = utcnow()
    if note:
        record["note"] = str(note)[:500]
    write_json_atomic(_path(agent_id), record)
    if was != status:
        journal.append("event", f"agent:{agent_id}", f"{was} -> {status}",
                       actor=ACTOR)
    return record


def pause(agent_id: str, *, note: str = "") -> dict:
    return set_status(agent_id, "BLOCKED", note=note or "paused")


def resume(agent_id: str) -> dict:
    return set_status(agent_id, "READY", note="resumed")


def kill(agent_id: str, *, why: str = "cancelled") -> list[dict]:
    """Stop this agent AND everything below it.

    Cancellation propagates downward because a killed parent whose child
    keeps working is the runaway this runtime exists to make impossible.
    """
    stopped = []
    for child in children(agent_id):
        stopped.extend(kill(child["id"], why=f"parent {agent_id} cancelled"))
    stopped.append(set_status(agent_id, "CANCELLED", note=why))
    return stopped


def kill_all(*, why: str = "operator stopped everything") -> list[dict]:
    """'Stop everything.' Every agent, one pass, no exceptions."""
    stopped = []
    for record in all_agents():
        if record.get("status") not in FINISHED:
            stopped.append(set_status(record["id"], "CANCELLED", note=why))
    return stopped


def archive(agent_id: str) -> dict:
    record = set_status(agent_id, "COMPLETED", note="archived")
    return record


# ---- what are they doing? (the brief's §20) -------------------------------

def roster() -> list[dict]:
    """One line per worker, ordered the way a person would read it."""
    order = {"RUNNING": 0, "READY": 1, "WAITING_OPERATOR": 2, "BLOCKED": 3}
    rows = []
    for record in all_agents():
        rows.append({
            "id": record["id"], "name": record.get("name") or record["id"],
            "type": record.get("type"), "status": record.get("status"),
            "mission": record.get("mission", "")[:120],
            "project": record.get("project") or "",
            "parent": record.get("parent") or ROOT,
            "capabilities": len(record.get("capabilities") or []),
        })
    rows.sort(key=lambda r: (order.get(r["status"], 9), r["name"].lower()))
    return rows


def spoken_roster() -> str:
    """The answer to "what are your workers doing?", out loud.

    Counted and named, never a log dump: `speech` rules apply because
    this is read in a room.
    """
    from aletheia import speech
    rows = [r for r in roster() if r["status"] not in FINISHED]
    if not rows:
        return "No workers running."
    said = []
    for row in rows[:4]:
        working = row["status"].replace("_", " ").lower()
        said.append(f"{row['name']} is {working} on {row['mission'][:60]}")
    line = speech.and_list(said) + "."
    if len(rows) > 4:
        line += f" And {len(rows) - 4} more."
    return line[0].upper() + line[1:]
