""""Do I have time for lunch before my haircut" answered about TODAY while
the haircut was Saturday, and "what's after my haircut" went to a model
(2026-10-23). The day of the thing he named, around it.
"""
import datetime as dt
import unittest
from unittest import mock

from aletheia import calendar, localtime, quick, voice


class BeforeAndAfterMyHaircut(unittest.TestCase):
    def setUp(self):
        tz = localtime.operator_tz()
        day = dt.datetime.now(tz).date() + dt.timedelta(days=2)
        at = lambda h: dt.datetime.combine(day, dt.time(h, 0), tzinfo=tz)  # noqa: E731
        self.events = [
            {"id": "a", "title": "coffee with Jo", "start": at(8).isoformat(), "end": at(9).isoformat()},
            {"id": "b", "title": "haircut", "start": at(10).isoformat(), "end": at(11).isoformat()},
            {"id": "c", "title": "lunch with Sam", "start": at(13).isoformat(), "end": at(14).isoformat()},
        ]
        patcher = mock.patch.object(calendar, "all_events", return_value=self.events)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_the_free_time_rule_leaves_it_alone(self):
        self.assertNotEqual((voice.interpret("do I have time for lunch before my haircut").get("command") or {}).get("kind"),
                            "free_time")

    def test_whats_after_it(self):
        said = quick.answer("what's after my haircut")
        self.assertIn("lunch with Sam at 1 pm", said)

    def test_whats_before_it(self):
        self.assertIn("coffee with Jo at 8 am", quick.answer("what's before my haircut"))

    def test_time_between_it_and_the_next_thing(self):
        said = quick.answer("do I have time for a nap after my haircut")
        self.assertIn("2 hours free between them", said)

    def test_time_before_it(self):
        said = quick.answer("do I have time for breakfast before my haircut")
        self.assertIn("an hour free between them", said)

    def test_nothing_called_that_is_left_to_a_model(self):
        self.assertIsNone(quick.answer("what's after my dentist appointment"))


if __name__ == "__main__":
    unittest.main()
