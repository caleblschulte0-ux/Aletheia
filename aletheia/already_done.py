"""Is this already true? Asked in code, before anybody's model is asked anything.

The live acceptance pass, 2026-09-18: a work session spent a local pass and a
frontier turn on a charter step (`plan:barkly#3`) that was COMPLETE at the base
commit. Only a doc note about it was stale. That cost a four minute local draft
on a laptop with one Ollama queue, a frontier turn, and a branch nobody needed -
to discover something reading one file would have said in a millisecond.

Three rules, and they are the whole module:

- **DETERMINISTIC ONLY.** Nothing here asks a model whether the work is done. A
  model deciding "already done" is precisely how work silently stops happening,
  and it is unfalsifiable afterwards: every skip must name a fact somebody can
  go and look at. `check` makes no network call and loads no model.
- **UNKNOWN MEANS DO THE WORK.** Every check returns nothing unless it is sure,
  the same safety argument as `quick.py`: it may only ever remove a wasted pass,
  never an answer. A check that is not certain says nothing and the work runs.
- **A SKIP IS RECORDED LIKE ANYTHING ELSE.** The verdict carries the check that
  produced it and the evidence it read, so "why did nothing happen" and "what
  did you do without asking me" both have an honest answer.

Two checks today:

`state` - the item's own store already says done. The charter step is `done`,
the task is COMPLETED, the work item's durable state is DONE. Free.

`file`  - the file the step asks for already exists AND already says it. Only
for a step that names an output file (a document step). It needs at least two
distinctive content words from the step, EVERY one of them present in the file,
and at least one adjacent PAIR of them present adjacent in the file: scattered
words are a coincidence, a phrase is the thing. Requires a checkout the caller
already has; it never makes one.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from aletheia import work_states as ws

#: A verdict a caller may act on. `done` is only ever True when `by` names the
#: check that proved it and `evidence` says what it read.
CHECKS = ("state", "file")

#: Words that say what KIND of work this is rather than what it is about. They
#: are the same words in every step, so they prove nothing about this one.
CHROME = frozenset("""
a an the and or of to for in on at by with from into about that this these those
add adds added adding write writes wrote writing draft drafts drafted drafting
create creates created creating make makes made making update updates updated
updating document documents documented documenting describe describes described
describing note notes noted explain explains explained cover covers covered
section sessions sections page pages doc docs documentation file files
readme readme.md md markdown text new short brief simple small it its is are be
we our us his her their he she they i you your my me please should must need
needs needed so then also as it's step steps task tasks project projects
""".split())

_WORD = re.compile(r"[A-Za-z][A-Za-z0-9_.-]*")
#: A step with fewer distinctive words than this proves nothing by matching.
MIN_WORDS = 2
#: How much of a file is read before a match is decided (documents, not dumps).
MAX_FILE_CHARS = 200_000


def _words(text: str) -> list[str]:
    out = []
    for raw in _WORD.findall(str(text or "")):
        word = raw.casefold().strip(".-_")
        if not word or word in CHROME or len(word) < 3:
            continue
        out.append(word)
    return out


def content_words(text: str) -> list[str]:
    """The distinctive words of a step, in order, deduplicated. Pure."""
    return list(dict.fromkeys(_words(text)))


def _says_it(body: str, wanted: list[str]) -> dict:
    """Does this text already say what those words ask for? Conservative.

    Every word present, AND one adjacent pair of them adjacent here too."""
    found = _words(body[:MAX_FILE_CHARS])
    have = set(found)
    missing = [w for w in wanted if w not in have]
    if missing:
        return {"says_it": False, "missing": missing[:6]}
    pairs = {(wanted[i], wanted[i + 1]) for i in range(len(wanted) - 1)}
    for i in range(len(found) - 1):
        if (found[i], found[i + 1]) in pairs:
            return {"says_it": True, "phrase": f"{found[i]} {found[i + 1]}"}
    # Every word is somewhere in the file and no two of them are together: that
    # is a coincidence, not the thing the step asked for.
    return {"says_it": False, "missing": [], "why": "the words are scattered, never together"}


def _no(checked: list[str], why: str = "") -> dict:
    return {"done": False, "by": "", "why": why, "evidence": {}, "checked": checked}


def _charter_step(payload: dict) -> dict | None:
    slug, n = str(payload.get("slug") or ""), payload.get("n")
    if not slug or n in (None, ""):
        return None
    try:
        from aletheia import plans
        plan = plans.load(slug)
    except Exception:  # noqa: BLE001 - an unreadable plan proves nothing
        return None
    for step in plan.get("steps") or []:
        if str(step.get("n")) == str(n):
            return step
    return None


def by_state(it: dict) -> dict:
    """The item's own store already says done. Free, and never wrong when True."""
    payload = it.get("payload") or {}
    step = _charter_step(payload)
    if step is not None and step.get("state") == "done":
        return {"done": True, "by": "state",
                "why": f"the charter step {payload.get('slug')}#{payload.get('n')} is already marked done",
                "evidence": {"store": "plans", "slug": payload.get("slug"), "n": payload.get("n"),
                             "state": "done"},
                "checked": ["state"]}
    native = str(it.get("native_state") or "").upper()
    if it.get("source") == "tasks" and native in {"COMPLETED", "CANCELLED"}:
        return {"done": True, "by": "state",
                "why": f"the task is already {native.lower()}",
                "evidence": {"store": "tasks", "id": it.get("id"), "state": native},
                "checked": ["state"]}
    if it.get("state") == ws.DONE:
        return {"done": True, "by": "state", "why": "the work item is already DONE",
                "evidence": {"store": it.get("source"), "id": it.get("id"), "state": ws.DONE},
                "checked": ["state"]}
    return _no(["state"])


