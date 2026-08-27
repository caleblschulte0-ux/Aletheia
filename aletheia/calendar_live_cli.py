"""Operator CLI for configured official calendar providers.

No credential material is printed. `execute` does not create authority: it calls
the existing calendar_provider.execute_write_plan, which requires an exact
APPROVED plan and rechecks the kill switch before the provider is touched.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path

from aletheia import calendar_live, calendar_provider


def _object(path: str) -> dict:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("JSON file must contain an object")
    return value


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Aletheia official live calendar")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    sync = sub.add_parser("sync")
    sync.add_argument("--now", help="aware ISO timestamp for acceptance testing")
    exe = sub.add_parser("execute")
    exe.add_argument("plan_file")
    exe.add_argument("approval_id")
    args = ap.parse_args(argv)

    if args.cmd == "status":
        ok, reason = calendar_live.available()
        print(("READY: " if ok else "NOT READY: ") + reason)
        return 0 if ok else 2
    if args.cmd == "sync":
        now = (dt.datetime.fromisoformat(args.now.replace("Z", "+00:00"))
               if args.now else None)
        print(json.dumps(calendar_live.refresh(now=now), indent=2, ensure_ascii=False))
        return 0
    plan = _object(args.plan_file)
    provider = calendar_live.build_provider()
    print(json.dumps(
        calendar_provider.execute_write_plan(plan, args.approval_id, provider),
        indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
