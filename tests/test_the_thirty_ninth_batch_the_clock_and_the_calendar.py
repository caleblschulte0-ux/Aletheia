"""Thirty-ninth sandbox batch, 2026-10-05: the clock and the calendar, from
arithmetic - nine model turns of four to five seconds each.

    > what time is it in an hour / what's 3 hours from now / how long until 5
    > is it morning or evening / is it the weekend / what quarter is it
    > how many days left in the month / in the year / how many weeks until christmas
    > what time did I ask you that
"""
import datetime as dt
import unittest
from unittest import mock
from zoneinfo import ZoneInfo

from aletheia import quick

TZ = ZoneInfo("America/Chicago")


class TheClock(unittest.TestCase):
    def test_moved_forward_and_back(self):
        with mock.patch("aletheia.localtime.operator_tz", return_value=TZ):
            now = dt.datetime.now(TZ)
            ahead = quick.answer("what time is it in an hour")
            back = quick.answer("what time was it 2 hours ago")
        self.assertRegex(ahead, r"^It'll be \d{1,2}(:\d{2})? [ap]m( tomorrow)?\.$")
        self.assertRegex(back, r"^\d{1,2}(:\d{2})? [ap]m( yesterday)?\.$")
        self.assertIn(quick._clock_words(now + dt.timedelta(hours=1)), ahead)

    def test_until_a_time_reads_a_bare_hour_the_way_a_person_means_it(self):
        with mock.patch("aletheia.localtime.operator_tz", return_value=TZ):
            bare = quick.answer("how long until 5")
            noon = quick.answer("how long until noon")
        self.assertRegex(bare, r"^.+, until 5 [ap]m( tomorrow)?\. If you mean 5 [ap]m, that's .+\.$")
        self.assertNotIn("until 5 am.", bare.split(" If")[0] + ".")   # the small hours are never the first reading
        self.assertRegex(noon, r"^.+, until 12 pm( tomorrow)?\.$")

    def test_the_part_of_the_day_and_the_weekend(self):
        with mock.patch("aletheia.localtime.operator_tz", return_value=TZ):
            part = quick.answer("is it morning or evening")
            weekend = quick.answer("is it the weekend")
        self.assertRegex(part, r"^(Morning|Afternoon|Evening|Night) - it's .+ on \w+day\.$")
        self.assertRegex(weekend, r"^(Yes, it's (Saturday|Sunday) - the weekend|No, it's \w+day; the weekend is \d day(s)? away)")


class TheCalendar(unittest.TestCase):
    def test_quarter_days_left_and_weeks_until(self):
        with mock.patch("aletheia.localtime.today", return_value=dt.date(2026, 10, 4)):
            self.assertEqual(quick.answer("what quarter is it"), "The fourth quarter of 2026, which runs to the end of December.")
            self.assertEqual(quick.answer("how many days left in the month"), "27 days after today; the month ends Saturday the 31st of October.")
            self.assertEqual(quick.answer("how many days left in the year"), "88 days after today; the year ends Thursday the 31st of December.")
            self.assertEqual(quick.answer("how many weeks until christmas"), "11 weeks and 5 days - 82 days, Friday 25 December.")
            self.assertEqual(quick.answer("how many days until christmas"), "82 days, Friday 25 December.")

    def test_when_he_asked_is_the_threads_stamp(self):
        turns = [{"he_asked": "how many weeks until christmas", "she_answered": "11 weeks", "at": "2026-10-05T02:22:00+00:00"},
                 {"he_asked": "what time did i ask you that", "she_answered": "", "at": "2026-10-05T02:23:00+00:00"}]
        with mock.patch("aletheia.converse.recent", return_value=turns):
            said = quick.answer("what time did i ask you that")
        self.assertTrue(said.startswith('You asked "how many weeks until christmas" '), said)
        # ...and live, where the question being answered is not in the thread yet
        with mock.patch("aletheia.converse.recent", return_value=turns[:1]):
            self.assertTrue(quick.answer("what time did i ask you that").startswith('You asked "how many weeks until christmas" '))
        with mock.patch("aletheia.converse.recent", return_value=[]):
            self.assertIn("thread is empty", quick.answer("when was that"))


if __name__ == "__main__":
    unittest.main()
