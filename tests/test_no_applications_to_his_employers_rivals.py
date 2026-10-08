"""His words, 2026-10-08: "Maybe refrain from applying anywhere that's ECGs
direct competition like enova" - ECG being his employer, a small-business
funder, and Enova (OnDeck, Headway Capital) its direct competition."""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import apply_run, hunt_funnel, job_fit, rulings


class HisEmployersRivals(unittest.TestCase):
    def setUp(self):
        p = mock.patch.object(rulings, "DEFAULT_PATH", rulings.REPO_RULINGS)
        p.start()
        self.addCleanup(p.stop)

    def test_the_ruling_carries_his_words_and_enova(self):
        ruling = rulings.for_switch("rivals")
        self.assertIn("enova", rulings.quote(ruling))
        self.assertIn("Enova", ruling["employers"])

    def test_enova_and_its_brands_are_refused_by_name(self):
        for company in ("Enova", "Enova International", "OnDeck", "Headway Capital, LLC"):
            self.assertIn("competes directly", job_fit.rival_reason(company), company)
        self.assertEqual(job_fit.rival_reason("Renova Health"), "")
        self.assertEqual(job_fit.rival_reason("Mercury"), "")

    def test_a_filled_application_to_a_rival_is_never_sent(self):
        why = job_fit.quick_reason({"company": "Kapitus", "job_title": "Partnerships Manager",
                                    "fit": {"realistic": True, "by": "model"}}, known={})
        self.assertIn("competes directly", why)

    def test_a_rival_is_not_realistic_before_any_model_is_asked(self):
        asked = []
        fit = job_fit.verdict({"company": "Enova", "job_title": "Business Analyst"}, "", {},
                              think=lambda *a, **k: asked.append(1))
        self.assertFalse(fit["realistic"])
        self.assertEqual((fit["by"], asked), ("rules", []))

    def test_the_recheck_closes_a_waiting_rival_without_reading_it(self):
        closed = {}
        rec = {"id": "r", "state": "AWAITING_YOU", "company": "OnDeck", "job_title": "Account Manager"}
        with mock.patch.object(apply_run, "all_runs", lambda state=None: [rec] if state == "AWAITING_YOU" else []), \
                mock.patch.object(apply_run, "close", lambda rid, why, **_: closed.__setitem__(rid, why)):
            job_fit.recheck_waiting(describe=lambda job: self.fail("read the posting"), known={})
        self.assertIn("competes directly", closed["r"])

    def test_the_funnel_counts_it_without_the_name(self):
        self.assertEqual(hunt_funnel._unfit_bucket("OnDeck competes directly with his employer"), "rival")


class WithoutARuling(unittest.TestCase):
    def test_no_ruling_file_refuses_nobody(self):
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(rulings, "DEFAULT_PATH", Path(tmp) / "none.json"):
            self.assertEqual(job_fit.rival_reason("Enova"), "")


if __name__ == "__main__":
    unittest.main()
