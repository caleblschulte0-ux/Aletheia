"""Safe primitives for file-backed durable runtime state.

Sensitive runtime data must not accidentally become repository history. Newer
Aletheia subsystems therefore default to ``state/private/`` (gitignored) while
allowing the operator to move that state elsewhere with
``ALETHEIA_PRIVATE_STATE``. One-record-per-file stores avoid shared append-hot
files across cloud and PC writers.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

from aletheia.fleet import REPO_ROOT

_ID_RE = re.compile(r"[a-z0-9][a-z0-9._-]{0,127}")
MAX_JSON_BYTES = 256 * 1024


def utcnow() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def private_root() -> Path:
    override = os.environ.get("ALETHEIA_PRIVATE_STATE", "").strip()
    return Path(override).expanduser() if override else REPO_ROOT / "state" / "private"


def private_dir(*parts: str) -> Path:
    root = private_root()
    for part in parts:
        root = root / safe_id(part, name="state path component")
    return root


def safe_id(value: str, *, name: str = "id") -> str:
    if not isinstance(value, str) or not _ID_RE.fullmatch(value):
        raise ValueError(f"{name} must match {_ID_RE.pattern!r}")
    return value


def read_json(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"unreadable JSON state {path}: {exc}") from exc
    if len(raw.encode("utf-8")) > MAX_JSON_BYTES:
        raise ValueError(f"state {path} exceeds {MAX_JSON_BYTES} bytes")
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"unreadable JSON state {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"state {path} must contain a JSON object")
    return value


def _encoded(value: dict[str, Any]) -> str:
    data = json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    if len(data.encode("utf-8")) > MAX_JSON_BYTES:
        raise ValueError(f"JSON state exceeds {MAX_JSON_BYTES} bytes")
    return data


def write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = _encoded(value)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    finally:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass


def create_json_exclusive(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(_encoded(value))
        handle.flush()
        os.fsync(handle.fileno())
