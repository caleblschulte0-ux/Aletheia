"""Talked to her, 2026-10-12: "do I have any interviews" answered from the calendar and "when's my
interview" went to a model, because the reader only knew "when 's" with a space."""

import datetime as dt
import unittest
from unittest import mock

from aletheia import quick


class WhensMyInterview(unittest.TestCase):

    def test_every_way_of_asking_when_is_the_calendar(self):
        at = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=1)).isoformat()
        with mock.patch("aletheia.calendar.all_events", return_value=[{"title": "an interview with Via", "start": at}]):
            for asked in ("when's my interview", "When is my interview?", "whens my interview again",
                          "when is the Via interview", "what time is my interview", "when's my next interview",
                          "what's the time of my interview", "when is my interview with via"):
                self.assertTrue((quick.answer(asked) or "").startswith("Your interview with Via is"), asked)

    def test_other_whens_are_left_alone(self):
        self.assertNotEqual((quick.match("when's my dentist appointment") or ("",))[0], "interview_when")
        self.assertNotEqual((quick.match("when is my interview prep") or ("",))[0], "interview_when")


if __name__ == "__main__":
    unittest.main()
