"""BDR and SDR roles are applied to, by his ruling of 2026-10-07.

He said "definitely don't wanna do sales... no cold calling" on 2026-09-13,
and both interviews the hunt then won were development-rep roles. Asked
whether she should apply to BDR/SDR roles, he said "Yes to both".
"""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import campaign, job_fit, profile, rulings

HIS = {"work_not_wanted": "sales, cold calling, quota", "work_wanted": "partnerships"}
COLD = "You will make 60 calls a day doing outbound prospecting and exceed a monthly quota."
EMAIL = "You will prospect through email sequences and LinkedIn and exceed a monthly quota."


def _facts_a_form_is_answered_from():
    """The facts the form-question writer is shown for an SDR form."""
    seen = {}

    def think(system, text, **kw):
        seen.update(kw["context"]["facts"])
        return {"answers": {}}

    record = {"url": "https://jobs.example/sdr", "job_title": "Sales Development Representative",
              "questions": [{"selector": "#q1", "label": "Are you comfortable making cold calls?",
                             "type": "text", "required": True}]}
    with mock.patch.object(profile, "known", return_value=dict(HIS)), \
            mock.patch.object(campaign, "obvious_answers", return_value={}):
        campaign.answer_from_facts(record, "resume", think=think)
    return seen


class WithHisRuling(unittest.TestCase):
    def setUp(self):
        p = mock.patch.object(rulings, "DEFAULT_PATH", rulings.REPO_RULINGS)
        p.start()
        self.addCleanup(p.stop)

    def test_the_ruling_is_in_the_registry_with_his_words(self):
        ruling = rulings.for_switch("bdr_sdr")
        self.assertTrue(ruling and ruling["on"])
        self.assertIn("Yes to both", rulings.quote(ruling))

    def test_development_reps_pass_with_a_quota_and_no_cold_calls(self):
        for title in ("Business Development Representative", "SDR, Mid-Market",
                      "Sales Development Representative", "BDR - AI Labs",
                      "Business Development Associate", "Account Development Representative",
                      "Market Development Rep", "Lead Development Representative (Inbound)"):
            self.assertEqual(job_fit.unwanted_reason(title, EMAIL, HIS), "", title)

    def test_a_development_rep_who_cold_calls_is_left_out(self):
        # His words, 2026-10-08: "I am not comfortable with cold calls ...
        # I'm not a cold caller."
        for text in (COLD, "Prospect by cold-calling small businesses.", "Make 80+ dials per day."):
            self.assertIn("cold calling",
                          job_fit.unwanted_reason("Sales Development Representative", text, HIS), text)
        self.assertIn("not a cold caller", rulings.quote(rulings.for_switch("bdr_sdr")))

    def test_every_other_sales_job_is_still_left_out(self):
        for title in ("Account Executive", "Inside Sales Representative", "Sales Manager",
                      "Market Development Manager, Sales", "Account Manager, Sales"):
            self.assertTrue(job_fit.unwanted_reason(title, "", HIS), title)
        self.assertTrue(job_fit.unwanted_reason("Customer Success Manager", COLD, HIS))

    def test_the_model_reading_a_posting_hears_the_carve_out(self):
        wanted, unwanted = job_fit.preferences(HIS)
        self.assertIn("BDR", wanted)
        self.assertIn("never cold calling", wanted)
        self.assertIn("partnerships", wanted)
        self.assertTrue(unwanted.startswith("sales, cold calling, quota"))
        self.assertIn("except", unwanted)

    def test_the_carve_out_never_switches_a_rule_on_he_never_said(self):
        quiet = {"work_not_wanted": "management", "work_wanted": ""}
        self.assertEqual(job_fit.unwanted_reason("Account Executive", "", quiet), "")
        self.assertEqual(job_fit.hands_on_reason("Warehouse Associate", quiet), "")

    def test_jobs_closed_as_sales_before_his_yes_are_judged_afresh(self):
        with mock.patch.object(profile, "load", return_value={
                "work_not_wanted": {"value": "sales", "at": "2026-09-13T12:00:00Z"}}):
            self.assertEqual(job_fit.preferences_changed_at(), "2026-10-08T12:15:11Z")

    def test_a_form_question_about_cold_calls_hears_his_yes(self):
        facts = _facts_a_form_is_answered_from()
        self.assertIn("BDR", facts["work_wanted"])
        self.assertIn("except", facts["work_not_wanted"])

    def test_the_search_looks_for_them(self):
        with mock.patch.object(profile, "roles_added", return_value=[]):
            roles = campaign._with_his_roles(["Partnerships Associate"], HIS)
        self.assertIn("Business Development Representative", roles)
        self.assertIn("Sales Development Representative", roles)


class WithoutARuling(unittest.TestCase):
    def test_no_ruling_file_leaves_his_sales_rule_whole(self):
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(rulings, "DEFAULT_PATH", Path(tmp) / "none.json"):
            self.assertTrue(job_fit.unwanted_reason("Business Development Representative", "", HIS))
            self.assertEqual(job_fit.preferences(HIS), ("partnerships", "sales, cold calling, quota"))
            with mock.patch.object(profile, "roles_added", return_value=[]):
                self.assertEqual(campaign._with_his_roles(["X"], HIS), ["X"])
            facts = _facts_a_form_is_answered_from()
            self.assertEqual(facts["work_not_wanted"], "sales, cold calling, quota")


if __name__ == "__main__":
    unittest.main()
