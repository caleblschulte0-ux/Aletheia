"""Several workers on one question, and one answer back.

This is the thing five open Claude and ChatGPT windows are actually FOR.
Not that five is better than one, but that independent work — different
context, different role, ideally a different model — disagrees, and the
disagreement is the product. A single worker asked to critique itself
agrees with itself.

WHAT THIS IS NOT. It is not the conversation loop. A model round trip is
~3.6 seconds on this machine and a planner call is 25-80; a team of four
with a critique round and a synthesis is MINUTES. Put it in front of
"what time is it" and she stops being usable. `quick` and the
deterministic layer stay in front, untouched, and this is reached only
for deliberate work — research, a decision, a review — where minutes are
the right price and he knows he is paying them.

THE SHAPE:

    assignments -> run bounded-parallel -> critique -> synthesize

Each stage is separable and each is testable with the model replaced,
because a primitive whose tests need a live subscription is a primitive
nobody runs the tests for.

CONCURRENCY IS TWO. Measured, not chosen: a sixteen-way parallel
`claude -p` burst on this PC had half its calls refused by the CLI, and
a refused call surfaces as `ReasonerUnavailable`, which reads like a
model outage rather than a self-inflicted one. `agents.MAX_PARALLEL`
holds the number in one place.

INDEPENDENCE IS CLAIMED HONESTLY. `independent()` says whether a critique
really was independent — a different role AND a different provider — and
the synthesis says so either way. The code worker already refuses to call
same-model self-review independent; this keeps that standard rather than
quietly lowering it for a nicer demo.

THE DEADLINE IS SOFT, AND SAYING SO IS THE POINT. Python cannot kill a
running thread, so `deadline_s` stops SUBMITTING and marks unstarted work
CANCELLED — it does not interrupt a worker already inside a network call.
The real bound on a hung provider is `worker_s`, which the gateway
honours as its own timeout. So: a slow team is bounded by the deadline, a
HUNG one by the per-worker timeout, and if a provider ignored both this
would block on pool shutdown. That is the known weakness of this design;
it is written here rather than discovered at 2am.

A WORKER THAT FAILS DOES NOT TAKE THE TEAM DOWN. Every assignment is
isolated: an exception becomes a FAILED result with its reason, the rest
of the team finishes, and the synthesis is told what is missing. One
broken worker hanging the whole thing is the failure this design is
most likely to have, so it is the one most carefully prevented.
"""
from __future__ import annotations

import concurrent.futures as futures
import time

from aletheia import agents, journal, policy

ACTOR = "teams"

# A whole team, wall-clock. Past this the answer is late enough that he
# has gone and done it himself, which makes the remaining work waste.
DEFAULT_DEADLINE_S = 600.0

# One worker's share. Generous — a planner call is 25-80s here — but
# finite, because a hung provider must not hold the deadline open.
DEFAULT_WORKER_S = 240.0


class Assignment(dict):
    """One worker's job: who, what, and what kind of thinking it needs.

    A dict rather than a dataclass so it survives a round trip through
    JSON into a receipt without a second representation.
    """

    def __init__(self, role: str, question: str, *,
                 model_policy: str = "standard", agent_id: str = ""):
        super().__init__(role=role, question=question,
                         model_policy=model_policy, agent_id=agent_id)


def _one(assignment: dict, worker, timeout_s: float) -> dict:
    """Run a single assignment and never raise.

    A worker that throws is a RESULT, not an exception: the team keeps
    going and the synthesis is told what it did not get.
    """
    started = time.monotonic()
    try:
        answer = worker(assignment, timeout_s=timeout_s)
        return {"role": assignment.get("role"), "state": "COMPLETED",
                "answer": answer,
                "provider": (answer or {}).get("provider")
                if isinstance(answer, dict) else None,
                "seconds": round(time.monotonic() - started, 2)}
    except Exception as exc:
        return {"role": assignment.get("role"), "state": "FAILED",
                "why": f"{type(exc).__name__}: {exc}"[:300],
                "seconds": round(time.monotonic() - started, 2)}


