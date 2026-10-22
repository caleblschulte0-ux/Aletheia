""""What's happening on Halloween" went to a model with a reminder set for
it (2026-10-22, every model off)."""
import datetime as dt
import unittest
from unittest import mock

from aletheia import localtime, quick


class ANamedDay(unittest.TestCase):
    def test_holidays_reach_the_day_agenda(self):
        for said in ("what's happening on halloween", "what do i have on christmas", "what's on my calendar on thanksgiving"):
            with self.subTest(said=said):
                self.assertIsNotNone(quick._groups("agenda_on", said).get("agenda_on"))

    def test_that_days_reminders_are_said(self):
        tz = localtime.operator_tz()
        when = dt.datetime.now(tz).date() + dt.timedelta(days=3)
        at = dt.datetime.combine(when, dt.time(9, 0), tzinfo=tz)
        with mock.patch("aletheia.calendar.all_events", return_value=[]), \
                mock.patch.object(quick, "_coming", return_value=[(at, "buy candy", "reminder")]):
            said = quick._agenda_on(f"{when.strftime('%B').casefold()} {when.day}")
        self.assertIn("Nothing on your calendar", said)
        self.assertIn("1 reminder: 9 am, buy candy", said)


if __name__ == "__main__":
    unittest.main()
