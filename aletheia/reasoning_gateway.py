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
import os
import time
from dataclasses import dataclass
from typing import Callable, Any

from aletheia import (
    brain, local_model_pool, model_pool_config, reasoner, training_data,
    work_states,
)

# The classes are the shared vocabulary (aletheia.work_states), not restated here.
POLICIES = set(work_states.REASONING_CLASSES)
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
# CODE WORK waits longer, and only when it says so (`work_budget_s`). A
# bounded repair drafted by qwen3:8b on his CPU-only laptop took 190 s for a
# one-function fix (measured 2026-09-16, model cold, another worker sharing
# the machine) - past the 180 s standard ceiling, so the local tier the brief
# asks for could never answer. Conversation keeps the 180 s ceiling above.
MAX_WORK_BUDGET_S = 600.0
# HOW LONG DEPENDS ON WHAT THE WORK IS, not on one number for the machine.
# His ruling, 2026-09-18, asked how long her own model should get: *"I don't
# know, like a while."* A while is two numbers, because one Ollama queue serves
# both a sentence he is standing there waiting for and a repair draft nobody is
# looking at: a Node repair DRAFT measured 217-270 s with the queue free and
# died at the old 300 s ceiling whenever the live Core was also talking to him.
# The ceilings themselves are `work_states.LOCAL_CEILING_S` (300 s attended,
# 1200 s background) so the conversation path can read the same number; the
# budgets below are this gateway's own.
ATTENDED = work_states.ATTENDED
BACKGROUND = work_states.BACKGROUND
# A background caller may spend the whole 20 minutes on the model and still
# have a moment to validate; attended work keeps the 600 s it had.
MAX_BACKGROUND_BUDGET_S = work_states.LOCAL_CEILING_S[BACKGROUND] + 60.0
# What a single local call may take, by class. Nothing gets the long one
# without asking for it by name (`attention=BACKGROUND`).
LOCAL_MAX_TIMEOUT_S = work_states.LOCAL_CEILING_S[ATTENDED]


def local_ceiling_s(attention: str = ATTENDED) -> float:
    """How long ONE call to her own model may take for this class of work."""
    return work_states.local_ceiling_s(attention)


