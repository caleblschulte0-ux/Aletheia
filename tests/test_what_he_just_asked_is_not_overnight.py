""""Good morning. Overnight: Marked done: call the bank; Set a reminder for
today at 12:19 pm: stretch" (2026-10-16, every model off): what he asked
for two minutes earlier is not news from the night. And "when's my next
reminder" said "submit my timesheet" one turn after "I'll remind you:
submit your timesheet"; "how long until Friday" on a Friday said "7 days"
as if he had lost track of the week."""
import datetime as dt
import unittest
from unittest import mock

from aletheia import converse, intercom, quick, recollection


def _stamp(minutes_ago: float) -> str:
    at = dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=minutes_ago)
    return at.strftime("%Y-%m-%dT%H:%M:%SZ")


class WhatHeJustAsked(unittest.TestCase):
    def _overnight(self, rows, turns):
        with mock.patch.object(quick, "_sent_records", return_value=[]), \
                mock.patch.object(recollection, "_read_journal", return_value=(rows, None)), \
                mock.patch.object(recollection, "_something_she_did", return_value=True), \
                mock.patch.object(recollection, "_row", side_effect=lambda e: e), \
                mock.patch.object(converse, "recent", return_value=turns):
            return quick._overnight()

    def test_this_conversation_is_left_out(self):
        # An hour ago is always after ten last night: the window starts two
        # to twenty-six hours back. Five hours was before it just after midnight.
        rows = [{"ts": _stamp(60), "what": "Sent the weekly summary"},
                {"ts": _stamp(3), "what": "Marked done: call the bank"}]
        turns = [{"at": _stamp(2.5), "he_asked": "i called the bank", "she_answered": "Done: call the bank."}]
        said = self._overnight(rows, turns)
        self.assertIn("weekly summary", said)
        self.assertNotIn("call the bank", said)

    def test_only_this_conversation_is_still_a_quiet_night_and_says_so(self):
        rows = [{"ts": _stamp(3), "what": "Marked done: call the bank"}]
        turns = [{"at": _stamp(2.5), "he_asked": "i called the bank", "she_answered": "Done: call the bank."}]
        said = self._overnight(rows, turns)
        self.assertTrue(said.startswith("A quiet night"), said)
        self.assertIn("what you've just asked me", said)

    def test_an_old_conversation_does_not_hide_the_night(self):
        rows = [{"ts": _stamp(60), "what": "Marked done: call the bank"}]
        turns = [{"at": _stamp(400), "he_asked": "hi", "she_answered": "Hi."}]
        self.assertIn("call the bank", self._overnight(rows, turns))

    def test_a_chain_of_turns_counts_back_to_its_start(self):
        rows = [{"ts": _stamp(40), "what": "Added a task: call bob"}]
        turns = [{"at": _stamp(39), "he_asked": "a", "she_answered": "b"},
                 {"at": _stamp(25), "he_asked": "c", "she_answered": "d"},
                 {"at": _stamp(10), "he_asked": "e", "she_answered": "f"}]
        self.assertNotIn("call bob", self._overnight(rows, turns))


class HisWordsInHerMouth(unittest.TestCase):
    def test_the_next_reminder_says_your(self):
        row = {"id": "r1", "kind": "once", "at": "2026-10-17T17:00:00+00:00",
               "command": {"kind": "notify", "text": "submit my timesheet"}}
        self.assertTrue(intercom._reminder_words(row).startswith("submit your timesheet"))


class FridayOnAFriday(unittest.TestCase):
    def test_it_says_today_first(self):
        from aletheia import localtime
        today = dt.datetime.now(localtime.operator_tz()).date()
        name = today.strftime("%A").lower()
        said = quick._until(name)
        self.assertTrue(said.startswith(f"It's {name.capitalize()} today."), said)
        self.assertIn("7 days", said)


if __name__ == "__main__":
    unittest.main()