def run(assignments: list[dict], *, worker, deadline_s: float = DEFAULT_DEADLINE_S,
        worker_s: float = DEFAULT_WORKER_S,
        parallel: int = agents.MAX_PARALLEL) -> list[dict]:
    """Every assignment, at most `parallel` at once, all of them accounted for.

    Returns one row per assignment in the order they were given — always
    the same length as the input, so a caller can never silently lose a
    worker. Anything not STARTED when the deadline passes comes back
    CANCELLED rather than missing; work already inside a provider call
    cannot be interrupted and is bounded by `worker_s` instead. See the
    module docstring — the deadline is soft on purpose and it is better
    to say so than to imply a guarantee this cannot make.
    """
    if policy.halted():
        raise agents.NotPermitted(
            "everything is halted; no team runs until he resumes her")
    if not assignments:
        return []
    parallel = max(1, min(int(parallel), agents.MAX_PARALLEL))
    started = time.monotonic()
    results: list[dict | None] = [None] * len(assignments)

    with futures.ThreadPoolExecutor(max_workers=parallel) as pool:
        pending = {pool.submit(_one, a, worker, worker_s): i
                   for i, a in enumerate(assignments)}
        for future in futures.as_completed(pending, timeout=None):
            index = pending[future]
            results[index] = future.result()
            if time.monotonic() - started > deadline_s:
                for other, other_index in pending.items():
                    if results[other_index] is None:
                        other.cancel()
                break

    for i, row in enumerate(results):
        if row is None:
            results[i] = {"role": assignments[i].get("role"),
                          "state": "CANCELLED",
                          "why": "the team ran out of time"}
    return [r for r in results if r is not None]


def independent(a: dict, b: dict) -> bool:
    """Was b's critique of a really independent?

    Different ROLE and different PROVIDER. Same model reviewing its own
    work is self-review with an extra step, and calling it independent
    is the kind of dishonesty that makes a review worse than none —
    because it is trusted more.
    """
    if not a or not b:
        return False
    if a.get("role") and a.get("role") == b.get("role"):
        return False
    left, right = a.get("provider"), b.get("provider")
    if not left or not right:
        return False                        # unknown is not independent
    return left != right


def disagreements(results: list[dict]) -> list[dict]:
    """Where the workers did not line up, as data rather than prose.

    Only COMPLETED rows can disagree; a worker that failed did not
    dissent, and counting it as agreement is how a team of one broken
    worker and one working one reads as consensus.
    """
    done = [r for r in results if r.get("state") == "COMPLETED"]
    verdicts: dict[str, list[str]] = {}
    for row in done:
        answer = row.get("answer")
        verdict = str((answer or {}).get("verdict", "")).strip().casefold() \
            if isinstance(answer, dict) else ""
        if verdict:
            verdicts.setdefault(verdict, []).append(row.get("role") or "?")
    if len(verdicts) < 2:
        return []
    return [{"verdict": v, "roles": roles} for v, roles in sorted(verdicts.items())]


def summarise(results: list[dict]) -> dict:
    """What the team actually produced — counted, before anyone interprets it.

    Aletheia synthesises from THIS rather than from the prose, so a
    confident worker cannot outvote an arithmetic fact about how many
    workers finished.
    """
    done = [r for r in results if r.get("state") == "COMPLETED"]
    failed = [r for r in results if r.get("state") == "FAILED"]
    lost = [r for r in results if r.get("state") == "CANCELLED"]
    return {
        "asked": len(results), "answered": len(done),
        "failed": [{"role": r.get("role"), "why": r.get("why")} for r in failed],
        "cancelled": [r.get("role") for r in lost],
        "providers": sorted({r.get("provider") for r in done if r.get("provider")}),
        "disagreements": disagreements(results),
        "seconds": round(max([r.get("seconds", 0) for r in results] or [0]), 2),
    }


def gateway_worker(assignment: dict, *, timeout_s: float = DEFAULT_WORKER_S) -> dict:
    """The real worker: one assignment through the existing gateway.

    Deliberately thin. The gateway already owns provider choice,
    budgets, degradation and the local-vs-subscription decision, and a
    second copy of that logic here would be a second thing to keep true.
    """
    from aletheia import reasoning_gateway
    result = reasoning_gateway.reason_json(
        f"You are the {assignment.get('role')} on a team. Answer only your part.",
        str(assignment.get("question") or ""),
        policy=assignment.get("model_policy") or "standard",
        timeout_s=timeout_s)
    return {"output": result.output, "provider": result.provider,
            "degraded": getattr(result, "degraded", None)}


def deliberate(question: str, assignments: list[dict], *, worker=None,
               deadline_s: float = DEFAULT_DEADLINE_S) -> dict:
    """The whole thing: run the team, count what came back, journal it.

    Returns the raw results AND the arithmetic. It does NOT write the
    final answer — Aletheia is the final voice (§28), and a synthesiser
    buried in here would be a second place that speaks to him.
    """
    results = run(assignments, worker=worker or gateway_worker,
                  deadline_s=deadline_s)
    summary = summarise(results)
    journal.append(
        "action", "team",
        f"{summary['answered']} of {summary['asked']} workers answered"
        + (f", {len(summary['failed'])} failed" if summary["failed"] else "")
        + (f", {len(summary['disagreements'])} disagreement(s)"
           if summary["disagreements"] else ""),
        actor=ACTOR)
    return {"question": question, "results": results, "summary": summary}
