"""Two-role local reasoning pool with bounded failover and training capture."""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Callable, Any

from aletheia import local_brain, model_pool_config, training_data

FAST_TIMEOUT_S = 20.0
DEEP_TIMEOUT_S = 60.0
DEEP_HINTS = (
    "architecture", "root cause", "debug", "code review", "review the code",
    "tradeoff", "trade-off", "investigate", "complex plan", "reason through",
    "deep analysis", "think hard",
)


class LocalPoolUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class LocalRun:
    role: str
    model: str
    think: bool
    output: dict
    turn_id: str | None
    duration_ms: int


def choose_role(text: str, context: dict | None = None) -> str:
    lowered = str(text).casefold()
    if any(hint in lowered for hint in DEEP_HINTS):
        return "deep"
    if len(str(text)) >= 1_200:
        return "deep"
    try:
        size = len(json.dumps(context or {}, ensure_ascii=False, default=str))
    except (TypeError, ValueError):
        size = 0
    return "deep" if size >= 6_000 else "fast"


def _config(role: str) -> local_brain.OllamaConfig:
    profile = model_pool_config.resolve(role)
    timeout = FAST_TIMEOUT_S if role == "fast" else DEEP_TIMEOUT_S
    return local_brain.OllamaConfig.for_model(
        profile["model"], think=profile["think"], timeout_s=timeout,
    )


def run_json(system_prompt: str, text: str, *, context: dict | None = None,
             role: str = "fast", validator: Callable[[dict], dict] | None = None) -> LocalRun:
    if role not in {"fast", "deep"}:
        raise ValueError("local role must be fast or deep")
    ctx = context or {}
    if not isinstance(ctx, dict):
        raise ValueError("local context must be an object")
    config = _config(role)
    payload = local_brain.build_payload(system_prompt, text, ctx, config)
    started = time.perf_counter()
    proposal = None
    try:
        proposal = local_brain.infer_json(system_prompt, text, context=ctx, config=config)
        output = validator(proposal) if validator else proposal
    except Exception as exc:
        elapsed = round((time.perf_counter() - started) * 1000)
        training_data.record_turn(
            provider="ollama", model=config.model, role=role, text=text, context=ctx,
            request_payload=payload, result=proposal, status="error",
            error_type=type(exc).__name__, error=str(exc), duration_ms=elapsed,
        )
        if isinstance(exc, (local_brain.LocalBrainError, ValueError, TypeError)):
            raise LocalPoolUnavailable(f"local {role} role failed ({type(exc).__name__})") from None
        raise
    elapsed = round((time.perf_counter() - started) * 1000)
    turn_id = training_data.record_turn(
        provider="ollama", model=config.model, role=role, text=text, context=ctx,
        request_payload=payload, result=output, status="validated", duration_ms=elapsed,
    )
    return LocalRun(role, config.model, config.think, output, turn_id, elapsed)


def auto_json(system_prompt: str, text: str, *, context: dict | None = None,
              validator: Callable[[dict], dict] | None = None,
              preferred_role: str | None = None) -> LocalRun:
    first = preferred_role or choose_role(text, context)
    if first not in {"fast", "deep"}:
        raise ValueError("preferred_role must be fast or deep")
    second = "deep" if first == "fast" else "fast"
    try:
        return run_json(system_prompt, text, context=context, role=first, validator=validator)
    except LocalPoolUnavailable:
        try:
            return run_json(system_prompt, text, context=context, role=second, validator=validator)
        except LocalPoolUnavailable:
            raise LocalPoolUnavailable("both local reasoning roles are unavailable") from None


def status() -> dict[str, Any]:
    profiles = {}
    for role in ("fast", "deep"):
        profile = model_pool_config.resolve(role)
        profiles[role] = {**profile, **local_brain.status(_config(role))}
    return {"profiles": profiles, "training": training_data.stats()}
