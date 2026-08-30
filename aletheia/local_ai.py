"""Read/configure the local-AI foundation without exposing model internals to callers."""
from __future__ import annotations

import argparse
import json

from aletheia import model_pool_config, reasoning_gateway, training_data


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m aletheia.local_ai")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    sub.add_parser("training")
    sub.add_parser("models")
    fb = sub.add_parser("feedback")
    fb.add_argument("turn_id")
    fb.add_argument("verdict", choices=["good", "bad", "mixed", "corrected"])
    fb.add_argument("--note", default="")
    args = parser.parse_args(argv)

    if args.cmd == "status":
        value = reasoning_gateway.status()
    elif args.cmd == "training":
        value = training_data.stats()
    elif args.cmd == "models":
        value = model_pool_config.show()
    else:
        value = {
            "feedback_id": training_data.record_feedback(
                args.turn_id, verdict=args.verdict, note=args.note,
            ),
            "turn_id": args.turn_id,
            "verdict": args.verdict,
        }
    print(json.dumps(value, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
