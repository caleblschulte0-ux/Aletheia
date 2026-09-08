"""What a worker knows, kept where Aletheia can still read it tomorrow.

The useful half of keeping a Claude window open for three weeks is not
the model. It is the accumulated context: what this project is, what was
decided and why, what was tried and failed, what is still open. Close the
tab and all of it is gone, which is why he has five windows he is afraid
to close.

So the knowledge lives here, in Aletheia's own store, and the model is
handed a bounded brief at the start of each assignment. A worker is
stateless from the vendor's point of view and continuous from his.

TWO KINDS OF MEMORY, AND KEEPING THEM APART IS THE WHOLE DESIGN.

**Distilled knowledge** — facts, decisions, open questions, blockers.
Small, durable, and the thing a brief is built from. It is written
deliberately, one line at a time.

**The transcript** — what a worker actually said on a given run. Useful
for debugging and worthless as context, because a model handed its own
previous output tends to agree with it. It is capped and rotated, and it
never goes into a brief.

Conflating them is how agent context grows forever until the brief is
mostly the agent talking to itself.

BOUNDED ON PURPOSE. `brief()` builds down to a byte budget by dropping
WHOLE entries, oldest first, never by slicing text. A half-sentence of a
decision is worse than its absence: absence is a gap the model can ask
about, and a truncated fact reads as complete. `situational.py` learned
this the same way.

PRIVATE. These are notes about his projects and his business. They live
in private state with the journal and the profile, gitignored, and the
repo is public.
"""
from __future__ import annotations

import json
from pathlib import Path

from aletheia.stateio import private_dir, read_json, safe_id, utcnow, write_json_atomic

ACTOR = "workspaces"

# What a worker may be told at the start of an assignment. Big enough for
# real project context, small enough that the model still has room to
# think — and to fail loudly rather than silently truncating.
BRIEF_BUDGET_BYTES = 8_000

# Distilled knowledge is meant to stay small. Past this something is
# being written that belongs in the transcript.
MAX_ENTRIES = 200
MAX_ENTRY_CHARS = 600

# The transcript is for debugging, so it is capped and rotates.
MAX_TRANSCRIPT = 50

# Least to most worth keeping. Used by BOTH the entry cap and the brief,
# because "what do we drop first" must have one answer: `brief()` was
# carefully keeping questions last while `remember()` was evicting them
# first, and the store won.
PRIORITY = ("fact", "artifact", "feedback", "decision", "blocker", "question")

KINDS = {
    "fact",        # something true about the project
    "decision",    # a choice, with its reason
    "question",    # open, unanswered, and worth carrying
    "blocker",     # why work stopped
    "artifact",    # a pointer: a branch, a PR, a file
    "feedback",    # what he said about the work
}


def _dir() -> Path:
    return private_dir("workspaces")


def _path(agent_id: str) -> Path:
    return _dir() / f"{safe_id(agent_id, name='agent id')}.json"


def load(agent_id: str) -> dict:
    try:
        value = read_json(_path(agent_id))
    except (OSError, ValueError):
        value = None
    if not isinstance(value, dict):
        return {"version": 1, "agent": agent_id, "entries": [], "transcript": []}
    value.setdefault("entries", [])
    value.setdefault("transcript", [])
    return value


def _save(agent_id: str, value: dict) -> dict:
    _dir().mkdir(parents=True, exist_ok=True)
    write_json_atomic(_path(agent_id), value)
    return value


def remember(agent_id: str, kind: str, text: str, *, source: str = "agent") -> dict:
    """One distilled line. Deliberate, small, and durable.

    Deduped against what is already there: a worker that re-derives the
    same fact on every run would otherwise fill its own brief with
    copies of one sentence and crowd out everything else.
    """
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {sorted(KINDS)}")
    text = " ".join(str(text or "").split())[:MAX_ENTRY_CHARS]
    if not text:
        raise ValueError("an empty note is not knowledge")
    space = load(agent_id)
    for existing in space["entries"]:
        if existing.get("kind") == kind and existing.get("text") == text:
            return existing                    # already known, not news
    entry = {"kind": kind, "text": text, "source": str(source)[:60],
             "at": utcnow()}
    space["entries"].append(entry)
    space["entries"] = _evict(space["entries"])
    _save(agent_id, space)
    return entry


