"""Declarative room scenes over the provider-neutral device registry.

Scenes are plans, not executions. Every target device must be verified ONLINE
and declare the requested ability before a scene can be considered executable.
Actual Home Assistant/device writes remain a provider integration and policy
boundary.
"""
from __future__ import annotations

from pathlib import Path

from aletheia import devices
from aletheia.stateio import private_dir, read_json, safe_id, utcnow, write_json_atomic

SCENES_DIR = private_dir("room") / "scenes"


def _path(scene_id: str) -> Path:
    return SCENES_DIR / f"{safe_id(scene_id, name='scene id')}.json"


def validate(scene: dict) -> None:
    required = {"version", "id", "name", "steps", "created_at", "updated_at"}
    missing = required - scene.keys()
    if missing:
        raise ValueError(f"scene missing {sorted(missing)}")
    if scene["version"] != 1:
        raise ValueError("unsupported scene version")
    safe_id(scene["id"], name="scene id")
    if not isinstance(scene["name"], str) or not scene["name"].strip():
        raise ValueError("scene name is required")
    if not isinstance(scene["steps"], list) or not scene["steps"]:
        raise ValueError("scene requires at least one step")
    for step in scene["steps"]:
        if not isinstance(step, dict) or set(step) - {"device", "ability", "value"}:
            raise ValueError("scene steps allow only device/ability/value")
        if not isinstance(step.get("device"), str) or not isinstance(step.get("ability"), str):
            raise ValueError("scene step device and ability are required")


def create(scene_id: str, name: str, steps: list[dict]) -> dict:
    if _path(scene_id).exists():
        raise FileExistsError(scene_id)
    now = utcnow()
    scene = {"version": 1, "id": safe_id(scene_id, name="scene id"), "name": name,
             "steps": steps, "created_at": now, "updated_at": now}
    validate(scene)
    write_json_atomic(_path(scene_id), scene)
    return scene


def load(scene_id: str) -> dict:
    scene = read_json(_path(scene_id))
    validate(scene)
    return scene


def plan(scene_id: str) -> dict:
    scene = load(scene_id)
    planned = []
    for step in scene["steps"]:
        device = devices.load(step["device"])
        devices.require_ability(device, step["ability"])
        planned.append({"device": device["id"], "provider": device["provider"],
                        "external_id": device["external_id"], "ability": step["ability"],
                        "value": step.get("value")})
    return {"scene": scene["id"], "status": "READY_FOR_PROVIDER", "steps": planned}
