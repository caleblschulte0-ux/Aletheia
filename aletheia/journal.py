"""The journal — Aletheia's durable memory (ROADMAP A6, built).

An append-only JSONL of what happened and what was decided, fleet-wide:
suggestion rulings, health transitions, front-door actions, briefs, plan
changes, operator notes. Any session in any repo can ask "what did we
decide about X" here instead of doing archaeology across six CLAUDE.mds.

Append-only is the contract: entries are never edited or pruned to tidy
up, same standing as the posted logs. One line per entry:
  {"ts": ..., "kind": ..., "actor": ..., "subject": ..., "text": ..., "refs": [...]}
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

from aletheia.fleet import REPO_ROOT

JOURNAL_PATH = REPO_ROOT / "state" / "journal" / "journal.jsonl"
KINDS = {"decision", "event", "alert", "recovery", "action", "brief", "plan", "note"}


def append(kind: str, subject: str, text: str, actor: str = "aletheia",
           refs: list[str] | None = None, path: Path | None = None) -> dict:
    if kind not in KINDS:
        raise ValueError(f"kind {kind!r} not in {sorted(KINDS)}")
    entry = {
        "ts": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "kind": kind,
        "actor": actor,
        "subject": subject,
        "text": text,
    }
    if refs:
        entry["refs"] = refs
    path = path or JOURNAL_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry


def entries(path: Path | None = None) -> list[dict]:
    path = path or JOURNAL_PATH
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            out.append(json.loads(line))
    return out


def since(hours: float, path: Path | None = None) -> list[dict]:
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=hours)
    cut = cutoff.strftime("%Y-%m-%dT%H:%M:%SZ")
    return [e for e in entries(path) if e["ts"] >= cut]


def search(term: str, path: Path | None = None) -> list[dict]:
    t = term.lower()
    return [
        e for e in entries(path)
        if t in e["subject"].lower() or t in e["text"].lower()
    ]


def _print(rows: list[dict]) -> None:
    for e in rows:
        print(f"{e['ts']}  [{e['kind']:8}] {e['actor']:9} {e['subject']}: {e['text']}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Aletheia's durable memory.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_add = sub.add_parser("add")
    p_add.add_argument("kind", choices=sorted(KINDS))
    p_add.add_argument("subject")
    p_add.add_argument("text")
    p_add.add_argument("--actor", default="operator")
    p_list = sub.add_parser("list")
    p_list.add_argument("--kind", choices=sorted(KINDS))
    p_list.add_argument("--last", type=int, default=20)
    p_search = sub.add_parser("search")
    p_search.add_argument("term")
    args = ap.parse_args(argv)

    if args.cmd == "add":
        e = append(args.kind, args.subject, args.text, actor=args.actor)
        print(f"journaled {e['ts']} [{e['kind']}] {e['subject']}")
        return 0
    if args.cmd == "search":
        rows = search(args.term)
        _print(rows)
        print(f"{len(rows)} match(es)", file=sys.stderr)
        return 0
    rows = entries()
    if args.kind:
        rows = [e for e in rows if e["kind"] == args.kind]
    _print(rows[-args.last:])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
