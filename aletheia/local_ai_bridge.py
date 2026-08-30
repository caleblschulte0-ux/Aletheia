"""Review-only CLI bridge from Aletheia-shaped input to the local model pool.

This proves that Aletheia can access the installed Ollama models without
modifying ``aletheia.assistant`` or any canonical action path.

Examples:
    python -m aletheia.local_ai_bridge status
    python -m aletheia.local_ai_bridge ask "What needs attention?"
    python -m aletheia.local_ai_bridge ask --mode fast "Summarize this"
    python -m aletheia.local_ai_bridge ask --mode deep "Review the architecture"
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from aletheia import brain, local_model_pool, model_pool_config


def _read_context(path: str | None) -> dict:
    if not path:
        return {}
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("context file must contain one JSON object")
    return value


def _emit(value: dict) -> int:
    print(json.dumps(value, ensure_ascii=False, indent=2, default=str))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m aletheia.local_ai_bridge",
        description="Branch-only bridge to Aletheia's local fast/deep model pool.",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status", help="show both local model roles and Ollama availability")
    sub.add_parser("profiles", help="show machine-local fast/deep model configuration")

    ask = sub.add_parser("ask", help="run one Aletheia brain proposal through the local pool")
    ask.add_argument("text")
    ask.add_argument("--mode", choices=("auto", "fast", "deep", "fallback"), default="auto")
    ask.add_argument("--context", help="optional JSON object file supplied as untrusted context")

    route = sub.add_parser("route", help="show which role auto-routing would choose without inference")
    route.add_argument("text")
    route.add_argument("--context")

    args = parser.parse_args(argv)

    if args.command == "status":
        return _emit(local_model_pool.status())
    if args.command == "profiles":
        return _emit(model_pool_config.show())

    context = _read_context(args.context)
    if args.command == "route":
        decision = local_model_pool.choose_role(args.text, context)
        return _emit({"role": decision.role, "reason": decision.reason})

    if args.mode == "fallback":
        return _emit({
            "route": {"role": "fallback", "reason": "explicit"},
            "output": brain.FALLBACK.run(args.text, context),
        })
    if args.mode == "fast":
        output = local_model_pool.run_fast(args.text, context)
        return _emit({"route": {"role": "fast", "reason": "explicit"}, "output": output})
    if args.mode == "deep":
        output = local_model_pool.run_deep(args.text, context)
        return _emit({"route": {"role": "deep", "reason": "explicit"}, "output": output})

    decision, output = local_model_pool.run_auto(args.text, context)
    return _emit({
        "route": {"role": decision.role, "reason": decision.reason},
        "output": output,
    })


if __name__ == "__main__":
    raise SystemExit(main())
