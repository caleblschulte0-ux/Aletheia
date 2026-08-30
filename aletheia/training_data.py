"""Local-only training/evaluation data capture for Aletheia reasoning turns.

The long-term model should learn from Aletheia's real use, not only synthetic
examples. This module preserves the exact request payload sent to a reasoning
provider, the provider/model identity, its validated result (or failure), and
optional later operator feedback/corrections.

Data is deliberately OUTSIDE the Git repository by default:

    Windows: %LOCALAPPDATA%\\Aletheia\\training
    other:   ~/.aletheia/training

No capture failure is allowed to break reasoning. The canonical store is one
JSON file per event so concurrent processes cannot corrupt one shared JSONL
file. ``export_jsonl`` produces a conventional portable dataset when needed.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import tempfile
import uuid
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
ENV_DATA_DIR = "ALETHEIA_TRAINING_DATA_DIR"
ENV_CAPTURE = "ALETHEIA_TRAINING_CAPTURE"


def _utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def capture_enabled() -> bool:
    raw = os.environ.get(ENV_CAPTURE, "1").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def data_root() -> Path:
    override = os.environ.get(ENV_DATA_DIR)
    if override:
        return Path(override).expanduser()
    local = os.environ.get("LOCALAPPDATA")
    if local:
        return Path(local) / "Aletheia" / "training"
    return Path.home() / ".aletheia" / "training"


def _safe_json(value: Any) -> Any:
    """Round-trip through JSON so the durable event is portable/stable."""
    return json.loads(json.dumps(value, ensure_ascii=False, default=str))


def _write_event(kind: str, event: dict[str, Any]) -> Path | None:
    if not capture_enabled():
        return None
    try:
        directory = data_root() / kind
        directory.mkdir(parents=True, exist_ok=True)
        event_id = str(event["id"])
        target = directory / f"{event_id}.json"
        payload = json.dumps(event, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
        fd, tmp_name = tempfile.mkstemp(prefix=f".{event_id}-", suffix=".tmp", dir=directory)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(payload)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp_name, target)
        finally:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)
        return target
    except (OSError, TypeError, ValueError):
        # Dataset retention matters, but it must never become an availability or
        # authority dependency for Aletheia's reasoning path.
        return None


def record_turn(*, provider: str, model: str, text: str, context: dict[str, Any],
                request_payload: dict[str, Any] | None = None,
                result: dict[str, Any] | None = None, status: str,
                error_type: str | None = None, error: str | None = None,
                duration_ms: int | None = None) -> str | None:
    """Persist one reasoning attempt and return its stable turn id.

    ``request_payload`` is the exact JSON body sent to the model runtime. Keeping
    it alongside the normalized input means future training can reproduce both
    the semantic example and the historical prompt/schema used to obtain it.
    """
    if not capture_enabled():
        return None
    turn_id = uuid.uuid4().hex
    event = {
        "schema_version": SCHEMA_VERSION,
        "id": turn_id,
        "kind": "reasoning_turn",
        "recorded_at": _utc_now(),
        "provider": provider,
        "model": model,
        "status": status,
        "input": {
            "text": text,
            "context": _safe_json(context),
        },
        "request_payload": _safe_json(request_payload) if request_payload is not None else None,
        "result": _safe_json(result) if result is not None else None,
        "error_type": error_type,
        "error": error,
        "duration_ms": duration_ms,
    }
    return turn_id if _write_event("turns", event) is not None else None


def record_feedback(turn_id: str, *, verdict: str, corrected_result: dict[str, Any] | None = None,
                    note: str = "") -> str | None:
    """Attach later quality signal/correction without rewriting the raw turn."""
    if not isinstance(turn_id, str) or not turn_id.strip():
        raise ValueError("turn_id is required")
    verdict = verdict.strip().lower()
    if verdict not in {"good", "bad", "mixed", "corrected"}:
        raise ValueError("verdict must be good, bad, mixed, or corrected")
    feedback_id = uuid.uuid4().hex
    event = {
        "schema_version": SCHEMA_VERSION,
        "id": feedback_id,
        "kind": "reasoning_feedback",
        "recorded_at": _utc_now(),
        "turn_id": turn_id,
        "verdict": verdict,
        "corrected_result": _safe_json(corrected_result) if corrected_result is not None else None,
        "note": str(note),
    }
    return feedback_id if _write_event("feedback", event) is not None else None


def iter_events() -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for kind in ("turns", "feedback"):
        directory = data_root() / kind
        if not directory.exists():
            continue
        for path in sorted(directory.glob("*.json")):
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(value, dict):
                events.append(value)
    return sorted(events, key=lambda x: (str(x.get("recorded_at", "")), str(x.get("id", ""))))


def stats() -> dict[str, Any]:
    rows = iter_events()
    turns = [row for row in rows if row.get("kind") == "reasoning_turn"]
    feedback = [row for row in rows if row.get("kind") == "reasoning_feedback"]
    by_model: dict[str, int] = {}
    for row in turns:
        model = str(row.get("model", "unknown"))
        by_model[model] = by_model.get(model, 0) + 1
    return {
        "capture_enabled": capture_enabled(),
        "data_root": str(data_root()),
        "turns": len(turns),
        "feedback": len(feedback),
        "by_model": dict(sorted(by_model.items())),
    }


def export_jsonl(path: str | Path) -> int:
    """Export all retained events to one portable JSONL file; return row count."""
    target = Path(path).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    rows = iter_events()
    with target.open("w", encoding="utf-8", newline="\n") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    return len(rows)
