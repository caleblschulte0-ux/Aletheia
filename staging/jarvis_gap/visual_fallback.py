"""Proposal-only visual desktop fallback for Playbook §15 / adapter rung 7.

Today's production computer controller is intentionally accessibility-first and
rejects coordinate clicking. That should stay true. This prototype defines a
SEPARATE fallback seam for the rare case where UI Automation cannot identify a
control.

It cannot click. It can only produce a hash-bound candidate target inside a
specific screenshot. A future production integration would still need policy,
an exact operator approval where required, execution, a fresh screenshot, and
verification before claiming success.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .mobile_sensors import ImageObservation

MIN_CONFIDENCE = 0.80
MAX_LABEL_CHARS = 200


class TargetBackend(Protocol):
    def locate(self, screenshot: ImageObservation, instruction: str,
               *, width: int, height: int) -> dict:
        """Return x/y/label/confidence for one candidate target."""


@dataclass(frozen=True)
class VisualTarget:
    screenshot_sha256: str
    x: int
    y: int
    width: int
    height: int
    label: str
    confidence: float

    @property
    def ready_for_review(self) -> bool:
        return self.confidence >= MIN_CONFIDENCE

    def as_dict(self) -> dict:
        return {
            "screenshot_sha256": self.screenshot_sha256,
            "x": self.x,
            "y": self.y,
            "width": self.width,
            "height": self.height,
            "label": self.label,
            "confidence": self.confidence,
            "ready_for_review": self.ready_for_review,
            "execution_authority": False,
        }


def validate_target(value: dict, screenshot: ImageObservation, *, width: int, height: int) -> VisualTarget:
    if screenshot.source != "windows.screenshot":
        raise ValueError("visual desktop target requires a Windows screenshot")
    if not isinstance(value, dict):
        raise ValueError("target output must be an object")
    allowed = {"x", "y", "label", "confidence"}
    unknown = set(value) - allowed
    if unknown:
        raise ValueError(f"target output has unknown fields {sorted(unknown)}")
    if isinstance(width, bool) or isinstance(height, bool) or not isinstance(width, int) or not isinstance(height, int):
        raise ValueError("screenshot dimensions must be integers")
    if not 1 <= width <= 20_000 or not 1 <= height <= 20_000:
        raise ValueError("screenshot dimensions are outside supported bounds")
    x, y = value.get("x"), value.get("y")
    if isinstance(x, bool) or isinstance(y, bool) or not isinstance(x, int) or not isinstance(y, int):
        raise ValueError("x/y must be integer pixels")
    if not 0 <= x < width or not 0 <= y < height:
        raise ValueError("target is outside the screenshot")
    label = value.get("label")
    if not isinstance(label, str) or not label.strip():
        raise ValueError("target label is required")
    confidence = value.get("confidence")
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not 0 <= float(confidence) <= 1:
        raise ValueError("confidence must be 0..1")
    return VisualTarget(
        screenshot_sha256=screenshot.digest,
        x=x,
        y=y,
        width=width,
        height=height,
        label=" ".join(label.split())[:MAX_LABEL_CHARS],
        confidence=float(confidence),
    )


class VisualTargetPlanner:
    """Locates a candidate target; never executes it."""

    def __init__(self, backend: TargetBackend) -> None:
        self.backend = backend

    def propose(self, screenshot: ImageObservation, instruction: str,
                *, width: int, height: int) -> VisualTarget:
        if not isinstance(instruction, str) or not instruction.strip():
            raise ValueError("instruction is required")
        candidate = self.backend.locate(
            screenshot, " ".join(instruction.split())[:1000], width=width, height=height
        )
        return validate_target(candidate, screenshot, width=width, height=height)
