"""Local model selection with no code edits required.

Precedence is intentionally simple:
1. explicit model passed by a caller;
2. ALETHEIA_LOCAL_AI_MODEL environment override;
3. local config file outside Git;
4. conservative bootstrap default.

The local config lives beside Aletheia's other machine-local data, so swapping
models never requires a repository commit.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

DEFAULT_MODEL = "qwen3:8b"
ENV_MODEL = "ALETHEIA_LOCAL_AI_MODEL"
ENV_CONFIG_DIR = "ALETHEIA_LOCAL_AI_CONFIG_DIR"


def config_root() -> Path:
    override = os.environ.get(ENV_CONFIG_DIR)
    if override:
        return Path(override).expanduser()
    local = os.environ.get("LOCALAPPDATA")
    if local:
        return Path(local) / "Aletheia" / "local-ai"
    return Path.home() / ".aletheia" / "local-ai"


def config_path() -> Path:
    return config_root() / "config.json"


def _validate_model(model: str) -> str:
    value = str(model).strip()
    if not value or len(value) > 200 or any(ch in value for ch in "\r\n\x00"):
        raise ValueError("model name must be non-empty, single-line, and bounded")
    return value


def load_saved_model() -> str | None:
    path = config_path()
    if not path.exists():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(value, dict) or not isinstance(value.get("model"), str):
        return None
    try:
        return _validate_model(value["model"])
    except ValueError:
        return None


def resolve_model(explicit: str | None = None) -> str:
    if explicit is not None:
        return _validate_model(explicit)
    env_model = os.environ.get(ENV_MODEL)
    if env_model:
        return _validate_model(env_model)
    return load_saved_model() or DEFAULT_MODEL


def save_model(model: str) -> Path:
    value = _validate_model(model)
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({"model": value}, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    return path


def show() -> dict:
    return {
        "model": resolve_model(),
        "source": (
            "environment" if os.environ.get(ENV_MODEL) else
            "local_config" if load_saved_model() else
            "default"
        ),
        "config_path": str(config_path()),
        "default": DEFAULT_MODEL,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m aletheia.model_config")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("show", help="show the effective local model")
    set_parser = sub.add_parser("set", help="change the saved local model")
    set_parser.add_argument("model")
    args = parser.parse_args(argv)
    if args.command == "set":
        path = save_model(args.model)
        output = {"model": resolve_model(), "saved_to": str(path)}
    else:
        output = show()
    print(json.dumps(output, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
