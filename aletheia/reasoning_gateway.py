"""Aletheia's replaceable reasoning gateway.

Aletheia is the boss; models are workers.  This module decides which worker gets
a reasoning request without granting any model execution authority.

Policies:
- routine: local fast/deep first, subscriptions if local cannot answer.
- standard: subscriptions first, local deep fallback when the cloud/subscription
  path is unavailable.
- critical: subscriptions are required for the returned answer.  Local models
  may still run as non-authoritative students via reasoner's shadow capture.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Any

from aletheia import brain, local_model_pool, reasoner, training_data

POLICIES = {"routine", "standard", "critical"}


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

    if policy == "routine":
        try:
            local = local_model_pool.auto_json(
                system_prompt, text, context=ctx, validator=checked,
                preferred_role="fast",
            )
            return GatewayResult(
                local.output, f"ollama:{local.model}", policy,
                local.role, local.model, turn_id=local.turn_id,
            )
        except local_model_pool.LocalPoolUnavailable as local_exc:
            try:
                output = reasoner.subscription_json(
                    system_prompt, text, context=ctx, model=model,
                    timeout_s=timeout_s, validator=checked,
                )
                return GatewayResult(
                    output, "subscription.auto", policy,
                    degraded=f"local routine path unavailable: {type(local_exc).__name__}",
                )
            except reasoner.ReasonerUnavailable:
                raise reasoner.ReasonerUnavailable(
                    "local routine reasoning and both subscription paths are unavailable"
                ) from None

    if policy == "critical":
        output = reasoner.subscription_json(
            system_prompt, text, context=ctx, model=model,
            timeout_s=timeout_s, validator=checked,
        )
        return GatewayResult(output, "subscription.auto", policy)

    # Standard: subscriptions retain priority/quality; local deep is the offline
    # bridge that keeps Aletheia useful when those subscriptions are unreachable.
    try:
        output = reasoner.subscription_json(
            system_prompt, text, context=ctx, model=model,
            timeout_s=timeout_s, validator=checked,
        )
        return GatewayResult(output, "subscription.auto", policy)
    except reasoner.ReasonerUnavailable as cloud_exc:
        try:
            local = local_model_pool.auto_json(
                system_prompt, text, context=ctx, validator=checked,
                preferred_role="deep",
            )
            return GatewayResult(
                local.output, f"ollama:{local.model}", policy,
                local.role, local.model,
                degraded=f"subscriptions unavailable: {type(cloud_exc).__name__}",
                turn_id=local.turn_id,
            )
        except local_model_pool.LocalPoolUnavailable:
            raise reasoner.ReasonerUnavailable(
                "subscription reasoning and both local reasoning roles are unavailable"
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
