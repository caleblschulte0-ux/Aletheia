"""One outcome, worked until it is done — look, act, look again (§3, §34).

The operator, 2026-09-02, after being shown a list of sixteen things she
can do: *"i dont need 16 commands i need to know i can ask this anything
and it will do it or route it to the right place ... find and apply to 10
jobs for me and it gets it done ... or i give it a video and say edit
this whatever it may be."*

He is right, and the gap was structural rather than missing verbs.
`agenda` compiles ONE plan from ONE sentence and runs it straight through.
`mission` is a budget and an authorization, not a loop. So nothing in the
system could do the thing every real task needs:

    look at what is actually there → decide → act → look at what happened
    → decide again → ... → stop when the outcome is met

"Edit this video — cut it down" died as a question for exactly that
reason: she cannot ask how long the video is and then decide, because
there is no "and then". One compile, one shot, no observation.

This module is the loop. Each ROUND re-reads the world (a fresh
situational snapshot, so a file written in round 1 is visible in round 2),
re-compiles against the goal AND everything that has happened so far, runs
the steps that survive screening, and records what came back. It stops
when the planner answers instead of planning, when nothing is left it may
do, when a question genuinely needs him, or when a bound is hit.

WHAT THIS DOES NOT WIDEN — every one of these is inherited, not
re-implemented, because a loop that re-derived its own permissions would
be a way around them:

- money: `agenda.refuse_money` runs on every plan and every step. There is
  no flag, here or anywhere, that turns it off;
- self-authorization: `agenda.FORBIDDEN_KINDS` still refuses approve,
  deny, halt, resume, intent, rule and dispatch;
- gates: every step executes through `intercom.execute_command`, the same
  door voice and the Command Center use, so operator_always stays
  operator_always;
- HALT: re-read before every round and before every step. A loop that
  checked once at the top would keep working for an hour after he said
  stop;
- the mission budget: re-read every round, and each round spends from it.

WHAT IT ADDS is bounded persistence, and the bounds are the interesting
part: a round ceiling, a step ceiling, a stop after two consecutive
rounds that achieve nothing, and a stop when a command repeats verbatim —
because an agent that runs `file_list` forty times has not been
persistent, it has hung. One barren round is deliberately survivable: a
failure is information the next round should act on (§31).
"""
from __future__ import annotations

import argparse
import json
import sys

from aletheia import (agenda, intercom, journal, mission, notifications,
                      planner, policy, stateio)
from aletheia.fleet import load_fleet

ACTOR = "aletheia-pursue"

MAX_GOAL_CHARS = 2_000
MAX_ROUNDS = 6
MAX_STEPS_PER_ROUND = 6
MAX_STEPS_TOTAL = 24
# Consecutive do-nothing rounds tolerated. One is a failure to learn from;
# two in a row is a pattern worth stopping on.
BARREN_ROUNDS = 2
# What the next round is told about the last ones. Bounded because it goes
# into a prompt: enough to decide with, never a transcript.
MAX_HISTORY_CHARS = 2_400
MAX_DETAIL_CHARS = 220

DONE = "DONE"                      # the planner answered instead of planning
NEEDS_OPERATOR = "NEEDS_OPERATOR"  # a real question only he can settle
BLOCKED = "BLOCKED"                # a capability gap stands in the way
STALLED = "STALLED"                # a round achieved nothing, or repeated itself
EXHAUSTED = "EXHAUSTED"            # out of rounds, steps, or mission budget
HALTED = "HALTED"


class PursuitError(RuntimeError):
    pass


def _signature(command: dict) -> str:
    return json.dumps(command, sort_keys=True, ensure_ascii=False)[:400]


def _history_block(rounds: list[dict]) -> str:
    """What has happened, newest last, trimmed to fit a prompt."""
    lines = []
    for record in rounds:
        for entry in record["ran"]:
            detail = entry["detail"].replace("\n", " ")[:MAX_DETAIL_CHARS]
            lines.append(f"- {entry['kind']}: {entry['outcome']}"
                         + (f" — {detail}" if detail else ""))
        for entry in record["refused"]:
            lines.append(f"- {entry.get('kind')}: REFUSED — {entry['reason'][:MAX_DETAIL_CHARS]}")
    if not lines:
        return ""
    block = "\n".join(lines)
    while len(block) > MAX_HISTORY_CHARS and lines:
        lines.pop(0)              # drop the OLDEST, keep what just happened
        block = "\n".join(lines)
    return block


