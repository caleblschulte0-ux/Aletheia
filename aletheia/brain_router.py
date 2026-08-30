"""Isolated local-first reasoning front door.

This is deliberately a new module on the ChatGPT integration branch rather
than a modification to ``aletheia.assistant``. Claude can review and wire the
same behavior into the canonical CLI later without main being touched now.

Usage:
    python -m aletheia.brain_router status
    python -m aletheia.brain_router interpret "what needs my attention?"
    python -m aletheia.brain_router interpret --provider local "draft a plan"
    python -m aletheia.brain_router interpret --provider fallback "test"
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from aletheia import brain, local_brain


def _print(value) -> int:
    print(json.dumps(value, indent=2, ensure_ascii=False, default=str))
    return 0


def _read_context(path: str | None) -> dict:
    if not path:
        return {}
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("context file must contain one JSON object")
    return raw


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m aletheia.brain_router",
        description="Local-first, fail-closed reasoning socket for Aletheia.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    status_parser = sub.add_parser("status", help="check Ollama and configured local model")
    status_parser.add_argument("--model")
    status_parser.add_argument("--url")

    interpret = sub.add_parser("interpret", help="interpret bounded operator text")
    interpret.add_argument("text")
    interpret.add_argument("--provider", choices=("auto", "local", "fallback"), default="auto")
    interpret.add_argument("--context", help="path to a JSON object used as untrusted context")
    interpret.add_argument("--model")
    interpret.add_argument("--url")

    args = parser.parse_args(argv)
    env_cfg = local_brain.OllamaConfig.from_env()
    cfg = local_brain.OllamaConfig(
        base_url=args.url or env_cfg.base_url,
        model=args.model or env_cfg.model,
        timeout_seconds=env_cfg.timeout_seconds,
    ).validated()

    if args.command == "status":
        return _print(local_brain.status(config=cfg))

    context = _read_context(args.context)
    if args.provider == "fallback":
        return _print(brain.FALLBACK.run(args.text, context))
    if args.provider == "local":
        return _print(local_brain.run_local(args.text, context, config=cfg))
    return _print(local_brain.run_auto(args.text, context, config=cfg))


if __name__ == "__main__":
    raise SystemExit(main())
