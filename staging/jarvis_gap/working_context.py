"""Bounded working-context fusion for phrases like "this" and "that".

Staging only. It does not scrape titles or guess projects. Every fact has an
explicit source, freshness and confidence. Sensitive values are omitted from
ordinary diagnostics and only enter a reasoning view when explicitly requested.
"""
from __future__ import annotations

import datetime as dt
import hashlib
from dataclasses import dataclass
from pathlib import Path

ALLOWED_KEYS = {
    "active_app", "active_window", "browser_url", "browser_title",
    "selected_file", "project_id", "clipboard",
}
SENSITIVE_KEYS = {"browser_url", "selected_file", "clipboard"}
DEFAULT_MAX_AGE_S = 120.0


def _utc(value: dt.datetime) -> dt.datetime:
    if not isinstance(value, dt.datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("observed_at must be timezone-aware")
    return value.astimezone(dt.timezone.utc)


@dataclass(frozen=True)
class ContextFact:
    key: str
    value: str
    source: str
    observed_at: dt.datetime
    confidence: float = 1.0

    def __post_init__(self) -> None:
        if self.key not in ALLOWED_KEYS:
            raise ValueError("unsupported context key")
        if not isinstance(self.value, str) or not self.value.strip():
            raise ValueError("context value required")
        if not isinstance(self.source, str) or not self.source.strip():
            raise ValueError("context source required")
        if (isinstance(self.confidence, bool) or not isinstance(self.confidence, (int, float))
                or not 0 <= float(self.confidence) <= 1):
            raise ValueError("confidence must be 0..1")
        _utc(self.observed_at)

    @property
    def digest(self) -> str:
        return hashlib.sha256(self.value.encode("utf-8")).hexdigest()

    def diagnostic(self) -> dict:
        out = {
            "key": self.key,
            "source": self.source,
            "observed_at": _utc(self.observed_at).isoformat(),
            "confidence": float(self.confidence),
        }
        if self.key in SENSITIVE_KEYS:
            out.update({"value_redacted": True, "sha256": self.digest})
        else:
            out["value"] = self.value
        return out


@dataclass(frozen=True)
class ProjectBinding:
    project_id: str
    root: str

    def __post_init__(self) -> None:
        if not isinstance(self.project_id, str) or not self.project_id.strip():
            raise ValueError("project_id required")
        if not isinstance(self.root, str) or not self.root.strip():
            raise ValueError("root required")


def project_for_file(path: str | Path, bindings: list[ProjectBinding]) -> str | None:
    candidate = Path(path).expanduser().resolve()
    matches = []
    for binding in bindings:
        if not isinstance(binding, ProjectBinding):
            raise TypeError("ProjectBinding required")
        root = Path(binding.root).expanduser().resolve()
        if candidate == root or root in candidate.parents:
            matches.append((len(root.parts), binding.project_id))
    if not matches:
        return None
    matches.sort(reverse=True)
    best_length = matches[0][0]
    best = {project_id for length, project_id in matches if length == best_length}
    if len(best) != 1:
        raise LookupError("selected file maps ambiguously to multiple projects")
    return next(iter(best))


class WorkingContext:
    def __init__(self, *, now: dt.datetime | None = None,
                 max_age_s: float = DEFAULT_MAX_AGE_S) -> None:
        if (isinstance(max_age_s, bool) or not isinstance(max_age_s, (int, float))
                or not 1 <= float(max_age_s) <= 3600):
            raise ValueError("max_age_s out of bounds")
        self.now = _utc(now or dt.datetime.now(dt.timezone.utc))
        self.max_age_s = float(max_age_s)
        self._facts: dict[str, ContextFact] = {}

    def add(self, fact: ContextFact) -> None:
        if not isinstance(fact, ContextFact):
            raise TypeError("ContextFact required")
        age = (self.now - _utc(fact.observed_at)).total_seconds()
        if age < -10:
            raise ValueError("context fact is implausibly future-dated")
        if age > self.max_age_s:
            raise ValueError("context fact is stale")
        existing = self._facts.get(fact.key)
        if existing and existing.value != fact.value:
            same_time = abs((_utc(existing.observed_at) - _utc(fact.observed_at)).total_seconds()) <= 1
            if same_time and abs(existing.confidence - fact.confidence) < 0.05:
                raise LookupError(f"ambiguous current {fact.key}")
            if (_utc(existing.observed_at), existing.confidence) >= (_utc(fact.observed_at), fact.confidence):
                return
        self._facts[fact.key] = fact

    def derive_project(self, bindings: list[ProjectBinding]) -> str | None:
        selected = self._facts.get("selected_file")
        if not selected:
            return None
        project = project_for_file(selected.value, bindings)
        if project is None:
            return None
        self.add(ContextFact(
            "project_id", project, "derived:selected_file",
            selected.observed_at, selected.confidence,
        ))
        return project

    def diagnostics(self) -> dict:
        return {key: fact.diagnostic() for key, fact in sorted(self._facts.items())}

    def reasoning_view(self, *, include_clipboard: bool = False,
                       include_selected_file: bool = True,
                       include_browser_url: bool = True) -> dict:
        out = {}
        for key, fact in self._facts.items():
            if key == "clipboard" and not include_clipboard:
                continue
            if key == "selected_file" and not include_selected_file:
                continue
            if key == "browser_url" and not include_browser_url:
                continue
            out[key] = {
                "value": fact.value,
                "source": fact.source,
                "confidence": float(fact.confidence),
            }
        return out
