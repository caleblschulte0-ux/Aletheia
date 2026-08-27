"""Operator CLI for bounded proactive rules.

This is intentionally a planning/configuration surface only. It can create,
list, enable, or disable rules; it never executes a proposed action.
"""
from __future__ import annotations

import argparse
import json

from aletheia import notifications, proactive


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Aletheia proactive rule tools")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    p = sub.add_parser("new")
    p.add_argument("id")
    p.add_argument("--on", dest="event_kind", required=True)
    p.add_argument("--action", choices=sorted(proactive.ACTIONS), required=True)
    p.add_argument("--priority", choices=sorted(notifications.PRIORITIES), default="NORMAL")
    p.add_argument("--source")
    p.add_argument("--subject-prefix")
    p.add_argument("--cooldown-minutes", type=int, default=0)
    p.add_argument("--once", action="store_true")
    p = sub.add_parser("enable"); p.add_argument("id")
    p = sub.add_parser("disable"); p.add_argument("id")
    args = ap.parse_args(argv)
    if args.cmd == "list":
        print(json.dumps(proactive.all_rules(), indent=2)); return 0
    if args.cmd == "enable":
        print(json.dumps(proactive.set_enabled(args.id, True), indent=2)); return 0
    if args.cmd == "disable":
        print(json.dumps(proactive.set_enabled(args.id, False), indent=2)); return 0
    value = proactive.create_rule(
        args.id, event_kind=args.event_kind, action=args.action,
        source=args.source, subject_prefix=args.subject_prefix,
        cooldown_minutes=args.cooldown_minutes, persistent=not args.once,
        priority=args.priority)
    print(json.dumps(value, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
