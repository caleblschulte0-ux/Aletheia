"""Provider-neutral FAST / DEEP / VISION routing contract.

This does not call a model and does not plan or execute actions. It only names
the reasoning role a bounded request requires, so image/depth requirements can
fail closed instead of silently degrading to the wrong worker.
"""
from __future__ import annotations

from dataclasses import dataclass

MAX_TEXT_CHARS = 20_000
ROLES = {"fast", "deep", "vision"}


@dataclass(frozen=True)
class ReasoningRequest:
    text: str
    has_image: bool = False
    depth: str = "routine"
    safety_critical: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.text, str) or not self.text.strip():
            raise ValueError("text is required")
        if len(self.text) > MAX_TEXT_CHARS:
            raise ValueError("text too long")
        if type(self.has_image) is not bool or type(self.safety_critical) is not bool:
            raise ValueError("boolean flags required")
        if self.depth not in {"routine", "deep"}:
            raise ValueError("depth invalid")


@dataclass(frozen=True)
class RouteDecision:
    primary_role: str
    required_modalities: tuple[str, ...]
    returned_answer_may_be_authoritative: bool
    reason: str

    def as_dict(self) -> dict:
        return {
            "primary_role": self.primary_role,
            "required_modalities": list(self.required_modalities),
            "returned_answer_may_be_authoritative": self.returned_answer_may_be_authoritative,
            "reason": self.reason,
            "execution_authority": False,
        }


def route(request: ReasoningRequest) -> RouteDecision:
    if not isinstance(request, ReasoningRequest):
        raise TypeError("ReasoningRequest required")
    authoritative = not request.safety_critical
    if request.has_image:
        return RouteDecision(
            "vision", ("text", "image"), authoritative,
            "image input requires VISION",
        )
    if request.depth == "deep":
        return RouteDecision(
            "deep", ("text",), authoritative,
            "deep text reasoning requested",
        )
    return RouteDecision(
        "fast", ("text",), authoritative,
        "routine text reasoning",
    )


def require_available(decision: RouteDecision, available_roles: set[str]) -> None:
    if not isinstance(decision, RouteDecision):
        raise TypeError("RouteDecision required")
    unknown = set(available_roles) - ROLES
    if unknown:
        raise ValueError(f"unknown roles {sorted(unknown)}")
    if decision.primary_role not in available_roles:
        raise RuntimeError(
            f"required role {decision.primary_role!r} unavailable; refusing silent downgrade"
        )