def _request_for(goal: str, rounds: list[dict]) -> str:
    """The goal, plus what has already been done about it."""
    history = _history_block(rounds)
    if not history:
        return goal
    return (
        f"{goal}\n\n--- what you have already done toward this, in order ---\n"
        f"{history}\n\n"
        "Plan only what is STILL needed. If the outcome above is already "
        'achieved, answer instead of planning: {"intent": "answer", '
        '"summary": "<what was accomplished>"}. Do not repeat a step that '
        "already succeeded.")


def pursue(goal: str, *, fleet: dict | None = None, executor=None,
           rounds: int = MAX_ROUNDS, require_mission: bool = True,
           on_round=None) -> dict:
    """Work one outcome in rounds. Returns a record of everything that ran."""
    goal = str(goal or "").strip()
    if not goal or len(goal) > MAX_GOAL_CHARS:
        raise ValueError(f"goal must be 1..{MAX_GOAL_CHARS} characters")
    if type(rounds) is not int or not 1 <= rounds <= MAX_ROUNDS:
        raise ValueError(f"rounds must be 1..{MAX_ROUNDS}")
    policy.ensure_not_halted()
    if require_mission and not mission.covers("agenda.execute"):
        running = mission.active()
        raise PursuitError(
            f"the running mission is {running['kind']!r}, which does not cover this"
            if running else
            "no mission is running — `python -m aletheia.mission start anything` "
            "authorizes a budget for working a goal without asking at every step")

    fleet = fleet if fleet is not None else load_fleet()
    executor = executor or intercom.execute_command
    history: list[dict] = []
    seen: set[str] = set()
    steps_run = 0
    barren = 0        # consecutive rounds that achieved nothing
    state, note, answer = EXHAUSTED, "", ""

    for number in range(1, rounds + 1):
        policy.ensure_not_halted()
        if require_mission and not mission.covers("agenda.execute"):
            state, note = EXHAUSTED, "the mission's budget ran out"
            break

        # A FRESH snapshot each round: the point of looking again is that
        # the world moved — a file she wrote in round 1 is in the workspace
        # listing in round 2, and a task she filed is in NOW.
        plan = planner.compile(_request_for(goal, history), fleet=fleet)

        if plan.intent == "answer":
            state, answer = DONE, plan.summary
            break
        if plan.intent == "clarify":
            state, note = NEEDS_OPERATOR, plan.summary
            break

        runnable, refused = agenda.screen(plan)
        runnable = runnable[:MAX_STEPS_PER_ROUND]
        if not runnable:
            gaps = [s for s in plan.steps if s.status == planner.GAP]
            if gaps:
                state = BLOCKED
                note = "; ".join(f"{s.capability} ({s.detail})" for s in gaps[:3])[:400]
            else:
                state = DONE if history else STALLED
                note = plan.summary or "nothing further to do"
            history.append({"round": number, "summary": plan.summary,
                            "ran": [], "refused": refused})
            break

        record = {"round": number, "summary": plan.summary, "ran": [], "refused": refused}
        progressed = False
        for step in runnable:
            policy.ensure_not_halted()
            if steps_run >= MAX_STEPS_TOTAL:
                record["refused"].append({"step": step.n, "kind": step.command["kind"],
                                          "reason": f"the {MAX_STEPS_TOTAL}-step ceiling for one goal"})
                state, note = EXHAUSTED, "the step ceiling for one goal was reached"
                break
            signature = _signature(step.command)
            if signature in seen:
                # Repeating a command verbatim is not persistence, it is a
                # loop. Stop and say so rather than burning his budget.
                record["refused"].append({"step": step.n, "kind": step.command["kind"],
                                          "reason": "already run verbatim this pursuit"})
                state, note = STALLED, f"it repeated {step.command['kind']} without new information"
                break
            seen.add(signature)
            agenda.refuse_money([step.capability] if step.capability else [])
            try:
                result = executor(step.command, fleet)
                if isinstance(result, dict):
                    outcome = str(result.get("outcome") or "done")
                    detail = str(result.get("detail") or "")
                else:
                    outcome, detail = "done", str(result or "")
            except policy.Halted:
                raise
            except intercom.Unavailable as exc:
                outcome, detail = "unavailable", str(exc)
            except Exception as exc:
                outcome, detail = "failed", f"{type(exc).__name__}: {exc}"
            steps_run += 1
            if outcome not in ("failed", "unavailable"):
                progressed = True
            record["ran"].append({"step": step.n, "kind": step.command["kind"],
                                  "outcome": outcome, "detail": detail[:MAX_DETAIL_CHARS]})

        history.append(record)
        if on_round:
            on_round(record)
        if state in (STALLED, EXHAUSTED) and note:
            break
        barren = barren + 1 if not progressed else 0
        if barren >= BARREN_ROUNDS:
            # ONE failed round is information, not a dead end: "the file is
            # locked" is exactly what should change the next attempt, and
            # §31 says failures are normal and recoverable. Two in a row is
            # a pattern, and the repeat guard already stops it retrying the
            # identical command in the meantime.
            state, note = STALLED, f"{barren} rounds in a row achieved nothing"
            break
    else:
        state, note = EXHAUSTED, f"{rounds} rounds were not enough"

    return _finish(goal, state, note, answer, history, steps_run)


