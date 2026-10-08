"""His rules apply to what is already filled in, not only to what is chosen next.

2026-10-08: his "I'm not a cold caller" and his $95K floor landed at 12:15Z,
and within the hour two Sales Development Representative applications filled
the night before went out on the standing grant - the send reads only a title
and the form's questions, and the posting said what the job was.
"""
import unittest
from unittest import mock

from aletheia import apply_run, job_fit, rulings

COLD = "You will make 60+ cold calls a day to book meetings for our account executives."
LOW = "Partner onboarding and reporting. The pay range is $60,000 - $72,000 per year."
FINE = "Run partner onboarding and reporting. The pay range is $100,000 - $120,000."


def _record(rid, title, **extra):
    return {"id": rid, "state": "AWAITING_YOU", "company": "Acme", "job_title": title,
            "url": f"https://example.com/{rid}", **extra}


class RecheckWaiting(unittest.TestCase):
    def setUp(self):
        p = mock.patch.object(rulings, "DEFAULT_PATH", rulings.REPO_RULINGS)
        p.start()
        self.addCleanup(p.stop)
        self.closed, self.stamped = {}, {}

    def _run(self, records, texts):
        def runs(state=None):
            return [r for r in records if r["state"] == state]
        with mock.patch.object(apply_run, "all_runs", runs), \
                mock.patch.object(apply_run, "close",
                                  lambda rid, why, **_: self.closed.__setitem__(rid, why)), \
                mock.patch.object(apply_run, "remember",
                                  lambda rid, **f: self.stamped.__setitem__(rid, f)):
            return job_fit.recheck_waiting(describe=lambda job: texts.get(job["url"], ""), known={})

    def test_a_cold_calling_sdr_job_filled_before_the_ruling_is_closed(self):
        rows = self._run([_record("a", "Sales Development Representative")],
                         {"https://example.com/a": COLD})
        self.assertEqual([r["id"] for r in rows], ["a"])
        self.assertIn("cold calling", self.closed["a"])

    def test_a_job_under_his_floor_is_closed(self):
        self._run([_record("b", "Partnerships Manager")], {"https://example.com/b": LOW})
        self.assertIn("under his $95,000 floor", self.closed["b"])

    def test_a_job_that_passes_is_stamped_and_not_read_again(self):
        rec = _record("c", "Partnerships Manager")
        self._run([rec], {"https://example.com/c": FINE})
        self.assertEqual(self.closed, {})
        self.assertIn("rechecked_at", self.stamped["c"])
        rec["rechecked_at"] = self.stamped["c"]["rechecked_at"]
        self.stamped.clear()
        self._run([rec], {"https://example.com/c": LOW})
        self.assertEqual((self.closed, self.stamped), ({}, {}))

    def test_a_posting_that_cannot_be_read_is_left_for_next_time(self):
        self._run([_record("d", "Sales Development Representative")], {})
        self.assertEqual((self.closed, self.stamped), ({}, {}))

    def test_the_floor_ruling_counts_as_a_change(self):
        self.assertGreaterEqual(job_fit.rules_changed_at(), "2026-10-08")


if __name__ == "__main__":
    unittest.main()
