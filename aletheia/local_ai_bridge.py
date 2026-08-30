"""Review-only CLI proving Aletheia's stable local reasoning integration gateway.

This CLI intentionally sits on TOP of ``aletheia.reasoning_gateway``. It is a
human-test surface for the same API canonical Aletheia could later call.

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

from aletheia import local_model_pool, model_pool_config, reasoning_gateway


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
        description="Branch-only test surface for Aletheia's reasoning integration gateway.",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status", help="show gateway + local model health")
    sub.add_parser("profiles", help="show machine-local fast/deep model configuration")

    ask = sub.add_parser("ask", help="run one Aletheia brain proposal through the gateway")
    ask.add_argument("text")
    ask.add_argument("--mode", choices=sorted(reasoning_gateway.MODES), default="auto")
    ask.add_argument("--context", help="optional JSON object file supplied as untrusted context")

    route = sub.add_parser("route", help="show which role auto-routing would choose without inference")
    route.add_argument("text")
    route.add_argument("--context")

    feedback = sub.add_parser("feedback", help="label one retained model turn")
    feedback.add_argument("turn_id")
    feedback.add_argument("--verdict", required=True, choices=("good", "bad", "mixed", "corrected"))
    feedback.add_argument("--note", default="")

    args = parser.parse_args(argv)

    if args.command == "status":
        return _emit(reasoning_gateway.status())
    if args.command == "profiles":
        return _emit(model_pool_config.show())
    if args.command == "feedback":
        return _emit(reasoning_gateway.feedback(
            args.turn_id, verdict=args.verdict, note=args.note))

    context = _read_context(args.context)
    if args.command == "route":
        decision = local_model_pool.choose_role(args.text, context)
        return _emit({"role": decision.role, "reason": decision.reason})

    result = reasoning_gateway.interpret_with_meta(args.text, context, mode=args.mode)
    return _emit(result.as_dict())


if __name__ == "__main__":
    raise SystemExit(main())
