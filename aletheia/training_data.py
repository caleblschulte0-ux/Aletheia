"""Private training/evaluation capture for Aletheia's future local model.

The store is deliberately local and gitignored via ``state/private``. It keeps
reasoning attempts, later feedback, and student-vs-teacher comparisons without
making data retention an availability dependency. Credential-shaped fields and
values are redacted before they touch disk.
"""
from __future__ import annotations

import json
import os
import re
import uuid
from pathlib import Path
from typing import Any

from aletheia import stateio

SCHEMA_VERSION = 2
ENV_CAPTURE = "ALETHEIA_TRAINING_CAPTURE"
MAX_NOTE = 4_000
_SECRET_KEY = re.compile(
    r"(?:pass(?:word|code)?|secret|api[_-]?key|access[_-]?token|refresh[_-]?token|"
    r"auth(?:orization)?|cookie|session[_-]?(?:id|key|token)|credential|private[_-]?key|"
    r"otp|mfa|2fa|recovery[_-]?code)", re.I,
)
_TOKEN_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b", re.I),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b", re.I),
    re.compile(r"\beyJ[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"),
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{8,}"),
)
_INLINE_SECRET = re.compile(
    r"(?i)\b(password|passcode|secret|api[ _-]?key|access[ _-]?token|token|otp|mfa|2fa)"
    r"\b\s*[:=]\s*([^\s,;]{3,})"
)


def capture_enabled() -> bool:
    return os.environ.get(ENV_CAPTURE, "1").strip().lower() not in {"0", "false", "no", "off"}


def data_root() -> Path:
    return stateio.private_dir("training")


def _redact_text(value: str) -> str:
    text = str(value)
    for pattern in _TOKEN_PATTERNS:
        text = pattern.sub("[REDACTED_SECRET]", text)
    text = _INLINE_SECRET.sub(lambda m: f"{m.group(1)}=[REDACTED_SECRET]", text)
    return text


def sanitize(value: Any, *, key: str = "") -> Any:
    """Return a JSON-safe copy with credential-bearing material removed."""
    if _SECRET_KEY.search(str(key)):
        return "[REDACTED_SECRET]"
    if isinstance(value, dict):
        return {str(k): sanitize(v, key=str(k)) for k, v in value.items()}
    if isinstance(value, list):
        return [sanitize(v) for v in value]
    if isinstance(value, tuple):
        return [sanitize(v) for v in value]
    if isinstance(value, str):
        return _redact_text(value)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return _redact_text(str(value))


def _write(kind: str, event: dict[str, Any]) -> str | None:
    if not capture_enabled():
        return None
    try:
        event_id = stateio.safe_id(str(event["id"]), name="training event id")
        target = data_root() / stateio.safe_id(kind, name="training kind") / f"{event_id}.json"
        stateio.write_json_atomic(target, sanitize(event))
        return event_id
    except (OSError, TypeError, ValueError):
        return None


def record_turn(*, provider: str, model: str, text: str, context: dict,
                result: dict | None, status: str, role: str | None = None,
                request_payload: dict | None = None, error_type: str | None = None,
                error: str | None = None, duration_ms: int | None = None) -> str | None:
    turn_id = uuid.uuid4().hex
    event = {
        "schema_version": SCHEMA_VERSION,
        "id": turn_id,
        "kind": "turn",
        "recorded_at": stateio.utcnow(),
        "provider": str(provider)[:200],
        "model": str(model)[:200],
        "role": role,
        "status": str(status)[:64],
        "input": {"text": text, "context": context},
        "request_payload": request_payload,
        "result": result,
        "error_type": error_type,
        "error": str(error or "")[:MAX_NOTE] or None,
        "duration_ms": duration_ms,
    }
    return _write("turns", event)


def record_teacher_pair(*, student_turn_id: str | None, teacher_turn_id: str | None = None,
                        teacher_provider: str, teacher_result: dict | None,
                        student_result: dict | None, route: str,
                        student_error: str | None = None) -> str | None:
    """Link a local student attempt to the stronger answer used by Aletheia."""
    pair_id = uuid.uuid4().hex
    event = {
        "schema_version": SCHEMA_VERSION,
        "id": pair_id,
        "kind": "teacher_pair",
        "recorded_at": stateio.utcnow(),
        "student_turn_id": student_turn_id,
        "teacher_turn_id": teacher_turn_id,
        "teacher_provider": str(teacher_provider)[:200],
        "route": str(route)[:80],
        "teacher_result": teacher_result,
        "student_result": student_result,
        "student_error": str(student_error or "")[:MAX_NOTE] or None,
        "label": "strong_provider_reference",
    }
    return _write("pairs", event)


def record_feedback(turn_id: str, *, verdict: str, corrected_result: dict | None = None,
                    note: str = "") -> str | None:
    turn_id = stateio.safe_id(turn_id, name="training turn id")
    verdict = str(verdict).strip().lower()
    if verdict not in {"good", "bad", "mixed", "corrected"}:
        raise ValueError("verdict must be good, bad, mixed, or corrected")
    feedback_id = uuid.uuid4().hex
    return _write("feedback", {
        "schema_version": SCHEMA_VERSION,
        "id": feedback_id,
        "kind": "feedback",
        "recorded_at": stateio.utcnow(),
        "turn_id": turn_id,
        "verdict": verdict,
        "corrected_result": corrected_result,
        "note": str(note)[:MAX_NOTE],
    })


def iter_events() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for kind in ("turns", "pairs", "feedback"):
        directory = data_root() / kind
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob("*.json")):
            try:
                value = stateio.read_json(path)
            except ValueError:
                continue
            rows.append(value)
    return sorted(rows, key=lambda row: (str(row.get("recorded_at", "")), str(row.get("id", ""))))


def stats() -> dict[str, Any]:
    rows = iter_events()
    counts = {"turns": 0, "pairs": 0, "feedback": 0}
    models: dict[str, int] = {}
    for row in rows:
        kind = row.get("kind")
        if kind == "turn":
            counts["turns"] += 1
            model = str(row.get("model") or "unknown")
            models[model] = models.get(model, 0) + 1
        elif kind == "teacher_pair":
            counts["pairs"] += 1
        elif kind == "feedback":
            counts["feedback"] += 1
    return {
        "capture_enabled": capture_enabled(),
        "data_root": str(data_root()),
        **counts,
        "by_model": dict(sorted(models.items())),
    }


def export_jsonl(path: str | Path) -> int:
    target = Path(path).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    rows = iter_events()
    with target.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    return len(rows)
