"""Aletheia's replaceable reasoning gateway.

Aletheia is the boss; models are workers. This module decides which worker gets
a reasoning request without granting any model execution authority.

Policies:
- routine: local fast/deep first, subscriptions if local cannot answer.
- standard: subscriptions first, local deep fallback when the cloud/subscription
  path is unavailable.
- critical: subscriptions are required for the returned answer. Local models
  may still run as non-authoritative students via reasoner's shadow capture.
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Callable, Any

from aletheia import (
    brain, local_model_pool, model_pool_config, reasoner, training_data,
)

POLICIES = {"routine", "standard", "critical"}
ROUTINE_TOTAL_TIMEOUT_S = 45.0
ROUTINE_LOCAL_TIMEOUT_S = 15.0
# 180, not 90 (2026-09-04): a planner call carries a 15 KB grammar and a
# 5 KB situational context, and a rant-shaped ask took 81 s on the
# operator's PC under load — past a 90 s cap split with the local model.
# The phone and the room already wait up to 300 s for a follow-up; the
# brain's own ceiling was the thing that gave up first.
STANDARD_TOTAL_TIMEOUT_S = 180.0
# The subscription gets almost all of the standard budget. It used to get
# half (45 s) so a local model could have the other half — but a local deep
# model that needs more than 15 s to plan a long ask cannot use 45 s
# either, and a rant-shaped plan the subscription answers in ~26 s was
# dying at the cap (2026-09-04). Local keeps the last 15 s: enough when
# the subscription fails FAST (a limit, an auth error), which is the case
# it exists for.
STANDARD_SUBSCRIPTION_SLICE_S = STANDARD_TOTAL_TIMEOUT_S - ROUTINE_LOCAL_TIMEOUT_S


@dataclass(frozen=True)
class GatewayResult:
    output: dict
    provider: str
    policy: str
    local_role: str | None = None
    local_model: str | None = None
    degraded: str | None = None
    turn_id: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "output": self.output,
            "provider": self.provider,
            "policy": self.policy,
            "local_role": self.local_role,
            "local_model": self.local_model,
            "degraded": self.degraded,
            "training_turn_id": self.turn_id,
        }


def _checked(validator: Callable[[dict], dict] | None):
    return validator or (lambda value: value)


def reason_json(system_prompt: str, text: str, *, context: dict | None = None,
                policy: str = "standard", model: str = reasoner.INTERPRET_MODEL,
                timeout_s: float = reasoner.TIMEOUT_S,
                validator: Callable[[dict], dict] | None = None) -> GatewayResult:
    if policy not in POLICIES:
        raise ValueError(f"policy must be one of {sorted(POLICIES)}")
    checked = _checked(validator)
    ctx = context or {}
    if not isinstance(ctx, dict):
        raise ValueError("reasoning context must be an object")
    # Preserve the reasoner's existing whole-context contract for every route.
    # In particular, routine local-first requests must not get a larger input
    # budget than subscription requests or attempt a provider before degrading.
    reasoner.validate_input(system_prompt, text, ctx)
    requested_budget = float(timeout_s)
    if not math.isfinite(requested_budget) or requested_budget < 0.5:
        raise ValueError("reasoning timeout must be finite and at least 0.5 seconds")
    started = time.monotonic()
    total_budget = min(
        requested_budget,
        ROUTINE_TOTAL_TIMEOUT_S if policy == "routine" else STANDARD_TOTAL_TIMEOUT_S,
    )

    def remaining() -> float:
        return max(0.0, total_budget - (time.monotonic() - started))

    # Configured is not running. With Ollama configured but stopped, the
    # subscription was capped to a 45 s slice "to leave room" for a model
    # that would never answer, and a long plan for a rant-shaped ask died at
    # the cap while a direct call took 26 s (2026-09-04, the night before
    # first real use). Routine asks also waited 15 s on it every time.
    local_enabled = model_pool_config.enabled() and local_model_pool.reachable()

    if policy == "routine":
        local_exc = None
        if local_enabled:
            try:
                local = local_model_pool.auto_json(
                    system_prompt, text, context=ctx, validator=checked,
                    allow_failover=False,
                    timeout_s=min(ROUTINE_LOCAL_TIMEOUT_S, max(0.5, remaining())),
                )
                return GatewayResult(
                    local.output, f"ollama:{local.model}", policy,
                    local.role, local.model, turn_id=local.turn_id,
                )
            except local_model_pool.LocalPoolUnavailable as exc:
                local_exc = exc
        if remaining() <= 0.5:
            raise reasoner.ReasonerUnavailable("routine reasoning time budget expired")
        try:
            output = reasoner.subscription_json(
                system_prompt, text, context=ctx, model=model,
                timeout_s=remaining(), validator=checked,
            )
            return GatewayResult(
                output, "subscription.auto", policy,
                degraded=(f"local routine path unavailable: {type(local_exc).__name__}"
                          if local_exc else None),
            )
        except reasoner.ReasonerUnavailable:
            suffix = "local routine path unavailable" if local_enabled else "local reasoning disabled"
            raise reasoner.ReasonerUnavailable(
                f"both subscription reasoning paths are unavailable; {suffix}"
            ) from None

    if policy == "critical":
        output = reasoner.subscription_json(
            system_prompt, text, context=ctx, model=model,
            timeout_s=remaining(), validator=checked,
        )
        return GatewayResult(output, "subscription.auto", policy)

    # Standard: subscriptions retain priority/quality; local deep is the offline
    # bridge that keeps Aletheia useful when those subscriptions are unreachable.
    try:
        subscription_budget = remaining()
        if local_enabled:
            subscription_budget = min(
                subscription_budget, STANDARD_SUBSCRIPTION_SLICE_S,
            )
        output = reasoner.subscription_json(
            system_prompt, text, context=ctx, model=model,
            timeout_s=subscription_budget, validator=checked,
        )
        return GatewayResult(output, "subscription.auto", policy)
    except reasoner.ReasonerUnavailable as cloud_exc:
        if not local_enabled:
            raise reasoner.ReasonerUnavailable(
                "both subscription reasoning paths are unavailable; local reasoning "
                f"disabled (subscription: {cloud_exc})"
            ) from None
        if remaining() <= 0.5:
            raise reasoner.ReasonerUnavailable(
                "subscription reasoning exhausted the standard time budget"
            ) from None
        try:
            local = local_model_pool.auto_json(
                system_prompt, text, context=ctx, validator=checked,
                preferred_role="deep",
                allow_failover=False,
                timeout_s=max(0.5, remaining()),
            )
            return GatewayResult(
                local.output, f"ollama:{local.model}", policy,
                local.role, local.model,
                degraded=f"subscriptions unavailable: {type(cloud_exc).__name__}",
                turn_id=local.turn_id,
            )
        except local_model_pool.LocalPoolUnavailable as local_exc:
            # Both causes travel with the refusal. On 2026-09-02 eight
            # planner calls answered only "unavailable" and the real reason
            # (the CLI refusing a burst of concurrent calls) was invisible.
            raise reasoner.ReasonerUnavailable(
                "subscription reasoning and local deep reasoning are unavailable "
                f"(subscription: {cloud_exc}; local: {local_exc})"
            ) from None


@dataclass(frozen=True)
class HybridReasoner:
    system_prompt: str
    policy: str = "standard"
    model: str = reasoner.INTERPRET_MODEL
    timeout_s: float = reasoner.TIMEOUT_S

    def infer(self, text: str, context: dict | None = None) -> dict:
        return reason_json(
            self.system_prompt, text, context=context, policy=self.policy,
            model=self.model, timeout_s=self.timeout_s,
            validator=brain.validate_output,
        ).output

    def provider(self, provider_id: str | None = None) -> brain.Provider:
        return brain.Provider(provider_id or f"reasoning.hybrid.{self.policy}", self.infer)


def status() -> dict[str, Any]:
    sub_ok, sub_detail = reasoner.available()
    try:
        local = local_model_pool.status()
    except Exception as exc:
        local = {"error": f"{type(exc).__name__}: {exc}"}
    return {
        "policies": sorted(POLICIES),
        "subscriptions": {"available": sub_ok, "detail": sub_detail},
        "local": local,
        "training": training_data.stats(),
    }
