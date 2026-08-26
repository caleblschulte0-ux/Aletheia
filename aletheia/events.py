"""Durable event bus + watchers for Aletheia.

The bus is deliberately file-oriented and append-only:
- one JSON file per event avoids cross-writer append conflicts;
- watcher definitions are immutable;
- cancellations and trigger receipts are separate files.

That lets the cloud pulse and the Windows Core share the same store through
git without both rewriting a hot state file. A corrupt watcher is isolated:
the event still exists and other valid watchers still evaluate.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import uuid
from pathlib import Path

from aletheia.stateio import private_dir

# Private by default: event subjects/summaries and watcher notes carry
# personal facts ("tell me when Alice replies") and this repo is public.
# The bus is therefore per-machine runtime state, evaluated by the local
# Core; a future cloud/PC shared bus needs its own privacy contract first.
EVENTS_DIR = private_dir("events")
WATCHERS_DIR = private_dir("watchers")

_EVENT_KIND = re.compile(r"^[a-z][a-z0-9_.-]{0,95}$")
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_SENSITIVE_KEY_PARTS = (
    "password", "passwd", "secret", "token", "cookie", "authorization", "private_key",
)
_ALLOWED_MATCH = frozenset({"kind", "source", "subject_prefix", "attributes"})


def _utcnow() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _new_id(prefix: str) -> str:
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    return f"{prefix}-{stamp}-{uuid.uuid4().hex[:10]}"


def _write_new_json(path: Path, value: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if len(payload.encode("utf-8")) > 32 * 1024:
        raise ValueError("record exceeds 32 KiB")
    with path.open("x", encoding="utf-8", newline="\n") as fh:
        fh.write(payload)
    return path


def _require_text(name: str, value: object, *, max_len: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be non-empty text")
    value = value.strip()
    if len(value) > max_len:
        raise ValueError(f"{name} exceeds {max_len} characters")
    if any(ord(ch) < 32 and ch not in "\t\n" for ch in value):
        raise ValueError(f"{name} contains control characters")
    return value


def _validate_attributes(value: object) -> dict:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError("attributes must be an object")
    if len(value) > 32:
        raise ValueError("attributes may contain at most 32 keys")
    clean = {}
    for key, item in value.items():
        key = _require_text("attribute key", key, max_len=64)
        lowered = key.lower()
        if any(part in lowered for part in _SENSITIVE_KEY_PARTS):
            raise ValueError(f"sensitive attribute key refused: {key}")
        if isinstance(item, (dict, list)):
            encoded = json.dumps(item, ensure_ascii=False, sort_keys=True)
            if len(encoded) > 2048:
                raise ValueError(f"attribute {key} exceeds 2048 encoded characters")
        elif item is not None and not isinstance(item, (str, int, float, bool)):
            raise ValueError(f"attribute {key} is not JSON-scalar/list/object")
        clean[key] = item
    encoded = json.dumps(clean, ensure_ascii=False, sort_keys=True)
    if len(encoded.encode("utf-8")) > 8 * 1024:
        raise ValueError("attributes exceed 8 KiB")
    return clean


def validate_event(event: dict) -> dict:
    if not isinstance(event, dict):
        raise ValueError("event must be an object")
    event_id = _require_text("event id", event.get("id"), max_len=128)
    if not _ID.fullmatch(event_id):
        raise ValueError("invalid event id")
    kind = _require_text("kind", event.get("kind"), max_len=96)
    if not _EVENT_KIND.fullmatch(kind):
        raise ValueError("kind must be lowercase dotted/dashed identifier")
    source = _require_text("source", event.get("source"), max_len=96)
    subject = _require_text("subject", event.get("subject"), max_len=256)
    summary = _require_text("summary", event.get("summary"), max_len=1024)
    occurred_at = _require_text("occurred_at", event.get("occurred_at"), max_len=40)
    try:
        parsed = dt.datetime.fromisoformat(occurred_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"occurred_at is not an ISO-8601 timestamp: {occurred_at!r}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("occurred_at must be timezone-aware")
    attrs = _validate_attributes(event.get("attributes", {}))
    return {
        "version": 1,
        "id": event_id,
        "kind": kind,
        "source": source,
        "subject": subject,
        "summary": summary,
        "occurred_at": occurred_at,
        "attributes": attrs,
    }


def emit(
    kind: str,
    subject: str,
    summary: str,
    *,
    source: str,
    attributes: dict | None = None,
    event_id: str | None = None,
    occurred_at: str | None = None,
    events_dir: Path | None = None,
    watchers_dir: Path | None = None,
) -> dict:
    """Persist one event, then evaluate every durable watcher against it."""
    events_dir = Path(events_dir) if events_dir else EVENTS_DIR
    watchers_dir = Path(watchers_dir) if watchers_dir else WATCHERS_DIR
    event = validate_event(
        {
            "id": event_id or _new_id("evt"),
            "kind": kind,
            "source": source,
            "subject": subject,
            "summary": summary,
            "occurred_at": occurred_at or _utcnow(),
            "attributes": attributes or {},
        }
    )
    _write_new_json(Path(events_dir) / f"{event['id']}.json", event)
    triggers, errors = evaluate_watchers(event, watchers_dir=watchers_dir)
    return {"event": event, "triggers": triggers, "watcher_errors": errors}


def validate_match(match: dict) -> dict:
    if not isinstance(match, dict) or not match:
        raise ValueError("watcher match must be a non-empty object")
    unknown = set(match) - _ALLOWED_MATCH
    if unknown:
        raise ValueError(f"unknown watcher match fields: {', '.join(sorted(unknown))}")
    out: dict = {}
    if "kind" in match:
        kind = _require_text("match.kind", match["kind"], max_len=96)
        if not _EVENT_KIND.fullmatch(kind):
            raise ValueError("match.kind is invalid")
        out["kind"] = kind
    if "source" in match:
        out["source"] = _require_text("match.source", match["source"], max_len=96)
    if "subject_prefix" in match:
        out["subject_prefix"] = _require_text(
            "match.subject_prefix", match["subject_prefix"], max_len=256,
        )
    if "attributes" in match:
        attrs = _validate_attributes(match["attributes"])
        if not attrs:
            raise ValueError("match.attributes may not be empty")
        out["attributes"] = attrs
    return out


def validate_watcher(watcher: dict) -> dict:
    if not isinstance(watcher, dict):
        raise ValueError("watcher must be an object")
    watcher_id = _require_text("watcher id", watcher.get("id"), max_len=128)
    if not _ID.fullmatch(watcher_id):
        raise ValueError("invalid watcher id")
    created_at = _require_text("created_at", watcher.get("created_at"), max_len=40)
    created_by = _require_text("created_by", watcher.get("created_by"), max_len=128)
    note = _require_text("note", watcher.get("note"), max_len=512)
    once = watcher.get("once")
    if not isinstance(once, bool):
        raise ValueError("once must be boolean")
    return {
        "version": 1,
        "id": watcher_id,
        "created_at": created_at,
        "created_by": created_by,
        "note": note,
        "once": once,
        "match": validate_match(watcher.get("match")),
    }


def create_watcher(
    match: dict,
    *,
    note: str,
    created_by: str,
    once: bool = True,
    watcher_id: str | None = None,
    watchers_dir: Path | None = None,
) -> dict:
    watchers_dir = Path(watchers_dir) if watchers_dir else WATCHERS_DIR
    watcher = validate_watcher(
        {
            "id": watcher_id or _new_id("watch"),
            "created_at": _utcnow(),
            "created_by": created_by,
            "note": note,
            "once": once,
            "match": match,
        }
    )
    _write_new_json(Path(watchers_dir) / "definitions" / f"{watcher['id']}.json", watcher)
    return watcher


def cancel_watcher(
    watcher_id: str,
    *,
    cancelled_by: str,
    reason: str,
    watchers_dir: Path | None = None,
) -> dict:
    watchers_dir = Path(watchers_dir) if watchers_dir else WATCHERS_DIR
    watcher_id = _require_text("watcher id", watcher_id, max_len=128)
    if not _ID.fullmatch(watcher_id):
        raise ValueError("invalid watcher id")
    definition = Path(watchers_dir) / "definitions" / f"{watcher_id}.json"
    if not definition.is_file():
        raise FileNotFoundError(f"unknown watcher {watcher_id}")
    receipt = {
        "version": 1,
        "watcher_id": watcher_id,
        "cancelled_at": _utcnow(),
        "cancelled_by": _require_text("cancelled_by", cancelled_by, max_len=128),
        "reason": _require_text("reason", reason, max_len=512),
    }
    path = Path(watchers_dir) / "cancelled" / f"{watcher_id}.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    _write_new_json(path, receipt)
    return receipt


def _matches(event: dict, match: dict) -> bool:
    if "kind" in match and event["kind"] != match["kind"]:
        return False
    if "source" in match and event["source"] != match["source"]:
        return False
    if "subject_prefix" in match and not event["subject"].startswith(match["subject_prefix"]):
        return False
    for key, expected in match.get("attributes", {}).items():
        if event.get("attributes", {}).get(key) != expected:
            return False
    return True


def _trigger_files(watcher_id: str, watchers_dir: Path) -> list[Path]:
    directory = Path(watchers_dir) / "triggers" / watcher_id
    if not directory.is_dir():
        return []
    return sorted(p for p in directory.iterdir() if p.is_file() and p.suffix == ".json")


def watcher_state(watcher: dict, *, watchers_dir: Path | None = None) -> str:
    watchers_dir = Path(watchers_dir) if watchers_dir else WATCHERS_DIR
    wid = watcher["id"]
    if (Path(watchers_dir) / "cancelled" / f"{wid}.json").is_file():
        return "CANCELLED"
    if watcher["once"] and _trigger_files(wid, Path(watchers_dir)):
        return "TRIGGERED"
    return "ACTIVE"


def evaluate_watchers(
    event: dict,
    *,
    watchers_dir: Path | None = None,
) -> tuple[list[dict], list[dict]]:
    """Evaluate one event. Bad definitions are isolated, never fatal to the bus."""
    watchers_dir = Path(watchers_dir) if watchers_dir else WATCHERS_DIR
    event = validate_event(event)
    root = Path(watchers_dir)
    definitions = root / "definitions"
    if not definitions.is_dir():
        return [], []
    triggers: list[dict] = []
    errors: list[dict] = []
    for path in sorted(definitions.glob("*.json")):
        try:
            watcher = validate_watcher(json.loads(path.read_text(encoding="utf-8")))
            if watcher_state(watcher, watchers_dir=root) != "ACTIVE":
                continue
            if not _matches(event, watcher["match"]):
                continue
            receipt = {
                "version": 1,
                "watcher_id": watcher["id"],
                "event_id": event["id"],
                "triggered_at": _utcnow(),
                "kind": event["kind"],
                "source": event["source"],
                "subject": event["subject"],
                "summary": event["summary"],
            }
            trigger_path = root / "triggers" / watcher["id"] / f"{event['id']}.json"
            if trigger_path.exists():
                receipt = json.loads(trigger_path.read_text(encoding="utf-8"))
            else:
                _write_new_json(trigger_path, receipt)
            triggers.append(receipt)
        except Exception as exc:
            errors.append({"definition": path.name, "error": f"{type(exc).__name__}: {exc}"})
    return triggers, errors


def list_events(*, events_dir: Path | None = None, limit: int = 50) -> list[dict]:
    events_dir = Path(events_dir) if events_dir else EVENTS_DIR
    if limit < 1 or limit > 500:
        raise ValueError("limit must be between 1 and 500")
    root = Path(events_dir)
    if not root.is_dir():
        return []
    out = []
    for path in sorted(root.glob("*.json"), reverse=True)[:limit]:
        try:
            out.append(validate_event(json.loads(path.read_text(encoding="utf-8"))))
        except Exception:
            continue
    return out


def list_watchers(*, watchers_dir: Path | None = None) -> list[dict]:
    watchers_dir = Path(watchers_dir) if watchers_dir else WATCHERS_DIR
    root = Path(watchers_dir)
    definitions = root / "definitions"
    if not definitions.is_dir():
        return []
    out = []
    for path in sorted(definitions.glob("*.json")):
        try:
            watcher = validate_watcher(json.loads(path.read_text(encoding="utf-8")))
        except Exception as exc:
            out.append({"id": path.stem, "state": "INVALID", "error": f"{type(exc).__name__}: {exc}"})
            continue
        watcher = dict(watcher)
        watcher["state"] = watcher_state(watcher, watchers_dir=root)
        watcher["trigger_count"] = len(_trigger_files(watcher["id"], root))
        out.append(watcher)
    return out


def _parse_attr(values: list[str]) -> dict:
    attrs = {}
    for value in values:
        if "=" not in value:
            raise ValueError(f"attribute must be key=value: {value}")
        key, raw = value.split("=", 1)
        try:  # `n=5` matches an int attribute, `to=red` stays a string
            attrs[key] = json.loads(raw)
        except json.JSONDecodeError:
            attrs[key] = raw
    return attrs


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Aletheia durable event bus and watchers.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    emit_p = sub.add_parser("emit")
    emit_p.add_argument("--kind", required=True)
    emit_p.add_argument("--source", required=True)
    emit_p.add_argument("--subject", required=True)
    emit_p.add_argument("--summary", required=True)
    emit_p.add_argument("--attr", action="append", default=[])

    watch_p = sub.add_parser("watch")
    watch_p.add_argument("--kind")
    watch_p.add_argument("--source")
    watch_p.add_argument("--subject-prefix")
    watch_p.add_argument("--attr", action="append", default=[])
    watch_p.add_argument("--note", required=True)
    watch_p.add_argument("--created-by", default="operator")
    watch_p.add_argument("--persistent", action="store_true")

    cancel_p = sub.add_parser("cancel")
    cancel_p.add_argument("watcher_id")
    cancel_p.add_argument("--by", default="operator")
    cancel_p.add_argument("--reason", required=True)

    events_p = sub.add_parser("events")
    events_p.add_argument("--limit", type=int, default=20)

    sub.add_parser("watchers")

    args = ap.parse_args(argv)
    if args.cmd == "emit":
        result = emit(
            args.kind,
            args.subject,
            args.summary,
            source=args.source,
            attributes=_parse_attr(args.attr),
        )
        print(json.dumps(result, indent=2))
        return 0
    if args.cmd == "watch":
        match = {}
        if args.kind:
            match["kind"] = args.kind
        if args.source:
            match["source"] = args.source
        if args.subject_prefix:
            match["subject_prefix"] = args.subject_prefix
        attrs = _parse_attr(args.attr)
        if attrs:
            match["attributes"] = attrs
        watcher = create_watcher(
            match,
            note=args.note,
            created_by=args.created_by,
            once=not args.persistent,
        )
        print(json.dumps(watcher, indent=2))
        return 0
    if args.cmd == "cancel":
        print(json.dumps(
            cancel_watcher(args.watcher_id, cancelled_by=args.by, reason=args.reason),
            indent=2,
        ))
        return 0
    if args.cmd == "events":
        print(json.dumps(list_events(limit=args.limit), indent=2))
        return 0
    if args.cmd == "watchers":
        print(json.dumps(list_watchers(), indent=2))
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
