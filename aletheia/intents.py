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

from aletheia import journal, planner, policy, stateio
from aletheia.fleet import load_fleet

ACTOR = "aletheia-intent"
PROPOSED, EXECUTED, RETIRED, FAILED = "PROPOSED", "EXECUTED", "RETIRED", "FAILED"


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
            continue  # a corrupt record is not an authorization
        if state is None or record.get("state") == state:
            out.append(record)
    return out


def propose(request: str, quote: str = "", fleet: dict | None = None,
            materialize: bool = True, **compile_kw) -> dict:
    """Compile a sentence into a plan, persist it, and ask for it.

    Returns the record. Nothing has run when this returns — deliberately.
    """
    fleet = fleet if fleet is not None else load_fleet()
    plan = planner.compile(request, fleet=fleet, **compile_kw)
    digest = plan_hash(plan)
    intent_id = f"intent-{digest[:10]}"
    approval_id = intent_id

    gap_tasks: list[str] = []
    if materialize:
        try:
            gap_tasks = planner.materialize_gaps(plan)
        except Exception as exc:  # a gap that could not be filed is not a
            journal.append("event", "intent",  # reason to lose the plan
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
    stateio.write_json_atomic(_record_path(intent_id), record)

    if plan.executable:
        policy.request(
            approval_id,
            requested_action=f"run {len(plan.executable)} step(s): "
                             + ", ".join(s.command["kind"] for s in plan.executable),
            reason=f'operator said: "{(quote or request)[:200]}"',
            consequence=plan.summary or "see the plan",
            reversible=False, capability="intent.execute")
    journal.append("plan", "intent",
                   f"{intent_id}: {len(plan.executable)} executable, "
                   f"{len(plan.blocked)} blocked — {plan.summary or request[:120]}",
                   actor=ACTOR)
    return record


def spoken(record: dict) -> str:
    """What Thea says back. Short, honest about what is and is not happening."""
    runnable = [s for s in record["steps"] if s["status"] == planner.EXECUTABLE]
    gaps_named = [s for s in record["steps"] if s["status"] == planner.GAP]
    manual = [s for s in record["steps"] if s["status"] == planner.MANUAL]
    refused = [s for s in record["steps"] if s["status"] == planner.REFUSED]
    # Degradation is checked FIRST. The deterministic fallback also reports
    # intent "clarify", and answering a failed provider with a polite
    # "could you clarify?" would hide an outage behind a conversational tic.
    if record.get("degraded") and not runnable:
        return f"I could not plan that: {record['degraded'][:160]}"
    if record.get("intent") == "clarify":
        return record.get("summary") or "I need one thing cleared up before I plan that."
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

    Called from the Core's runtime tick. Idempotent by state transition:
    a record leaves PROPOSED before its receipts are written, so a crash
    mid-plan cannot replay the steps that already ran.
    """
    fleet = fleet if fleet is not None else load_fleet()
    done: list[dict] = []
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

        # Re-derive the fingerprint from what is stored NOW. An approval
        # authorized one exact plan; anything else is refused, not adapted.
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
        record["state"] = EXECUTED
        record["executed_at"] = stateio.utcnow()
        stateio.write_json_atomic(_record_path(record["id"]), record)
        receipts = planner.execute(plan, fleet=fleet,
                                   quote=record.get("operator_quote", ""),
                                   executor=executor)
        record["receipts"] = receipts
        if any(r["outcome"] not in ("done",) for r in receipts):
            record["state"] = FAILED
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
    p_list.add_argument("--state", choices=[PROPOSED, EXECUTED, RETIRED, FAILED])
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
