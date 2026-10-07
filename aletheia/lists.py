"""His own named lists: packing, gift ideas, movies to watch, things for the house.

"Make a list called packing" and "add socks to my packing list" went to the
planner (2026-10-07). The shopping list is its own store because buying is
its own path; every other list he keeps is just a name and its lines, in
his words, in private state.

Taking a line off is a soft delete - it is marked done and kept - so
"actually put it back" has something to put back.
"""
from __future__ import annotations

import re

from aletheia.stateio import private_dir, read_json, utcnow, write_json_atomic

#: Lists that are somebody else's store, never a named list of his.
NOT_NAMED = ("shopping", "grocery", "groceries", "task", "tasks", "to do", "todo", "to-do", "reminder", "reminders")


def slug_of(name: str) -> str:
    """'Gift Ideas' -> 'gift-ideas'. Empty when nothing is left."""
    return re.sub(r"[^a-z0-9]+", "-", " ".join(str(name or "").casefold().split())).strip("-")[:40]


def _path(name: str):
    return private_dir("lists") / f"{slug_of(name)}.json"


def _load(name: str, *, deleted: bool = True) -> dict | None:
    path = _path(name)
    if not path.is_file():
        return None
    try:
        held = read_json(path)
    except ValueError:
        return None
    return held if deleted or not held.get("deleted") else None


def drop(name: str) -> int | None:
    """Delete a list: marked deleted, never removed, so nothing he wrote is
    lost. Returns how many lines it had open, or None when there is none."""
    held = _load(name, deleted=False)
    if held is None:
        return None
    held["deleted"] = True
    held["updated_at"] = utcnow()
    write_json_atomic(_path(name), held)
    return sum(1 for i in held["items"] if not i.get("done"))


def is_named_list(name: str) -> bool:
    words = " ".join(str(name or "").casefold().split())
    return bool(slug_of(words)) and words not in NOT_NAMED


def exists(name: str) -> bool:
    return _load(name, deleted=False) is not None


def create(name: str) -> tuple[dict, bool]:
    """(the list, whether it was new). A deleted list made again comes back
    empty, its old lines kept in the file as done."""
    if not is_named_list(name):
        raise ValueError(f"{name!r} is not a list of its own")
    held = _load(name)
    if held is not None and held.get("deleted"):
        held.pop("deleted", None)
        for item in held["items"]:
            item["done"] = True
        held["updated_at"] = utcnow()
        write_json_atomic(_path(name), held)
        return held, True
    if held is not None:
        return held, False
    value = {"version": 1, "name": " ".join(str(name).split()), "items": [], "created_at": utcnow(),
             "updated_at": utcnow()}
    write_json_atomic(_path(name), value)
    return value, True


def add(name: str, items: list[str]) -> list[str]:
    """Add lines; returns the lines added (a line already open is not doubled)."""
    held, _new = create(name)
    open_now = {i["text"].casefold() for i in held["items"] if not i.get("done")}
    added = []
    for item in items:
        text = " ".join(str(item or "").split())
        if text and text.casefold() not in open_now:
            held["items"].append({"text": text, "added_at": utcnow()})
            open_now.add(text.casefold())
            added.append(text)
    held["updated_at"] = utcnow()
    write_json_atomic(_path(name), held)
    return added


def items(name: str) -> list[str] | None:
    """The open lines, or None when there is no such list."""
    held = _load(name, deleted=False)
    if held is None:
        return None
    return [i["text"] for i in held["items"] if not i.get("done")]


def done_items(name: str) -> list[tuple[str, str]]:
    """(line, when it came off), newest first - what he has watched off a
    watch list or read off a reading list. Empty for no such list."""
    held = _load(name, deleted=False)
    if held is None:
        return []
    rows = [(i["text"], str(i.get("done_at") or "")) for i in held["items"] if i.get("done") and i.get("done_at")]
    return sorted(rows, key=lambda r: r[1], reverse=True)


def kind_of(name: str) -> str | None:
    """"watch" or "read" when a list's name says which, else None."""
    low = " ".join(str(name or "").casefold().split())
    if re.search(r"\b(?:watch|movies?|films?|shows?|tv|series)\b", low):
        return "watch"
    if re.search(r"\b(?:read|reading|books?)\b", low):
        return "read"
    return None


def take_off(name: str, which: str) -> tuple[list[str], str]:
    """(lines taken off, why-not). "everything" clears the list."""
    held = _load(name, deleted=False)
    if held is None:
        return [], f"You don't have a {name} list."
    needle = " ".join(str(which or "").casefold().split())
    live = [i for i in held["items"] if not i.get("done")]
    if needle in ("everything", "all", "it all", "all of it", "everything on it"):
        hits = live
    else:
        # "Remove the hat" when he added "a hat" (2026-10-07: "Nothing
        # matches 'the hat'"). The article is how he said it, not the thing.
        def bare(words):
            return re.sub(r"^(?:a|an|the|some|my) ", "", " ".join(str(words).casefold().split()))
        hits = [i for i in live if i["text"].casefold() == needle] or \
               [i for i in live if bare(i["text"]) == bare(needle)] or \
               [i for i in live if needle and needle in i["text"].casefold()] or \
               [i for i in live if bare(needle) and bare(needle) in i["text"].casefold()]
    if not hits:
        return [], f"There's nothing called {which} on your {held['name']} list."
    if len(hits) > 1 and needle not in ("everything", "all", "it all", "all of it", "everything on it"):
        from aletheia import speech
        return [], f"Which one - {speech.or_list([h['text'] for h in hits[:4]])}?"
    for hit in hits:
        hit["done"] = True
        hit["done_at"] = utcnow()
    held["updated_at"] = utcnow()
    write_json_atomic(_path(name), held)
    return [h["text"] for h in hits], ""


def all_lists() -> list[dict]:
    root = private_dir("lists")
    out = []
    for path in sorted(root.glob("*.json")) if root.is_dir() else []:
        try:
            held = read_json(path)
        except ValueError:
            continue
        if held.get("deleted"):
            continue
        out.append({"name": held.get("name") or path.stem,
                    "open": sum(1 for i in held.get("items") or [] if not i.get("done"))})
    return out
