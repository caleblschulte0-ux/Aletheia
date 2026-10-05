"""Thirty-first sandbox batch, 2026-10-05: his place and clock, letters, chance,
and date arithmetic - nine model turns for what code knows.

    > where am I / what's my timezone / what time zone are you in     three models
    > set my city to Springfield / I'm in central time                the planner, approvals
    > what's 3pm my time in london / when it's 9am in tokyo ...       two models
    > spell necessary                                                 [8.5s]
    > flip a coin / roll a die / pick a number between 1 and 10       three models
    > the date in 30 days / 10 days ago / days since january 1        three models
"""
import datetime as dt
import unittest
from unittest import mock
from zoneinfo import ZoneInfo

from aletheia import localtime, quick, voice


class HisPlaceAndClock(unittest.TestCase):
    def test_the_sentences_compile(self):
        self.assertEqual(voice.interpret("set my city to Springfield")["command"], {"kind": "profile_set", "field": "city", "value": "Springfield"})
        self.assertEqual(voice.interpret("I'm in central time")["command"],
                         {"kind": "remember", "domain": "identity", "key": "timezone", "value": "America/Chicago", "about": "your time zone"})
        self.assertEqual(voice.interpret("my timezone is eastern")["command"]["value"], "America/New_York")

    def test_where_am_i_and_the_zone(self):
        with mock.patch("aletheia.profile.answer", side_effect=lambda f: {"city": "Springfield", "state": "XX"}.get(f, "")):
            self.assertEqual(quick.answer("where am i"), "I can't see where you are. Your city on file is Springfield, XX.")
        with mock.patch("aletheia.localtime.operator_timezone", return_value="America/Chicago"), \
             mock.patch("aletheia.localtime.operator_tz", return_value=ZoneInfo("America/Chicago")):
            said = quick.answer("what's my timezone")
        self.assertTrue(said.startswith("Central time - it's "), said)

    def test_a_clock_read_in_the_other_zone(self):
        with mock.patch("aletheia.localtime.operator_tz", return_value=ZoneInfo("America/Chicago")):
            london = quick.answer("what's 3pm my time in london")
            here = quick.answer("when it's 9am in tokyo what time is it here")
        self.assertRegex(london, r"^3 pm your time is (8|9) pm in London\.$")
        self.assertRegex(here, r"^9 am in Tokyo is (6|7) pm the day before for you\.$")


class LettersChanceAndDates(unittest.TestCase):
    def test_spelling_and_chance(self):
        self.assertEqual(quick.answer("spell necessary"), "Necessary: N, E, C, E, S, S, A, R, Y.")
        self.assertIn(quick.answer("flip a coin"), ("Heads.", "Tails."))
        self.assertRegex(quick.answer("roll a die"), r"^[1-6]\.$")
        self.assertRegex(quick.answer("roll two dice"), r"^[1-6] and [1-6] - \d+ together\.$")
        self.assertRegex(quick.answer("pick a number between 1 and 10"), r"^(10|[1-9])\.$")

    def test_date_arithmetic_on_his_calendar(self):
        today = localtime.today()
        ahead = today + dt.timedelta(days=30)
        self.assertEqual(quick.answer("what's the date in 30 days"),
                         f"{ahead.strftime('%A')} the {quick._ordinal(ahead.day)} of {ahead.strftime('%B')}" + (f" {ahead.year}" if ahead.year != today.year else "") + ".")
        back = today - dt.timedelta(days=10)
        self.assertTrue(quick.answer("what day was it 10 days ago").startswith(back.strftime("%A")))
        since = quick.answer("how many days since january 1")
        self.assertRegex(since, r"^\d+ days, since \w+ the 1st of January( \d{4})?\.$")


if __name__ == "__main__":
    unittest.main()
