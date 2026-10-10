"""His 2026-10-10 ruling: no Greenhouse applications for now; company sites instead."""
import unittest
from unittest import mock

from aletheia import job_fit, rulings


class PausedSystem(unittest.TestCase):
    def setUp(self):
        real = mock.patch.object(rulings, "DEFAULT_PATH", rulings.REPO_RULINGS)
        real.start()
        self.addCleanup(real.stop)

    def test_greenhouse_forms_are_refused_with_a_sentence(self):
        for url in ("https://boards.greenhouse.io/acme/jobs/1", "https://job-boards.greenhouse.io/acme/jobs/2"):
            self.assertIn("paused", job_fit.paused_system_reason(url))

    def test_an_employers_own_page_is_not_refused(self):
        self.assertEqual(job_fit.paused_system_reason("https://www.samsara.com/careers/roles/1?gh_jid=1"), "")
        self.assertEqual(job_fit.paused_system_reason("https://jobs.lever.co/acme/1"), "")

    def test_the_verdict_and_the_send_check_both_use_it(self):
        job = {"company": "Acme", "title": "Account Manager", "url": "https://boards.greenhouse.io/acme/jobs/1"}
        self.assertFalse(job_fit.verdict(job, think=False)["realistic"])
        self.assertIn("paused", job_fit.quick_reason({"company": "Acme", "job_title": "Account Manager",
                                                       "url": job["url"]}))

    def test_no_ruling_file_pauses_nothing(self):
        with mock.patch.object(rulings, "DEFAULT_PATH", rulings.REPO_RULINGS.parent / "none.json"):
            self.assertEqual(job_fit.paused_system_reason("https://boards.greenhouse.io/a/jobs/1"), "")


if __name__ == "__main__":
    unittest.main()
