""""Move my doctor's appointment to Friday", with nothing by that name.

2026-10-29, talking to her with the models off:

    > move my doctor's appointment to friday
      I don't see doctor's appointment on your calendar. ...

His "my" was eaten, and "lunch with Bob" came back as "lunch with bob".
"""
import unittest
from unittest import mock

from aletheia import calendar, voice


class NotOnHisCalendar(unittest.TestCase):
    def _say(self, sentence):
        with mock.patch.object(calendar, "all_events", return_value=[]), \
                mock.patch.object(voice, "_her_upcoming_holds", return_value=[]):
            return voice.interpret(sentence)["say"]

    def test_his_my_comes_back_as_your(self):
        said = self._say("move my doctor's appointment to friday")
        self.assertTrue(said.startswith("I don't see your doctor's appointment on your calendar."), said)

    def test_a_name_keeps_its_capital(self):
        said = self._say("move lunch with Bob to 12")
        self.assertTrue(said.startswith("I don't see lunch with Bob on your calendar."), said)


if __name__ == "__main__":
    unittest.main()
