"""Saying "approve" would have shut her down.

Found by looking at his actual wall on 2026-09-09. The headline, in the
largest text on the page:

    1 decision waiting: Fully shut down Aletheia / stop her from
    listening entirely

Requested 2026-09-05 - four days earlier - with this recorded reason:

    operator said: "spoken to the wall: thea I said Alithia, like your
    name, the program that ..."

He was talking ABOUT her name. It compiled into a shutdown request and
then sat there. And because it was the ONLY pending approval, a bare
"approve" - said four days later, about anything at all - would have run
it without a question, because one pending item was treated as
unambiguous.

One pending item IS unambiguous about which. It is not evidence that he
knows what it is. "Approve" answers something he has just been told, and
after a few minutes that assumption is gone.
"""
from __future__ import annotations

import datetime as dt
import unittest
from unittest import mock

from aletheia import voice


def approval(*, minutes_ago=None, days_ago=None, stamp=True,
             consequence="Remember your landlord is Dana"):
    value = {"id": "intent-x", "state": "PENDING",
             "requested_action": "run 1 step(s): note",
             "consequence": consequence}
    if stamp:
        gap = dt.timedelta(minutes=minutes_ago or 0, days=days_ago or 0)
        value["requested_at"] = (dt.datetime.now(dt.timezone.utc) - gap).isoformat()
    return value


class ABareYesCase(unittest.TestCase):
    def _ask(self, pending):
        with mock.patch("aletheia.policy.all_approvals", return_value=pending), \
             mock.patch.object(voice, "_approve_by_voice",
                               return_value={"command": {"kind": "approve"},
                                             "say": None}) as ran:
            said = voice.interpret("approve") or {}
        return ran.called, (said.get("say") or "")

    def test_something_just_asked_still_runs_on_a_bare_yes(self):
        """The ordinary case, and it must not get slower or chattier."""
        ran, _ = self._ask([approval(minutes_ago=0)])
        self.assertTrue(ran)

    def test_inside_the_window_still_runs(self):
        ran, _ = self._ask([approval(
            minutes_ago=voice.ANSWERING_WINDOW_MINUTES - 1)])
        self.assertTrue(ran)

    def test_past_the_window_asks_instead_of_running(self):
        ran, said = self._ask([approval(
            minutes_ago=voice.ANSWERING_WINDOW_MINUTES + 1)])
        self.assertFalse(ran)
        self.assertIn("approve that", said)

    def test_the_four_day_old_shutdown_is_not_run_by_a_bare_yes(self):
        """The exact thing that was sitting on his wall."""
        ran, said = self._ask([approval(
            days_ago=4, consequence="Fully shut down Aletheia")])
        self.assertFalse(ran, "a bare yes shut her down")
        self.assertIn("Fully shut down Aletheia", said)
        self.assertIn("4 days ago", said)

    def test_it_says_how_old_so_he_can_tell(self):
        """"From four days ago" is the part that makes him stop."""
        _ran, said = self._ask([approval(days_ago=2)])
        self.assertIn("2 days ago", said)
        _ran, said = self._ask([approval(minutes_ago=200)])
        self.assertIn("hour", said)

    def test_an_unreadable_timestamp_is_not_treated_as_fresh(self):
        """The safe mistake is asking which one, never running the wrong one."""
        for broken in ({"id": "x", "state": "PENDING",
                        "requested_action": "run 1 step(s): note",
                        "consequence": "something"},
                       {"id": "x", "state": "PENDING", "requested_at": "not a date",
                        "requested_action": "run 1 step(s): note",
                        "consequence": "something"}):
            with self.subTest(approval=broken):
                ran, _said = self._ask([broken])
                self.assertFalse(ran)

    def test_it_still_names_what_he_would_be_agreeing_to(self):
        _ran, said = self._ask([approval(days_ago=1,
                                         consequence="Send Dana the report")])
        self.assertIn("Send Dana the report", said)

    def test_the_sentence_is_sayable(self):
        _ran, said = self._ask([approval(days_ago=3)])
        self.assertNotIn("intent-", said)
        self.assertNotIn("{", said)
        self.assertTrue(said.strip().endswith("."), said)


class HowLongAgoCase(unittest.TestCase):
    def test_it_reads_like_a_person_would_say_it(self):
        self.assertIn("day", voice._how_long_ago(approval(days_ago=3)))
        self.assertIn("hour", voice._how_long_ago(approval(minutes_ago=120)))
        self.assertIn("few minutes", voice._how_long_ago(approval(minutes_ago=2)))

    def test_a_missing_timestamp_does_not_crash_the_sentence(self):
        self.assertTrue(voice._how_long_ago({}).strip())


if __name__ == "__main__":
    unittest.main()
