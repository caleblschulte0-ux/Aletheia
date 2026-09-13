"""One folded subject line stopped her reading email for a whole night.

2026-09-13, once a minute:

    core:runtime:mail  subsystem failing: ValueError: summary contains control characters

An acknowledgement arrived with its subject folded across two header
lines. `make_header` keeps the fold, `events.emit` refuses a summary with a
carriage return in it, and the exception left `mail.poll_events` before it
saved what it had seen. So on every beat the message BEFORE it was emitted
again, and not one message AFTER it was ever read — including a
verification code a form was waiting on.

Three things are held here: a header is one line, one message is never the
whole poll, and an employer's acknowledgement with a folded subject still
reaches the job-reply check it was meant for.

The code is its own half. It DID arrive, in the inbox she reads, about a
minute after the click. The record called the employer "Acme ..." and the
subject said "Acme Technologies", and a substring of one in the other is
neither. Every employer, subject and code below is invented.
"""
from __future__ import annotations

import datetime as dt
import json
import tempfile
import unittest
from email import message_from_bytes
from pathlib import Path
from unittest import mock

from aletheia import apply_run, communications, events, journal, mail, policy, runtime

ACK = "Application for Inbound Sales Development Representative received by Team Northwind!"
FOLDED_ACK = ACK.replace(" Team", "\r\n Team")

FOLDED = (b"From: no-reply@ats.example.com\r\n"
          b"Subject: Application for Inbound Sales Development Representative received by\r\n"
          b" Team Northwind!\r\n"
          b"Date: Sun, 13 Sep 2026 03:19:01 +0000\r\n"
          b"Message-ID: <ack@example.com>\r\n\r\n")


def message(subject, mid, date="Sun, 13 Sep 2026 03:19:01 +0000",
            sender="no-reply@ats.example.com"):
    return {"from": sender, "subject": subject, "date": date, "message_id": mid}


class FakeTransport:
    def __init__(self, unread):
        self.unread = list(unread)

    def fetch_unread(self, limit):
        return self.unread[:limit]


class AHeaderIsOneLineCase(unittest.TestCase):
    def test_a_folded_subject_comes_back_unfolded(self):
        msg = message_from_bytes(FOLDED)
        self.assertIn("\r", str(msg.get("Subject")))  # the shape that broke it
        self.assertEqual(mail._header(msg, "Subject"), ACK)

    def test_one_line_strips_every_control_character(self):
        self.assertEqual(mail.one_line("a\r\n\tb\x00c\x7f  d"), "a b c d")


class OneMessageIsNeverTheWholePollCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        r = Path(tmp.name)
        self.root = r
        for target, name, value in (
                (mail, "MAIL_DIR", r / "mail"), (events, "EVENTS_DIR", r / "events"),
                (events, "WATCHERS_DIR", r / "watchers"),
                (communications, "THREADS_DIR", r / "threads"),
                (communications, "MESSAGES_DIR", r / "messages"),
                (communications, "EXPECT_DIR", r / "expect"),
                (policy, "APPROVALS_DIR", r / "approvals"), (policy, "HALT_PATH", r / "halt"),
                (journal, "JOURNAL_PATH", r / "journal.jsonl")):
            p = mock.patch.object(target, name, value); p.start(); self.addCleanup(p.stop)
        mail.MAIL_DIR.mkdir(parents=True, exist_ok=True)
        (mail.MAIL_DIR / "poll-state.json").write_text(
            json.dumps({"version": 1, "seen": []}), encoding="utf-8")

    def inbox(self):
        # Newest first, the way IMAP hands them over; the bad one in the middle.
        return FakeTransport([
            message("Security code for your application to Acme Technologies", "<acme>",
                    "Sun, 13 Sep 2026 05:18:34 +0000"),
            message("Security code for your application to Globex", "<globex>",
                    "Sun, 13 Sep 2026 03:22:38 +0000"),
            message(FOLDED_ACK, "<ack>"),
            message("Security code for your application to Northwind", "<northwind-code>",
                    "Sun, 13 Sep 2026 03:18:05 +0000"),
        ])

    def summaries(self):
        return sorted(e["summary"] for e in events.list_events(events_dir=events.EVENTS_DIR))

    def test_a_subject_with_a_carriage_return_does_not_stop_the_poll(self):
        actions = mail.poll_events(transport=self.inbox())
        self.assertEqual([a["action"] for a in actions], ["received"] * 4)
        self.assertEqual(len(self.summaries()), 4)
        self.assertTrue(all("\r" not in s for s in self.summaries()))
        self.assertIn("Acme Technologies", " ".join(self.summaries()))

    def test_nothing_is_emitted_twice(self):
        t = self.inbox()
        mail.poll_events(transport=t)
        self.assertEqual(mail.poll_events(transport=t), [])
        self.assertEqual(len(self.summaries()), 4)

    def test_a_message_the_bus_refuses_is_skipped_and_the_rest_are_read(self):
        real_emit = events.emit

        def refuse_the_ack(kind, subject, summary, **kw):
            if "Team Northwind" in summary:
                raise ValueError("summary contains control characters")
            return real_emit(kind, subject, summary, **kw)

        t = self.inbox()
        with mock.patch.object(events, "emit", side_effect=refuse_the_ack):
            actions = mail.poll_events(transport=t)
        self.assertEqual(sorted(a["action"] for a in actions),
                         ["received", "received", "received", "skipped"])
        self.assertIn("Acme Technologies", " ".join(self.summaries()))
        # Saved: the next beat neither repeats the three nor retries the one.
        self.assertEqual(mail.poll_events(transport=t), [])
        self.assertEqual(len(self.summaries()), 3)

    def test_the_folded_acknowledgement_still_reaches_the_job_reply_check(self):
        mail.poll_events(transport=FakeTransport([message(FOLDED_ACK, "<ack>")]))
        ledger = {"https://boards.greenhouse.io/embed/job_app?for=northwind&token=2": {
            "id": "apply-nw", "at": "2026-09-13T03:14:50Z", "company": "Northwind",
            "job_title": "Inbound Sales Development Representative — Northwind"}}
        with mock.patch.object(apply_run, "already_sent", return_value=ledger), \
                mock.patch.object(runtime, "notifications") as notes, \
                mock.patch.object(runtime.proactive, "all_rules", return_value=[]), \
                mock.patch.object(runtime, "_scheduling_reply", return_value=None), \
                mock.patch.object(runtime, "_advisor_judgment", return_value=None):
            actions = runtime.process_new_events(
                now=dt.datetime(2026, 9, 13, 13, 0, tzinfo=dt.timezone.utc),
                cursor_path=self.root / "cursor.json")
        replies = [a for a in actions if a["action"] == "job_reply"]
        self.assertEqual(replies, [{"event": replies[0]["event"], "action": "job_reply",
                                    "application": "apply-nw",
                                    "outcome": "acknowledgement"}])
        notes.publish.assert_not_called()


