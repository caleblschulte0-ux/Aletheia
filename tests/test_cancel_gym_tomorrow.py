""""Cancel gym tomorrow", "skip date night", "what time is church Sunday" and
"how many things do I have this weekend" all went to a model or the planner
(2026-10-23) while the holds they named were hers, pencilled in a turn before.
"""
import datetime as dt
import unittest
from unittest import mock

from aletheia import calendar, localtime, quick, voice


class CancelGymTomorrow(unittest.TestCase):
    def setUp(self):
        tz = localtime.operator_tz()
        today = dt.datetime.now(tz).date()
        tomorrow = today + dt.timedelta(days=1)
        sunday = today + dt.timedelta(days=(6 - today.weekday()) % 7 or 7)
        at = lambda d, h: dt.datetime.combine(d, dt.time(h, 0), tzinfo=tz).isoformat()  # noqa: E731
        self.events = [
            {"id": "g", "title": "gym", "start": at(tomorrow, 18), "end": at(tomorrow, 19),
             "status": "TENTATIVE", "source": "hold:voice"},
            {"id": "d", "title": "date night", "start": at(tomorrow, 19), "end": at(tomorrow, 20),
             "status": "TENTATIVE", "source": "hold:voice"},
            {"id": "c", "title": "church", "start": at(sunday, 10), "end": at(sunday, 11),
             "status": "TENTATIVE", "source": "hold:voice"},
        ]
        self.sunday = sunday
        patcher = mock.patch.object(calendar, "all_events", return_value=self.events)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _cmd(self, sentence):
        return voice.interpret(sentence).get("command") or {}

    def test_cancel_with_the_day_takes_her_hold_off(self):
        cmd = self._cmd("cancel gym tomorrow")
        self.assertEqual(cmd.get("kind"), "hold_release", cmd)
        self.assertEqual(cmd.get("title"), "gym")

    def test_skip_is_cancel_for_her_own_hold(self):
        cmd = self._cmd("skip date night")
        self.assertEqual((cmd.get("kind"), cmd.get("title")), ("hold_release", "date night"))

    def test_the_wrong_day_is_said_not_guessed(self):
        out = voice.interpret("cancel gym today")
        self.assertIsNone(out.get("command"))
        self.assertIn("not today", out.get("say") or "")

    def test_skip_names_nothing_of_hers_and_steps_aside(self):
        self.assertNotEqual(self._cmd("skip this song").get("kind"), "hold_release")

    def test_what_time_with_the_day_named(self):
        self.assertIn("10 am", quick.answer("what time is church sunday") or "")

    def test_how_many_things_reads_the_weekend(self):
        said = quick.answer("how many things do i have tomorrow") or ""
        self.assertIn("gym", said)
        self.assertIn("date night", said)


if __name__ == "__main__":
    unittest.main()
