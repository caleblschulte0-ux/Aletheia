"""Read-only/operator CLI for the Phase 11 audio-router control plane.

This CLI deliberately cannot activate a route: this branch has no reviewed live
Windows routing backend. It inventories devices, validates plans, and proposes
logical plans from JSON so the live acceptance step can be evidence-driven.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from aletheia import audio_router


def _json_file(path: str) -> object:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    return value


def _inventory_summary(devices: list[dict]) -> dict:
    inputs = [d for d in devices if d["input_channels"] > 0]
    outputs = [d for d in devices if d["output_channels"] > 0]
    virtual_tokens = ("cable", "voicemeeter", "virtual", "vb-audio")
    virtual = [d for d in devices if any(t in d["name"].casefold() for t in virtual_tokens)]
    return {
        "device_count": len(devices),
        "input_capable": len(inputs),
        "output_capable": len(outputs),
        "virtual_candidates": len(virtual),
        "ready_for_live_route_test": bool(inputs and outputs and virtual),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Aletheia Phase 11 audio-router tools")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("inventory", help="read sounddevice inventory; changes nothing")
    p = sub.add_parser("show", help="validate and print one private route plan")
    p.add_argument("plan_id")
    p = sub.add_parser("plan", help="create a private logical route plan from JSON files")
    p.add_argument("plan_id")
    p.add_argument("--purpose", choices=sorted(audio_router.ROUTE_PURPOSES), required=True)
    p.add_argument("--endpoints", required=True, help="JSON file containing endpoint array")
    p.add_argument("--routes", required=True, help="JSON file containing route array")
    p.add_argument("--notes", default="")
    args = ap.parse_args(argv)

    if args.cmd == "inventory":
        try:
            devices = audio_router.sounddevice_inventory()
        except RuntimeError as exc:
            print(json.dumps({"available": False, "reason": str(exc)}, indent=2))
            return 2
        print(json.dumps({"available": True, "summary": _inventory_summary(devices),
                          "devices": devices}, indent=2))
        return 0
    if args.cmd == "show":
        print(json.dumps(audio_router.load_plan(args.plan_id), indent=2))
        return 0
    endpoints = _json_file(args.endpoints)
    routes = _json_file(args.routes)
    if not isinstance(endpoints, list) or not isinstance(routes, list):
        raise SystemExit("endpoint and route JSON files must contain arrays")
    value = audio_router.build_plan(args.plan_id, purpose=args.purpose,
                                    endpoints=endpoints, routes=routes, notes=args.notes)
    print(json.dumps(value, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