def _finish(goal: str, state: str, note: str, answer: str,
            history: list[dict], steps_run: int) -> dict:
    done = sum(1 for r in history for e in r["ran"]
               if e["outcome"] not in ("failed", "unavailable"))
    record = {
        "goal": goal, "state": state, "note": note, "answer": answer,
        "rounds": history, "steps_run": steps_run, "steps_succeeded": done,
        "at": stateio.utcnow(),
    }
    mission.note(f"pursue: {goal[:80]} — {state} after {steps_run} step(s)", spent=1)
    journal.append("action", "pursue",
                   f"{goal[:100]} — {state}, {done}/{steps_run} step(s) over "
                   f"{len(history)} round(s)", actor=ACTOR)
    try:
        notifications.publish(
            f"{state}: {goal[:60]}", spoken(record)[:400], priority="NORMAL",
            source="pursue", dedupe_key=f"pursue:{record['at']}:{goal[:40]}")
    except Exception:
        pass
    return record


def spoken(record: dict) -> str:
    """What she says back — the outcome, not the machinery."""
    state = record["state"]
    if state == DONE:
        return record["answer"] or f"Done — {record['steps_succeeded']} step(s)."
    if state == NEEDS_OPERATOR:
        return f"I need one thing from you: {record['note']}"
    if state == BLOCKED:
        return f"I got as far as I can. What stops me: {record['note']}"
    if state == HALTED:
        return "Stopped — you halted me."
    plural = "" if record["steps_succeeded"] == 1 else "s"
    return (f"I did {record['steps_succeeded']} step{plural} and stopped: "
            f"{record['note'] or 'no further progress'}.")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Give her an outcome; she works it until it is done.")
    ap.add_argument("goal")
    ap.add_argument("--rounds", type=int, default=MAX_ROUNDS)
    ap.add_argument("--no-mission", action="store_true",
                    help="one goal without a mission budget — for when you are watching")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    try:
        record = pursue(args.goal, rounds=args.rounds,
                        require_mission=not args.no_mission,
                        on_round=lambda r: print(
                            f"  round {r['round']}: {r['summary'][:90]}",
                            file=sys.stderr))
    except Exception as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(record, indent=2))
        return 0
    print(spoken(record))
    for r in record["rounds"]:
        for entry in r["ran"]:
            print(f"  {r['round']}.{entry['step']} {entry['kind']}: {entry['outcome']}"
                  + (f" — {entry['detail']}" if entry["detail"] else ""))
        for entry in r["refused"]:
            print(f"  {r['round']}.{entry.get('step', '-')} {entry.get('kind')} "
                  f"REFUSED — {entry['reason']}")
    return 0 if record["state"] in (DONE, NEEDS_OPERATOR, BLOCKED) else 2


if __name__ == "__main__":
    raise SystemExit(main())
