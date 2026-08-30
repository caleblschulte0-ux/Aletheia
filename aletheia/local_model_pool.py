"""Two-role local reasoning pool with bounded failover and training capture."""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Callable, Any

from aletheia import local_brain, model_pool_config, training_data

FAST_TIMEOUT_S = 12.0
DEEP_TIMEOUT_S = 45.0
SMOKE_TIMEOUT_S = {"fast": 120.0, "deep": 180.0}
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


def _config(role: str, timeout_s: float | None = None,
            think_override: bool | None = None) -> local_brain.OllamaConfig:
    profile = model_pool_config.resolve(role)
    timeout = timeout_s if timeout_s is not None else (
        FAST_TIMEOUT_S if role == "fast" else DEEP_TIMEOUT_S
    )
    return local_brain.OllamaConfig.for_model(
        profile["model"],
        think=profile["think"] if think_override is None else think_override,
        timeout_s=timeout,
    )


def run_json(system_prompt: str, text: str, *, context: dict | None = None,
             role: str = "fast", validator: Callable[[dict], dict] | None = None,
             timeout_s: float | None = None,
             require_enabled: bool = True,
             think_override: bool | None = None) -> LocalRun:
    if role not in {"fast", "deep"}:
        raise ValueError("local role must be fast or deep")
    if require_enabled and not model_pool_config.enabled():
        raise LocalPoolUnavailable("local reasoning is disabled")
    ctx = context or {}
    if not isinstance(ctx, dict):
        raise ValueError("local context must be an object")
    started = time.perf_counter()
    proposal = None
    config = None
    payload = None
    try:
        config = _config(role, timeout_s, think_override)
        payload = local_brain.build_payload(system_prompt, text, ctx, config)
        proposal = local_brain.infer_json(system_prompt, text, context=ctx, config=config)
        output = validator(proposal) if validator else proposal
    except Exception as exc:
        elapsed = round((time.perf_counter() - started) * 1000)
        if config is not None:
            training_data.record_turn(
                provider="ollama", model=config.model, role=role, text=text, context=ctx,
                request_payload=payload, result=proposal, status="error",
                error_type=type(exc).__name__, error=str(exc), duration_ms=elapsed,
            )
        if isinstance(exc, local_brain.LocalBrainError):
            # LocalBrainError messages are deliberately bounded diagnostics
            # containing no prompt, response body, URL path, or credentials.
            # Keep the underlying timeout/transport class useful to the
            # operator instead of collapsing every failure to one vague type.
            raise LocalPoolUnavailable(
                f"local {role} role failed: {exc}"
            ) from None
        if isinstance(exc, (ValueError, TypeError)):
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
              preferred_role: str | None = None,
              allow_failover: bool = True,
              timeout_s: float | None = None,
              require_enabled: bool = True) -> LocalRun:
    first = preferred_role or choose_role(text, context)
    if first not in {"fast", "deep"}:
        raise ValueError("preferred_role must be fast or deep")
    second = "deep" if first == "fast" else "fast"
    try:
        return run_json(
            system_prompt, text, context=context, role=first,
            validator=validator, timeout_s=timeout_s,
            require_enabled=require_enabled,
        )
    except LocalPoolUnavailable:
        if not allow_failover:
            raise
        try:
            return run_json(
                system_prompt, text, context=context, role=second,
                validator=validator, timeout_s=timeout_s,
                require_enabled=require_enabled,
            )
        except LocalPoolUnavailable:
            raise LocalPoolUnavailable("both local reasoning roles are unavailable") from None


def smoke() -> dict[str, Any]:
    """Prove both configured models exist and satisfy the JSON transport contract."""
    results = {}
    for role in ("fast", "deep"):
        config = _config(role)
        observed = local_brain.status(config)
        if not observed.get("online") or not observed.get("model_available"):
            raise LocalPoolUnavailable(
                f"local {role} model is not ready: {observed.get('detail', 'unavailable')}"
            )

        def validate(value: dict, expected=role) -> dict:
            if value != {"ok": True, "role": expected}:
                raise ValueError(f"local {expected} smoke response did not match contract")
            return value

        run = run_json(
            "Return exactly the requested JSON object. You have no tools or authority.",
            f'Return exactly {{"ok":true,"role":"{role}"}}.',
            role=role, validator=validate, require_enabled=False,
            # Activation is allowed to cold-load the model once. Normal
            # production requests retain the 12s/45s route limits above.
            timeout_s=SMOKE_TIMEOUT_S[role],
            # This proves the tag, transport, JSON mode, and model response.
            # Full deep thinking is a production behavior, not an activation
            # prerequisite for an exact six-token transport probe.
            think_override=False,
        )
        results[role] = {
            "model": run.model,
            "duration_ms": run.duration_ms,
            "ok": True,
        }
    return {"ok": True, "roles": results}


def status() -> dict[str, Any]:
    profiles = {}
    for role in ("fast", "deep"):
        profile = model_pool_config.resolve(role)
        # Status is an operator diagnostic, not inference. A sick local service
        # must not make the command wait for the models' full generation limits.
        profiles[role] = {
            **profile,
            **local_brain.status(_config(role, timeout_s=2.0)),
        }
    return {
        **model_pool_config.settings(),
        "profiles": profiles,
        "training": training_data.stats(),
    }
