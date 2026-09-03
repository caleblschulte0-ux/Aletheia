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
import os
import sys
from pathlib import Path

from aletheia.fleet import REPO_ROOT

# Tests and other deliberately isolated tooling may redirect the journal before
# importing Aletheia. Normal runtime behavior is unchanged: without the env
# override this is the durable fleet journal in the repository.
JOURNAL_PATH = Path(
    os.environ.get("ALETHEIA_JOURNAL_PATH")
    or (REPO_ROOT / "state" / "journal" / "journal.jsonl")
)
KINDS = {"decision", "event", "alert", "recovery", "action", "brief", "plan", "note", "task"}
# The in-repo journal directory. A read from HERE also merges the private
# PC writer; a read from anywhere else is a caller that meant somewhere else.
REPO_JOURNAL_DIR = REPO_ROOT / "state" / "journal"

# One journal, several writer FILES. The cloud (Actions, CLI) appends to
# journal.jsonl; the PC Core appends to journal-pc.jsonl. Two machines
# appending to the same file meant every `git pull` on the PC conflicted
# with every cloud commit — the 2026-08-26 bootstrap abort. Per-writer
# files make journal conflicts structurally impossible; entries() reads
# them all as one stream.


def use_pc_journal() -> Path:
    """Route this PROCESS's appends to the PC writer file — which lives in
    PRIVATE state, not in the repository (2026-09-03).

    The operator: *"is there a reason that that can't live on my personal
    machine?"* There was not. The repository is public because GitHub Pages
    needs it to be, and Pages serves the wall, which reads exactly one file:
    `state/pulse/latest.json`. His journal was never required to be there —
    it was there because that is where the fleet observatory's journal
    started, and the personal system grew into the same file.

    What that meant in practice: every action she took on his behalf, in his
    own words, was committed and pushed to a public repository. `browse_read`
    excerpts of authenticated pages, recalled memories, subscription and
    finance totals, inbox metadata — anything a command receipt summarised
    reached the journal and then GitHub.

    So the PC's journal is now `state/private/journal/journal-pc.jsonl`
    (gitignored, and the Core no longer commits `state/journal` at all).
    The in-repo journal remains for the CLOUD writers — Actions runs, pulse,
    briefs — which are fleet telemetry rather than his life, and `entries()`
    still reads every writer file as one stream, so nothing that reads the
    journal notices the difference.
    """
    global JOURNAL_PATH
    from aletheia.stateio import private_dir
    target = private_dir("journal")
    target.mkdir(parents=True, exist_ok=True)
    JOURNAL_PATH = target / "journal-pc.jsonl"
    return JOURNAL_PATH


def _writer_files(path: Path) -> list[Path]:
    files = {path} if path.exists() else set()
    # The PC writer lives in private state now; a reader pointed at the repo
    # journal must still see it, or `entries()` would silently lose every
    # local action the moment it moved.
    #
    # ONLY for the default repo location. A caller that redirected
    # JOURNAL_PATH — every test does, and so does isolated tooling — means
    # exactly where it pointed, and dragging his real private journal into
    # that read is the cross-contamination `-t .` exists to prevent. It
    # bit two suites the moment this was written unconditionally.
    try:
        if path.parent == REPO_JOURNAL_DIR:
            from aletheia.stateio import private_dir
            private = private_dir("journal")
            if private.is_dir():
                files.update(f for f in private.glob("journal*.jsonl") if f.is_file())
    except Exception:
        pass
    if path.parent.is_dir():
        files |= set(path.parent.glob("journal*.jsonl"))
    return sorted(files)


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
    """Every entry from every writer file, one stream ordered by time."""
    path = path or JOURNAL_PATH
    out = []
    for f in _writer_files(path):
        # utf-8-sig: tolerate a BOM from a Windows-side writer
        for line in f.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if line:
                out.append(json.loads(line))
    out.sort(key=lambda e: e.get("ts", ""))  # stable: same-file order kept
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
