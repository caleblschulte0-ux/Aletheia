""""Every other Tuesday" is listed as every other Tuesday (2026-10-12).

It was listed as "every 2 weeks at 6 pm", the day gone; "every 3 weeks on
Friday" went to the planner; and "when is my grandma reminder" said
"next tomorrow at 6 pm".
"""
import unittest
from unittest import mock

from aletheia import intercom, policy, voice


def spec(weeks, anchor):
    return {"id": "remind-every-1", "kind": "interval", "every_minutes": weeks * 10080, "anchor": anchor,
            "enabled": True, "command": {"kind": "notify_operator", "text": "call grandma"}}


class ListedWithItsDay(unittest.TestCase):
    def test_every_other_tuesday(self):
        # His zone is US Central; the day reads the same anywhere from UTC-12 to UTC.
        self.assertEqual(intercom._reminder_words(spec(2, "2026-10-13T18:00:00-05:00")), "call grandma — every other Tuesday at 6 pm")

    def test_every_three_weeks(self):
        self.assertEqual(intercom._reminder_words(spec(3, "2026-10-16T09:00:00-05:00")),
                         "call grandma — every 3 weeks on Friday at 9 am")

    def test_every_other_day_unchanged(self):
        row = {**spec(1, "2026-10-13T18:00:00-05:00"), "every_minutes": 2880}
        self.assertEqual(intercom._reminder_words(row), "call grandma — every other day at 6 pm")


class EveryThreeWeeksOnFriday(unittest.TestCase):
    def test_compiles(self):
        with mock.patch.object(policy, "all_approvals", return_value=[]):
            got = voice.interpret("thea remind me every 3 weeks on friday at 9am to water the cactus")["command"]
        self.assertEqual((got["kind"], got["days"], got["every"], got["time"]), ("remind_weekly", ["friday"], 3, "09:00"))


if __name__ == "__main__":
    unittest.main()