def by_file(text: str, *, root: str | Path, out_path: str) -> dict:
    """The file this step asks for already exists and already says it.

    `root` is a checkout the caller already has; nothing here makes one."""
    checked = ["file"]
    wanted = content_words(text)
    if len(wanted) < MIN_WORDS:
        return _no(checked, "the step names too little to prove anything by matching")
    if not out_path:
        return _no(checked, "the step names no file to look in")
    path = Path(root) / out_path
    try:
        if not path.is_file():
            return _no(checked, f"{out_path} does not exist yet")
        body = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return _no(checked, f"{out_path} could not be read ({type(exc).__name__})")
    verdict = _says_it(body, wanted)
    if not verdict["says_it"]:
        missing = verdict.get("missing") or []
        return _no(checked, (f"{out_path} does not mention " + ", ".join(missing[:4])) if missing
                   else f"{out_path} {verdict.get('why', 'does not say it')}")
    return {"done": True, "by": "file",
            "why": f"{out_path} already says it ({verdict['phrase']!r} is in it, and every word of the step)",
            "evidence": {"file": out_path, "phrase": verdict["phrase"], "words": wanted[:8],
                         "bytes": len(body)},
            "checked": checked}


def check(it: dict, *, root: str | Path | None = None, out_path: str = "",
          text: str = "") -> dict:
    """Is this work already true? {"done", "by", "why", "evidence", "checked"}.

    Never raises, never asks a model, never touches the network. False with a
    `why` is the answer for everything it is not certain about."""
    try:
        verdict = by_state(it)
        if verdict["done"]:
            return verdict
        checked = list(verdict["checked"])
        if root is not None and out_path:
            said = by_file(text or str(it.get("title") or ""), root=root, out_path=out_path)
            said["checked"] = checked + list(said["checked"])
            return said
        return _no(checked, verdict.get("why") or "")
    except Exception as exc:  # noqa: BLE001 - a check may never be why work stops
        return _no([], f"the already-done check could not run ({type(exc).__name__})")


def skipped(it: dict, verdict: dict, *, route: str = "") -> dict[str, Any]:
    """The outcome for work that did not need doing, said honestly.

    It is DONE - the thing he wanted is true - and the report says it was
    already true rather than claiming she did it."""
    return {
        "state": ws.DONE, "kind": "already", "route": route,
        "reason": f"already done: {verdict.get('why') or 'it was already true'}"[:300],
        "next": "nothing: it was already true",
        "did": f"checked whether {str(it.get('title') or it.get('id'))[:80]} still needed doing; "
               f"{verdict.get('why') or 'it was already true'}. Nothing was drafted and no model was asked."[:300],
        "evidence": {"already_done": {k: verdict.get(k) for k in ("by", "why", "evidence", "checked")}},
    }
