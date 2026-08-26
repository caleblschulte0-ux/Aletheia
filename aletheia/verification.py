"""Capability-aware ActionRecord helpers and durable receipt reconciliation.

`outcomes.py` remains the evidence store. This module adds capability-specific
verification profiles that distinguish execution proof from outcome proof, then
reconciles facts that existing adapters already persist (mail receipts, UIA and
browser journal records, agent task state) into private ActionRecords. It never
changes an execution gate or grants authority.
"""
from __future__ import annotations

import hashlib
import json
import re
import uuid

from aletheia import outcomes

PROFILES = {
    "computer.control": {"auto_verify_execution": True,"execution_evidence": "backend read-back/step verification","outcome_evidence": "the approved desktop plan itself is the bounded outcome"},
    "calendar.write": {"auto_verify_execution": True,"execution_evidence": "provider returned normalized state matching the approved plan","outcome_evidence": "provider state matches requested calendar state"},
    "browser.interact": {"auto_verify_execution": False,"execution_evidence": "approved browser steps completed","outcome_evidence": "site state proves the user's intended result"},
    "email.send": {"auto_verify_execution": False,"execution_evidence": "SMTP accepted the message and local exactly-once receipt exists","outcome_evidence": "delivery/receipt evidence or another independently observed result"},
    "automation.execute": {"auto_verify_execution": False,"execution_evidence": "occurrence claimed exactly once and command returned done","outcome_evidence": "the scheduled command's intended external result is independently observed"},
    "agent.delegate": {"auto_verify_execution": False,"execution_evidence": "work order created and task parked WAITING_EXTERNAL","outcome_evidence": "worker completes the task with evidence accepted by the orchestrator"},
}


def profile(capability: str) -> dict:
    return dict(PROFILES.get(capability, {"auto_verify_execution": False,"execution_evidence": "capability returned without exception","outcome_evidence": "independent evidence of the intended result"}))


def _digest(value: object) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def new_action_id(capability: str, *, seed: object | None = None) -> str:
    prefix = capability.replace(".", "-")[:30]
    suffix = _digest(seed)[:16] if seed is not None else uuid.uuid4().hex[:16]
    return f"verify-{prefix}-{suffix}"[:64]


def begin(capability: str, *, provider: str, intent: str, plan: dict,
          requested_by: str = "operator", approval_id: str | None = None,
          policy_decision: str | None = None, reversible: bool | None = None,
          inputs_summary: str = "", data_disclosed: list[str] | None = None,
          action_id: str | None = None) -> dict:
    action_id = action_id or new_action_id(capability)
    try:
        existing = outcomes.load(action_id)
    except (FileNotFoundError, ValueError):
        existing = None
    if existing is not None:
        if existing["capability"] != capability or existing["plan_sha256"] != _digest(plan):
            raise ValueError("existing verification action does not match requested plan")
        return existing
    return outcomes.start(action_id, capability=capability, provider=provider, intent=intent, plan=plan,
                          requested_by=requested_by, approval_id=approval_id,
                          policy_decision=policy_decision, reversible=reversible,
                          inputs_summary=inputs_summary, data_disclosed=data_disclosed)


def record_execution(action_id: str, *, succeeded: bool, result_summary: str,
                     evidence: list[dict] | None = None,
                     failure_terminal: bool = False,
                     auto_verify: bool | None = None) -> dict:
    value = outcomes.load(action_id)
    if value["status"] in outcomes.TERMINAL:
        return value
    if value["status"] in {"STARTED", "FAILED_RETRYABLE"}:
        outcomes.add_attempt(action_id,
            outcome="SUCCEEDED" if succeeded else ("FAILED_TERMINAL" if failure_terminal else "FAILED_RETRYABLE"),
            result_summary=result_summary)
    if not succeeded:
        return outcomes.load(action_id)
    for item in evidence or []:
        eid = item.get("id") or f"ev-{len(outcomes.load(action_id)['evidence']) + 1}"
        current = outcomes.load(action_id)
        if any(e.get("id") == eid for e in current["evidence"]):
            continue
        outcomes.add_evidence(action_id, eid, kind=item["kind"], observed=item.get("observed"),
                              expected=item.get("expected"), source=item.get("source", "local"))
    current = outcomes.load(action_id)
    should_verify = profile(current["capability"])["auto_verify_execution"] if auto_verify is None else auto_verify
    if should_verify and current["status"] == "AWAITING_VERIFICATION" and current["evidence"]:
        return outcomes.verify(action_id)
    return current


def execution_record(capability: str, *, provider: str, intent: str, plan: dict,
                     succeeded: bool, result_summary: str,
                     evidence: list[dict] | None = None,
                     requested_by: str = "operator", approval_id: str | None = None,
                     policy_decision: str | None = None, reversible: bool | None = None,
                     inputs_summary: str = "", data_disclosed: list[str] | None = None,
                     action_id: str | None = None,
                     auto_verify: bool | None = None,
                     failure_terminal: bool = False) -> dict:
    record = begin(capability, provider=provider, intent=intent, plan=plan,
                   requested_by=requested_by, approval_id=approval_id,
                   policy_decision=policy_decision, reversible=reversible,
                   inputs_summary=inputs_summary, data_disclosed=data_disclosed,
                   action_id=action_id)
    return record_execution(record["id"], succeeded=succeeded, result_summary=result_summary,
                            evidence=evidence, auto_verify=auto_verify,
                            failure_terminal=failure_terminal)


