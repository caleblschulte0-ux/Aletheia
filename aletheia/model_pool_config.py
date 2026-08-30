"""Machine-local model-role configuration for Aletheia's local reasoning pool.

Roles are stable; concrete model names are not.  Swapping the fast/deep local
models must never require a Git commit. Configuration lives in Aletheia's
private state; environment variables may constrain it or opt in only when no
explicit machine-local off switch exists.
"""
from __future__ import annotations

import os
from typing import Any

from aletheia import stateio

ENV_FAST_MODEL = "ALETHEIA_LOCAL_AI_FAST_MODEL"
ENV_DEEP_MODEL = "ALETHEIA_LOCAL_AI_DEEP_MODEL"
ENV_ENABLED = "ALETHEIA_LOCAL_AI_ENABLED"
ENV_SHADOW = "ALETHEIA_LOCAL_AI_SHADOW"
DEFAULTS: dict[str, dict[str, Any]] = {
    "fast": {"model": "qwen3:8b", "think": False},
    "deep": {"model": "qwen3.6:27b", "think": True},
}
SETTING_DEFAULTS = {"enabled": False, "shadow": False}


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


def _bool(value: object, default: bool) -> bool:
    if type(value) is bool:
        return value
    text = str(value or "").strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return default


def settings() -> dict[str, Any]:
    saved = _saved()
    enabled_env = os.environ.get(ENV_ENABLED)
    shadow_env = os.environ.get(ENV_SHADOW)
    saved_enabled = saved.get("enabled")
    saved_shadow = saved.get("shadow")

    # A machine-local explicit "off" is an emergency brake. Environment
    # variables may opt in when no local decision exists, or turn a saved opt-in
    # off, but they may never undo `local_ai deactivate` or enable shadowing
    # behind an operator's explicit local setting.
    if saved_enabled is False:
        enabled = False
        enabled_source = "local_config"
    elif enabled_env is not None:
        enabled = _bool(enabled_env, SETTING_DEFAULTS["enabled"])
        enabled_source = "environment"
    else:
        enabled = _bool(saved_enabled, SETTING_DEFAULTS["enabled"])
        enabled_source = "local_config" if "enabled" in saved else "default"

    if saved_shadow is False:
        shadow = False
        shadow_source = "local_config"
    elif shadow_env is not None:
        shadow = _bool(shadow_env, SETTING_DEFAULTS["shadow"])
        shadow_source = "environment"
    else:
        shadow = _bool(saved_shadow, SETTING_DEFAULTS["shadow"])
        shadow_source = "local_config" if "shadow" in saved else "default"
    # A disabled local pool never gets to run background students, even if a
    # stale machine-local setting says shadow=true.
    return {
        "enabled": enabled,
        "shadow": bool(enabled and shadow),
        "enabled_source": enabled_source,
        "shadow_source": shadow_source,
    }


def enabled() -> bool:
    return bool(settings()["enabled"])


def shadow_enabled() -> bool:
    return bool(settings()["shadow"])


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


def save_settings(*, enabled: bool | None = None,
                  shadow: bool | None = None):
    current = _saved()
    effective = settings()
    current["enabled"] = effective["enabled"] if enabled is None else bool(enabled)
    current["shadow"] = effective["shadow"] if shadow is None else bool(shadow)
    if not current["enabled"]:
        current["shadow"] = False
    path = config_path()
    stateio.write_json_atomic(path, current)
    return path


def show() -> dict[str, Any]:
    return {
        **settings(),
        "fast": resolve("fast"),
        "deep": resolve("deep"),
        "config_path": str(config_path()),
    }