INBOX = [  # newest first; invented employers in the shapes real subjects take
    ("Sun, 13 Sep 2026 05:18:34 +0000",
     "Security code for your application to Acme Technologies", "acmeCD01"),
    ("Sun, 13 Sep 2026 03:27:49 +0000",
     "Security code for your application to Initech, Inc.", "initCD02"),
    ("Sun, 13 Sep 2026 03:22:38 +0000",
     "Security code for your application to Globex", "globCD03"),
    ("Sun, 13 Sep 2026 02:15:24 +0000",
     "Security code for your application to -UMB-", "umbCODE4"),
    ("Sun, 13 Sep 2026 02:13:00 +0000",
     "Security code for your application to Hooli.io", "hooliCD5"),
]
BODY = ("Hi, Copy and paste this code into the security code field on "
        "your application: {} After you enter the code, resubmit your application.")


class CodeTransport:
    def fetch_unread(self, _limit):
        return [{"date": d, "subject": s, "from": "no-reply@ats.example.com",
                 "message_id": c} for d, s, c in INBOX]

    def fetch_body(self, message_id):
        return {"text": BODY.format(message_id)}


class TheEmployerIsNamedTheWayTheEmailNamesItCase(unittest.TestCase):
    def setUp(self):
        for target, name, value in ((mail, "SmtpImapTransport", CodeTransport),
                                    (apply_run, "CODE_WAIT_TRIES", 1),
                                    (apply_run, "CODE_WAIT_S", 0)):
            p = mock.patch.object(target, name, value); p.start(); self.addCleanup(p.stop)

    def test_a_truncated_name_gets_its_full_names_code(self):
        clicked = dt.datetime(2026, 9, 13, 5, 17, 24, tzinfo=dt.timezone.utc).timestamp()
        self.assertEqual(apply_run._emailed_code("Acme ...", since=clicked), "acmeCD01")

    def test_suffixes_and_punctuation_do_not_decide(self):
        for employer, code in (("Initech", "initCD02"), ("UMB", "umbCODE4"),
                               ("Hooli", "hooliCD5"), ("Acme Technologies", "acmeCD01")):
            with self.subTest(employer=employer):
                self.assertEqual(apply_run._emailed_code(employer), code)

    def test_one_employer_still_never_gets_anothers_code(self):
        self.assertEqual(apply_run._emailed_code("Vandelay"), "")
        self.assertFalse(apply_run.names_the_employer(
            "Security code for your application to Globex", "Acme ..."))
        self.assertFalse(apply_run.names_the_employer(
            "Security code for your application to Acme Technologies", "Acme Ventures"))


if __name__ == "__main__":
    unittest.main()
