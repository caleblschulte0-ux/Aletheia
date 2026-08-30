"""Branch-only two-tier local reasoning pool for Aletheia.

This is a reviewable integration seam, not canonical runtime wiring. It gives
Aletheia-shaped callers access to two replaceable local roles:

- fast: everyday model, thinking off
- deep: heavier model, thinking on

Both still produce the existing ``aletheia.brain`` proposal contract. Neither
role can execute tools or bypass Aletheia policy/approval layers.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any

from aletheia import brain, local_brain, model_pool_config, training_data

DEEP_HINTS = (
    "deep analysis", "think hard", "architecture", "root cause", "debug",
    "review the code", "code review", "tradeoff", "trade-off", "compare",
    "reason through", "investigate", "complex plan", "large plan",
)


@dataclass(frozen=True)
class RouteDecision:
    role: str
    reason: str


def _context_size(context: dict[str, Any]) -> int:
    try:
        return len(json.dumps(context, ensure_ascii=False, default=str))
    except (TypeError, ValueError):
        return 0


def choose_role(text: str, context: dict[str, Any] | None = None) -> RouteDecision:
    """Deterministically choose a local role without asking another model."""
    lowered = text.lower()
    if any(hint in lowered for hint in DEEP_HINTS):
        return RouteDecision("deep", "explicit deep-reasoning cue")
    if len(text) >= 1200:
        return RouteDecision("deep", "long operator input")
    if _context_size(context or {}) >= 8000:
        return RouteDecision("deep", "large supplied context")
    return RouteDecision("fast", "default low-latency route")


def _config_for(role: str) -> tuple[local_brain.OllamaConfig, bool]:
    profile = model_pool_config.resolve_profile(role)
    base = local_brain.OllamaConfig.from_env()
    cfg = local_brain.OllamaConfig(
        base_url=base.base_url,
        model=profile["model"],
        timeout_seconds=base.timeout_seconds,
    ).validated()
    return cfg, bool(profile["think"])


def _run_role(role: str, text: str, context: dict[str, Any] | None = None) -> dict:
    """Run one configured role and retain exact request/result for training."""
    local_brain._validate_input(text)
    ctx = context or {}
    if not isinstance(ctx, dict):
        raise ValueError("context must be an object")
    cfg, think = _config_for(role)
    payload = local_brain._build_payload(text, ctx, cfg)
    payload["think"] = think
    started = time.perf_counter()
    proposal: dict | None = None
    try:
        response = local_brain._request_json(cfg, "/api/chat", payload)
        proposal = local_brain._proposal_from_response(response)
        result = brain.validate_output(proposal)
    except Exception as exc:
        training_data.record_turn(
            provider=f"ollama:{role}", model=cfg.model, text=text, context=ctx,
            request_payload=payload, result=proposal, status="error",
            error_type=type(exc).__name__, error=str(exc)[:4000],
            duration_ms=round((time.perf_counter() - started) * 1000),
        )
        raise
    training_data.record_turn(
        provider=f"ollama:{role}", model=cfg.model, text=text, context=ctx,
        request_payload=payload, result=result, status="validated",
        duration_ms=round((time.perf_counter() - started) * 1000),
    )
    return result


def run_fast(text: str, context: dict[str, Any] | None = None) -> dict:
    return _run_role("fast", text, context)


def run_deep(text: str, context: dict[str, Any] | None = None) -> dict:
    return _run_role("deep", text, context)


def run_auto(text: str, context: dict[str, Any] | None = None) -> tuple[RouteDecision, dict]:
    """Route locally, degrade to the other tier once, then fail closed.

    The fallback order is deterministic and does not broaden authority:
    selected local role -> other local role -> canonical deterministic clarify.
    """
    decision = choose_role(text, context)
    first = run_deep if decision.role == "deep" else run_fast
    second = run_fast if decision.role == "deep" else run_deep
    try:
        return decision, first(text, context)
    except (local_brain.LocalBrainError, brain.BrainOutputError, ValueError, TypeError):
        try:
            failover = RouteDecision(
                "fast" if decision.role == "deep" else "deep",
                f"{decision.role} failed; one local failover attempt",
            )
            return failover, second(text, context)
        except (local_brain.LocalBrainError, brain.BrainOutputError, ValueError, TypeError):
            return RouteDecision("fallback", "both local roles failed"), brain.FALLBACK.run(text, context or {})


def status() -> dict[str, Any]:
    """Report Ollama availability for both configured roles without executing inference."""
    output: dict[str, Any] = {"profiles": {}, "training_capture": training_data.stats()}
    for role in ("fast", "deep"):
        profile = model_pool_config.resolve_profile(role)
        cfg, _ = _config_for(role)
        model_status = local_brain.status(config=cfg)
        output["profiles"][role] = {
            "model": profile["model"],
            "think": profile["think"],
            "source": profile["source"],
            "online": model_status["online"],
            "model_available": model_status["model_available"],
        }
    return output
