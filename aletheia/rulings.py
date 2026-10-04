"""His standing rulings, as data: `config/rulings.json`.

The switches that widen what she does on her own (interview scheduling,
one day others) live in private state on his PC and are flipped at his
keyboard - which is right, and which is also why, on 2026-10-02, nine days
after he said *"I want it to be to the point where she'll just auto
schedule an interview for me"*, the switch was still off: nobody had been
at the keyboard. His words that day: *"she's not watching my inbox,
scheduling me meetings ... Fix it."*

So a ruling is a REVIEWED REGISTRY EDIT carrying his words (CLAUDE.md:
grants live in registries and widen only by a reviewed registry edit), and
it is the DEFAULT for a switch he has never touched himself. The private
switch file, once he has set it at the keyboard, is newer and wins - a
ruling never overrides his own hand. A ruling file that is missing or
malformed grants nothing (fails closed), and a ruling can never reach a
high-risk or operator_always capability: `authority.allows` refuses those
whatever any file says.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from aletheia.fleet import REPO_ROOT

#: The registry, bound from the environment so the suite can point at a
#: file that does not exist: a ruling makes the beat CREATE a standing
#: grant, and one created in a runtime test's tick stayed live for every
#: later test in the process (a calendar write auto-approved itself in
#: tests/test_calendar_provider.py). The sandbox reads the real one.
DEFAULT_PATH = Path(os.environ.get("ALETHEIA_RULINGS") or (REPO_ROOT / "config" / "rulings.json"))
REPO_RULINGS = REPO_ROOT / "config" / "rulings.json"
#: The switches a ruling may set. Add one only with his words in the file.
SWITCHES = ("interviews", "discovery")


def load(path: Path | None = None) -> list[dict]:
    """Every well-formed ruling, or [] - a broken registry grants nothing."""
    try:
        raw = json.loads((path or DEFAULT_PATH).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    rows = raw.get("rulings") if isinstance(raw, dict) else None
    out = []
    for row in rows or []:
        if not isinstance(row, dict) or not row.get("id") or row.get("switch") not in SWITCHES:
            continue
        quotes = [q for q in (row.get("quotes") or []) if isinstance(q, dict) and str(q.get("said") or "").strip()]
        if not quotes:
            continue  # a ruling without his words is not a ruling
        out.append({"id": str(row["id"]), "switch": str(row["switch"]), "on": bool(row.get("on")),
                    "window": row.get("window") if isinstance(row.get("window"), dict) else None,
                    "since": str(row.get("since") or ""), "quotes": quotes,
                    "means": str(row.get("means") or "")})
    return out


def for_switch(name: str, path: Path | None = None) -> dict | None:
    """The newest ruling about one switch, or None."""
    rows = [r for r in load(path) if r["switch"] == name]
    return max(rows, key=lambda r: r["since"]) if rows else None


def quote(ruling: dict) -> str:
    """His words on the ruling, the newest first, for a journal line or a grant."""
    said = sorted(ruling.get("quotes") or [], key=lambda q: str(q.get("on") or ""), reverse=True)
    return " | ".join(f"{q.get('on', '')}: {q.get('said', '')}" for q in said)[:600]
