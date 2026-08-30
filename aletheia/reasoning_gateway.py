"""Review-only Aletheia-facing integration layer for replaceable reasoning providers.

This module is deliberately shaped so canonical Aletheia can adopt it later
with a tiny caller change. It hides Ollama, model-role routing, failover, and
training capture behind one stable interface.

Canonical-compatible path:
    reasoning_gateway.interpret(text, context) -> existing brain output dict

Metadata path for UI/observability/feedback:
    reasoning_gateway.interpret_with_meta(...) -> GatewayResult

This staging module does not execute tools, mutate Aletheia state, or widen any
approval/authority boundary.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from aletheia import brain, local_model_pool, training_data

GATEWAY_VERSION = 1
MODES = {"auto", "fast", "deep", "fallback"}


@dataclass(frozen=True)
class GatewayResult:
    requested_mode: str
    role: str
    reason: str
    model: str | None
    think: bool | None
    turn_id: str | None
    output: dict

    def as_dict(self) -> dict[str, Any]:
        return {
            "gateway_version": GATEWAY_VERSION,
            "requested_mode": self.requested_mode,
            "route": {"role": self.role, "reason": self.reason},
            "provider": {
                "kind": "ollama" if self.model is not None else "deterministic",
                "model": self.model,
                "think": self.think,
            },
            "training": {"turn_id": self.turn_id},
            "output": self.output,
        }


def _context(value: dict[str, Any] | None) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError("context must be an object")
    return value


def interpret_with_meta(
    text: str,
    context: dict[str, Any] | None = None,
    *,
    mode: str = "auto",
) -> GatewayResult:
    """Interpret one bounded operator turn through the configured reasoning layer."""
    if mode not in MODES:
        raise ValueError(f"mode must be one of {sorted(MODES)}")
    ctx = _context(context)

    if mode == "fallback":
        output = brain.FALLBACK.run(text, ctx)
        return GatewayResult(
            requested_mode=mode,
            role="fallback",
            reason="explicit deterministic fallback",
            model=None,
            think=None,
            turn_id=None,
            output=output,
        )

    if mode == "fast":
        role_run = local_model_pool.run_fast_traced(text, ctx)
        return GatewayResult(
            requested_mode=mode,
            role="fast",
            reason="explicit fast role",
            model=role_run.model,
            think=role_run.think,
            turn_id=role_run.turn_id,
            output=role_run.output,
        )

    if mode == "deep":
        role_run = local_model_pool.run_deep_traced(text, ctx)
        return GatewayResult(
            requested_mode=mode,
            role="deep",
            reason="explicit deep role",
            model=role_run.model,
            think=role_run.think,
            turn_id=role_run.turn_id,
            output=role_run.output,
        )

    pool_run = local_model_pool.run_auto_traced(text, ctx)
    role_run = pool_run.role_run
    return GatewayResult(
        requested_mode=mode,
        role=pool_run.route.role,
        reason=pool_run.route.reason,
        model=role_run.model if role_run else None,
        think=role_run.think if role_run else None,
        turn_id=role_run.turn_id if role_run else None,
        output=pool_run.output,
    )


def interpret(
    text: str,
    context: dict[str, Any] | None = None,
    *,
    mode: str = "auto",
) -> dict:
    """Canonical-compatible API: return only Aletheia's existing brain output shape."""
    return interpret_with_meta(text, context, mode=mode).output


def status() -> dict[str, Any]:
    """Read-only integration health for canonical/UI callers."""
    return {
        "gateway_version": GATEWAY_VERSION,
        "modes": sorted(MODES),
        "pool": local_model_pool.status(),
    }


def feedback(
    turn_id: str,
    *,
    verdict: str,
    note: str = "",
    corrected_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Attach operator quality signal to a retained local reasoning turn."""
    feedback_id = training_data.record_feedback(
        turn_id,
        verdict=verdict,
        corrected_result=corrected_result,
        note=note,
    )
    return {
        "turn_id": turn_id,
        "feedback_id": feedback_id,
        "verdict": verdict,
    }


def training_status() -> dict[str, Any]:
    return training_data.stats()


def export_training(path: str | Path) -> dict[str, Any]:
    target = Path(path).expanduser()
    count = training_data.export_jsonl(target)
    return {"exported": count, "path": str(target)}
