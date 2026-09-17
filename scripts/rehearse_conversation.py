"""Rehearse a whole conversation, for real code and fake world: nothing is sent, nothing is booked.

    python scripts/rehearse_conversation.py                 # replies read by rules only
    python scripts/rehearse_conversation.py --frontier-off  # replies read by HER OWN model
    python scripts/rehearse_conversation.py --frontier-off --model qwen3:8b

What it proves (continuity brief IV.15/IV.16): a draft to a property manager, his
approval, the send, a reply offering two tour times (one clashing with something
already on his calendar), conflict detection, a proposal of the free one, his
approval, their confirmation, a calendar hold confirmed onto a (fake) live
calendar through its own approval, a second question nobody answers, a follow-up
coming due, sent under a standing grant he created in words, the answer, and the
thread closing.

SAFETY: every store is a throwaway directory (private state, the repo-anchored
stores `talk --sandbox` redirects, the journal, the machine key, the workspace);
ALETHEIA_REHEARSAL is set before anything imports; mail goes through
`conversations.FakeMailTransport` and the calendar through
`calendar_provider.InMemoryCalendarProvider`. The real mail transport is replaced
by one that raises, so a mistake here fails loudly instead of emailing anyone.
His "approvals" and "words" are simulated and labelled as such in the transcript.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def isolate(room: Path, *, frontier_off: bool, model: str) -> None:
    os.environ["ALETHEIA_PRIVATE_STATE"] = str(room / "private")
    os.environ["ALETHEIA_JOURNAL_PATH"] = str(room / "journal.jsonl")
    os.environ["ALETHEIA_WORKSPACE"] = str(room / "workspace")
    os.environ["ALETHEIA_MACHINE_KEY"] = str(room / "machine.key")
    os.environ["ALETHEIA_APPROVALS_DIR"] = str(room / "approvals")
    os.environ["ALETHEIA_REHEARSAL"] = "1"
    os.environ.setdefault("ALETHEIA_TZ", "America/Chicago")
    if frontier_off:
        os.environ["ALETHEIA_FRONTIER_OFF"] = "1"
        os.environ["ALETHEIA_LOCAL_AI_ENABLED"] = "1"
        if model:
            os.environ["ALETHEIA_LOCAL_AI_FAST_MODEL"] = model
    (room / "workspace").mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(ROOT))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--frontier-off", action="store_true", help="read replies with her own local model")
    ap.add_argument("--model", default="qwen3-vl:4b", help="the local fast model (with --frontier-off)")
    ap.add_argument("--json", default="", help="also write the transcript as JSON here")
    args = ap.parse_args(argv)
    room = Path(tempfile.mkdtemp(prefix="rehearse-conversation-"))
    isolate(room, frontier_off=args.frontier_off, model=args.model)

    from aletheia import talk
    talk._redirect_repo_stores(room)
    from aletheia import (calendar, calendar_provider, calendar_reasoning as cr, contacts, conversation_authority as ca,
                          conversations as conv, intercom, journal, mail, notifications, policy,
                          reply_understanding as ru)

    class NoRealMail:
        def __init__(self, *a, **k):
            raise AssertionError("the rehearsal reached for the real mail account")
    mail.SmtpImapTransport = NoRealMail
    assert intercom.rehearsing(), "rehearsal flag not set"

    zone = cr._zone()
    transcript: list[dict] = []
    started_all = time.monotonic()
    use_model = bool(args.frontier_off)
    think = None
    if use_model:
        from aletheia import reasoning_gateway
        assert reasoning_gateway.frontier_off()
        print(f"frontier OFF; local model ready: {reasoning_gateway.local_ready()} "
              f"(fast role: {os.environ.get('ALETHEIA_LOCAL_AI_FAST_MODEL')})")

    fake = conv.FakeMailTransport(address="caleb@example.test")
    provider = calendar_provider.InMemoryCalendarProvider("fake.calendar")
    now0 = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
    clock = {"now": now0}

    def local(when):
        return when.astimezone(zone).strftime("%a %b %d %I:%M %p %Z")

    def step(title, fn):
        before = {t["id"]: t["state"] for t in conv.all_threads()}
        t0 = time.monotonic()
        detail = fn()
        took = round(time.monotonic() - t0, 2)
        after = {t["id"]: t["state"] for t in conv.all_threads()}
        moves = [f"{before.get(k, 'new')} -> {v}" for k, v in after.items() if before.get(k) != v]
        row = {"step": len(transcript) + 1, "title": title, "sim_time": local(clock["now"]), "seconds": took,
               "transitions": moves, "detail": detail}
        transcript.append(row)
        print(f"\n[{row['step']:02d}] {title}   (sim {row['sim_time']}, {took}s)")
        for move in moves:
            print(f"     state: {move}")
        for line in (detail if isinstance(detail, list) else [detail]):
            if line:
                print(f"     {line}")
        return detail

    def beat(hours=0.0, days=0.0):
        clock["now"] = clock["now"] + dt.timedelta(hours=hours, days=days)
        mail.poll_events(limit=50, transport=fake)
        result = conv.reconcile(now=clock["now"], transport=fake, use_model=use_model, think=think,
                                provider=provider)
        lines = []
        for sent in result["sent"]:
            lines.append(f"send: {sent.get('outcome')} {sent.get('kind', '')} to {sent.get('to')} "
                         f"(authorized by {sent.get('via', sent.get('detail', ''))})")
        for reply in result["replies"]:
            lines.append(f"reply read: {reply.get('category')} by {reply.get('understood_by')}"
                         + (f" in {reply.get('model_seconds')}s" if reply.get("model_seconds") is not None else "")
                         + f" -> next action: {reply.get('action')}")
        for follow in result["followups"]:
            lines.append(f"follow-up drafted; covered by his grant: {follow['covered_by_grant']}")
        for written in result["calendar"]:
            lines.append(f"live calendar: {written}")
        for error in result["errors"]:
            lines.append(f"ERROR: {error}")
        return lines

    def deliver(text, hours, subject="Re: The two-bedroom listing at 412 Elm Street"):
        fake.deliver(sender="Dana Reyes <dana@harborview-rentals.test>", subject=subject, text=text,
                     when=clock["now"] + dt.timedelta(hours=hours))

    def thread():
        return conv.all_threads()[0]

    def say():
        return f'Thea: "{conv.status_words("they", now=clock["now"])}"'

    mail.poll_events(limit=50, transport=fake)                     # baseline the (fake) inbox
    contacts.create("dana-reyes", "Dana Reyes", emails=["dana@harborview-rentals.test"],
                    aliases=["the property manager"], provenance="rehearsal fixture")

    step("Caleb: \"email the property manager about the two-bedroom listing at 412 Elm Street\"", lambda: [
        (lambda t: f"drafted to {t['recipient']['name']} <{t['recipient']['address']}> "
                   f"(recipient from: {t['recipient']['source']}); message needs {t['messages'][0]['capability']}: "
                   f"{t['messages'][0]['authority_why']}")(
            conv.start("the property manager", about="the two-bedroom listing at 412 Elm Street",
                       asks=["Could I come see the unit sometime this week or next?", "Is parking included?"],
                       now=clock["now"], via="rehearsal (simulated voice)",
                       meeting={"minutes": 45, "title": "Tour: 412 Elm Street", "location": "412 Elm Street"})),
        "draft body:\n" + "\n".join("       | " + ln for ln in thread()["messages"][0]["body"].splitlines()),
        say()])

    step("a beat before he answers: nothing may leave", lambda: beat(hours=0.05) + [f"outbox: {len(fake.outbox)}"])

    step("Caleb approves the draft (simulated tap on the approval)", lambda: [
        policy.decide(thread()["messages"][0]["approval"], "APPROVED", via="operator-cli (simulated)",
                      because="rehearsal")["state"]] + beat(hours=0.1) + [f"outbox: {len(fake.outbox)}", say()])

    # Something already on his calendar at the first time they will offer.
    probe_ref = clock["now"] + dt.timedelta(hours=2)
    reply_text = ("Hi Caleb,\n\nThanks for reaching out! The unit is still available. We can do a showing "
                  "Thursday at 2pm or Friday at 10am - which works better for you?\n\nBest,\nDana Reyes\n"
                  "Harborview Rentals")
    offered = ru.extract_times(reply_text, reference=probe_ref)
    busy = calendar.parse_time(offered[0]["start"])
    calendar.create("dentist", "Dentist appointment", (busy - dt.timedelta(minutes=30)).isoformat(),
                    (busy + dt.timedelta(minutes=45)).isoformat(), location="Oak Dental, 200 Oak St")
    step("his calendar already has: Dentist appointment", lambda: [
        f"{local(busy - dt.timedelta(minutes=30))} to {local(busy + dt.timedelta(minutes=45))} at Oak Dental"])

    step("Dana replies offering two times", lambda: (deliver(reply_text, hours=2) or []) + beat(hours=2.5) + [
        "times read: " + "; ".join(f"{c['human']} free={c['free']}"
                                   + (f" ({'; '.join(c['conflicts'])})" if c["conflicts"] else "")
                                   for c in thread()["scheduling"].get("checked", [])),
        f"pencilled in: {thread()['scheduling'].get('slot', {}).get('human')} "
        f"(hold {thread()['scheduling'].get('hold')}, TENTATIVE, her calendar only)",
        "reply drafted:\n" + "\n".join("       | " + ln for ln in thread()["messages"][-1]["body"].splitlines()),
        f"that reply needs {thread()['messages'][-1]['capability']}: {thread()['messages'][-1]['authority_why']}",
        say()])

    step("Caleb approves the reply (simulated)", lambda: [
        policy.decide(thread()["messages"][-1]["approval"], "APPROVED", via="operator-cli (simulated)",
                      because="rehearsal")["state"]] + beat(hours=0.2) + [
        f"scheduling: {thread()['scheduling']['state']}", say()])

    step("Dana confirms", lambda: (deliver("Friday at 10 is confirmed. See you then!", hours=1) or []) + beat(hours=1.5) + [
        f"scheduling: {thread()['scheduling']['state']}; hold now "
        f"{calendar.load(thread()['scheduling']['hold'])['status']}",
        f"live calendar write approval: {thread()['scheduling'].get('write_approval')} "
        f"({policy.load(thread()['scheduling']['write_approval'])['state']}, calendar.write)",
        "open questions: " + "; ".join(a["text"] for a in thread()["open_asks"] if not a.get("answered_in")),
        say()])

    step("Caleb approves putting it on his (fake) live calendar", lambda: [
        policy.decide(thread()["scheduling"]["write_approval"], "APPROVED", via="operator-cli (simulated)",
                      because="rehearsal")["state"]] + beat(hours=0.1) + [
        f"fake provider now holds {len(provider.list_events((clock['now'] - dt.timedelta(days=1)).isoformat(), (clock['now'] + dt.timedelta(days=14)).isoformat()))} event(s)"])

    words = "You can follow up with the property manager without asking me, up to two times."
    step(f"Caleb types (simulated, at the keyboard): \"{words}\"", lambda: [
        (lambda g: f"grant {g['id']}: scope {json.dumps(g['scope'])}, {g['max_uses']} message(s) until {g['expires']}, "
                   f"machine-bound={bool(g.get('machine_binding'))}")(ca.grant_from_words(words, via="operator-cli"))])

    step("the room hears the same sentence", lambda: [
        __import__("aletheia.voice", fromlist=["interpret"]).interpret(f"thea {words}")["say"]])

    step("two days pass with no answer about parking", lambda: beat(days=2) + [say()])
    step("a third day: the follow-up comes due", lambda: beat(days=1.2) + [
        "follow-up sent:\n" + "\n".join("       | " + ln for ln in fake.outbox[-1].get_content().splitlines()),
        f"authorized by: {thread()['messages'][-1].get('approved_via')}", say()])

    step("Dana answers the parking question",
         lambda: (deliver("Sorry for the slow reply - yes, parking is included, one assigned spot per unit.", hours=3)
                  or []) + beat(hours=4) + [f"thread: {thread()['state']} - {thread()['reason']}", say()])

    final = thread()
    total = round(time.monotonic() - started_all, 1)
    print("\n==== summary ====")
    print(f"mode: {'frontier OFF, replies read by her own model' if use_model else 'replies read by rules'}")
    print(f"emails in the fake outbox: {len(fake.outbox)}; real transports touched: 0")
    print("state history: " + " -> ".join(h["to"] for h in final["history"]))
    for reply in final["replies"]:
        took = f" in {reply['model_seconds']}s" if reply.get("model_seconds") is not None else ""
        note = f"; model note: {reply['model_error']}" if reply.get("model_error") else ""
        print(f"reply: {reply['category']} read by {reply['understood_by']}{took}{note}")
    print(f"notifications: {[n['title'] for n in notifications.all_notifications()]}")
    print(f"total wall time: {total}s; throwaway state: {room}")
    if args.json:
        Path(args.json).write_text(json.dumps({"mode": "local" if use_model else "rules", "steps": transcript,
                                               "history": final["history"], "replies": final["replies"],
                                               "total_s": total}, indent=1, default=str), encoding="utf-8")
    return 0 if final["state"] == conv.CLOSED else 1


if __name__ == "__main__":
    raise SystemExit(main())
