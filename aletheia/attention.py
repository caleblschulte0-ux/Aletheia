"""Phase 19 attention policy: quiet hours, deferral and escalation.

Aletheia already has a private notification center. This module answers a
different question: *when is a notice eligible to interrupt the operator?*
It does not send push notifications, execute tasks, or widen authority.

Zero-intrusion defaults:
- quiet hours are disabled until the operator configures them;
- no priority bypasses quiet hours by default;
- no escalation rule exists by default.

Every notification gets a separate private attention record. That keeps the
notification itself an immutable-ish fact while delivery policy can evolve.
Future push providers should consume only ``ready()`` records and call
``mark_delivered`` with provider evidence. The local UI may still show every
notification regardless of attention state.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from aletheia import notifications
from aletheia.stateio import private_dir, read_json, safe_id, utcnow, write_json_atomic

BASE_DIR = private_dir("attention")
POLICY_PATH = BASE_DIR / "policy.json"
DELIVERY_DIR = BASE_DIR / "delivery"

DELIVERY_STATES = {"READY", "DEFERRED", "DELIVERED", "CANCELLED"}
_PRIORITY_ORDER = {"INFO": 0, "NORMAL": 1, "IMPORTANT": 2, "URGENT": 3}


def _parse_iso(value: str) -> dt.datetime:
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError(f"invalid timestamp {value!r}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return parsed


def _parse_clock(value: str, name: str) -> dt.time:
    try:
        parsed = dt.time.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be HH:MM") from exc
    if parsed.tzinfo is not None:
        raise ValueError(f"{name} must not contain a timezone")
    return parsed.replace(second=0, microsecond=0)


def _timezone(value: str) -> ZoneInfo:
    try:
        return ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError(f"unknown timezone {value!r}") from exc


def default_policy() -> dict:
    return {
        "version": 1,
        "quiet_hours": {"enabled": False},
        "bypass_priorities": [],
        "escalations": [],
    }


def validate_policy(value: dict) -> dict:
    if not isinstance(value, dict) or value.get("version") != 1:
        raise ValueError("attention policy must be version 1")
    unknown = set(value) - {"version", "quiet_hours", "bypass_priorities", "escalations", "updated_at"}
    if unknown:
        raise ValueError(f"unsupported attention policy fields: {sorted(unknown)}")
    quiet = value.get("quiet_hours")
    if not isinstance(quiet, dict) or not isinstance(quiet.get("enabled"), bool):
        raise ValueError("quiet_hours.enabled must be boolean")
    quiet_unknown = set(quiet) - {"enabled", "timezone", "start", "end"}
    if quiet_unknown:
        raise ValueError(f"unsupported quiet_hours fields: {sorted(quiet_unknown)}")
    clean_quiet: dict = {"enabled": quiet["enabled"]}
    if quiet["enabled"]:
        timezone = quiet.get("timezone")
        if not isinstance(timezone, str) or not timezone.strip():
            raise ValueError("enabled quiet hours require timezone")
        _timezone(timezone)
        start = _parse_clock(quiet.get("start"), "quiet_hours.start")
        end = _parse_clock(quiet.get("end"), "quiet_hours.end")
        if start == end:
            raise ValueError("quiet hours start and end may not be equal")
        clean_quiet.update({"timezone": timezone.strip(),
                            "start": start.strftime("%H:%M"),
                            "end": end.strftime("%H:%M")})
    bypass = value.get("bypass_priorities", [])
    if not isinstance(bypass, list) or any(p not in notifications.PRIORITIES for p in bypass):
        raise ValueError("bypass_priorities must contain notification priorities")
    if len(set(bypass)) != len(bypass):
        raise ValueError("bypass_priorities must be unique")
    escalations = value.get("escalations", [])
    if not isinstance(escalations, list) or len(escalations) > 4:
        raise ValueError("escalations must contain at most four rules")
    clean_rules = []
    seen_from: set[str] = set()
    for rule in escalations:
        if not isinstance(rule, dict) or set(rule) != {"from", "to", "after_minutes"}:
            raise ValueError("each escalation needs exactly from, to, after_minutes")
        source, target, after = rule["from"], rule["to"], rule["after_minutes"]
        if source not in notifications.PRIORITIES or target not in notifications.PRIORITIES:
            raise ValueError("escalation priorities are invalid")
        if _PRIORITY_ORDER[target] <= _PRIORITY_ORDER[source]:
            raise ValueError("escalation must strictly increase priority")
        if type(after) is not int or not 1 <= after <= 7 * 24 * 60:
            raise ValueError("escalation after_minutes must be 1..10080")
        if source in seen_from:
            raise ValueError(f"duplicate escalation source {source}")
        seen_from.add(source)
        clean_rules.append({"from": source, "to": target, "after_minutes": after})
    # A chain must become *harder* to reach as severity rises; otherwise a
    # NORMAL notice could jump multiple levels earlier than intended.
    by_from = {r["from"]: r for r in clean_rules}
    for rule in clean_rules:
        next_rule = by_from.get(rule["to"])
        if next_rule and next_rule["after_minutes"] <= rule["after_minutes"]:
            raise ValueError("escalation thresholds must increase along a chain")
    clean = {"version": 1, "quiet_hours": clean_quiet,
             "bypass_priorities": sorted(bypass, key=lambda p: _PRIORITY_ORDER[p]),
             "escalations": sorted(clean_rules, key=lambda r: (_PRIORITY_ORDER[r["from"]], r["after_minutes"]))}
    if value.get("updated_at"):
        _parse_iso(value["updated_at"])
        clean["updated_at"] = value["updated_at"]
    return clean


def load_policy() -> dict:
    if not POLICY_PATH.exists():
        return default_policy()
    return validate_policy(read_json(POLICY_PATH))


def save_policy(value: dict) -> dict:
    clean = validate_policy(value)
    clean["updated_at"] = utcnow()
    write_json_atomic(POLICY_PATH, clean)
    return clean


def configure(*, quiet_enabled: bool = False, timezone: str | None = None,
              quiet_start: str | None = None, quiet_end: str | None = None,
              bypass_priorities: list[str] | None = None,
              escalations: list[dict] | None = None) -> dict:
    quiet: dict = {"enabled": quiet_enabled}
    if quiet_enabled:
        quiet.update({"timezone": timezone, "start": quiet_start, "end": quiet_end})
    return save_policy({"version": 1, "quiet_hours": quiet,
                        "bypass_priorities": bypass_priorities or [],
                        "escalations": escalations or []})


def _quiet_window(now: dt.datetime, policy_value: dict) -> tuple[bool, dt.datetime | None]:
    quiet = policy_value["quiet_hours"]
    if not quiet["enabled"]:
        return False, None
    tz = _timezone(quiet["timezone"])
    local = now.astimezone(tz)
    start_t = _parse_clock(quiet["start"], "quiet_hours.start")
    end_t = _parse_clock(quiet["end"], "quiet_hours.end")
    today_start = dt.datetime.combine(local.date(), start_t, tzinfo=tz)
    today_end = dt.datetime.combine(local.date(), end_t, tzinfo=tz)
    if start_t < end_t:  # same-day window, e.g. 13:00 -> 15:00
        if today_start <= local < today_end:
            return True, today_end
        return False, None
    # Cross-midnight, e.g. 22:00 -> 07:00.
    if local >= today_start:
        return True, dt.datetime.combine(local.date() + dt.timedelta(days=1), end_t, tzinfo=tz)
    if local < today_end:
        return True, today_end
    return False, None


def effective_priority(original: str, created_at: str, now: dt.datetime,
                       policy_value: dict) -> tuple[str, list[dict]]:
    if original not in notifications.PRIORITIES:
        raise ValueError("invalid notification priority")
    created = _parse_iso(created_at).astimezone(dt.timezone.utc)
    age_minutes = max(0, int((now.astimezone(dt.timezone.utc) - created).total_seconds() // 60))
    current = original
    applied: list[dict] = []
    by_from = {r["from"]: r for r in policy_value["escalations"]}
    while current in by_from:
        rule = by_from[current]
        if age_minutes < rule["after_minutes"]:
            break
        applied.append(rule)
        current = rule["to"]
    return current, applied


def classify_notice(notice: dict, *, now: dt.datetime | None = None,
                    policy_value: dict | None = None) -> dict:
    notifications.validate(notice)
    now = now or dt.datetime.now(dt.timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    policy_value = validate_policy(policy_value or load_policy())
    effective, escalations = effective_priority(notice["priority"], notice["created_at"], now, policy_value)
    quiet, quiet_end = _quiet_window(now, policy_value)
    bypass = effective in set(policy_value["bypass_priorities"])
    state = "DEFERRED" if quiet and not bypass else "READY"
    result = {"state": state, "effective_priority": effective,
              "escalations": escalations, "quiet_hours_active": quiet,
              "quiet_bypassed": bool(quiet and bypass)}
    if state == "DEFERRED" and quiet_end is not None:
        result["deliver_after"] = quiet_end.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return result


def _delivery_path(notice_id: str) -> Path:
    return DELIVERY_DIR / f"{safe_id(notice_id, name='notification id')}.json"


def _load_delivery(notice_id: str) -> dict:
    value = read_json(_delivery_path(notice_id))
    if value.get("state") not in DELIVERY_STATES:
        raise ValueError("attention delivery record has invalid state")
    return value


def reconcile_notice(notice: dict, *, now: dt.datetime | None = None,
                     policy_value: dict | None = None) -> dict:
    """Create/update one attention record without delivering anything."""
    notifications.validate(notice)
    now = now or dt.datetime.now(dt.timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    path = _delivery_path(notice["id"])
    existing = _load_delivery(notice["id"]) if path.exists() else None
    if existing and existing["state"] == "DELIVERED":
        return existing
    if notice["state"] == "ACKNOWLEDGED":
        value = existing or {"version": 1, "notice_id": notice["id"],
                             "created_at": now.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
        value.update({"state": "CANCELLED", "cancelled_reason": "notification acknowledged",
                      "updated_at": now.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")})
        write_json_atomic(path, value)
        return value
    classification = classify_notice(notice, now=now, policy_value=policy_value)
    value = existing or {"version": 1, "notice_id": notice["id"],
                         "created_at": now.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    value.update({"state": classification["state"],
                  "original_priority": notice["priority"],
                  "effective_priority": classification["effective_priority"],
                  "quiet_hours_active": classification["quiet_hours_active"],
                  "quiet_bypassed": classification["quiet_bypassed"],
                  "escalations": classification["escalations"],
                  "updated_at": now.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")})
    if "deliver_after" in classification:
        value["deliver_after"] = classification["deliver_after"]
    else:
        value.pop("deliver_after", None)
    write_json_atomic(path, value)
    return value


def reconcile(*, now: dt.datetime | None = None, policy_value: dict | None = None) -> list[dict]:
    now = now or dt.datetime.now(dt.timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    policy_value = validate_policy(policy_value or load_policy())
    return [reconcile_notice(n, now=now, policy_value=policy_value)
            for n in notifications.all_notifications(limit=500)]


def all_delivery_records(*, state: str | None = None) -> list[dict]:
    if state is not None and state not in DELIVERY_STATES:
        raise ValueError("invalid attention delivery state")
    if not DELIVERY_DIR.is_dir():
        return []
    out = []
    for path in DELIVERY_DIR.glob("*.json"):
        try:
            value = _load_delivery(path.stem)
        except ValueError:
            continue
        if state is None or value["state"] == state:
            out.append(value)
    return sorted(out, key=lambda v: (v.get("effective_priority", ""), v.get("updated_at", "")), reverse=True)


def ready(*, now: dt.datetime | None = None) -> list[dict]:
    reconcile(now=now)
    return all_delivery_records(state="READY")


def mark_delivered(notice_id: str, *, provider: str, evidence: str,
                   now: dt.datetime | None = None) -> dict:
    """Record observed external/local delivery; never sends it itself."""
    provider = provider.strip() if isinstance(provider, str) else ""
    evidence = evidence.strip() if isinstance(evidence, str) else ""
    if not provider or len(provider) > 128:
        raise ValueError("delivery provider is required")
    if not evidence or len(evidence) > 1000:
        raise ValueError("delivery evidence is required")
    now = now or dt.datetime.now(dt.timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    value = _load_delivery(notice_id)
    if value["state"] == "DELIVERED":
        return value
    if value["state"] != "READY":
        raise ValueError("only READY attention records may be marked delivered")
    value.update({"state": "DELIVERED", "provider": provider, "evidence": evidence,
                  "delivered_at": now.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                  "updated_at": now.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")})
    write_json_atomic(_delivery_path(notice_id), value)
    return value


def status(*, now: dt.datetime | None = None) -> dict:
    now = now or dt.datetime.now(dt.timezone.utc)
    records = reconcile(now=now)
    counts = {state: 0 for state in DELIVERY_STATES}
    for value in records:
        counts[value["state"]] += 1
    policy_value = load_policy()
    quiet, quiet_end = _quiet_window(now, policy_value)
    return {"policy": policy_value, "quiet_hours_active": quiet,
            "quiet_hours_end": quiet_end.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if quiet_end else None,
            "counts": counts}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Aletheia attention policy")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    sub.add_parser("ready")
    p = sub.add_parser("configure")
    p.add_argument("--quiet", action="store_true")
    p.add_argument("--tz")
    p.add_argument("--start")
    p.add_argument("--end")
    p.add_argument("--bypass", default="", help="comma priorities, e.g. URGENT")
    p.add_argument("--escalations", default="[]", help="JSON list of escalation rules")
    args = ap.parse_args(argv)
    if args.cmd == "status":
        print(json.dumps(status(), indent=2)); return 0
    if args.cmd == "ready":
        print(json.dumps(ready(), indent=2)); return 0
    try:
        escalation_rules = json.loads(args.escalations)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"invalid --escalations JSON: {exc}")
    value = configure(quiet_enabled=args.quiet, timezone=args.tz,
                      quiet_start=args.start, quiet_end=args.end,
                      bypass_priorities=[x.strip().upper() for x in args.bypass.split(",") if x.strip()],
                      escalations=escalation_rules)
    print(json.dumps(value, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
