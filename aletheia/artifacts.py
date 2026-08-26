"""Private artifact metadata, integrity checks and extraction evidence.

This is the common substrate for future PDF/DOCX/spreadsheet/image intelligence.
It does not parse documents itself. Local files are fingerprinted, bounded, and
recorded in private runtime state; extracted facts stay tied to provenance and a
source artifact instead of becoming unattributed memory.
"""
from __future__ import annotations

import hashlib
import mimetypes
from pathlib import Path

from aletheia.stateio import create_json_exclusive, private_dir, read_json, safe_id, utcnow, write_json_atomic

ARTIFACTS_DIR = private_dir("artifacts")
MAX_FILE_BYTES = 256 * 1024 * 1024
MAX_TEXT_EXTRACTION = 64 * 1024


def _root(artifact_id: str) -> Path:
    return ARTIFACTS_DIR / safe_id(artifact_id, name="artifact id")


def _meta_path(artifact_id: str) -> Path:
    return _root(artifact_id) / "artifact.json"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def register_file(artifact_id: str, path: str | Path, *, source: str = "local") -> dict:
    safe_id(artifact_id, name="artifact id")
    file_path = Path(path).expanduser().resolve()
    if not file_path.is_file():
        raise FileNotFoundError(file_path)
    size = file_path.stat().st_size
    if size > MAX_FILE_BYTES:
        raise ValueError(f"artifact exceeds {MAX_FILE_BYTES} bytes")
    mime, _ = mimetypes.guess_type(file_path.name)
    value = {"version": 1, "id": artifact_id, "kind": "local_file", "source": source,
             "name": file_path.name, "local_path": str(file_path), "size_bytes": size,
             "sha256": _sha256(file_path), "mime_type": mime or "application/octet-stream",
             "registered_at": utcnow()}
    create_json_exclusive(_meta_path(artifact_id), value)
    return value


def register_reference(artifact_id: str, *, source: str, reference: str,
                       name: str = "", mime_type: str = "application/octet-stream") -> dict:
    """Register a connector/cloud reference without pretending local bytes exist."""
    safe_id(artifact_id, name="artifact id")
    if not isinstance(source, str) or not source.strip() or not isinstance(reference, str) or not reference.strip():
        raise ValueError("source and reference are required")
    value = {"version": 1, "id": artifact_id, "kind": "reference", "source": source,
             "reference": reference, "name": name or artifact_id, "mime_type": mime_type,
             "registered_at": utcnow()}
    create_json_exclusive(_meta_path(artifact_id), value)
    return value


def load(artifact_id: str) -> dict:
    return read_json(_meta_path(artifact_id))


def verify_local(artifact_id: str) -> dict:
    value = load(artifact_id)
    if value.get("kind") != "local_file":
        return {"verified": False, "reason": "artifact has no local bytes"}
    path = Path(value["local_path"])
    if not path.is_file():
        return {"verified": False, "reason": "local file missing"}
    size = path.stat().st_size
    if size != value["size_bytes"]:
        return {"verified": False, "reason": "size changed", "observed_size": size}
    digest = _sha256(path)
    return {"verified": digest == value["sha256"], "observed_sha256": digest,
            "reason": "hash matches" if digest == value["sha256"] else "content changed"}


def add_extraction(artifact_id: str, extraction_id: str, *, kind: str,
                   content: str | dict | list, extractor: str,
                   locator: str = "") -> dict:
    load(artifact_id)  # source must exist
    safe_id(extraction_id, name="extraction id")
    if kind not in {"text", "fact", "table", "metadata", "summary"}:
        raise ValueError("invalid extraction kind")
    if not isinstance(extractor, str) or not extractor.strip():
        raise ValueError("extractor provenance is required")
    if kind == "text":
        if not isinstance(content, str) or len(content.encode("utf-8")) > MAX_TEXT_EXTRACTION:
            raise ValueError("text extraction must be bounded UTF-8 text")
    elif not isinstance(content, (str, dict, list)):
        raise ValueError("extraction content must be text, object, or list")
    value = {"version": 1, "id": extraction_id, "artifact_id": artifact_id,
             "kind": kind, "content": content, "extractor": extractor, "recorded_at": utcnow()}
    if locator:
        value["locator"] = locator
    create_json_exclusive(_root(artifact_id) / "extractions" / f"{extraction_id}.json", value)
    return value


def extractions(artifact_id: str) -> list[dict]:
    load(artifact_id)
    root = _root(artifact_id) / "extractions"
    if not root.is_dir():
        return []
    out = []
    for path in sorted(root.glob("*.json")):
        try:
            out.append(read_json(path))
        except ValueError:
            continue
    return out