def reconcile_mail_receipts() -> list[dict]:
    from aletheia import mail, policy
    if not mail.MAIL_DIR.is_dir():
        return []
    out = []
    for receipt_path in sorted(mail.MAIL_DIR.glob("mail-*.sent.json")):
        try:
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            draft_id = receipt["id"]
            approval = policy.load(draft_id)
        except (OSError, json.JSONDecodeError, KeyError, ValueError):
            continue
        plan = {"draft_id": draft_id, "approved_action": approval.get("requested_action", "")}
        aid = new_action_id("email.send", seed=plan)
        try:
            value = execution_record(
                "email.send", provider="smtp", intent=f"send approved email {draft_id}", plan=plan,
                succeeded=receipt.get("outcome") == "sent", result_summary=receipt.get("detail", ""),
                evidence=[{"id":"sent-receipt","kind":"truthy","observed":receipt.get("outcome") == "sent","source":"mail receipt"}],
                requested_by="operator", approval_id=draft_id,
                policy_decision=approval.get("state"), reversible=False,
                action_id=aid, auto_verify=False,
            )
            out.append({"capability":"email.send","action_record":value["id"],"status":value["status"]})
        except ValueError:
            continue
    return out


def reconcile_computer_journal() -> list[dict]:
    from aletheia import journal, policy
    out = []
    pattern = re.compile(r"^COMPLETED run=(\S+) approval=(\S+) steps=(\d+)$")
    for entry in journal.entries():
        if entry.get("subject") != "computer:run":
            continue
        match = pattern.match(str(entry.get("text", "")))
        if not match:
            continue
        run_id, approval_id, steps = match.groups()
        try:
            approval = policy.load(approval_id)
        except Exception:
            continue
        plan = {"run_id": run_id, "approval_action": approval.get("requested_action", ""), "steps": int(steps)}
        aid = new_action_id("computer.control", seed=plan)
        try:
            value = execution_record(
                "computer.control", provider="windows-uia", intent=f"approved desktop run {run_id}", plan=plan,
                succeeded=True, result_summary=entry["text"],
                evidence=[{"id":"computer-completed","kind":"truthy","observed":True,"source":"computer journal"}],
                requested_by="operator", approval_id=approval_id,
                policy_decision=approval.get("state"), reversible=True, action_id=aid,
            )
            out.append({"capability":"computer.control","action_record":value["id"],"status":value["status"]})
        except ValueError:
            continue
    return out


def reconcile_browser_journal() -> list[dict]:
    from aletheia import journal
    out = []
    for entry in journal.entries():
        if entry.get("subject") != "browser:interact":
            continue
        text = str(entry.get("text", ""))
        plan = {"journal_ts":entry.get("ts", ""), "execution_summary":text}
        aid = new_action_id("browser.interact", seed=plan)
        try:
            value = execution_record(
                "browser.interact", provider="playwright", intent="approved browser interaction", plan=plan,
                succeeded=True, result_summary=text,
                evidence=[{"id":"browser-executed","kind":"truthy","observed":True,"source":"browser journal"}],
                requested_by="operator", reversible=False, action_id=aid, auto_verify=False,
            )
            out.append({"capability":"browser.interact","action_record":value["id"],"status":value["status"]})
        except ValueError:
            continue
    return out


def reconcile_agent_tasks() -> list[dict]:
    from aletheia import tasks
    out=[]
    for task in tasks.all_tasks():
        result=str(task.get("result", ""))
        if task.get("status") not in {"WAITING_EXTERNAL", "COMPLETED"} or "work order issue #" not in result:
            continue
        plan={"task_id":task["id"],"worker":task.get("assigned_worker", ""),"work_order":result}
        aid=new_action_id("agent.delegate",seed=plan)
        try:
            value=execution_record(
                "agent.delegate",provider="github.actions",intent=f"delegate task {task['id']}",plan=plan,
                succeeded=True,result_summary=result,
                evidence=[{"id":"work-order","kind":"truthy","observed":True,"source":"task state"}],
                requested_by="operator",reversible=True,action_id=aid,auto_verify=False)
            if task.get("status") == "COMPLETED" and str(task.get("result", "")).strip() and value["status"] == "AWAITING_VERIFICATION":
                # The task engine's COMPLETED+result is the existing evidence contract
                # for delegated work; add it as outcome evidence and verify.
                try:
                    outcomes.add_evidence(value["id"],"worker-result",kind="truthy",observed=True,source="task completion")
                    value=outcomes.verify(value["id"])
                except (ValueError, FileExistsError):
                    value=outcomes.load(value["id"])
            out.append({"capability":"agent.delegate","action_record":value["id"],"status":value["status"]})
        except ValueError:
            continue
    return out


def reconcile_durable_receipts() -> list[dict]:
    out=[]
    for fn in (reconcile_mail_receipts,reconcile_computer_journal,reconcile_browser_journal,reconcile_agent_tasks):
        out.extend(fn())
    return out
