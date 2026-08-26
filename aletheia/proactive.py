"""Bounded proactive rules with cooldown and dedupe receipts.

Rules consume plain event dictionaries and produce *proposals* such as surface,
notify, or enqueue. They never execute the proposed action. Existing policy and
capability gates remain authoritative.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path

from aletheia.fleet import REPO_ROOT
from aletheia.stateio import create_json_exclusive, read_json, safe_id, utcnow, write_json_atomic

RULES_DIR = REPO_ROOT / "state" / "proactive" / "rules"
RECEIPTS_DIR = REPO_ROOT / "state" / "proactive" / "receipts"
ACTIONS = {"surface", "notify", "enqueue"}


def _path(rule_id: str) -> Path:
    return RULES_DIR / f"{safe_id(rule_id, name='rule id')}.json"


def create_rule(rule_id: str, *, event_kind: str, action: str,
                source: str | None = None, subject_prefix: str | None = None,
                cooldown_minutes: int = 0, persistent: bool = True) -> dict:
    if action not in ACTIONS:
        raise ValueError(f"action must be one of {sorted(ACTIONS)}")
    if cooldown_minutes < 0:
        raise ValueError("cooldown must be non-negative")
    if _path(rule_id).exists():
        raise FileExistsError(rule_id)
    if not event_kind:
        raise ValueError("event_kind is required")
    value = {"version": 1, "id": rule_id, "event_kind": event_kind, "action": action,
             "cooldown_minutes": cooldown_minutes, "persistent": bool(persistent),
             "enabled": True, "created_at": utcnow()}
    if source:
        value["source"] = source
    if subject_prefix:
        value["subject_prefix"] = subject_prefix
    write_json_atomic(_path(rule_id), value)
    return value


def matches(rule: dict, event: dict) -> bool:
    if not rule.get("enabled", False):
        return False
    if event.get("kind") != rule.get("event_kind"):
        return False
    if rule.get("source") and event.get("source") != rule["source"]:
        return False
    if rule.get("subject_prefix") and not str(event.get("subject", "")).startswith(rule["subject_prefix"]):
        return False
    return True


def _receipt_root(rule_id: str) -> Path:
    return RECEIPTS_DIR / safe_id(rule_id, name="rule id")


def _receipts(rule_id: str) -> list[dict]:
    root = _receipt_root(rule_id)
    if not root.is_dir():
        return []
    out = []
    for p in root.glob("*.json"):
        try:
            out.append(read_json(p))
        except ValueError:
            continue
    return sorted(out, key=lambda r: r.get("triggered_at", ""), reverse=True)


def evaluate(rule: dict, event: dict, *, now: dt.datetime | None = None) -> dict | None:
    if not matches(rule, event):
        return None
    event_id = safe_id(str(event.get("id", "")), name="event id")
    now = now or dt.datetime.now(dt.timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    event_receipt = _receipt_root(rule["id"]) / f"{event_id}.json"
    if event_receipt.exists():
        return None
    prior = _receipts(rule["id"])
    cooldown = dt.timedelta(minutes=rule.get("cooldown_minutes", 0))
    if cooldown and prior:
        last = dt.datetime.fromisoformat(prior[0]["triggered_at"].replace("Z", "+00:00"))
        if now.astimezone(dt.timezone.utc) - last.astimezone(dt.timezone.utc) < cooldown:
            return None
    receipt = {"version": 1, "rule_id": rule["id"], "event_id": event_id,
               "action": rule["action"],
               "triggered_at": now.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
               "proposal": {"kind": rule["action"], "event_id": event_id}}
    create_json_exclusive(event_receipt, receipt)
    return receipt


def all_rules() -> list[dict]:
    if not RULES_DIR.is_dir():
        return []
    out = []
    for p in sorted(RULES_DIR.glob("*.json")):
        try:
            out.append(read_json(p))
        except ValueError:
            continue
    return out
