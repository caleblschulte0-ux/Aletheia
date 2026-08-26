import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import communications, events, journal, mail, policy


class FakeTransport:
    def __init__(self, unread): self.unread=unread
    def fetch_unread(self, limit): return self.unread[:limit]
    def send(self, msg): raise AssertionError("send not expected")


def message(subject="Hello", sender="Bob <bob@example.com>", mid="<m1@example.com>"):
    return {"from":sender,"subject":subject,"date":"Wed, 26 Aug 2026 18:00:00 -0500","message_id":mid}


class MailEventsCase(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        r=Path(self.tmp.name)
        patches=[
            mock.patch.object(mail,"MAIL_DIR",r/"mail"),
            mock.patch.object(events,"EVENTS_DIR",r/"events"),
            mock.patch.object(events,"WATCHERS_DIR",r/"watchers"),
            mock.patch.object(communications,"THREADS_DIR",r/"threads"),
            mock.patch.object(communications,"MESSAGES_DIR",r/"messages"),
            mock.patch.object(communications,"EXPECT_DIR",r/"expect"),
            mock.patch.object(policy,"APPROVALS_DIR",r/"approvals"),
            mock.patch.object(policy,"HALT_PATH",r/"halt"),
            mock.patch.object(journal,"JOURNAL_PATH",r/"journal.jsonl"),
        ]
        for p in patches: p.start(); self.addCleanup(p.stop)

    def enable_events(self):
        mail.MAIL_DIR.mkdir(parents=True,exist_ok=True)
        (mail.MAIL_DIR/"poll-state.json").write_text(json.dumps({"version":1,"seen":[]}),encoding="utf-8")

    def make_expectation(self, thread="t1", expectation="e1", subject="Hello"):
        communications.create_thread(thread,participants=["me","bob@example.com"],subject=subject)
        communications.record_message("out-"+thread,thread_id=thread,direction="OUTBOUND",channel="email",participant="bob@example.com",summary="question",occurred_at="2026-08-26T17:00:00-05:00")
        return communications.expect_reply(expectation,thread_id=thread,after_message_id="out-"+thread,from_participant="bob@example.com")

    def test_first_poll_baselines_existing_unread_without_events(self):
        actions=mail.poll_events(transport=FakeTransport([message(),message(mid="<m2@example.com>")]))
        self.assertEqual(actions,[{"action":"baseline","count":2}])
        self.assertEqual(events.list_events(events_dir=events.EVENTS_DIR),[])
        self.assertEqual(mail.poll_events(transport=FakeTransport([message(),message(mid="<m2@example.com>")])),[])

    def test_new_unread_emits_once_even_if_still_unread(self):
        self.enable_events(); t=FakeTransport([message()])
        first=mail.poll_events(transport=t); second=mail.poll_events(transport=t)
        self.assertEqual([x["action"] for x in first],["received"])
        self.assertEqual(second,[])
        self.assertEqual([e["kind"] for e in events.list_events(events_dir=events.EVENTS_DIR)],["mail.received"])

    def test_exact_waiting_sender_records_reply_and_bus_event(self):
        self.enable_events(); self.make_expectation()
        actions=mail.poll_events(transport=FakeTransport([message()]))
        self.assertEqual([x["action"] for x in actions],["received","reply"])
        self.assertEqual(len(communications.messages("t1")),2)
        kinds={e["kind"] for e in events.list_events(events_dir=events.EVENTS_DIR)}
        self.assertIn("mail.received",kinds); self.assertIn("mail.reply",kinds)
        resolved=communications.evaluate_all()
        self.assertEqual(resolved[0]["status"],"REPLIED")

    def test_subject_disambiguates_same_sender(self):
        self.enable_events(); self.make_expectation("t1","e1","Project Alpha"); self.make_expectation("t2","e2","Project Beta")
        actions=mail.poll_events(transport=FakeTransport([message(subject="Re: Project Beta")]))
        replies=[x for x in actions if x["action"]=="reply"]
        self.assertEqual(replies[0]["expectation"],"e2")
        self.assertEqual(len(communications.messages("t1")),1); self.assertEqual(len(communications.messages("t2")),2)

    def test_ambiguous_sender_never_guesses_thread(self):
        self.enable_events(); self.make_expectation("t1","e1",""); self.make_expectation("t2","e2","")
        actions=mail.poll_events(transport=FakeTransport([message(subject="Something else")]))
        self.assertIn("ambiguous",[x["action"] for x in actions])
        self.assertEqual(len(communications.messages("t1")),1); self.assertEqual(len(communications.messages("t2")),1)
        self.assertIn("mail.reply_ambiguous",{e["kind"] for e in events.list_events(events_dir=events.EVENTS_DIR)})


if __name__=="__main__": unittest.main()
