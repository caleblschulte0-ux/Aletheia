"""Machine-local configuration for Aletheia's local model pool.

This staging module deliberately lives outside the canonical assistant wiring.
It defines *roles*, not permanent model identities:

- fast: low-latency everyday reasoning, thinking disabled by default
- deep: heavier reasoning, thinking enabled by default

The backing model names are machine-local configuration, so upgrading or
replacing either role requires no Aletheia code change or Git commit.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

ENV_CONFIG_DIR = "ALETHEIA_LOCAL_AI_CONFIG_DIR"
ENV_FAST_MODEL = "ALETHEIA_LOCAL_AI_FAST_MODEL"
ENV_DEEP_MODEL = "ALETHEIA_LOCAL_AI_DEEP_MODEL"

DEFAULTS: dict[str, dict[str, Any]] = {
    "fast": {"model": "qwen3:8b", "think": False},
    "deep": {"model": "qwen3.6:27b", "think": True},
}


def config_root() -> Path:
    override = os.environ.get(ENV_CONFIG_DIR)
    if override:
        return Path(override).expanduser()
    local = os.environ.get("LOCALAPPDATA")
    if local:
        return Path(local) / "Aletheia" / "local-ai"
    return Path.home() / ".aletheia" / "local-ai"


def config_path() -> Path:
    return config_root() / "model-pool.json"


def _model(value: str) -> str:
    value = str(value).strip()
    if not value or len(value) > 200 or any(ch in value for ch in "\r\n\x00"):
        raise ValueError("model name must be non-empty, single-line, and bounded")
    return value


def _load_saved() -> dict[str, Any]:
    path = config_path()
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def resolve_profile(role: str) -> dict[str, Any]:
    if role not in DEFAULTS:
        raise ValueError("role must be fast or deep")
    saved = _load_saved().get(role, {})
    if not isinstance(saved, dict):
        saved = {}
    env_name = ENV_FAST_MODEL if role == "fast" else ENV_DEEP_MODEL
    raw_model = os.environ.get(env_name) or saved.get("model") or DEFAULTS[role]["model"]
    raw_think = saved.get("think", DEFAULTS[role]["think"])
    return {
        "role": role,
        "model": _model(raw_model),
        "think": bool(raw_think),
        "source": (
            "environment" if os.environ.get(env_name) else
            "local_config" if saved.get("model") else
            "default"
        ),
    }


def save_profile(role: str, *, model: str | None = None, think: bool | None = None) -> Path:
    current = _load_saved()
    effective = resolve_profile(role)
    entry = current.get(role, {})
    if not isinstance(entry, dict):
        entry = {}
    entry["model"] = _model(model if model is not None else effective["model"])
    entry["think"] = effective["think"] if think is None else bool(think)
    current[role] = entry
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(current, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    return path


def show() -> dict[str, Any]:
    return {
        "fast": resolve_profile("fast"),
        "deep": resolve_profile("deep"),
        "config_path": str(config_path()),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m aletheia.model_pool_config")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("show")
    for role in ("fast", "deep"):
        p = sub.add_parser(f"set-{role}")
        p.add_argument("model")
        think = p.add_mutually_exclusive_group()
        think.add_argument("--think", action="store_true")
        think.add_argument("--no-think", action="store_true")
    args = parser.parse_args(argv)
    if args.command == "show":
        output = show()
    else:
        role = args.command.removeprefix("set-")
        think_value = None
        if args.think:
            think_value = True
        elif args.no_think:
            think_value = False
        path = save_profile(role, model=args.model, think=think_value)
        output = {"saved_to": str(path), "profile": resolve_profile(role)}
    print(json.dumps(output, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
