"""The continuity vocabulary: what state unfinished work is in, and what it needs.

His brief, 2026-09-16 (`docs/CONTINUITY_BRIEF.md`): *"I should never not be
able to work on my projects."* A model being out changes WHICH work can run
now, never whether Aletheia works. That needs three small closed sets that
every queue, the picker, the code worker and the interfaces share:

- `WORK_STATES` — one durable state for any unfinished item, whatever store
  it lives in. It does not replace a store's own states (tasks keep
  `contracts.TASK_STATES`, charter steps keep todo/doing/done/blocked); it is
  the common reading of them (`aletheia.work_engine` maps each store onto it).
- `REQUIREMENTS` — what a step needs in order to run, stated by the work,
  checked live by `aletheia.work_requirements`.
- `GAP_OUTCOMES` — what "no tool for this" becomes: a next action, never a
  dead end.

Pure data plus two tiny helpers; this module imports nothing from Aletheia so
anything may import it. Enums live here and are re-exported by
`aletheia.contracts`; never restate them elsewhere.
"""
from __future__ import annotations

# ---- work states -------------------------------------------------------------

READY = "READY"
RUNNING = "RUNNING"
BLOCKED_MODEL = "BLOCKED_MODEL"              # the reasoning it needs is out now (Claude resting...)
BLOCKED_USER = "BLOCKED_USER"                # needs Caleb: an approval, a decision, a fact, a setup
BLOCKED_LOGIN = "BLOCKED_LOGIN"              # needs a signed-in session or a verification code
BLOCKED_EXTERNAL = "BLOCKED_EXTERNAL"        # waiting on the world: a reply, a result, a date
RETRY_LATER = "RETRY_LATER"                  # transient; carries a not-before
NEEDS_STRONGER_MODEL = "NEEDS_STRONGER_MODEL"  # investigated locally; beyond the local tier
DONE = "DONE"
FAILED = "FAILED"

WORK_STATES = {
    READY, RUNNING, BLOCKED_MODEL, BLOCKED_USER, BLOCKED_LOGIN,
    BLOCKED_EXTERNAL, RETRY_LATER, NEEDS_STRONGER_MODEL, DONE, FAILED,
}
WORK_TERMINAL = {DONE, FAILED}
# Rule 3: every unfinished item that is not simply runnable says WHY and WHAT NEXT.
WORK_WAITING = WORK_STATES - WORK_TERMINAL - {READY, RUNNING}

# ---- reasoning classes (the gateway's policies) -------------------------------

ROUTINE = "routine"      # local first; a subscription only if local cannot answer
STANDARD = "standard"    # frontier first; local fallback when frontier is out
CRITICAL = "critical"    # frontier required; local may shadow, never answer
REASONING_CLASSES = {ROUTINE, STANDARD, CRITICAL}

# Who a queued item is assigned to, as the requirement it implies. A task for a
# frontier worker is reserved for a stronger model (NEEDS_STRONGER_MODEL when none
# can think); a task for the local repair tier needs only her own model.
LOCAL_REPAIR_WORKER = "local-repair"
FRONTIER_WORKERS = {"claude", "codex", "chatgpt", "frontier"}
LOCAL_WORKERS = {LOCAL_REPAIR_WORKER, "local", "ollama"}

# ---- requirements ---------------------------------------------------------------

REQUIREMENTS = {
    "local_reasoning",     # her own model answers (Ollama reachable)
    "frontier_reasoning",  # Claude / Codex / ChatGPT answers (not resting)
    "reasoning",           # any thinker at all (standard class: frontier or local)
    "browser",             # a browser that really loads a page
    "network",             # the internet is reachable
    "filesystem",          # local files readable/writable
    "terminal",            # can run local processes
    "code_execution",      # can run tests / scripts locally
    "github",              # a GitHub token that works
    "email",               # mail configured
    "calendar",            # a calendar provider configured
    "user_approval",       # Caleb must approve (never self-approved)
    "user_decision",       # Caleb must choose / answer
    "login",               # a signed-in account session
    "external_reply",      # someone outside must answer first
    "payment",             # money moves: always his, never hers
}

# When a requirement is not met, the state the item waits in.
BLOCKED_BY = {
    "local_reasoning": BLOCKED_MODEL,
    "frontier_reasoning": BLOCKED_MODEL,
    "reasoning": BLOCKED_MODEL,
    "browser": RETRY_LATER,
    "network": RETRY_LATER,
    "filesystem": RETRY_LATER,
    "terminal": RETRY_LATER,
    "code_execution": RETRY_LATER,
    "github": BLOCKED_USER,
    "email": BLOCKED_USER,
    "calendar": BLOCKED_USER,
    "user_approval": BLOCKED_USER,
    "user_decision": BLOCKED_USER,
    "login": BLOCKED_LOGIN,
    "external_reply": BLOCKED_EXTERNAL,
    "payment": BLOCKED_USER,
}

# ---- capability-gap outcomes (brief II.6) ----------------------------------------

GAP_OUTCOMES = {
    "other_tool",          # an existing tool can do it another way
    "browser_path",        # do it through the browser
    "local_workaround",    # a local script / deterministic path
    "ask_caleb",           # he has to say or do something
    "wait_external",       # an outside event has to happen first
    "install_configure",   # the capability exists but needs setup
    "small_capability",    # queue a bounded addition (local repair tier may take it)
    "large_capability",    # queue for a frontier model
    "refuse_policy",       # policy forbids it (money, authority, safety)
}
# The work state a gap outcome leaves its item in.
GAP_STATE = {
    "other_tool": READY,
    "browser_path": READY,
    "local_workaround": READY,
    "ask_caleb": BLOCKED_USER,
    "wait_external": BLOCKED_EXTERNAL,
    "install_configure": BLOCKED_USER,
    "small_capability": READY,
    "large_capability": NEEDS_STRONGER_MODEL,
    "refuse_policy": FAILED,
}


def problems(item: dict) -> list[str]:
    """What is wrong with a work item's continuity fields (empty = fine).

    Checks only the shared fields: state, requires, and rule 3 (a waiting
    item carries `reason` and `next`; RETRY_LATER also `not_before`)."""
    out: list[str] = []
    if not isinstance(item, dict):
        return ["work item must be an object"]
    state = item.get("state")
    if state not in WORK_STATES:
        out.append(f"state {state!r} not in {sorted(WORK_STATES)}")
    for req in item.get("requires") or []:
        if req not in REQUIREMENTS:
            out.append(f"requirement {req!r} not in {sorted(REQUIREMENTS)}")
    if state in WORK_WAITING:
        if not str(item.get("reason") or "").strip():
            out.append(f"{state} needs a reason")
        if not str(item.get("next") or "").strip():
            out.append(f"{state} needs a next condition or action")
    if state == RETRY_LATER and not item.get("not_before"):
        out.append("RETRY_LATER needs a not_before")
    return out
