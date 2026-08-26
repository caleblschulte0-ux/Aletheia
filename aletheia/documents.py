"""Private document metadata/text ingestion and evidence lookup.

This handles text already extracted by a trusted adapter. It does not pretend to
parse arbitrary PDFs/Office files without the corresponding parser. Content is
hashed, bounded, private, and searchable with literal case-insensitive terms.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from aletheia.stateio import private_dir, read_json, safe_id, utcnow, write_json_atomic

DOCS_DIR = private_dir("documents")
MAX_TEXT_CHARS = 1_000_000


def _path(document_id: str) -> Path:
    return DOCS_DIR / f"{safe_id(document_id, name='document id')}.json"


def ingest_text(document_id: str, *, title: str, text: str, source: str,
                mime_type: str = "text/plain", metadata: dict | None = None) -> dict:
    if _path(document_id).exists():
        raise FileExistsError(document_id)
    if not isinstance(title, str) or not title.strip() or not isinstance(source, str) or not source.strip():
        raise ValueError("title and source are required")
    if not isinstance(text, str) or len(text) > MAX_TEXT_CHARS:
        raise ValueError(f"text must be a string <= {MAX_TEXT_CHARS} characters")
    if metadata is not None and not isinstance(metadata, dict):
        raise ValueError("metadata must be an object")
    now = utcnow()
    value = {"version": 1, "id": safe_id(document_id, name="document id"), "title": title.strip(),
             "mime_type": mime_type, "source": source, "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
             "text": text, "metadata": metadata or {}, "created_at": now, "updated_at": now}
    write_json_atomic(_path(document_id), value)
    return value


def load(document_id: str) -> dict:
    value = read_json(_path(document_id))
    if value.get("sha256") != hashlib.sha256(str(value.get("text", "")).encode("utf-8")).hexdigest():
        raise ValueError("document content hash mismatch")
    return value


def search(term: str, *, limit: int = 20) -> list[dict]:
    q = term.casefold().strip()
    if not q:
        raise ValueError("search term is empty")
    if limit < 1 or limit > 100:
        raise ValueError("limit must be 1..100")
    if not DOCS_DIR.is_dir():
        return []
    hits = []
    for path in DOCS_DIR.glob("*.json"):
        try:
            doc = load(path.stem)
        except ValueError:
            continue
        text = doc["text"]
        pos = text.casefold().find(q)
        if pos < 0 and q not in doc["title"].casefold():
            continue
        start = max(0, pos - 160) if pos >= 0 else 0
        end = min(len(text), (pos + len(term) + 240) if pos >= 0 else 400)
        hits.append({"id": doc["id"], "title": doc["title"], "source": doc["source"],
                     "sha256": doc["sha256"], "snippet": text[start:end]})
    return hits[:limit]
