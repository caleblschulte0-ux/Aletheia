"""Fail-closed Jarvis orchestration loop.

This is executable only with injected adapters.  It never imports the live
Core, never opens a browser, never talks to Windows UIA, never touches the
network, and never writes Aletheia's canonical memory.

The important behavior is the ordering:
    observe -> recall -> understand -> plan -> authorize
    -> execute one step -> verify it -> next step -> propose memory -> commit

No action executes before whole-plan authorization.  A failed action or failed
verification stops the run immediately.  There is deliberately no autonomous
retry or plan mutation yet.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from .contracts import ActionReceipt, LoopOutcome, LoopPhase, Observation, Plan
from .ports import (
    ActionPort,
    AuthorityPort,
    MemoryPort,
    PerceptionPort,
    ReasoningPort,
    VerificationPort,
    VoicePort,
)
from .trace import Trace, TraceEvent


@dataclass(frozen=True)
class LoopResult:
    outcome: LoopOutcome
    summary: str
    plan: Plan | None
    receipts: tuple[ActionReceipt, ...]
    observations: tuple[Observation, ...]
    trace: tuple[TraceEvent, ...]


class JarvisLoop:
    """One-turn supervisor with explicit authority and verification seams."""

    def __init__(
        self,
        *,
        perception: PerceptionPort,
        reasoning: ReasoningPort,
        authority: AuthorityPort,
        actions: ActionPort,
        verification: VerificationPort,
        memory: MemoryPort,
        voice: VoicePort | None = None,
        max_steps: int = 20,
    ) -> None:
        if max_steps < 1:
            raise ValueError("max_steps must be positive")
        self.perception = perception
        self.reasoning = reasoning
        self.authority = authority
        self.actions = actions
        self.verification = verification
        self.memory = memory
        self.voice = voice
        self.max_steps = max_steps

    def _result(
        self,
        outcome: LoopOutcome,
        summary: str,
        *,
        plan: Plan | None,
        receipts: Sequence[ActionReceipt],
        observations: Sequence[Observation],
        trace: Trace,
    ) -> LoopResult:
        if self.voice and summary:
            self.voice.say(summary)
        return LoopResult(
            outcome=outcome,
            summary=summary,
            plan=plan,
            receipts=tuple(receipts),
            observations=tuple(observations),
            trace=trace.events,
        )

    def run(self, utterance: str) -> LoopResult:
        trace = Trace()
        utterance = utterance.strip()
        if not utterance:
            trace.add(LoopPhase.FAILED, "empty operator turn refused")
            return self._result(
                LoopOutcome.FAILED,
                "I need an operator request before I can do anything.",
                plan=None,
                receipts=(),
                observations=(),
                trace=trace,
            )

        try:
            trace.add(LoopPhase.OBSERVING, "collecting bounded context")
            observations = list(self.perception.observe(utterance))

            trace.add(LoopPhase.OBSERVING, "recalling bounded memory")
            memories = list(self.memory.recall(utterance))

            trace.add(LoopPhase.UNDERSTANDING, "resolving operator intent")
            intent = self.reasoning.understand(utterance, observations, memories)

            trace.add(LoopPhase.PLANNING, "building typed action plan", goal=intent.goal)
            plan = self.reasoning.plan(intent, observations, memories)
            if len(plan.steps) > self.max_steps:
                trace.add(
                    LoopPhase.FAILED,
                    "plan exceeded local staging step budget",
                    count=len(plan.steps),
                    maximum=self.max_steps,
                )
                return self._result(
                    LoopOutcome.FAILED,
                    f"Plan refused: {len(plan.steps)} steps exceeds the {self.max_steps}-step staging limit.",
                    plan=plan,
                    receipts=(),
                    observations=observations,
                    trace=trace,
                )

            if not plan.steps:
                trace.add(LoopPhase.COMPLETE, "turn requires no external action")
                return self._result(
                    LoopOutcome.NO_ACTION,
                    plan.rationale or "No action is required.",
                    plan=plan,
                    receipts=(),
                    observations=observations,
                    trace=trace,
                )

            trace.add(
                LoopPhase.AWAITING_AUTHORITY,
                "requesting authority for exact plan",
                plan_id=plan.plan_id,
                highest_risk=plan.highest_risk.value,
            )
            allowed, authority_reason = self.authority.authorize(plan)
            if not allowed:
                trace.add(LoopPhase.REFUSED, "authority refused plan", reason=authority_reason)
                return self._result(
                    LoopOutcome.REFUSED,
                    authority_reason or "That plan was not authorized.",
                    plan=plan,
                    receipts=(),
                    observations=observations,
                    trace=trace,
                )

            receipts: list[ActionReceipt] = []
            current_observations = observations
            for index, step in enumerate(plan.steps):
                trace.add(
                    LoopPhase.ACTING,
                    "executing authorized step",
                    index=index,
                    capability=step.capability,
                    risk=step.risk.value,
                )
                receipt = self.actions.execute(step, plan_id=plan.plan_id)
                receipts.append(receipt)
                if not receipt.ok:
                    trace.add(
                        LoopPhase.FAILED,
                        "action adapter reported failure",
                        index=index,
                        capability=step.capability,
                        error=receipt.error,
                    )
                    return self._result(
                        LoopOutcome.FAILED,
                        f"{step.capability} failed: {receipt.error}",
                        plan=plan,
                        receipts=receipts,
                        observations=current_observations,
                        trace=trace,
                    )

                trace.add(
                    LoopPhase.VERIFYING,
                    "verifying requested effect",
                    index=index,
                    capability=step.capability,
                )
                verified, reason, fresh = self.verification.verify(
                    step, receipt, before=current_observations
                )
                if fresh:
                    current_observations = list(fresh)
                if not verified:
                    trace.add(
                        LoopPhase.FAILED,
                        "verification rejected action result",
                        index=index,
                        capability=step.capability,
                        reason=reason,
                    )
                    return self._result(
                        LoopOutcome.FAILED,
                        reason or f"I could not verify {step.capability}.",
                        plan=plan,
                        receipts=receipts,
                        observations=current_observations,
                        trace=trace,
                    )

            trace.add(LoopPhase.REMEMBERING, "proposing memory from verified turn")
            candidates = list(
                self.memory.propose(intent, plan, receipts, current_observations)
            )
            if candidates:
                self.memory.commit(candidates)

            trace.add(
                LoopPhase.COMPLETE,
                "all authorized steps executed and verified",
                steps=len(receipts),
                memories=len(candidates),
            )
            return self._result(
                LoopOutcome.COMPLETE,
                plan.rationale or f"Completed {len(receipts)} verified step(s).",
                plan=plan,
                receipts=receipts,
                observations=current_observations,
                trace=trace,
            )

        except Exception as exc:
            trace.add(
                LoopPhase.FAILED,
                "adapter boundary raised",
                error_type=type(exc).__name__,
                error=str(exc),
            )
            return self._result(
                LoopOutcome.FAILED,
                f"Stopped safely: {type(exc).__name__}: {exc}",
                plan=locals().get("plan"),
                receipts=locals().get("receipts", ()),
                observations=locals().get("current_observations", locals().get("observations", ())),
                trace=trace,
            )
