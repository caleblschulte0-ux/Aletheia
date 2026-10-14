""""The milk expires on Friday", then "what's expiring this week" was "I
can't think" (2026-10-14)."""
import datetime as dt
import unittest
from unittest import mock

from aletheia import localtime, quick


class Expiring(unittest.TestCase):
    def test_soonest_first_inside_the_week(self):
        today = dt.datetime.now(localtime.operator_tz()).date()
        soon, later = today + dt.timedelta(days=1), today + dt.timedelta(days=40)
        rows = [{"text": f"the cheese expires {later.strftime('%B')} {later.day}", "ts": ""},
                {"text": f"the yogurt expires {soon.strftime('%B')} {soon.day}", "ts": ""}]
        with mock.patch.object(quick, "_notes", return_value=rows):
            self.assertEqual(quick.answer("what's expiring this week"), "The yogurt expires tomorrow.")
            self.assertEqual(quick.answer("is anything going bad soon"), "The yogurt expires tomorrow.")
            self.assertEqual(quick.answer("what's expiring today"), "Nothing you told me about expires today.")

    def test_never_told(self):
        with mock.patch.object(quick, "_notes", return_value=[]):
            self.assertIn("haven't told me when anything expires", quick.answer("what's expiring this week"))


if __name__ == "__main__":
    unittest.main()
