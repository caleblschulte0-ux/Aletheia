"""Run the Jarvis loop entirely in simulation.

Usage:
    python -m staging.jarvis_v0.demo

The word SIMULATED is intentional: this module cannot control the PC.
"""
from __future__ import annotations

import json

from .fakes import demo_stack
from .loop import JarvisLoop


def main() -> int:
    stack = demo_stack()
    result = JarvisLoop(**stack).run("Open Barkly and tell me what is going on.")
    print(json.dumps(
        {
            "simulated": True,
            "outcome": result.outcome.value,
            "summary": result.summary,
            "plan_id": result.plan.plan_id if result.plan else None,
            "steps": [receipt.capability for receipt in result.receipts],
            "trace": [
                {"phase": event.phase.value, "message": event.message}
                for event in result.trace
            ],
        },
        indent=2,
    ))
    return 0 if result.outcome.value == "complete" else 1


if __name__ == "__main__":
    raise SystemExit(main())
