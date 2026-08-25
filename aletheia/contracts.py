"""Aletheia's vocabulary — the core data contracts (Playbook §111, Phase 1).

These are the objects everything else speaks: Capability, Provider, Goal,
Task, Agent, Approval, ActionRecord. They are deliberately plain dicts
with validators, not classes — the same shape on disk, over the intercom,
in a worker's hands, and in tests. Enums live here and ONLY here; a
module that needs task states imports them, never restates them.

Minimum viable on purpose (Playbook §115: "do not over-engineer").
Fields marked optional may be absent; unknown fields are refused so the
vocabulary cannot drift silently.
"""
from __future__ import annotations

# ---- enums (Playbook §§28, 56, 104) ----------------------------------------

TASK_STATES = {
    "QUEUED", "READY", "RUNNING",
    "WAITING_OPERATOR", "WAITING_EXTERNAL", "WAITING_DEPENDENCY",
    "BLOCKED", "RETRY_SCHEDULED",
    "FAILED_RETRYABLE", "FAILED_TERMINAL",
    "COMPLETED", "CANCELLED",
}
TASK_TERMINAL = {"COMPLETED", "CANCELLED", "FAILED_TERMINAL"}

CAPABILITY_STATUSES = {
    "AVAILABLE", "DEGRADED", "EXPERIMENTAL",
    "NEEDS_CONFIGURATION", "UNAVAILABLE", "NOT_BUILT",
}

RISK_CLASSES = {"read", "low", "medium", "high"}

# none: runs freely · registry_grant: gated by config (e.g. front_door)
# operator_once: prepared, one approval per use · operator_always: §56 L4
APPROVAL_POLICIES = {"none", "registry_grant", "operator_once", "operator_always"}

AGENT_ROLES = {
    "GENERAL_REASONING", "DEEP_REASONING", "CODING", "CODE_REVIEW",
    "RESEARCH", "VISION", "VOICE", "WRITING", "PLANNING", "FAST_CLASSIFICATION",
}

APPROVAL_STATES = {"PENDING", "APPROVED", "DENIED", "EXPIRED"}

GOAL_STATES = {"open", "done", "dropped"}          # carried by plans/*.json today
GOAL_STEP_STATES = {"todo", "doing", "done", "blocked"}


# ---- validator machinery ----------------------------------------------------

def _check(obj: dict, name: str, required: dict, optional: dict) -> list[str]:
    """required/optional: field -> type or (type, allowed-values-set)."""
    problems: list[str] = []
    if not isinstance(obj, dict):
        return [f"{name} must be an object"]
    for field, spec in required.items():
        if field not in obj:
            problems.append(f"{name}.{field}: missing")
    for field, value in obj.items():
        if field not in required and field not in optional:
            problems.append(f"{name}.{field}: unknown field")
            continue
        spec = required.get(field, optional.get(field))
        typ, allowed = spec if isinstance(spec, tuple) else (spec, None)
        if not isinstance(value, typ):
            problems.append(f"{name}.{field}: expected {typ.__name__}")
        elif allowed is not None and value not in allowed:
            problems.append(f"{name}.{field}: {value!r} not in {sorted(allowed)}")
    return problems


# ---- the seven contracts ----------------------------------------------------

def validate_capability(c: dict) -> list[str]:
    return _check(c, "Capability", required={
        "id": str,                      # dotted, e.g. "github.workflow.dispatch"
        "description": str,
        "provider": str,                # Provider id currently serving it
        "status": (str, CAPABILITY_STATUSES),
        "risk_class": (str, RISK_CLASSES),
        "approval_policy": (str, APPROVAL_POLICIES),
        "caller": str,                  # rule zero: what really invokes it, or the ticket
    }, optional={
        "inputs": list, "outputs": list, "verification": str, "notes": str,
    })


def validate_provider(p: dict) -> list[str]:
    return _check(p, "Provider", required={
        "id": str,
        "description": str,
        "kind": (str, {"local_module", "github_actions", "subscription_client",
                       "api", "human"}),
    }, optional={
        "authentication": str, "notes": str,
    })


def validate_goal(g: dict) -> list[str]:
    """The Goal contract is carried by plans/*.json today (aletheia.plans):
    slug/title/goal/state/created/steps. This validator IS that schema —
    one contract, one store."""
    problems = _check(g, "Goal", required={
        "slug": str, "title": str, "goal": str,
        "state": (str, GOAL_STATES), "created": str, "steps": list,
    }, optional={})
    for i, s in enumerate(g.get("steps", []) if isinstance(g, dict) else []):
        problems += _check(s, f"Goal.steps[{i}]", required={
            "n": int, "text": str, "state": (str, GOAL_STEP_STATES),
        }, optional={"repo": str})
    return problems


def validate_task(t: dict) -> list[str]:
    return _check(t, "Task", required={
        "id": str,
        "description": str,
        "status": (str, TASK_STATES),
        "created_at": str,
        "updated_at": str,
        "attempts": int,
    }, optional={
        "goal": str,                    # parent Goal slug
        "priority": int,
        "deadline": str,
        "dependencies": list,           # task ids
        "assigned_worker": str,         # Agent id
        "required_capabilities": list,  # Capability ids
        "result": str,
        "error": str,
    })


def validate_agent(a: dict) -> list[str]:
    problems = _check(a, "Agent", required={
        "id": str,
        "provider": str,
        "description": str,
        "roles": list,
    }, optional={
        "strengths": str, "limitations": str, "notes": str,
    })
    for role in a.get("roles", []) if isinstance(a, dict) else []:
        if role not in AGENT_ROLES:
            problems.append(f"Agent.roles: {role!r} not in {sorted(AGENT_ROLES)}")
    return problems


def validate_approval(ap: dict) -> list[str]:
    return _check(ap, "Approval", required={
        "id": str,
        "requested_action": str,
        "reason": str,
        "consequence": str,
        "reversible": bool,
        "state": (str, APPROVAL_STATES),
        "requested_at": str,
    }, optional={
        "expires": str, "task": str, "decided_at": str, "decided_via": str,
    })


def validate_action_record(r: dict) -> list[str]:
    return _check(r, "ActionRecord", required={
        "id": str,
        "capability": str,
        "provider": str,
        "requested_by": str,
        "timestamp": str,
        "policy_decision": str,
        "result": str,
    }, optional={
        "task_id": str, "inputs_summary": str, "verification": str,
        "reversible": bool,
    })
