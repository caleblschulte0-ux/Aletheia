"""It typed an hour-old code into the box and the form said no.

2026-09-12. Stripe, GitLab and Scale AI went in; Databricks (twice) and
Reddit came back, and the screenshots said it in red::

    Incorrect security code

The codes typed were real. They were just the WRONG ONES — the oldest in
the inbox rather than the one the page had asked for seconds earlier:

    Reddit      typed ApHIj2MW (15:46)   page had asked with z40RQw7h (16:07)
    Databricks  typed gOF5SXbK (14:45)   page had asked with sPmVR8cI (16:06)

The lookup walked `reversed(mine)` on the belief that IMAP returns
oldest-first. It returns NEWEST-first, so reversing it walked deliberately
to the stalest code every time. The three that worked had exactly one
unread code each, where oldest and newest are the same message — which is
why it looked like it worked.

So: sort by the date header and take the newest, never trust the order a
server happens to return. And a code is per application, so the employer
has to be part of the choice: Databricks' code in Reddit's form fails in a
way that looks identical to a wrong code.

The fixture below is the real inbox from that afternoon — eleven security
codes, five of them Databricks.
"""
from __future__ import annotations

import unittest
from unittest import mock

from aletheia import apply_run

INBOX = [   # exactly as IMAP returned them: newest first
    ("Sat, 12 Sep 2026 16:07:43 +0000", "Security code for your application to Scale AI", "inzVaCYK"),
    ("Sat, 12 Sep 2026 16:07:17 +0000", "Security code for your application to Reddit", "z40RQw7h"),
    ("Sat, 12 Sep 2026 16:06:46 +0000", "Security code for your application to Databricks", "sPmVR8cI"),
    ("Sat, 12 Sep 2026 16:06:21 +0000", "Security code for your application to Databricks", "WCVS0dDj"),
    ("Sat, 12 Sep 2026 16:04:20 +0000", "Security code for your application to GitLab", "gDbSBg37"),
    ("Sat, 12 Sep 2026 16:02:32 +0000", "Security code for your application to Stripe", "T6OTB1b1"),
    ("Sat, 12 Sep 2026 15:46:46 +0000", "Security code for your application to Reddit", "ApHIj2MW"),
    ("Sat, 12 Sep 2026 15:46:18 +0000", "Security code for your application to Databricks", "1GBUyU9G"),
    ("Sat, 12 Sep 2026 15:38:42 +0000", "Security code for your application to Databricks", "kwsGIRvz"),
    ("Sat, 12 Sep 2026 15:12:01 +0000", "Security code for your application to Databricks", "gOF5SXbK"),
    ("Sat, 12 Sep 2026 14:45:54 +0000", "Security code for your application to Databricks", "oLDeSTc1"),
]
BODY = ("Hi Caleb, Copy and paste this code into the security code field on "
        "your application: {} After you enter the code, resubmit your "
        "application. (c) 2026 Greenhouse 18 West 18th Street, New York")


class FakeTransport:
    def __init__(self, rows=INBOX):
        self.rows = list(rows)

    def fetch_unread(self, _limit):
        return [{"date": d, "subject": s, "from": "no-reply@us.greenhouse-mail.io",
                 "message_id": code} for d, s, code in self.rows]

    def fetch_body(self, message_id):
        return {"text": BODY.format(message_id)}


class TheNewestCodeWinsCase(unittest.TestCase):
    def setUp(self):
        from aletheia import mail
        p = mock.patch.object(mail, "SmtpImapTransport", FakeTransport)
        p.start()
        self.addCleanup(p.stop)
        for name, value in (("CODE_WAIT_TRIES", 1), ("CODE_WAIT_S", 0)):
            p = mock.patch.object(apply_run, name, value)
            p.start()
            self.addCleanup(p.stop)

    def test_the_code_the_page_just_asked_with(self):
        """Five Databricks codes in the inbox; only the newest is current."""
        self.assertEqual(apply_run._emailed_code("Databricks"), "sPmVR8cI")

    def test_reddits_newest_not_reddits_oldest(self):
        self.assertEqual(apply_run._emailed_code("Reddit"), "z40RQw7h")

    def test_one_employer_never_gets_anothers_code(self):
        for employer, expected in (("Stripe", "T6OTB1b1"),
                                   ("GitLab", "gDbSBg37"),
                                   ("Scale AI", "inzVaCYK")):
            with self.subTest(employer=employer):
                self.assertEqual(apply_run._emailed_code(employer), expected)

    def test_the_order_the_server_returns_does_not_decide(self):
        """The real defect: it trusted IMAP's ordering and got it backwards."""
        from aletheia import mail
        with mock.patch.object(mail, "SmtpImapTransport",
                               lambda: FakeTransport(list(reversed(INBOX)))):
            self.assertEqual(apply_run._emailed_code("Databricks"), "sPmVR8cI")

    def test_an_employer_with_no_code_gets_nothing(self):
        self.assertEqual(apply_run._emailed_code("Anthropic"), "")

    def test_an_unreadable_date_never_wins(self):
        rows = [("not a date", "Security code for your application to Figma", "BROKEN01"),
                ("Sat, 12 Sep 2026 16:07:43 +0000",
                 "Security code for your application to Figma", "GOOD0002")]
        from aletheia import mail
        with mock.patch.object(mail, "SmtpImapTransport", lambda: FakeTransport(rows)):
            self.assertEqual(apply_run._emailed_code("Figma"), "GOOD0002")


if __name__ == "__main__":
    unittest.main()
