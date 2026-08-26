"""Capability composition without authority escalation.

Recipes describe how outcomes emerge from reusable primitives. Planning checks
registry truth and returns ordered steps plus gaps; it never executes the steps
and never treats one capability's permission as another's.
"""
from __future__ import annotations

from aletheia import gaps

RECIPES = {
    "meeting.schedule": ["contacts.resolve", "calendar.availability", "communication.track"],
    "reply.wait": ["communication.track", "watcher.evaluate"],
    "room.scene": ["device.registry", "room.scene.plan"],
    "capability.expand": ["capability.gap.assess", "task.persist", "agent.delegate"],
    "handle.project": ["context.resolve", "project.manage", "task.persist", "action.verify"],
}


def register_recipe(name: str, requirements: list[str], *, registry: dict | None = None) -> dict:
    """Return a validated recipe proposal; runtime global recipes stay code-reviewed.

    This deliberately does not mutate RECIPES from user input. Dynamic code/data
    registration would turn a planning convenience into an authority surface.
    """
    if not isinstance(name, str) or not name.strip() or "." not in name:
        raise ValueError("recipe name must be a dotted non-empty string")
    if not isinstance(requirements, list) or not requirements or any(not isinstance(x, str) or not x for x in requirements):
        raise ValueError("requirements must be non-empty capability ids")
    if len(set(requirements)) != len(requirements):
        raise ValueError("recipe requirements must be unique")
    report = gaps.assess(requirements, registry=registry)
    return {"name": name, "requirements": list(requirements), "assessment": report}


def plan(name: str, *, registry: dict | None = None) -> dict:
    if name not in RECIPES:
        raise KeyError(f"no capability recipe {name!r}")
    requirements = RECIPES[name]
    report = gaps.assess(requirements, registry=registry)
    return {
        "recipe": name,
        "steps": [{"n": i + 1, "capability": cid} for i, cid in enumerate(requirements)],
        "ready": report["satisfied"],
        "gaps": {"blocked": report["blocked"], "unknown": report["unknown"]},
    }
