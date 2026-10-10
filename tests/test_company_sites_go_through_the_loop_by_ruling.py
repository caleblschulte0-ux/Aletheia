"""His 2026-10-10 ruling: apply on company sites, not only Greenhouse; never LinkedIn or Indeed."""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import apply_run, rulings


class CompanySitesByRuling(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patch = mock.patch.object(apply_run, "engine_settings_path",
                                  return_value=Path(self.tmp.name) / "apply_engine.json")
        patch.start()
        self.addCleanup(patch.stop)
        real = mock.patch.object(rulings, "DEFAULT_PATH", rulings.REPO_RULINGS)
        real.start()
        self.addCleanup(real.stop)

    def test_the_ruling_turns_the_loop_on_for_a_company_site(self):
        self.assertTrue(rulings.for_switch("site_loop")["on"])
        self.assertTrue(apply_run.uses_loop("https://careers.acme.example/jobs/1"))

    def test_a_greenhouse_job_keeps_its_adapter(self):
        self.assertFalse(apply_run.uses_loop("https://boards.greenhouse.io/x/jobs/1", "greenhouse"))

    def test_linkedin_and_indeed_are_never_the_loops(self):
        for url in ("https://www.linkedin.com/jobs/view/1", "https://www.indeed.com/viewjob?jk=1"):
            self.assertFalse(apply_run.uses_loop(url))

    def test_his_own_hand_off_beats_the_ruling(self):
        Path(apply_run.engine_settings_path()).write_text('{"loop_for_unadapted": false}')
        self.assertFalse(apply_run.uses_loop("https://careers.acme.example/jobs/1"))

    def test_no_ruling_file_means_off(self):
        with mock.patch.object(rulings, "DEFAULT_PATH", Path(self.tmp.name) / "none.json"):
            self.assertFalse(apply_run.loop_engine_on())


if __name__ == "__main__":
    unittest.main()
