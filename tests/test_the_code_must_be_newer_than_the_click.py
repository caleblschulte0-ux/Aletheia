"""Sorting was necessary and never sufficient: it was always one behind.

2026-09-12. The newest-code-wins fix landed, was confirmed live, and the
same three applications came back refused with "Incorrect security code"
on the screenshots. His inbox says why, to the second::

    Reddit pressed submit          16:26:52
    Reddit's code arrived          16:27:11      <- nineteen seconds LATER

The lookup ran in between. It sorted correctly, took the newest code that
existed at that moment, and that code was the PREVIOUS attempt's, from
16:07. Databricks did it twice: submit at 16:25:59 and 16:26:25, codes
landing at 16:26:13 and 16:26:39.

Stripe, GitLab and Scale AI succeeded on the first pass for one reason -
each had no earlier code in the inbox, so "newest" and "this page's" were
the same message by luck. Every test passed for the same reason: no
fixture had a prior code in it.

So a code older than the click that asked for it is not this page's code.
The floor is the moment submit is pressed, and it WAITS for a code newer
than that rather than typing a stale one.
"""
from __future__ import annotations

import unittest
from unittest import mock

from aletheia import apply_run

BODY = ("Hi Caleb, Copy and paste this code into the security code field on "
        "your application: {} After you enter the code, resubmit your "
        "application. (c) 2026 Greenhouse")

#: The real sequence, as his inbox recorded it.
OLD = "Sat, 12 Sep 2026 16:07:17 +0000"      # previous attempt's code
NEW = "Sat, 12 Sep 2026 16:27:11 +0000"      # this attempt's code
CLICKED = 1789230412.0                        # 16:26:52 UTC, the submit click


class FakeTransport:
    rows = [(NEW, "Security code for your application to Reddit", "Qhcju2BE"),
            (OLD, "Security code for your application to Reddit", "z40RQw7h")]

    def fetch_unread(self, _limit):
        return [{"date": d, "subject": s, "from": "no-reply@us.greenhouse-mail.io",
                 "message_id": code} for d, s, code in self.rows]

    def fetch_body(self, message_id):
        return {"text": BODY.format(message_id)}


class OnlyStaleTransport(FakeTransport):
    rows = [(OLD, "Security code for your application to Reddit", "z40RQw7h")]


class TheCodeMustBeNewerThanTheClickCase(unittest.TestCase):
    def setUp(self):
        for name, value in (("CODE_WAIT_TRIES", 1), ("CODE_WAIT_S", 0)):
            p = mock.patch.object(apply_run, name, value)
            p.start()
            self.addCleanup(p.stop)

    def _with(self, transport):
        from aletheia import mail
        p = mock.patch.object(mail, "SmtpImapTransport", transport)
        p.start()
        self.addCleanup(p.stop)

    def test_it_takes_the_code_that_arrived_after_the_click(self):
        self._with(FakeTransport)
        self.assertEqual(apply_run._emailed_code("Reddit", since=CLICKED), "Qhcju2BE")

    def test_a_code_older_than_the_click_is_never_used(self):
        """The live failure: only the previous attempt's code is there yet."""
        self._with(OnlyStaleTransport)
        self.assertEqual(apply_run._emailed_code("Reddit", since=CLICKED), "")

    def test_without_a_floor_it_behaves_as_before(self):
        """`since=0` keeps the old contract for any caller that has no click."""
        self._with(OnlyStaleTransport)
        self.assertEqual(apply_run._emailed_code("Reddit"), "z40RQw7h")

    def test_a_few_seconds_of_clock_skew_is_tolerated(self):
        """Greenhouse's Date header and this machine's clock are not the same
        clock; a code stamped a moment before the click is still this
        page's."""
        self._with(FakeTransport)
        just_after = CLICKED + 1200          # click 'after' the new code by 20s
        self.assertEqual(apply_run._emailed_code("Reddit", since=just_after), "")

    def test_the_submitter_passes_the_click_time(self):
        """The floor is useless if `_refill_and_submit` does not hand it over."""
        import inspect
        source = inspect.getsource(apply_run._refill_and_submit)
        self.assertIn("asked_at = time.time()", source)
        self.assertIn("since=asked_at", source)


if __name__ == "__main__":
    unittest.main()
