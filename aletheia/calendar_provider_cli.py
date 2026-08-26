"""CLI for the provider-neutral calendar boundary.

This caller can normalize provider-shaped fixtures and construct exact write
plans/approval requests. It deliberately cannot connect to Google/Outlook; a
live adapter remains a separate capability and configuration task.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from aletheia import calendar_provider


def _json_file(path: str) -> dict:
    value=json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value,dict): raise ValueError("JSON file must contain an object")
    return value


def main(argv: list[str] | None=None) -> int:
    ap=argparse.ArgumentParser(description="Aletheia calendar provider contract")
    sub=ap.add_subparsers(dest="cmd",required=True)
    n=sub.add_parser("normalize"); n.add_argument("file")
    p=sub.add_parser("plan"); p.add_argument("action",choices=["CREATE","UPDATE","CANCEL"]); p.add_argument("--provider",required=True); p.add_argument("--event-file"); p.add_argument("--external-id")
    a=sub.add_parser("request-approval"); a.add_argument("approval_id"); a.add_argument("plan_file"); a.add_argument("--reason",default="calendar change")
    args=ap.parse_args(argv)
    if args.cmd=="normalize":
        print(json.dumps(calendar_provider.normalize_event(_json_file(args.file)),indent=2,ensure_ascii=False)); return 0
    if args.cmd=="plan":
        event=_json_file(args.event_file) if args.event_file else None
        print(json.dumps(calendar_provider.build_write_plan(args.action,args.provider,event=event,external_id=args.external_id),indent=2,ensure_ascii=False)); return 0
    plan=_json_file(args.plan_file)
    print(json.dumps(calendar_provider.request_write_approval(args.approval_id,plan,reason=args.reason),indent=2,ensure_ascii=False)); return 0


if __name__=="__main__": raise SystemExit(main())
