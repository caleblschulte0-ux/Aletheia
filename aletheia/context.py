"""Bounded recent-reference context for phrases like 'it', 'him', and 'that'.

This is intentionally not an LLM. It stores explicit referents with type and
recency, and resolves only when a unique eligible referent exists. Ambiguity is
returned as an error instead of silently choosing the wrong person/project.
Recent conversational referents are private runtime data and are gitignored.
"""
from __future__ import annotations

from aletheia.stateio import create_json_exclusive, private_dir, read_json, safe_id, utcnow

REFS_DIR = private_dir("context") / "refs"


def remember(ref_id: str, *, kind: str, value: str, label: str = "") -> dict:
    safe_id(ref_id, name="reference id")
    if kind not in {"person", "project", "task", "message", "file", "place", "thing"}:
        raise ValueError("invalid reference kind")
    if not isinstance(value, str) or not value.strip():
        raise ValueError("reference value is required")
    if not isinstance(label, str):
        raise ValueError("reference label must be a string")
    record = {"version": 1, "id": ref_id, "kind": kind, "value": value,
              "label": label, "at": utcnow()}
    create_json_exclusive(REFS_DIR / f"{ref_id}.json", record)
    return record


def recent(*, kind: str | None = None, limit: int = 20) -> list[dict]:
    if limit < 1 or limit > 200:
        raise ValueError("limit must be between 1 and 200")
    if not REFS_DIR.is_dir():
        return []
    values = []
    for path in REFS_DIR.glob("*.json"):
        try:
            value = read_json(path)
        except ValueError:
            continue
        if value.get("kind") not in {"person", "project", "task", "message", "file", "place", "thing"}:
            continue
        values.append(value)
    values.sort(key=lambda x: (x.get("at", ""), x.get("id", "")), reverse=True)
    if kind:
        values = [v for v in values if v.get("kind") == kind]
    return values[:limit]


def resolve(*, kind: str | None = None, label: str | None = None) -> dict:
    candidates = recent(kind=kind)
    if label:
        q = " ".join(label.casefold().split())
        candidates = [c for c in candidates
                      if " ".join(c.get("label", "").casefold().split()) == q]
    if not candidates:
        raise KeyError("no matching recent referent")
    by_value = {c["value"]: c for c in candidates}
    if len(by_value) != 1:
        raise LookupError("recent context is ambiguous; name the referent explicitly")
    return next(iter(by_value.values()))