def _evict(entries: list[dict]) -> list[dict]:
    """Trim to the cap by dropping the least important, oldest first.

    NOT by age alone. A blocker from Tuesday still blocks on Friday,
    while the two hundredth routine fact does not, and evicting by age
    let noise push out the open questions that a brief is mostly for.
    """
    if len(entries) <= MAX_ENTRIES:
        return entries
    ranked = sorted(
        enumerate(entries),
        key=lambda pair: (PRIORITY.index(pair[1].get("kind"))
                          if pair[1].get("kind") in PRIORITY else 0,
                          pair[1].get("at", "")))
    keep = {index for index, _ in ranked[-MAX_ENTRIES:]}
    # Back into the order they were written, so the file still reads as
    # a history rather than as a ranking.
    return [entry for index, entry in enumerate(entries) if index in keep]


def resolve(agent_id: str, text: str) -> bool:
    """An open question that has been answered stops being carried."""
    wanted = " ".join(str(text or "").split())
    space = load(agent_id)
    before = len(space["entries"])
    space["entries"] = [e for e in space["entries"]
                        if not (e.get("kind") in {"question", "blocker"}
                                and e.get("text") == wanted)]
    if len(space["entries"]) == before:
        return False
    _save(agent_id, space)
    return True


def record_run(agent_id: str, assignment: dict, result: dict) -> dict:
    """What a worker said on one run. Debugging material, never context.

    Kept apart from the distilled entries on purpose: a model handed its
    own previous output agrees with it, and a brief built from
    transcripts is a worker talking to itself.
    """
    space = load(agent_id)
    space["transcript"].append({
        "at": utcnow(),
        "role": str(assignment.get("role") or "")[:60],
        "question": str(assignment.get("question") or "")[:400],
        "state": str(result.get("state") or "")[:40],
        "provider": str(result.get("provider") or "")[:60],
        "why": str(result.get("why") or "")[:300],
    })
    space["transcript"] = space["transcript"][-MAX_TRANSCRIPT:]
    return _save(agent_id, space)


def entries(agent_id: str, kind: str = "") -> list[dict]:
    rows = load(agent_id)["entries"]
    return [e for e in rows if not kind or e.get("kind") == kind]


def brief(agent_id: str, *, budget: int = BRIEF_BUDGET_BYTES) -> str:
    """Everything this worker should know, inside a byte budget.

    Built by dropping WHOLE entries, oldest first, never by slicing
    text: a half-sentence of a decision reads as a complete one, while a
    missing entry is a gap the model can ask about.

    Open questions and blockers are kept LAST because they are what the
    assignment is usually about, so they are the last thing dropped.
    """
    from aletheia import agents
    try:
        record = agents.load(agent_id)
    except Exception:
        record = {"name": agent_id, "mission": "", "project": ""}

    head = [f"You are {record.get('name') or agent_id}."]
    if record.get("mission"):
        head.append(f"Your mission: {record['mission']}")
    if record.get("project"):
        head.append(f"Project: {record['project']}")
    header = "\n".join(head)

    # The same priority the cap uses, so the store and the brief cannot
    # disagree about what matters.
    order = list(PRIORITY)
    rows = load(agent_id)["entries"]
    ranked = sorted(
        rows,
        key=lambda e: (order.index(e["kind"]) if e.get("kind") in order else 0,
                       e.get("at", "")))

    lines: list[str] = []
    used = len(header.encode("utf-8"))
    # Fill from the MOST important end so the last thing dropped is the
    # open question, then put it back in reading order.
    for entry in reversed(ranked):
        line = f"- [{entry['kind']}] {entry['text']}"
        cost = len(line.encode("utf-8")) + 1
        if used + cost > budget:
            continue
        used += cost
        lines.append(line)
    lines.reverse()

    if not lines:
        # An empty workspace is still a workspace, and saying so stops a
        # model concluding the project has no history.
        return header + "\n\nNothing recorded about this yet."
    return header + "\n\nWhat you know so far:\n" + "\n".join(lines)


def forget(agent_id: str) -> bool:
    """Retire a worker's memory when the worker is retired."""
    path = _path(agent_id)
    try:
        path.unlink()
        return True
    except OSError:
        return False