def work_budget_ceiling_s(attention: str = ATTENDED) -> float:
    """The most a caller may claim with `work_budget_s`, by class of work."""
    if attention not in work_states.ATTENTION:
        raise ValueError(f"attention must be one of {sorted(work_states.ATTENTION)}")
    return MAX_BACKGROUND_BUDGET_S if attention == BACKGROUND else MAX_WORK_BUDGET_S


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
                validator: Callable[[dict], dict] | None = None,
                local_timeout_s: float | None = None,
                max_context_bytes: int = reasoner.MAX_CONTEXT_BYTES,
                work_budget_s: float | None = None,
                attention: str = ATTENDED) -> GatewayResult:
    """`local_timeout_s` bounds a routine local attempt. `max_context_bytes`
    is the reasoner's own per-call bound (the code worker shows whole files;
    everyone else keeps 8 KB). `work_budget_s` lets long-running code work
    (never a conversation) replace the 180 s standard/critical ceiling, up to
    `work_budget_ceiling_s(attention)`.

    `attention` says WHAT THE WORK IS: ATTENDED (the default - he is waiting on
    it) or BACKGROUND (a draft, a review, a reading nobody is sitting in front
    of). It is the only thing that buys her own model the long ceiling, and it
    is never inherited: a caller that does not say BACKGROUND gets the 300 s
    conversation has always had, however large a budget it asked for."""
    if policy not in POLICIES:
        raise ValueError(f"policy must be one of {sorted(POLICIES)}")
    if attention not in work_states.ATTENTION:
        raise ValueError(f"attention must be one of {sorted(work_states.ATTENTION)}")
    checked = _checked(validator)
    ctx = context or {}
    if not isinstance(ctx, dict):
        raise ValueError("reasoning context must be an object")
    # Preserve the reasoner's existing whole-context contract for every route.
    # In particular, routine local-first requests must not get a larger input
    # budget than subscription requests or attempt a provider before degrading.
    limit = reasoner._bounded_context_limit(max_context_bytes)
    reasoner.validate_input(system_prompt, text, ctx, max_context_bytes=limit)
    requested_budget = float(timeout_s)
    if not math.isfinite(requested_budget) or requested_budget < 0.5:
        raise ValueError("reasoning timeout must be finite and at least 0.5 seconds")
    started = time.monotonic()
    ceiling = ROUTINE_TOTAL_TIMEOUT_S if policy == "routine" else STANDARD_TOTAL_TIMEOUT_S
    if work_budget_s is not None and policy != "routine":
        work = float(work_budget_s)
        cap = work_budget_ceiling_s(attention)
        if not math.isfinite(work) or not 0.5 <= work <= cap:
            raise ValueError(f"work budget must be 0.5..{cap:.0f} seconds")
        ceiling = work
    total_budget = min(requested_budget, ceiling)

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
                    timeout_s=min(_local_slice(local_timeout_s), max(0.5, remaining())),
                    attention=attention,
                )
                return GatewayResult(
                    local.output, f"ollama:{local.model}", policy,
                    local.role, local.model, turn_id=local.turn_id,
                )
            except local_model_pool.LocalPoolUnavailable as exc:
                local_exc = exc
        if remaining() <= 0.5:
            raise reasoner.ReasonerUnavailable(
                "I ran out of thinking time before an answer came back")
        try:
            output = _subscription_json(
                system_prompt, text, context=ctx, model=model,
                timeout_s=remaining(), validator=checked, max_context_bytes=limit,
            )
            return GatewayResult(
                output, "subscription.auto", policy,
                degraded=(f"local routine path unavailable: {type(local_exc).__name__}"
                          if local_exc else None),
            )
        except reasoner.ReasonerUnavailable:
            suffix = ("and the local model could not either" if local_enabled
                      else "and local reasoning is switched off")
            raise reasoner.ReasonerUnavailable(
                f"neither Claude nor the ChatGPT browser could answer just "
                f"now, {suffix}"
            ) from None

    if policy == "critical":
        output = _subscription_json(
            system_prompt, text, context=ctx, model=model,
            timeout_s=remaining(), validator=checked, max_context_bytes=limit,
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
        output = _subscription_json(
            system_prompt, text, context=ctx, model=model,
            timeout_s=subscription_budget, validator=checked, max_context_bytes=limit,
        )
        return GatewayResult(output, "subscription.auto", policy)
    except reasoner.ReasonerUnavailable as cloud_exc:
        if not local_enabled:
            raise reasoner.ReasonerUnavailable(
                "neither Claude nor the ChatGPT browser could answer just now, "
                f"and local reasoning is switched off ({cloud_exc})"
            ) from None
        if remaining() <= 0.5:
            raise reasoner.ReasonerUnavailable(
                "I ran out of thinking time before an answer came back"
            ) from None
        try:
            # DEEP FIRST, THEN WHATEVER FITS. On this laptop the deep model
            # (27B, about 19 GB) has never once run - 31 recorded attempts, 31
            # failures - because it does not fit in 16 GB, and with failover
            # off this bridge had never carried a single request. His words,
            # 2026-09-10: something "that'll never run out even if it's not
            # the best". The fast model fits; not the best is the point.
            local = local_model_pool.auto_json(
                system_prompt, text, context=ctx, validator=checked,
                preferred_role="deep",
                allow_failover=True,
                timeout_s=min(local_ceiling_s(attention), max(0.5, remaining())),
                attention=attention,
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


# ---- continuity: frontier off, and the two rungs by name --------------------------
#
# His 2026-09-16 brief: a subsystem asks for a CLASS of reasoning, not a company.
# Callers that keep their own chain (a sticky agent session) still reach the
# companies only through here, so there is one place that knows who they are and
# one switch that can say "pretend they are all out" (acceptance test A).

FRONTIER_OFF_ENV = "ALETHEIA_FRONTIER_OFF"


def frontier_off() -> bool:
    """True when this process is simulating Claude/Codex/ChatGPT unavailable.

    Only ever REMOVES ability: it cannot make anything run that would not."""
    return str(os.environ.get(FRONTIER_OFF_ENV, "")).strip().lower() in {"1", "true", "yes", "on"}


def _local_slice(requested: float | None) -> float:
    if requested is None:
        return ROUTINE_LOCAL_TIMEOUT_S
    value = float(requested)
    if not math.isfinite(value):
        return ROUTINE_LOCAL_TIMEOUT_S
    return max(0.5, min(value, ROUTINE_TOTAL_TIMEOUT_S))


def _subscription_json(system_prompt: str, text: str, **kwargs) -> dict:
    if frontier_off():
        raise reasoner.ReasonerUnavailable(
            "the frontier models are switched off for this run")
    return reasoner.subscription_json(system_prompt, text, **kwargs)


def frontier_json(system_prompt: str, text: str, *, context: dict | None = None,
                  model: str = reasoner.INTERPRET_MODEL,
                  timeout_s: float = reasoner.TIMEOUT_S,
                  validator: Callable[[dict], dict] | None = None) -> GatewayResult:
    """One frontier answer with the provider named (Claude, then the ChatGPT
    browser). For a caller that holds its own fallback (an agent session that
    stops asking once they are out). Raises ReasonerUnavailable."""
    if frontier_off():
        raise reasoner.ReasonerUnavailable(
            "the frontier models are switched off for this run")
    value, provider = reasoner._subscription_json_with_provider(
        system_prompt, text, context=context, model=model,
        timeout_s=timeout_s, validator=validator)
    return GatewayResult(value, provider, "critical")


def frontier_available() -> bool:
    """Could a frontier model plausibly answer now, WITHOUT asking one: not
    switched off and Claude not known to be resting. Cheap and optimistic."""
    if frontier_off():
        return False
    try:
        return reasoner.resting_until() is None
    except Exception:
        return True


def frontier_status(now=None) -> dict:
    """Which frontier worker could answer, WITHOUT asking one (no round trip):
    {"ok", "why", "wake", "resets_at"}. The companies are named here so a
    requirement check never has to know them."""
    if frontier_off():
        return {"ok": False, "why": "the frontier models are switched off for this run",
                "wake": "when the frontier models are switched back on", "resets_at": None}
    reasons, soonest = [], None
    claude_cli = reasoner.cli_path()
    claude_until = reasoner.resting_until(now)
    if claude_cli and claude_until is None:
        return {"ok": True, "why": "Claude CLI present with no limit on record", "wake": "", "resets_at": None}
    if claude_until is not None:
        reasons.append(f"Claude is resting until {claude_until.strftime('%Y-%m-%dT%H:%M:%SZ')}")
        soonest = claude_until
    elif not claude_cli:
        reasons.append("the Claude CLI is not installed")
    codex_cli = reasoner.codex_path()
    codex = reasoner.codex_resting(now)
    if codex_cli and codex is None:
        return {"ok": True, "why": "Codex CLI present with no limit on record"
                + (f" ({reasons[0]})" if reasons else ""), "wake": "", "resets_at": None}
    if codex is not None:
        reasons.append(f"Codex is resting until {codex[0].strftime('%Y-%m-%dT%H:%M:%SZ')}")
        soonest = codex[0] if soonest is None else min(soonest, codex[0])
    elif not codex_cli:
        reasons.append("the Codex CLI is not installed")
    return {"ok": False, "why": "; ".join(reasons) or "no frontier model is reachable",
            "wake": ("when Claude's or Codex's limit resets" if soonest is not None
                     else "when a frontier CLI is installed and signed in"),
            "resets_at": soonest}


def local_ready() -> bool:
    """Her own model is switched on AND answering (cached probe)."""
    return bool(model_pool_config.enabled() and local_model_pool.reachable())


def local_json(system_prompt: str, text: str, *, context: dict | None = None,
               role: str = "fast", validator: Callable[[dict], dict] | None = None,
               timeout_s: float | None = None,
               think_override: bool | None = None,
               attention: str = ATTENDED) -> GatewayResult:
    """One answer from her own model in a named role. Raises
    local_model_pool.LocalPoolUnavailable, whose words say why. `attention`
    chooses the per-call ceiling exactly as in `reason_json`."""
    run = local_model_pool.run_json(system_prompt, text, context=context, role=role,
                                    validator=validator, timeout_s=timeout_s,
                                    think_override=think_override, attention=attention)
    return GatewayResult(run.output, f"ollama:{run.model}", "routine",
                         run.role, run.model, turn_id=run.turn_id)


def thinker(policy: str, **fixed) -> Callable[..., dict]:
    """A drop-in for the old `reasoner.subscription_json(system, text, *,
    context, model, timeout_s, validator)` seam that asks for a CLASS."""
    if policy not in POLICIES:
        raise ValueError(f"policy must be one of {sorted(POLICIES)}")

    def think(system_prompt: str, text: str, **kwargs) -> dict:
        merged = {**fixed, **kwargs}
        allowed = {k: merged[k] for k in ("context", "model", "timeout_s", "validator",
                                          "local_timeout_s") if k in merged}
        return reason_json(system_prompt, text, policy=policy, **allowed).output
    think.policy = policy  # type: ignore[attr-defined]
    return think


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
        "frontier_off": frontier_off(),
        "subscriptions": {"available": sub_ok, "detail": sub_detail},
        "local": local,
        "training": training_data.stats(),
    }
