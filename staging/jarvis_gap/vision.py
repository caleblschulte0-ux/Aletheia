"""Read-only vision worker contract for future camera/screenshot reasoning.

A VISION worker may answer questions about pixels. It may not execute tools or
smuggle an action plan into its result. This is the missing worker seam between
Playbook §7/§15/§86 and today's text-only local reasoning path.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .mobile_sensors import ImageObservation

MAX_QUESTION_CHARS = 1200
MAX_ANSWER_CHARS = 1200
MAX_BASIS_CHARS = 600
FORBIDDEN_OUTPUT_FIELDS = {
    "action", "actions", "click", "coordinates", "x", "y", "steps", "command",
    "tool", "tool_call", "execute", "url",
}


class VisionBackend(Protocol):
    def analyze(self, image: ImageObservation, question: str, *, context: dict) -> dict:
        """Return a candidate JSON-like answer. No authority is implied."""


@dataclass(frozen=True)
class VisionAnswer:
    answer: str
    confidence: float
    basis: str
    image_sha256: str

    def as_dict(self) -> dict:
        return {
            "answer": self.answer,
            "confidence": self.confidence,
            "basis": self.basis,
            "image_sha256": self.image_sha256,
        }


def _text(value, *, name: str, limit: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return " ".join(value.split())[:limit]


def validate_backend_output(value: dict, image: ImageObservation) -> VisionAnswer:
    if not isinstance(value, dict):
        raise ValueError("vision output must be an object")
    forbidden = set(value) & FORBIDDEN_OUTPUT_FIELDS
    if forbidden:
        raise PermissionError(
            f"vision is read-only; action-shaped fields are forbidden: {sorted(forbidden)}"
        )
    unknown = set(value) - {"answer", "confidence", "basis"}
    if unknown:
        raise ValueError(f"vision output has unknown fields {sorted(unknown)}")
    confidence = value.get("confidence")
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not 0 <= float(confidence) <= 1:
        raise ValueError("confidence must be 0..1")
    return VisionAnswer(
        answer=_text(value.get("answer"), name="answer", limit=MAX_ANSWER_CHARS),
        confidence=float(confidence),
        basis=_text(value.get("basis"), name="basis", limit=MAX_BASIS_CHARS),
        image_sha256=image.digest,
    )


class VisionReasoner:
    """Bounded read-only facade around an injected future VISION provider."""

    def __init__(self, backend: VisionBackend) -> None:
        self.backend = backend

    def ask(self, image: ImageObservation, question: str, *, context: dict | None = None) -> VisionAnswer:
        if not isinstance(image, ImageObservation):
            raise TypeError("image must be ImageObservation")
        question = _text(question, name="question", limit=MAX_QUESTION_CHARS)
        ctx = context or {}
        if not isinstance(ctx, dict):
            raise ValueError("context must be an object")
        candidate = self.backend.analyze(image, question, context=ctx)
        return validate_backend_output(candidate, image)
