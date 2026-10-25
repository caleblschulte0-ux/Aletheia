""""I need to change my furnace filter every 3 months" became a task with no
due date (2026-10-25), so "when do I need to change the furnace filter"
could never be a date. It is kept the way the interval reader knows."""
import datetime as dt
import unittest
from unittest import mock

from aletheia import localtime, quick, voice


class HowOftenIsKept(unittest.TestCase):
    def test_said_as_a_need_or_a_chore_it_is_the_interval_note(self):
        for said, note in (
                ("I need to change my furnace filter every 3 months", "the furnace filter should be changed every 3 months"),
                ("the furnace filter needs changing every 3 months", "the furnace filter should be changed every 3 months"),
                ("the water filter needs to be replaced every 6 months", "the water filter should be replaced every 6 months"),
                ("we should clean the gutters every year", "the gutters should be cleaned every year"),
                ("I need to empty the dehumidifier every two days", "the dehumidifier should be emptied every two days")):
            self.assertEqual(voice._interpret(said)["command"], {"kind": "note", "text": note}, said)

    def test_a_call_and_an_it_are_not_maintenance(self):
        self.assertNotEqual((voice._interpret("I need to call mom every week")["command"] or {}).get("kind"), "note")
        got = (voice._interpret("it needs changing every week") or {}).get("command") or {}
        self.assertNotEqual(got.get("text"), "the it should be changed every week")

    def test_every_year_with_no_number_comes_due_a_year_on(self):
        done = dt.datetime(2026, 10, 24, 15, tzinfo=dt.timezone.utc)
        notes = [{"text": "I cleaned the gutters yesterday", "ts": (done + dt.timedelta(days=1)).isoformat()},
                 {"text": "the gutters should be cleaned every year", "ts": done.isoformat()}]
        with mock.patch.object(quick, "_notes", return_value=notes), \
                mock.patch.object(localtime, "operator_tz", return_value=dt.timezone.utc):
            due, doing, _said, last = quick._interval_due("gutters")
        self.assertEqual((due, doing, last), (dt.date(2027, 10, 24), "clean the gutters", dt.date(2026, 10, 24)))


if __name__ == "__main__":
    unittest.main()
