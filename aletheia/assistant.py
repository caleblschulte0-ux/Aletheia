"""The assistant CLI — the operator's front door to the personal-OS verbs.

    python -m aletheia.assistant state
    python -m aletheia.assistant meet bob --from 2026-08-31 --to 2026-09-04 --tz America/Chicago
    python -m aletheia.assistant schedule add-daily morning-brief brief --tz America/Chicago --time 08:00

One thin argparse layer over the personal-OS modules (Phases 14–22
foundations). Every verb prints the module's JSON truth and nothing
else: no verb here executes an external action, widens a gate, or
bypasses policy — proposals stay proposals, and world-touching halves
(purchase.execute, reservation.book, …) remain NOT_BUILT in the
registry. This CLI exists so each library capability has a real caller
(rule zero: wired, or NOT_BUILT) and so the operator can drive the
private stores from the PC without writing Python.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys

from aletheia import (authority, brain, communications, composition, contacts, context,
                      current_state, devices, documents, finance, handler, meetings,
                      notifications, outcomes, places, proactive, projects, recovery,
                      reservations, room, scheduler, shopping, subscriptions, travel,
                      vehicles)


def _print(value) -> int:
    print(json.dumps(value, indent=2, ensure_ascii=False, default=str))
    return 0


def _csv(value: str | None) -> list[str]:
    return [x.strip() for x in value.split(",") if x.strip()] if value else []


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="python -m aletheia.assistant",
        description="Operator front door to Aletheia's personal-OS verbs.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("state", help="canonical current-state snapshot")

    p = sub.add_parser("notifications", help="list notifications")
    p.add_argument("--state", choices=sorted(notifications.STATES), default=None)
    p = sub.add_parser("ack", help="acknowledge a notification")
    p.add_argument("id")

    p = sub.add_parser("meet", help="propose meeting slots with a known person")
    p.add_argument("person")
    p.add_argument("--from", dest="start", required=True, help="YYYY-MM-DD")
    p.add_argument("--to", dest="end", required=True, help="YYYY-MM-DD")
    p.add_argument("--tz", required=True)
    p.add_argument("--minutes", type=int, default=30)
    p.add_argument("--not-before", default="09:00")
    p.add_argument("--not-after", default="17:00")
    p.add_argument("--buffer", type=int, default=0)

    p = sub.add_parser("schedule", help="durable schedules")
    ssub = p.add_subparsers(dest="sched_cmd", required=True)
    ssub.add_parser("list")
    ssub.add_parser("due")
    q = ssub.add_parser("add-once")
    q.add_argument("id"); q.add_argument("kind"); q.add_argument("--at", required=True)
    q.add_argument("--arg", action="append", default=[], help="key=value command args")
    q = ssub.add_parser("add-interval")
    q.add_argument("id"); q.add_argument("kind")
    q.add_argument("--every-minutes", type=int, required=True)
    q.add_argument("--anchor", required=True)
    q.add_argument("--arg", action="append", default=[])
    q = ssub.add_parser("add-daily")
    q.add_argument("id"); q.add_argument("kind")
    q.add_argument("--tz", required=True); q.add_argument("--time", required=True)
    q.add_argument("--arg", action="append", default=[])
    q = ssub.add_parser("add-weekly")
    q.add_argument("id"); q.add_argument("kind")
    q.add_argument("--tz", required=True); q.add_argument("--time", required=True)
    q.add_argument("--weekdays", required=True, help="comma list of 0..6 (0=Monday)")
    q.add_argument("--arg", action="append", default=[])
    q = ssub.add_parser("enable"); q.add_argument("id")
    q = ssub.add_parser("disable"); q.add_argument("id")

    p = sub.add_parser("handle", help="persistent handle-it requests")
    hsub = p.add_subparsers(dest="handle_cmd", required=True)
    q = hsub.add_parser("new")
    q.add_argument("id"); q.add_argument("--intent", required=True)
    q.add_argument("--requires", default="", help="comma list of capability ids")
    q = hsub.add_parser("refresh"); q.add_argument("id")
    q = hsub.add_parser("done"); q.add_argument("id"); q.add_argument("--evidence", required=True)
    q = hsub.add_parser("cancel"); q.add_argument("id"); q.add_argument("--reason", required=True)

    p = sub.add_parser("project", help="first-class projects")
    psub = p.add_subparsers(dest="project_cmd", required=True)
    psub.add_parser("list")
    q = psub.add_parser("new")
    q.add_argument("id"); q.add_argument("title"); q.add_argument("--goal", required=True)
    q = psub.add_parser("update")
    q.add_argument("id"); q.add_argument("--status"); q.add_argument("--add-task")
    q.add_argument("--add-person"); q.add_argument("--blocker"); q.add_argument("--decision")

    p = sub.add_parser("context", help="recent-referent memory ('him', 'that')")
    csub = p.add_subparsers(dest="context_cmd", required=True)
    q = csub.add_parser("remember")
    q.add_argument("id"); q.add_argument("--kind", required=True)
    q.add_argument("--value", required=True); q.add_argument("--label", default="")
    q = csub.add_parser("resolve")
    q.add_argument("--kind"); q.add_argument("--label")

    p = sub.add_parser("place", help="saved places and observed travel times")
    plsub = p.add_subparsers(dest="place_cmd", required=True)
    q = plsub.add_parser("new")
    q.add_argument("id"); q.add_argument("name")
    q.add_argument("--address", default=""); q.add_argument("--alias", action="append", default=[])
    q = plsub.add_parser("resolve"); q.add_argument("query")
    q = plsub.add_parser("travel")
    q.add_argument("origin"); q.add_argument("destination")
    q.add_argument("--minutes", type=int, required=True)
    q.add_argument("--mode", default="drive"); q.add_argument("--source", required=True)

    p = sub.add_parser("doc", help="private document text store")
    dsub = p.add_subparsers(dest="doc_cmd", required=True)
    q = dsub.add_parser("ingest")
    q.add_argument("id"); q.add_argument("--title", required=True)
    q.add_argument("--source", required=True)
    q.add_argument("--file", help="read text from this file; default stdin")
    q = dsub.add_parser("search"); q.add_argument("term")

    p = sub.add_parser("shop", help="shopping workflow (proposal-only)")
    shsub = p.add_subparsers(dest="shop_cmd", required=True)
    q = shsub.add_parser("new")
    q.add_argument("id"); q.add_argument("--need", required=True)
    q.add_argument("--budget", type=float)
    q = shsub.add_parser("candidate")
    q.add_argument("workflow"); q.add_argument("id"); q.add_argument("--title", required=True)
    q.add_argument("--price", type=float); q.add_argument("--source", required=True)
    q = shsub.add_parser("select"); q.add_argument("workflow"); q.add_argument("id")
    q = shsub.add_parser("propose"); q.add_argument("workflow")

    p = sub.add_parser("subs", help="recurring subscription visibility")
    susub = p.add_subparsers(dest="subs_cmd", required=True)
    susub.add_parser("list")
    q = susub.add_parser("new")
    q.add_argument("id"); q.add_argument("--merchant", required=True)
    q.add_argument("--amount", type=float); q.add_argument("--cadence", default="monthly")
    q.add_argument("--next-charge")
    q = susub.add_parser("cancel-request"); q.add_argument("id")

    p = sub.add_parser("finance", help="read-only financial visibility")
    fsub = p.add_subparsers(dest="finance_cmd", required=True)
    fsub.add_parser("net")
    fsub.add_parser("accounts")
    q = fsub.add_parser("account")
    q.add_argument("id"); q.add_argument("--name", required=True)
    q.add_argument("--kind", required=True); q.add_argument("--balance", type=float, required=True)
    q.add_argument("--source", required=True)

    p = sub.add_parser("vehicle", help="vehicle records and service due")
    vsub = p.add_subparsers(dest="vehicle_cmd", required=True)
    q = vsub.add_parser("new"); q.add_argument("id"); q.add_argument("--name", required=True)
    q = vsub.add_parser("odometer"); q.add_argument("id"); q.add_argument("miles", type=int)
    q = vsub.add_parser("rule")
    q.add_argument("vehicle"); q.add_argument("id"); q.add_argument("--description", required=True)
    q.add_argument("--every-miles", type=int); q.add_argument("--every-days", type=int)
    q.add_argument("--last-miles", type=int); q.add_argument("--last-date")
    q = vsub.add_parser("due"); q.add_argument("id")

    p = sub.add_parser("trip", help="travel itineraries")
    tsub = p.add_subparsers(dest="trip_cmd", required=True)
    q = tsub.add_parser("new")
    q.add_argument("id"); q.add_argument("--title", required=True)
    q.add_argument("--from", dest="start", required=True); q.add_argument("--to", dest="end", required=True)
    q = tsub.add_parser("item")
    q.add_argument("trip"); q.add_argument("id"); q.add_argument("--kind", required=True)
    q.add_argument("--title", required=True); q.add_argument("--start"); q.add_argument("--end")
    q.add_argument("--confirmation")
    q = tsub.add_parser("gaps"); q.add_argument("id")

    p = sub.add_parser("reserve", help="reservation workflow (proposal-only)")
    rsub = p.add_subparsers(dest="reserve_cmd", required=True)
    q = rsub.add_parser("new")
    q.add_argument("id"); q.add_argument("--kind", required=True)
    q.add_argument("--description", required=True); q.add_argument("--party", type=int)
    q = rsub.add_parser("candidate")
    q.add_argument("reservation"); q.add_argument("id"); q.add_argument("--provider", required=True)
    q.add_argument("--place", required=True); q.add_argument("--slot", required=True)
    q = rsub.add_parser("select"); q.add_argument("reservation"); q.add_argument("id")
    q = rsub.add_parser("propose"); q.add_argument("reservation")
    q = rsub.add_parser("confirm")
    q.add_argument("reservation"); q.add_argument("--confirmation-id", required=True)
    q.add_argument("--source", required=True)

    p = sub.add_parser("device", help="provider-neutral device registry")
    desub = p.add_subparsers(dest="device_cmd", required=True)
    q = desub.add_parser("register")
    q.add_argument("id"); q.add_argument("--name", required=True); q.add_argument("--kind", required=True)
    q.add_argument("--room", required=True); q.add_argument("--provider", required=True)
    q.add_argument("--external-id", required=True)
    q.add_argument("--ability", action="append", required=True)
    q = desub.add_parser("room"); q.add_argument("room")

    p = sub.add_parser("scene", help="room scenes (plans, never executions)")
    scsub = p.add_subparsers(dest="scene_cmd", required=True)
    q = scsub.add_parser("new")
    q.add_argument("id"); q.add_argument("name")
    q.add_argument("--step", action="append", required=True,
                   help="device:ability[:value], repeatable")
    q = scsub.add_parser("plan"); q.add_argument("id")

    p = sub.add_parser("grant", help="delegated-authority grant records")
    gsub = p.add_subparsers(dest="grant_cmd", required=True)
    q = gsub.add_parser("new")
    q.add_argument("id"); q.add_argument("--capabilities", required=True, help="comma list")
    q.add_argument("--approval", required=True, help="an APPROVED approval id")
    q.add_argument("--expires", required=True); q.add_argument("--max-uses", type=int, default=100)
    q = gsub.add_parser("revoke"); q.add_argument("id")

    p = sub.add_parser("comm", help="communication threads and reply expectations")
    cmsub = p.add_subparsers(dest="comm_cmd", required=True)
    q = cmsub.add_parser("thread")
    q.add_argument("id"); q.add_argument("--with", dest="participants", required=True,
                   help="comma list of participants")
    q.add_argument("--subject", default="")
    q = cmsub.add_parser("message")
    q.add_argument("id"); q.add_argument("thread")
    q.add_argument("--direction", choices=sorted(communications.DIRECTIONS), required=True)
    q.add_argument("--channel", choices=sorted(communications.CHANNELS), required=True)
    q.add_argument("--from", dest="participant", required=True)
    q.add_argument("--summary", required=True); q.add_argument("--at")
    q = cmsub.add_parser("expect")
    q.add_argument("id"); q.add_argument("thread")
    q.add_argument("--after", required=True, help="outbound message id")
    q.add_argument("--from", dest="participant", required=True)
    q.add_argument("--deadline")
    cmsub.add_parser("expectations")

    p = sub.add_parser("rule", help="bounded proactive rules")
    rusub = p.add_subparsers(dest="rule_cmd", required=True)
    rusub.add_parser("list")
    q = rusub.add_parser("new")
    q.add_argument("id"); q.add_argument("--on", dest="event_kind", required=True)
    q.add_argument("--action", choices=sorted(proactive.ACTIONS), required=True)
    q.add_argument("--source"); q.add_argument("--subject-prefix")
    q.add_argument("--cooldown-minutes", type=int, default=0)
    q.add_argument("--once", action="store_true")
    q = rusub.add_parser("disable"); q.add_argument("id")
    q = rusub.add_parser("enable"); q.add_argument("id")

    p = sub.add_parser("outcome", help="action records with evidence-gated verification")
    osub = p.add_subparsers(dest="outcome_cmd", required=True)
    osub.add_parser("list")
    q = osub.add_parser("start")
    q.add_argument("id"); q.add_argument("--capability", required=True)
    q.add_argument("--provider", required=True); q.add_argument("--intent", required=True)
    q.add_argument("--plan", required=True, help="JSON object")
    q = osub.add_parser("attempt")
    q.add_argument("id"); q.add_argument("--outcome",
                   choices=sorted(outcomes.ATTEMPT_OUTCOMES), required=True)
    q.add_argument("--note", default="")
    q = osub.add_parser("evidence")
    q.add_argument("id"); q.add_argument("evidence_id")
    q.add_argument("--kind", choices=sorted(outcomes.EVIDENCE_KINDS), required=True)
    q.add_argument("--observed", required=True, help="JSON value")
    q.add_argument("--expected", help="JSON value")
    q = osub.add_parser("verify"); q.add_argument("id")

    p = sub.add_parser("compose", help="capability recipes")
    q = p.add_subparsers(dest="compose_cmd", required=True).add_parser("plan")
    q.add_argument("recipe", choices=sorted(composition.RECIPES))

    p = sub.add_parser("interpret", help="deterministic fallback brain (never guesses)")
    p.add_argument("text")

    p = sub.add_parser("recover", help="retry/backoff decision for a failure")
    p.add_argument("--code", required=True); p.add_argument("--attempts", type=int, required=True)
    p.add_argument("--max-attempts", type=int, default=5)

    args = ap.parse_args(argv)

    def cmd_args(pairs: list[str], kind: str) -> dict:
        command = {"kind": kind}
        for pair in pairs:
            if "=" not in pair:
                raise SystemExit(f"--arg must be key=value: {pair}")
            key, value = pair.split("=", 1)
            command[key] = value
        return command

    if args.cmd == "state":
        return _print(current_state.snapshot())
    if args.cmd == "notifications":
        return _print(notifications.all_notifications(state=args.state))
    if args.cmd == "ack":
        return _print(notifications.set_state(args.id, "ACKNOWLEDGED"))
    if args.cmd == "meet":
        return _print(meetings.propose(
            args.person, start_day=args.start, end_day=args.end,
            duration_minutes=args.minutes, timezone=args.tz,
            not_before=args.not_before, not_after=args.not_after,
            buffer_minutes=args.buffer))
    if args.cmd == "schedule":
        c = args.sched_cmd
        if c == "list":
            return _print(scheduler.all_schedules())
        if c == "due":
            return _print([r for r in (scheduler.claim_due(s) for s in scheduler.all_schedules()) if r])
        if c == "enable":
            return _print(scheduler.set_enabled(args.id, True))
        if c == "disable":
            return _print(scheduler.set_enabled(args.id, False))
        command = cmd_args(args.arg, args.kind)
        if c == "add-once":
            return _print(scheduler.create(args.id, command, kind="once", at=args.at))
        if c == "add-interval":
            return _print(scheduler.create(args.id, command, kind="interval",
                                           every_minutes=args.every_minutes, anchor=args.anchor))
        if c == "add-daily":
            return _print(scheduler.create(args.id, command, kind="daily",
                                           timezone=args.tz, time=args.time))
        return _print(scheduler.create(args.id, command, kind="weekly", timezone=args.tz,
                                       time=args.time,
                                       weekdays=[int(d) for d in _csv(args.weekdays)]))
    if args.cmd == "handle":
        c = args.handle_cmd
        if c == "new":
            return _print(handler.create(args.id, intent=args.intent,
                                         required_capabilities=_csv(args.requires)))
        if c == "refresh":
            return _print(handler.refresh(args.id))
        if c == "done":
            return _print(handler.complete(args.id, evidence=args.evidence))
        return _print(handler.cancel(args.id, reason=args.reason))
    if args.cmd == "project":
        c = args.project_cmd
        if c == "list":
            return _print(projects.all_projects())
        if c == "new":
            return _print(projects.create(args.id, args.title, goal=args.goal))
        return _print(projects.update(args.id, status=args.status, add_task=args.add_task,
                                      add_person=args.add_person, blocker=args.blocker,
                                      decision=args.decision))
    if args.cmd == "context":
        if args.context_cmd == "remember":
            return _print(context.remember(args.id, kind=args.kind, value=args.value,
                                           label=args.label))
        return _print(context.resolve(kind=args.kind, label=args.label))
    if args.cmd == "place":
        c = args.place_cmd
        if c == "new":
            return _print(places.create(args.id, args.name, address=args.address,
                                        aliases=args.alias))
        if c == "resolve":
            return _print(places.resolve(args.query))
        return _print(places.record_travel(args.origin, args.destination,
                                           minutes=args.minutes, mode=args.mode,
                                           source=args.source))
    if args.cmd == "doc":
        if args.doc_cmd == "ingest":
            text = (open(args.file, encoding="utf-8").read() if args.file
                    else sys.stdin.read())
            return _print(documents.ingest_text(args.id, title=args.title, text=text,
                                                source=args.source))
        return _print(documents.search(args.term))
    if args.cmd == "shop":
        c = args.shop_cmd
        if c == "new":
            return _print(shopping.create(args.id, need=args.need, budget=args.budget))
        if c == "candidate":
            return _print(shopping.add_candidate(args.workflow, args.id, title=args.title,
                                                 price=args.price, source=args.source))
        if c == "select":
            return _print(shopping.select(args.workflow, args.id))
        return _print(shopping.propose_purchase(args.workflow))
    if args.cmd == "subs":
        c = args.subs_cmd
        if c == "list":
            return _print(subscriptions.all_subscriptions())
        if c == "new":
            return _print(subscriptions.create(args.id, merchant=args.merchant,
                                               amount=args.amount, cadence=args.cadence,
                                               next_charge=args.next_charge))
        return _print(subscriptions.request_cancel(args.id))
    if args.cmd == "finance":
        c = args.finance_cmd
        if c == "net":
            return _print(finance.net_worth())
        if c == "accounts":
            return _print(finance.accounts())
        return _print(finance.record_account(args.id, name=args.name, kind=args.kind,
                                             balance=args.balance, source=args.source))
    if args.cmd == "vehicle":
        c = args.vehicle_cmd
        if c == "new":
            return _print(vehicles.create(args.id, name=args.name))
        if c == "odometer":
            return _print(vehicles.record_odometer(args.id, args.miles))
        if c == "rule":
            return _print(vehicles.add_service_rule(
                args.vehicle, args.id, description=args.description,
                every_miles=args.every_miles, every_days=args.every_days,
                last_miles=args.last_miles, last_date=args.last_date))
        return _print(vehicles.due(args.id))
    if args.cmd == "trip":
        c = args.trip_cmd
        if c == "new":
            return _print(travel.create(args.id, title=args.title, start_date=args.start,
                                        end_date=args.end))
        if c == "item":
            return _print(travel.add_item(args.trip, args.id, kind=args.kind, title=args.title,
                                          start=args.start, end=args.end,
                                          confirmation=args.confirmation))
        return _print(travel.gaps(args.id))
    if args.cmd == "reserve":
        c = args.reserve_cmd
        if c == "new":
            return _print(reservations.create(args.id, kind=args.kind,
                                              description=args.description,
                                              party_size=args.party))
        if c == "candidate":
            return _print(reservations.add_candidate(args.reservation, args.id,
                                                     provider=args.provider, place=args.place,
                                                     slot=args.slot))
        if c == "select":
            return _print(reservations.select(args.reservation, args.id))
        if c == "propose":
            return _print(reservations.propose_booking(args.reservation))
        return _print(reservations.confirm(args.reservation,
                                           confirmation_id=args.confirmation_id,
                                           source=args.source))
    if args.cmd == "device":
        if args.device_cmd == "register":
            return _print(devices.register(args.id, name=args.name, kind=args.kind,
                                           room=args.room, provider=args.provider,
                                           external_id=args.external_id,
                                           abilities=args.ability))
        return _print(devices.in_room(args.room))
    if args.cmd == "scene":
        if args.scene_cmd == "new":
            steps = []
            for raw in args.step:
                parts = raw.split(":", 2)
                if len(parts) < 2:
                    raise SystemExit(f"--step must be device:ability[:value]: {raw}")
                step = {"device": parts[0], "ability": parts[1]}
                if len(parts) == 3:
                    step["value"] = parts[2]
                steps.append(step)
            return _print(room.create(args.id, args.name, steps))
        return _print(room.plan(args.id))
    if args.cmd == "grant":
        if args.grant_cmd == "new":
            return _print(authority.create(args.id, capability_ids=_csv(args.capabilities),
                                           approval_id=args.approval, expires=args.expires,
                                           max_uses=args.max_uses))
        return _print(authority.revoke(args.id))
    if args.cmd == "comm":
        c = args.comm_cmd
        if c == "thread":
            return _print(communications.create_thread(args.id,
                                                       participants=_csv(args.participants),
                                                       subject=args.subject))
        if c == "message":
            return _print(communications.record_message(
                args.id, thread_id=args.thread, direction=args.direction,
                channel=args.channel, participant=args.participant,
                summary=args.summary, occurred_at=args.at))
        if c == "expect":
            return _print(communications.expect_reply(
                args.id, thread_id=args.thread, after_message_id=args.after,
                from_participant=args.participant, deadline=args.deadline))
        return _print(communications.all_expectations())
    if args.cmd == "rule":
        c = args.rule_cmd
        if c == "list":
            return _print(proactive.all_rules())
        if c == "new":
            return _print(proactive.create_rule(
                args.id, event_kind=args.event_kind, action=args.action,
                source=args.source, subject_prefix=args.subject_prefix,
                cooldown_minutes=args.cooldown_minutes, persistent=not args.once))
        return _print(proactive.set_enabled(args.id, args.rule_cmd == "enable"))
    if args.cmd == "outcome":
        c = args.outcome_cmd
        if c == "list":
            return _print(outcomes.all_actions())
        if c == "start":
            return _print(outcomes.start(args.id, capability=args.capability,
                                         provider=args.provider, intent=args.intent,
                                         plan=json.loads(args.plan)))
        if c == "attempt":
            return _print(outcomes.add_attempt(args.id, outcome=args.outcome, note=args.note))
        if c == "evidence":
            return _print(outcomes.add_evidence(
                args.id, args.evidence_id, kind=args.kind,
                observed=json.loads(args.observed),
                expected=json.loads(args.expected) if args.expected else None))
        return _print(outcomes.verify(args.id))
    if args.cmd == "compose":
        return _print(composition.plan(args.recipe))
    if args.cmd == "interpret":
        return _print(brain.FALLBACK.run(args.text))
    if args.cmd == "recover":
        return _print(recovery.next_step(failure_code=args.code, attempts=args.attempts,
                                         max_attempts=args.max_attempts))
    return 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, KeyError, LookupError, PermissionError,
            FileExistsError, FileNotFoundError) as exc:
        print(f"refused: {exc}", file=sys.stderr)
        raise SystemExit(1)
