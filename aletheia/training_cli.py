"""Operator utilities for Aletheia's local future-model dataset."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from aletheia import training_data


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m aletheia.training_cli")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status", help="show retained training/evaluation data counts")

    export = sub.add_parser("export", help="export retained events as portable JSONL")
    export.add_argument("path")

    feedback = sub.add_parser("feedback", help="label/correct a retained reasoning turn")
    feedback.add_argument("turn_id")
    feedback.add_argument("--verdict", required=True, choices=("good", "bad", "mixed", "corrected"))
    feedback.add_argument("--note", default="")
    feedback.add_argument("--corrected-json", help="path to corrected brain-result JSON")

    args = parser.parse_args(argv)
    if args.command == "status":
        output = training_data.stats()
    elif args.command == "export":
        count = training_data.export_jsonl(args.path)
        output = {"exported": count, "path": str(Path(args.path).expanduser())}
    else:
        corrected = None
        if args.corrected_json:
            corrected = json.loads(Path(args.corrected_json).read_text(encoding="utf-8"))
            if not isinstance(corrected, dict):
                raise ValueError("corrected JSON must be one object")
        feedback_id = training_data.record_feedback(
            args.turn_id, verdict=args.verdict, corrected_result=corrected, note=args.note)
        output = {"feedback_id": feedback_id, "turn_id": args.turn_id, "verdict": args.verdict}
    print(json.dumps(output, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
