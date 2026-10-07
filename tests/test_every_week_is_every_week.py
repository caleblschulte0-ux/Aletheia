"""A repeat is never set as a one-off, and a few facts about him are sums."""
import datetime as dt
import unittest
from unittest import mock

from aletheia import quick, voice


def cmd(said):
    return (voice._interpret(said) or {}).get("command") or {}


class EveryWeekIsEveryWeek(unittest.TestCase):
    def test_every_tuesday_night_is_weekly(self):
        self.assertEqual(cmd("remind me to take out the trash every tuesday night"),
                         {"kind": "remind_weekly", "days": ["tuesday"], "time": "21:00",
                          "text": "take out the trash"})

    def test_a_bare_evening_hour(self):
        self.assertEqual(cmd("remind me to water the plants every monday and thursday at 6")["time"], "18:00")

    def test_every_morning_is_daily(self):
        self.assertEqual(cmd("remind me to stretch every morning"),
                         {"kind": "remind_daily", "time": "09:00", "text": "stretch"})

    def test_a_repeat_it_cannot_read_is_never_a_one_off(self):
        for said in ("remind me to call mom every other sunday", "remind me to run every other day at 6"):
            self.assertNotEqual(cmd(said).get("kind"), "remind_at", said)

    def test_one_sunday_is_still_one_sunday(self):
        self.assertEqual(cmd("remind me to call mom on sunday").get("kind"), "remind_at")


class HisBirthday(unittest.TestCase):
    def test_saying_it_remembers_it(self):
        self.assertEqual(cmd("my birthday is march 3rd 1995"),
                         {"kind": "remember", "domain": "identity", "key": "birthday", "value": "march 3rd 1995"})

    def test_how_old_am_i(self):
        held = {"identity": {"birthday": {"value": "march 3rd 1995"}}}
        with mock.patch("aletheia.memory.everything", return_value=held):
            said = quick.answer("how old am i")
        today = dt.date.today()
        self.assertIn(f"You're {today.year - 1995 - ((today.month, today.day) < (3, 3))}", said)

    def test_none_on_file_says_how_to_tell_her(self):
        with mock.patch("aletheia.memory.everything", return_value={}):
            self.assertIn("my birthday is", quick.answer("when is my birthday"))


class Sums(unittest.TestCase):
    def test_a_tip(self):
        self.assertEqual(quick.answer("what's a 20% tip on 45"), "$9.00 tip, $54.00 total.")

    def test_weeks_until(self):
        self.assertRegex(quick.answer("how many weeks until christmas") or "", r"weeks?.*25 December")


if __name__ == "__main__":
    unittest.main()
