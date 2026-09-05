"""Arbitrary asks, made durable and approvable (Playbook §27, §56, §97).

`aletheia.planner` can turn a sentence into a gated plan. This is what
happens to that plan afterwards, and it is the difference between a party
trick and a personal OS: the plan is PERSISTED, it is bound to an approval
by a hash of itself, and the Core executes it later — after the
conversation that produced it has ended, which is where real work lives.

The approval binding is the pattern already ratified for computer control
and for email: the approval carries a sha256 of the exact plan. Approving
authorizes THAT plan and no other. If anything about it changes between
the ask and the approval — a step edited, a capability that went missing,
the registry rewritten — the hash no longer matches and execution is
refused rather than adapted. "Approve" is never a blank cheque on a
sentence Aletheia has since reinterpreted.

Nothing here widens authority. Every step still runs through
`intercom.execute_command` and the gates behind it; halt is re-read before
each one. What this adds is only the ability for the thing being gated to
have come from a sentence instead of from a slot.

Private storage: an intent record contains the operator's own words.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import threading

from aletheia import intercom, journal, planner, policy, quick, stateio
from aletheia.fleet import load_fleet

ACTOR = "aletheia-intent"
PROPOSED, RUNNING, EXECUTED, RETIRED, FAILED, INTERRUPTED = (
    "PROPOSED", "RUNNING", "EXECUTED", "RETIRED", "FAILED", "INTERRUPTED")
_RUN_LOCK = threading.Lock()


def intents_dir():
    return stateio.private_dir("intents")


def plan_hash(plan: planner.Plan) -> str:
    """A fingerprint of exactly what would run.

    Only the executable steps, in order, with their full arguments. The
    summary is prose and may be reworded without changing what happens;
    the commands are the thing being authorized.
    """
    material = [{"n": s.n, "command": s.command} for s in plan.executable]
    raw = json.dumps(material, sort_keys=True, separators=(",", ":"),
                     ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _record_path(intent_id: str):
    return intents_dir() / f"{stateio.safe_id(intent_id, name='intent id')}.json"


def load(intent_id: str) -> dict:
    return stateio.read_json(_record_path(intent_id))


def all_intents(state: str | None = None) -> list[dict]:
    out = []
    directory = intents_dir()
    if not directory.is_dir():
        return out
    for path in sorted(directory.glob("*.json")):
        try:
            record = stateio.read_json(path)
        except ValueError:
            continue
        if state is None or record.get("state") == state:
            out.append(record)
    return out


def read_only(plan: planner.Plan) -> bool:
    """Does this plan only look at things?

    Found in real use: the room mic hears a half-sentence, the planner
    turns it into "report current operational status", and that files a
    durable intent AND an operator_always approval. Eight of them
    accumulated in a day — "acknowledge operator's remark; no action
    required" sitting in his queue waiting to be authorised.

    A plan that only reads is answered on the spot. Approvals are for
    things that change the world; spending his attention on anything else
    is what teaches him to stop reading the queue.
    """
    steps = plan.executable
    return bool(steps) and all(
        s.command["kind"] in intercom.READ_ONLY_KINDS for s in steps)


def propose(request: str, quote: str = "", fleet: dict | None = None,
            materialize: bool = True, **compile_kw) -> dict:
    """Compile a sentence into a plan, persist it, and ask for it.

    A strict ChatGPT direct-work envelope is the one exception: it is already a
    typed plan produced outside the PC, is bound to the original operator quote,
    contains no arbitrary typed/private text, and executes only through an
    explicitly active local Work Session. Routing it here means ChatGPT can use
    the existing `intent` intercom kind without depending on the Claude CLI
    planner while that provider is unavailable.

    Ordinary requests follow the durable planner path below unchanged.
    """
    from aletheia import work_direct
    if work_direct.is_direct(request):
        return work_direct.execute(request, quote=quote)

    # AN ANSWER SHE ALREADY HAS COSTS A FILE READ. Measured 2026-09-05: a
    # `claude -p` round trip is ~3.6s whether the answer is one word or
    # nine thousand characters, and "are you halted?" was paying it TWICE
    # — once for the planner to decide it was a question, once for
    # `converse` to answer it. Seven seconds for a boolean on the same
    # disk. `quick` reads the same stores the wall does and returns None
    # for anything it is not certain about, so this only ever removes
    # latency; it can never remove an answer.
    fast = quick.answer(request)
    if fast:
        return {"id": f"intent-quick-{hashlib.sha256(request.encode()).hexdigest()[:8]}",
                "state": RETIRED, "request": request,
                "operator_quote": quote or request,
                "summary": fast, "intent": "answer", "spoken": fast,
                "read_only": True, "fast_path": True, "steps": [],
                "proposed_at": stateio.utcnow()}

    fleet = fleet if fleet is not None else load_fleet()
    plan = planner.compile(request, fleet=fleet, **compile_kw)
    digest = plan_hash(plan)
    intent_id = f"intent-{digest[:10]}"
    approval_id = intent_id

    # What he asked for and could not have, counted in his own words. A gap
    # named on Tuesday and the same gap on Friday were indistinguishable:
    # `materialize_gaps` files a build task the first time and then quietly
    # does nothing, so a capability asked for eleven times and one mentioned
    # once looked identical on the task list forever.
    try:
        from aletheia import demand
        demand.record_plan(plan, request)
    except Exception:
        pass

    gap_tasks: list[str] = []
    if materialize:
        try:
            gap_tasks = planner.materialize_gaps(plan)
        except Exception as exc:
            journal.append("event", "intent",
                           f"could not materialize gaps: {type(exc).__name__}: {exc}",
                           actor=ACTOR)

    record = {
        "id": intent_id,
        "state": PROPOSED,
        "request": request,
        "operator_quote": quote or request,
        "summary": plan.summary,
        "intent": plan.intent,
        "plan_sha256": digest,
        "approval": approval_id,
        "provider": plan.provider,
        "degraded": plan.degraded,
        "steps": [{"n": s.n, "status": s.status, "detail": s.detail,
                   "command": s.command, "capability": s.capability}
                  for s in plan.steps],
        "gap_tasks": gap_tasks,
        "proposed_at": stateio.utcnow(),
    }
    if read_only(plan):
        receipts = planner.execute(plan, fleet=fleet, quote=quote or request)
        record["state"] = EXECUTED
        record["receipts"] = receipts
        record["read_only"] = True
        journal.append("action", "intent",
                       f"answered on the spot (read-only): {plan.summary[:120]}",
                       actor=ACTOR)
        return record
    if not plan.executable and plan.intent in ("answer", "clarify"):
        # HE ASKED A QUESTION. Until 2026-09-03 this retired the record and
        # spoken() fell through to plan.summary — a one-line restatement of
        # what he had just said. She was an executor with no mouth: ask her
        # anything a person asks an assistant and she handed back a gist.
        # A question now gets a real answer, from the same subscription
        # everything else runs on. Nothing is executed here.
        record["state"] = RETIRED
        record["read_only"] = True
        if plan.intent == "clarify":
            # A clarifying question is ALREADY the right thing to say. Sending
            # it through converse turned "Which sister — Ana or Mia?" into a
            # paragraph about ambiguity, which is worse in every way. Only a
            # question he asked gets answered here.
            return record
        from aletheia import converse
        try:
            record["spoken"] = converse.answer(request)["answer"]
        except converse.ConverseError as exc:
            # Its message already names the real reason and the fix ("Claude
            # CLI is not on PATH"). Rewriting that into a class name is how
            # an actionable failure becomes a shrug.
            record["spoken"] = str(exc)
        except Exception as exc:
            # An unreachable model must not turn into silence: say which
            # half failed, because "she said nothing" and "she could not
            # think" are different problems with different fixes.
            record["spoken"] = (
                f"I couldn't reach a model to answer that ({type(exc).__name__}). "
                "Everything else still works.")
        return record
    stateio.write_json_atomic(_record_path(intent_id), record)

    if plan.executable and not read_only(plan):
        kinds = [s.command["kind"] for s in plan.executable]
        tier = intercom.plan_tier(kinds)
        record["tier"] = tier
        capability = ("intent.execute.routine" if tier == intercom.TIER_ROUTINE
                      else "intent.execute")
        approval = policy.request(
            approval_id,
            requested_action=f"run {len(plan.executable)} step(s): " + ", ".join(kinds),
            reason=f'operator said: "{(quote or request)[:200]}"',
            consequence=plan.summary or "see the plan",
            reversible=tier == intercom.TIER_ROUTINE, capability=capability)
        record["approval_state"] = approval.get("state")
    journal.append("plan", "intent",
                   f"{intent_id}: {len(plan.executable)} executable, "
                   f"{len(plan.blocked)} blocked — {plan.summary or request[:120]}",
                   actor=ACTOR)
    return record


def spoken(record: dict) -> str:
    """What Thea says back. Short, honest about what is and is not happening."""
    # A real answer, when the ask was a QUESTION, beats every summary below.
    # Narrow on purpose: `clarify` and the degraded no-provider case keep
    # their own wording, which is already the right thing to say.
    if record.get("intent") == "answer" and record.get("spoken"):
        return str(record["spoken"])
    if record.get("direct_work"):
        return str(record.get("spoken") or record.get("summary") or "Work action completed.")[:600]

    runnable = [s for s in record["steps"] if s["status"] == planner.EXECUTABLE]
    gaps_named = [s for s in record["steps"] if s["status"] == planner.GAP]
    manual = [s for s in record["steps"] if s["status"] == planner.MANUAL]
    refused = [s for s in record["steps"] if s["status"] == planner.REFUSED]
    if record.get("degraded") and not runnable:
        return f"I could not plan that: {record['degraded'][:160]}"
    if record.get("intent") == "clarify":
        return record.get("summary") or "I need one thing cleared up before I plan that."
    if record.get("read_only"):
        answers = [str(r.get("detail", "")).strip()
                   for r in (record.get("receipts") or [])
                   if r.get("outcome") == "done" and str(r.get("detail", "")).strip()]
        if answers:
            return " ".join(answers)[:600]
        return record.get("summary") or "Nothing to do."
    parts = []
    if runnable:
        parts.append(f"{len(runnable)} step{'s' if len(runnable) != 1 else ''} ready — "
                     + ", ".join(s["command"]["kind"] for s in runnable)
                     + f". Say approve to run it ({record['approval']}).")
    if gaps_named:
        parts.append("I can't do "
                     + ", ".join(s["capability"] or "?" for s in gaps_named)
                     + " yet"
                     + (f"; filed {len(record.get('gap_tasks') or [])} build task(s)."
                        if record.get("gap_tasks") else "."))
    if manual:
        parts.append(f"{len(manual)} step{'s' if len(manual) != 1 else ''} only you can do.")
    if refused:
        parts.append(f"{len(refused)} proposed step{'s' if len(refused) != 1 else ''} "
                     "did not survive validation.")
    return " ".join(parts) or "Nothing to do."


def run_approved(fleet: dict | None = None, executor=None) -> list[dict]:
    """Execute every PROPOSED intent whose approval is APPROVED.

    Called from the Core's runtime tick. Each step is durably claimed before it
    runs and receipted immediately afterwards. A run abandoned by a crash is
    recovered from durable terminal receipts when possible. Otherwise it is
    marked INTERRUPTED and never replayed automatically.
    """
    # The periodic Core beat and an immediate HTTP kick can overlap in the
    # same process. Serializing claims prevents one beat from mistaking the
    # other's live RUNNING record for an abandoned process.
    with _RUN_LOCK:
        return _run_approved(fleet, executor)


def _run_approved(fleet: dict | None = None, executor=None) -> list[dict]:
    fleet = fleet if fleet is not None else load_fleet()
    done: list[dict] = []
    for record in all_intents(state=RUNNING):
        receipts = record.get("receipts") or []
        runnable = [s["n"] for s in record.get("steps", [])
                    if s.get("status") == planner.EXECUTABLE]
        receipt_steps = [item.get("n") for item in receipts]
        if (runnable and receipt_steps == runnable
                and all(item.get("outcome") == "done" for item in receipts)):
            record["state"] = EXECUTED
            record["executed_at"] = stateio.utcnow()
            record["recovered_at"] = record["executed_at"]
            detail = "all step receipts were durable; finalized after restart"
        elif receipts and receipts[-1].get("outcome") in ("failed", "halted"):
            record["state"] = FAILED
            record["failed_at"] = stateio.utcnow()
            record["recovered_at"] = record["failed_at"]
            detail = "terminal step receipt was durable; finalized after restart"
        else:
            record["state"] = INTERRUPTED
            record["interrupted_at"] = stateio.utcnow()
            if record.get("current_step") is not None:
                record["interrupted_reason"] = (
                    "execution stopped after the current step was claimed; its "
                    "outcome is unknown; automatic replay is refused")
            else:
                record["interrupted_reason"] = (
                    "execution stopped before the full plan completed; durable "
                    "receipts were preserved; automatic continuation is refused")
            detail = record["interrupted_reason"]
        stateio.write_json_atomic(_record_path(record["id"]), record)
        journal.append("alert" if record["state"] == INTERRUPTED else "event",
                       "intent", f"{record['id']}: {detail}", actor=ACTOR)
        done.append({"intent": record["id"], "outcome": record["state"],
                     "detail": detail})
    for record in all_intents(state=PROPOSED):
        approval_id = record.get("approval")
        if not approval_id:
            continue
        try:
            approval = policy.load(approval_id)
        except (OSError, json.JSONDecodeError, KeyError):
            continue
        if approval.get("state") == "DENIED":
            record["state"] = RETIRED
            record["retired_at"] = stateio.utcnow()
            stateio.write_json_atomic(_record_path(record["id"]), record)
            journal.append("decision", "intent",
                           f"{record['id']} denied — retired", actor=ACTOR)
            done.append({"intent": record["id"], "outcome": "denied"})
            continue
        if approval.get("state") != "APPROVED":
            continue

        runnable = [s for s in record["steps"] if s["status"] == planner.EXECUTABLE]
        material = [{"n": s["n"], "command": s["command"]} for s in runnable]
        digest = hashlib.sha256(json.dumps(
            material, sort_keys=True, separators=(",", ":"),
            ensure_ascii=False).encode("utf-8")).hexdigest()
        if digest != record.get("plan_sha256"):
            record["state"] = FAILED
            record["failed_reason"] = ("the plan changed after it was approved — "
                                       "refusing to run something else")
            stateio.write_json_atomic(_record_path(record["id"]), record)
            journal.append("alert", "intent",
                           f"{record['id']}: plan hash mismatch — refused", actor=ACTOR)
            done.append({"intent": record["id"], "outcome": "refused",
                         "detail": record["failed_reason"]})
            continue

        plan = planner.Plan(
            request=record["request"], summary=record.get("summary", ""),
            intent=record.get("intent", "plan"),
            steps=[planner.PlannedStep(s["n"], s["status"], s["detail"],
                                       s.get("command"), s.get("capability"))
                   for s in record["steps"]])
        record["state"] = RUNNING
        record["started_at"] = stateio.utcnow()
        record["receipts"] = []
        stateio.write_json_atomic(_record_path(record["id"]), record)

        def before_step(step, receipts):
            record["current_step"] = step.n
            record["current_kind"] = step.command["kind"]
            record["receipts"] = list(receipts)
            stateio.write_json_atomic(_record_path(record["id"]), record)

        def after_step(step, receipt, receipts):
            record["receipts"] = list(receipts)
            record["completed_steps"] = sum(
                1 for item in receipts if item.get("outcome") == "done")
            record.pop("current_step", None)
            record.pop("current_kind", None)
            stateio.write_json_atomic(_record_path(record["id"]), record)

        receipts = planner.execute(plan, fleet=fleet,
                                   quote=record.get("operator_quote", ""),
                                   executor=executor, before_step=before_step,
                                   after_step=after_step)
        record["receipts"] = receipts
        record["state"] = (FAILED if any(
            r["outcome"] != "done" for r in receipts) else EXECUTED)
        record["finished_at"] = stateio.utcnow()
        if record["state"] == EXECUTED:
            record["executed_at"] = record["finished_at"]
        stateio.write_json_atomic(_record_path(record["id"]), record)
        done.append({"intent": record["id"], "outcome": record["state"],
                     "receipts": receipts})
    return done


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Durable arbitrary asks.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_new = sub.add_parser("new", help="propose a plan from a sentence")
    p_new.add_argument("request")
    p_new.add_argument("--quote", default="")
    p_list = sub.add_parser("list")
    p_list.add_argument("--state", choices=[
        PROPOSED, RUNNING, EXECUTED, RETIRED, FAILED, INTERRUPTED])
    p_show = sub.add_parser("show")
    p_show.add_argument("id")
    sub.add_parser("run", help="execute every approved intent")
    args = ap.parse_args(argv)

    if args.cmd == "new":
        record = propose(args.request, quote=args.quote)
        print(spoken(record))
        return 0
    if args.cmd == "list":
        rows = all_intents(state=args.state)
        for record in rows:
            print(f"{record['id']}  {record['state']:9}  {record.get('summary', '')[:70]}")
        print(f"{len(rows)} intent(s)", file=sys.stderr)
        return 0
    if args.cmd == "show":
        print(json.dumps(load(args.id), indent=2))
        return 0
    for result in run_approved():
        print(f"{result['intent']}: {result['outcome']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
