"""On his PC, 2026-09-23, 32 of the newest 40 "failed" applications were
pages that were never forms - a job-alert signup, a bot check, a taken-down
posting. Counting those as failures made "N could not be sent" mean
nothing. They are CLOSED as not-a-form now, and the morning brief carries
the job hunt as a section."""
from __future__ import annotations

import unittest
from unittest import mock

from aletheia import apply_run, brief


class NotAFormCase(unittest.TestCase):
    def test_the_record_is_closed_with_its_kind(self):
        with mock.patch("aletheia.apply_run._record_path") as path, \
             mock.patch("aletheia.stateio.write_json_atomic") as write:
            path.return_value = "x"
            record = apply_run._not_a_form("apply-1", "https://x/1", "a talent-network / job-alert signup, not an application",
                                           resume="", kept_job={"company": "Spectrum"})
        self.assertEqual(record["state"], apply_run.CLOSED)
        self.assertEqual(record["closed_kind"], apply_run.NOT_A_FORM)
        self.assertEqual(apply_run.closure_kind(record), apply_run.NOT_A_FORM)
        self.assertIn("signup", record["closed_because"])
        self.assertEqual(record["company"], "Spectrum")
        write.assert_called_once()

    def test_a_not_a_form_closure_is_not_an_unfit_one(self):
        """`closed_unfit` reopens unfit ones when his preferences change; a
        page that was never a form is not a judgement about the role."""
        record = {"state": "CLOSED", "closed_kind": "not-a-form", "company": "Spectrum",
                  "job_title": "Account Manager", "url": "https://x/1"}
        with mock.patch("aletheia.apply_run.all_runs", return_value=[record]):
            self.assertIsNone(apply_run.closed_unfit("Spectrum", "Account Manager", "https://x/1"))


class TheBriefCarriesTheJobHuntCase(unittest.TestCase):
    def test_sent_replies_and_waiting_make_a_section(self):
        hunt = {"readable": True, "today": {"sent": 3, "replies": 1, "ready": 0, "blocked": 2},
                "sent_list": [{"company": "Datadog"}, {"company": "Vanta"}, {"company": "Datadog"}],
                "waiting_on_him": [{"company": "Ramp", "questions": ["q"]}]}
        with mock.patch("aletheia.current_state.job_hunt", return_value=hunt):
            lines = brief._job_hunt_lines()
        text = "\n".join(lines)
        self.assertIn("## Job hunt", text)
        self.assertIn("**3 sent** today: Datadog, Vanta", text)
        self.assertIn("1 heard back", text)
        self.assertIn("1 stopped on a question only you can answer**: Ramp", text)
        self.assertIn("2 could not be sent", text)

    def test_no_hunt_is_no_section_and_never_an_error(self):
        with mock.patch("aletheia.current_state.job_hunt", return_value={"readable": True, "today": {}}):
            self.assertEqual(brief._job_hunt_lines(), [])
        with mock.patch("aletheia.current_state.job_hunt", side_effect=RuntimeError("boom")):
            self.assertEqual(brief._job_hunt_lines(), [])


if __name__ == "__main__":
    unittest.main()
