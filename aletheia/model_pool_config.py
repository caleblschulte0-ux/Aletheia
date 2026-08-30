"""Machine-local model-role configuration for Aletheia's local reasoning pool.

Roles are stable; concrete model names are not.  Swapping the fast/deep local
models must never require a Git commit.  Configuration lives in Aletheia's
private state and may be overridden by environment variables for testing.
"""
from __future__ import annotations

import json
import os
from typing import Any

from aletheia import stateio

ENV_FAST_MODEL = "ALETHEIA_LOCAL_AI_FAST_MODEL"
ENV_DEEP_MODEL = "ALETHEIA_LOCAL_AI_DEEP_MODEL"
DEFAULTS: dict[str, dict[str, Any]] = {
    "fast": {"model": "qwen3:8b", "think": False},
    "deep": {"model": "qwen3.6:27b", "think": True},
}


def config_path():
    return stateio.private_dir("local-ai") / "model-pool.json"


def _model(value: object) -> str:
    text = str(value or "").strip()
    if not text or len(text) > 200 or any(ch in text for ch in "\r\n\x00"):
        raise ValueError("model name must be non-empty, single-line, and bounded")
    return text


def _saved() -> dict:
    path = config_path()
    if not path.is_file():
        return {}
    try:
        return stateio.read_json(path)
    except ValueError:
        return {}


def resolve(role: str) -> dict[str, Any]:
    if role not in DEFAULTS:
        raise ValueError("role must be fast or deep")
    saved = _saved().get(role)
    saved = saved if isinstance(saved, dict) else {}
    env_name = ENV_FAST_MODEL if role == "fast" else ENV_DEEP_MODEL
    env_model = os.environ.get(env_name, "").strip()
    model = _model(env_model or saved.get("model") or DEFAULTS[role]["model"])
    think = saved.get("think", DEFAULTS[role]["think"])
    if type(think) is not bool:
        think = DEFAULTS[role]["think"]
    return {
        "role": role,
        "model": model,
        "think": think,
        "source": "environment" if env_model else "local_config" if saved.get("model") else "default",
    }


def save(role: str, *, model: str | None = None, think: bool | None = None):
    current = _saved()
    effective = resolve(role)
    current[role] = {
        "model": _model(model if model is not None else effective["model"]),
        "think": effective["think"] if think is None else bool(think),
    }
    path = config_path()
    stateio.write_json_atomic(path, current)
    return path


def show() -> dict[str, Any]:
    return {"fast": resolve("fast"), "deep": resolve("deep"), "config_path": str(config_path())}
