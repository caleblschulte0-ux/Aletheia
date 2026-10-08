"""His words, 2026-10-08, two rules in one breath.

"I am not comfortable with cold calls. So she should be putting no." And:
"Don't apply to any job whose salary is below 95K or ... 95K comparative to
making that in South Dakota. So, you know, 95K in California ain't quite
the same."
"""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import campaign, hunt_funnel, job_value, rulings


class WithHisRulings(unittest.TestCase):
    def setUp(self):
        p = mock.patch.object(rulings, "DEFAULT_PATH", rulings.REPO_RULINGS)
        p.start()
        self.addCleanup(p.stop)

    def test_the_floor_is_in_the_registry_with_his_words(self):
        ruling = rulings.for_switch("pay_floor")
        self.assertEqual(ruling["floor"], {"amount": 95000, "home": "SD"})
        self.assertIn("South Dakota", rulings.quote(ruling))

    def test_a_job_that_tops_out_under_95k_at_home_is_passed_over(self):
        why = job_value.under_his_floor({"salary": [60000, 80000], "location": "Sioux Falls, SD"})
        self.assertIn("under his $95,000 floor", why)
        self.assertIn("pay", hunt_funnel._unfit_bucket(why))

    def test_california_needs_more_than_95k(self):
        job = {"salary": [90000, 110000], "location": "San Francisco, CA"}
        why = job_value.under_his_floor(job)
        self.assertIn("about $", why)
        self.assertEqual(job_value.under_his_floor({**job, "location": "Sioux Falls, SD"}), "")

    def test_a_range_that_reaches_the_floor_is_kept(self):
        self.assertEqual(job_value.under_his_floor({"salary": [80000, 100000], "location": "Remote"}), "")

    def test_no_posted_pay_is_not_low_pay(self):
        self.assertEqual(job_value.under_his_floor({"location": "Remote"}, "Great team."), "")

    def test_the_posting_text_counts_when_the_board_gives_no_number(self):
        why = job_value.under_his_floor({"location": "Remote"}, "Pay: $55,000 - $70,000 per year.")
        self.assertIn("$70,000", why)

    def test_a_cold_call_question_is_answered_no(self):
        for choices in (["Yes", "No"], []):
            got = campaign._obvious("Are you comfortable making cold calls?", choices, {}, "",
                                    {"job_title": "SDR"}, {})
            self.assertEqual(got, "No", choices)


class WithoutARuling(unittest.TestCase):
    def test_no_ruling_file_cuts_nothing(self):
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(rulings, "DEFAULT_PATH", Path(tmp) / "none.json"):
            self.assertEqual(job_value.under_his_floor({"salary": [40000, 50000]}), "")


if __name__ == "__main__":
    unittest.main()
