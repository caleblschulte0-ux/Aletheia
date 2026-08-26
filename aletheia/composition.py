"""Deterministic multi-capability recipe validation and compilation.

Aletheia should solve outcomes by composing primitives instead of growing a
special-case command for every sentence. Recipes are data: dependency-ordered
capability steps. Compilation checks the live capability registry and reports
exact blockers; it never executes a step or pretends NOT_BUILT is usable.
"""
from __future__ import annotations

from aletheia import capabilities
from aletheia.stateio import safe_id


def validate_recipe(recipe: dict) -> None:
    required = {"version", "id", "title", "steps"}
    missing = required - recipe.keys()
    if missing:
        raise ValueError(f"recipe missing {sorted(missing)}")
    if recipe["version"] != 1:
        raise ValueError("unsupported recipe version")
    safe_id(recipe["id"], name="recipe id")
    if not isinstance(recipe["title"], str) or not recipe["title"].strip():
        raise ValueError("recipe title is required")
    if not isinstance(recipe["steps"], list) or not recipe["steps"]:
        raise ValueError("recipe steps must be a non-empty list")
    ids: set[str] = set()
    for step in recipe["steps"]:
        if not isinstance(step, dict):
            raise ValueError("recipe step must be an object")
        unknown = set(step) - {"id", "capability", "depends_on", "action", "inputs"}
        if unknown:
            raise ValueError(f"recipe step has unknown fields {sorted(unknown)}")
        sid = safe_id(step.get("id", ""), name="recipe step id")
        if sid in ids:
            raise ValueError(f"duplicate recipe step {sid!r}")
        ids.add(sid)
        if not isinstance(step.get("capability"), str) or not step["capability"].strip():
            raise ValueError(f"step {sid!r} capability is required")
        deps = step.get("depends_on", [])
        if not isinstance(deps, list) or any(not isinstance(d, str) for d in deps):
            raise ValueError(f"step {sid!r} depends_on must be strings")
        if len(set(deps)) != len(deps) or sid in deps:
            raise ValueError(f"step {sid!r} has invalid dependencies")
        if "inputs" in step and not isinstance(step["inputs"], dict):
            raise ValueError(f"step {sid!r} inputs must be an object")
        if "action" in step and (not isinstance(step["action"], str) or not step["action"].strip()):
            raise ValueError(f"step {sid!r} action must be non-empty")
    for step in recipe["steps"]:
        missing_deps = set(step.get("depends_on", [])) - ids
        if missing_deps:
            raise ValueError(f"step {step['id']!r} depends on unknown steps {sorted(missing_deps)}")
    topological_order(recipe)  # cycle check


def topological_order(recipe: dict) -> list[str]:
    steps = recipe.get("steps", [])
    by_id = {step.get("id"): step for step in steps if isinstance(step, dict)}
    visiting: set[str] = set()
    visited: set[str] = set()
    order: list[str] = []

    def visit(sid: str) -> None:
        if sid in visited:
            return
        if sid in visiting:
            raise ValueError("recipe dependency cycle detected")
        if sid not in by_id:
            raise ValueError(f"unknown recipe step {sid!r}")
        visiting.add(sid)
        for dep in by_id[sid].get("depends_on", []):
            visit(dep)
        visiting.remove(sid)
        visited.add(sid)
        order.append(sid)

    for step in steps:
        visit(step["id"])
    return order


def required_capabilities(recipe: dict) -> list[str]:
    validate_recipe(recipe)
    return list(dict.fromkeys(step["capability"] for step in recipe["steps"]))


def compile_recipe(recipe: dict, *, registry: dict | None = None) -> dict:
    validate_recipe(recipe)
    registry = registry or capabilities.load_registry()
    cap_index = {c["id"]: c for c in registry.get("capabilities", [])}
    by_id = {step["id"]: step for step in recipe["steps"]}
    compiled: dict[str, dict] = {}
    blockers: list[dict] = []
    for sid in topological_order(recipe):
        step = by_id[sid]
        cap = cap_index.get(step["capability"])
        dependency_blockers = [dep for dep in step.get("depends_on", [])
                               if compiled[dep]["status"] != "READY"]
        if dependency_blockers:
            status = "BLOCKED_DEPENDENCY"
            reason = f"blocked by steps {dependency_blockers}"
        elif cap is None:
            status = "BLOCKED_CAPABILITY"
            reason = f"capability {step['capability']} is unknown"
        elif cap["status"] != "AVAILABLE":
            status = "BLOCKED_CAPABILITY"
            reason = f"capability {step['capability']} is {cap['status']}"
        else:
            status = "READY"
            reason = ""
        row = {"id": sid, "capability": step["capability"], "status": status,
               "depends_on": list(step.get("depends_on", []))}
        if step.get("action"):
            row["action"] = step["action"]
        if step.get("inputs"):
            row["inputs"] = step["inputs"]
        if reason:
            row["reason"] = reason
            blockers.append({"step": sid, "reason": reason})
        compiled[sid] = row
    ordered = [compiled[sid] for sid in topological_order(recipe)]
    return {"recipe_id": recipe["id"], "ready": not blockers,
            "steps": ordered, "blockers": blockers}
