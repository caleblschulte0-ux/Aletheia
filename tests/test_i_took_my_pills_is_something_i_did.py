""""I took my pills", "I called mom", "I paid the rent", then "what did I do
today" answered "Nothing ticked off your list today" (2026-10-28): only
"I finished/did ..." counted. Something he told her he did is something he did."""
import datetime as dt
import unittest
from unittest import mock

from aletheia import quick, tasks


class WhatHeToldHerHeDid(unittest.TestCase):
    def said(self, *notes):
        now = dt.datetime.now(dt.timezone.utc).isoformat()
        rows = [{"text": t, "ts": now} for t in notes]
        with mock.patch.object(quick, "_notes", return_value=rows), mock.patch.object(tasks, "all_tasks", return_value=[]):
            return quick._tasks_done("")

    def test_other_verbs_count(self):
        got = self.said("I called mom", "I paid the rent", "I went to the gym")
        for part in ("called mom", "paid the rent", "went to the gym"):
            self.assertIn(part, got)
        self.assertTrue(got.startswith("Nothing ticked off your list today, but you told me you"), got)

    def test_the_pills_note_reads_in_his_voice(self):
        got = self.said("took my pills")
        self.assertIn("you took your pills", got)

    def test_a_note_that_is_not_a_deed_is_not_read_as_one(self):
        self.assertEqual(self.said("I parked on level 3", "my locker is 42"), "Nothing ticked off your list today.")


if __name__ == "__main__":
    unittest.main()
