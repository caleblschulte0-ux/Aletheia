"""Live 2026-09-23: Aptiv's application, driven by the general browser and
stopped on a question, was "read again with what she knows now" by the
form filler every twelve minutes, all day, and "could not be read" every
time - the page never had a form for it. A record the general browser holds
is the loop's; its mission is the truth."""
import unittest
from unittest import mock

from aletheia import apply_run, campaign


class TheRetryPassLeavesTheLoopsRecordsAlone(unittest.TestCase):
    LOOPS = {"id": "apply-2c485c24", "state": "NEEDS_YOU", "url": "https://www.aptiv.com/en/jobs/1",
             "engine": apply_run.ENGINE_LOOP, "mission": "bm-apply-for-this-job-0fb67f0f26",
             "questions": [{"label": "Country dropdown", "required": True}]}
    HERS = {"id": "apply-1111", "state": "NEEDS_YOU", "url": "https://boards.greenhouse.io/x/jobs/1",
            "questions": [{"label": "Desired pay", "required": True}]}

    def test_only_the_form_fillers_own_records_are_staged_again(self):
        calls = []

        def stager(url, **kw):
            calls.append(url)
            return {"id": "apply-1111", "url": url, "state": "AWAITING_YOU", "questions": []}
        journal_lines = []
        with mock.patch.object(apply_run, "all_runs",
                               side_effect=lambda state=None: [self.LOOPS, self.HERS] if state == "NEEDS_YOU" else []), \
             mock.patch.object(campaign, "read_resume", return_value=("C:/r.pdf", "resume text")), \
             mock.patch.object(campaign.policy, "ensure_not_halted"), \
             mock.patch.object(campaign.journal, "append", side_effect=lambda k, s, t, **kw: journal_lines.append(t)):
            out = campaign.retry_waiting(stager=stager, json_think=False, writer=False)
        self.assertEqual(calls, ["https://boards.greenhouse.io/x/jobs/1"], "Aptiv is never handed to the form filler")
        self.assertEqual(out["the_loops"], ["apply-2c485c24"])
        self.assertEqual(out["failed"], [])
        self.assertIn("1 in the general browser's hands", journal_lines[-1])
        self.assertNotIn("could not be read", journal_lines[-1].replace("0 could not be read", ""))


if __name__ == "__main__":
    unittest.main()
