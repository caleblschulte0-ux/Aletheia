"""Private durable notification center.

A notification is an operator-facing fact that needs surfacing; it is not an
execution mechanism. Dedupe keys prevent alert storms and acknowledgements are
explicit. External push delivery is a later provider concern.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path

from aletheia.stateio import private_dir, read_json, safe_id, utcnow, write_json_atomic

NOTICES_DIR = private_dir("notifications")
PRIORITIES = {"INFO", "NORMAL", "IMPORTANT", "URGENT"}
STATES = {"UNREAD", "READ", "ACKNOWLEDGED"}


def _path(notice_id: str) -> Path:
    return NOTICES_DIR / f"{safe_id(notice_id, name='notification id')}.json"


def _dedupe_id(key: str) -> str:
    return "notice-" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:20]


def validate(value: dict) -> None:
    required = {"version", "id", "title", "body", "priority", "state", "created_at", "updated_at"}
    missing = required - value.keys()
    if missing:
        raise ValueError(f"notification missing {sorted(missing)}")
    if value["version"] != 1 or value["priority"] not in PRIORITIES or value["state"] not in STATES:
        raise ValueError("unsupported notification version/priority/state")
    safe_id(value["id"], name="notification id")
    for key in ("title", "body"):
        if not isinstance(value[key], str) or not value[key].strip():
            raise ValueError(f"notification {key} is required")


def publish(title: str, body: str, *, priority: str = "NORMAL", source: str = "aletheia",
            dedupe_key: str | None = None, related: dict | None = None) -> dict:
    notice_id = _dedupe_id(dedupe_key) if dedupe_key else _dedupe_id(f"{utcnow()}:{title}:{body}")
    path = _path(notice_id)
    if path.exists():
        return load(notice_id)
    now = utcnow()
    value = {"version": 1, "id": notice_id, "title": title.strip(), "body": body.strip(),
             "priority": priority, "state": "UNREAD", "source": source,
             "created_at": now, "updated_at": now}
    if dedupe_key:
        value["dedupe_key"] = dedupe_key
    if related is not None:
        if not isinstance(related, dict):
            raise ValueError("related must be an object")
        value["related"] = related
    validate(value)
    write_json_atomic(path, value)
    return value


def load(notice_id: str) -> dict:
    value = read_json(_path(notice_id))
    validate(value)
    return value


# Parsed notices, keyed by a stat of every file. A stat is ~20x cheaper
# than an open-and-parse, and this store is read on every presence
# snapshot — which is three of the sentences he says most.
_NOTICES_CACHE: tuple | None = None


def _notices_signature() -> tuple:
    """What would have to change for the parse to be wrong.

    Per FILE, not the directory: Windows does not touch a directory's
    mtime when a file inside it is modified in place, and acknowledging a
    notice does exactly that. A directory-mtime cache would go on
    reporting a notice he had already dealt with.

    `os.scandir` rather than `glob` + `stat`: the DirEntry carries the
    stat the directory walk already read, where the pathlib pair costs
    three syscalls a file. Across 105 notices that was 55ms — most of
    what this cache exists to remove.
    """
    signed = []
    try:
        with os.scandir(NOTICES_DIR) as entries:
            for entry in entries:
                if not entry.name.endswith(".json"):
                    continue
                try:
                    info = entry.stat()
                    signed.append((entry.name, info.st_mtime_ns, info.st_size))
                except OSError:
                    signed.append((entry.name, None, None))
    except OSError:
        return ()
    return tuple(sorted(signed))


def _every_notice() -> list[dict]:
    """Every notice on disk, parsed once per change."""
    global _NOTICES_CACHE
    signature = _notices_signature()
    if _NOTICES_CACHE and _NOTICES_CACHE[0] == signature:
        return _NOTICES_CACHE[1]
    parsed = []
    for name, _mtime, _size in signature:
        try:
            parsed.append(load(name[:-len(".json")]))
        except ValueError:
            continue
    _NOTICES_CACHE = (signature, parsed)
    return parsed


def all_notifications(*, state: str | None = None, limit: int = 100) -> list[dict]:
    if state is not None and state not in STATES:
        raise ValueError("invalid notification state")
    if limit < 1 or limit > 500:
        raise ValueError("limit must be 1..500")
    if not NOTICES_DIR.is_dir():
        return []
    out = []
    for value in _every_notice():
        if state is None or value["state"] == state:
            # A COPY per row: callers read these into sentences, and one
            # that edited a dict would be editing the cache every later
            # reader sees.
            out.append(dict(value))
    out.sort(key=lambda n: (n["created_at"], n["id"]), reverse=True)
    return out[:limit]


def set_state(notice_id: str, state: str) -> dict:
    if state not in STATES:
        raise ValueError("invalid notification state")
    value = load(notice_id)
    value["state"] = state
    value["updated_at"] = utcnow()
    if state == "ACKNOWLEDGED":
        value["acknowledged_at"] = utcnow()
    write_json_atomic(_path(notice_id), value)
    return value


def unread_count() -> int:
    return len(all_notifications(state="UNREAD", limit=500))
