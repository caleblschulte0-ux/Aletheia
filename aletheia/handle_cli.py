"""Operator/worker CLI for persistent handle-it requests.

The CLI manipulates orchestration state only. Candidate commands are proposals;
execution still goes through the Core/intercom gates. This gives every v2 state
transition a real caller without widening authority.
"""
from __future__ import annotations

import argparse
import json

from aletheia import handler


def _candidate(text: str) -> dict:
    """id=capability,capability form; command execution is not accepted here."""
    if "=" not in text: raise argparse.ArgumentTypeError("candidate must be id=capability[,capability]")
    cid, raw=text.split("=",1); caps=[x.strip() for x in raw.split(",") if x.strip()]
    if not cid.strip(): raise argparse.ArgumentTypeError("candidate id required")
    return {"id":cid.strip(),"required_capabilities":caps}


def _reference(text: str) -> dict:
    if ":" in text:
        kind,label=text.split(":",1); return {"kind":kind,"label":label}
    return {"kind":text}


def _print(value) -> None: print(json.dumps(value,indent=2,ensure_ascii=False))


def main(argv: list[str] | None=None) -> int:
    ap=argparse.ArgumentParser(description="Persistent handle-it orchestration")
    sub=ap.add_subparsers(dest="cmd",required=True)
    n=sub.add_parser("new"); n.add_argument("id"); n.add_argument("intent"); n.add_argument("--requires",action="append",default=[]); n.add_argument("--candidate",type=_candidate,action="append",default=[]); n.add_argument("--recipe"); n.add_argument("--reference",type=_reference,action="append",default=[]); n.add_argument("--max-attempts",type=int,default=3)
    sub.add_parser("list")
    s=sub.add_parser("show"); s.add_argument("id")
    r=sub.add_parser("refresh"); r.add_argument("id")
    a=sub.add_parser("attempt"); a.add_argument("id"); a.add_argument("outcome",choices=sorted(handler.ATTEMPT_OUTCOMES)); a.add_argument("--failure-code",default=""); a.add_argument("--note",default=""); a.add_argument("--evidence",default="")
    v=sub.add_parser("verify"); v.add_argument("id"); v.add_argument("evidence")
    e=sub.add_parser("resume"); e.add_argument("id"); e.add_argument("--evidence",default="")
    c=sub.add_parser("cancel"); c.add_argument("id"); c.add_argument("reason")
    args=ap.parse_args(argv)
    if args.cmd=="new":
        candidates=args.candidate or None
        _print(handler.create(args.id,intent=args.intent,required_capabilities=args.requires,candidates=candidates,recipe=args.recipe,references=args.reference,max_attempts=args.max_attempts)); return 0
    if args.cmd=="list": _print(handler.all_requests()); return 0
    if args.cmd=="show": _print(handler.load(args.id)); return 0
    if args.cmd=="refresh": _print(handler.refresh(args.id)); return 0
    if args.cmd=="attempt": _print(handler.record_attempt(args.id,outcome=args.outcome,failure_code=args.failure_code,note=args.note,evidence=args.evidence)); return 0
    if args.cmd=="verify": _print(handler.verify(args.id,evidence=args.evidence)); return 0
    if args.cmd=="resume": _print(handler.resume_external(args.id,evidence=args.evidence)); return 0
    _print(handler.cancel(args.id,reason=args.reason)); return 0


if __name__=="__main__": raise SystemExit(main())
