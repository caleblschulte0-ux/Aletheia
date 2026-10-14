""""Is daylight saving time this weekend" went to the planner, which could
not plan it with no model (2026-10-14). Asked about a window, she answers
yes or no for that window, then says when."""
import datetime as dt
import unittest
from unittest import mock
from zoneinfo import ZoneInfo

from aletheia import localtime, quick

TZ = ZoneInfo("America/Chicago")


def _next_change():
    now = dt.datetime.now(TZ)
    noon = now.replace(hour=12, minute=0, second=0, microsecond=0)
    return next((noon + dt.timedelta(days=d)).date() for d in range(1, 370)
                if bool((noon + dt.timedelta(days=d)).dst()) != bool(now.dst()))


class AWindow(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(localtime, "operator_tz", return_value=TZ)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_this_month_is_yes_or_no_against_the_real_change(self):
        change, today = _next_change(), dt.datetime.now(TZ).date()
        said = quick.answer("does daylight saving end this month")
        expected = "Yes - " if (change.year, change.month) == (today.year, today.month) else "No - "
        self.assertTrue(said.startswith(expected), said)
        self.assertIn(f"of {change.strftime('%B')}", said)

    def test_the_other_phrasings(self):
        for asked in ("is daylight saving time this weekend", "do the clocks change next weekend",
                      "is the time change tomorrow?"):
            said = quick.answer(asked) or ""
            self.assertTrue(said.startswith(("Yes - ", "No - ")), (asked, said))

    def test_no_window_is_the_old_answer(self):
        self.assertTrue(quick.answer("is it daylight saving time").startswith("You're on Central time"))


if __name__ == "__main__":
    unittest.main()
