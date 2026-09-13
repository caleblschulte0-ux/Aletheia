"""One role, two urls, and both of them got an application.

2026-09-13. His instruction, unprompted, while it was running: *"Make
sure that we are really focusing on not doing any duplicates, and we're
really keeping track of what ones we've applied for and not applied
for."*

An audit the same minute found the URL guard working perfectly — nineteen
sends, zero repeated urls, every one of them in the ledger — and one real
duplicate underneath it:

    2026-09-12T16:55:14Z  Databricks  Business Development Representative
        boards.greenhouse.io/embed/job_app?for=databricks&token=8423165002
    2026-09-13T02:50:54Z  Databricks  Business Development Representative
        boards.greenhouse.io/embed/job_app?for=databricks&token=8423167002

Adjacent gh_jids: one role posted to two locations. Two different urls,
so the ledger held two honest entries and the guard had nothing to object
to. Whoever opens both at Databricks sees one candidate applying twice
for one job.

So the rule grows a second half. `was_sent` still answers "has this exact
form already been submitted", which is the question that stops a re-stage
sending a second copy. `was_applied_to_role` answers "has this job
already been applied for", which is the question an employer would ask.

The narrowness is the point, and these tests exist mostly to hold it:
Databricks BDR and Databricks "Frontier AI Lab Account Executive" are two
real jobs, Stripe's two are two real jobs, GitLab's two are two real jobs
— all six should go, and a guard that counts applications per COMPANY
would have blocked half of them. It compares titles.
"""
from __future__ import annotations

import json
import pathlib
import tempfile
import unittest
from unittest import mock

from aletheia import apply_run


LEDGER = {
    "https://boards.greenhouse.io/embed/job_app?for=databricks&token=8423165002": {
        "id": "apply-153575ee", "at": "2026-09-12T16:55:14Z", "company": "Databricks",
        "job_title": "Business Development Representative — Databricks",
        "verdict": "confirmed"},
    "https://boards.greenhouse.io/embed/job_app?for=databricks&token=8519282002": {
        "id": "apply-30a9b8e4", "at": "2026-09-12T19:11:23Z", "company": "Databricks",
        "job_title": "Frontier AI Lab Account Executive — Databricks",
        "verdict": "confirmed"},
    "https://boards.greenhouse.io/embed/job_app?for=stripe&token=8100000": {
        "id": "apply-0078e378", "at": "2026-09-12T18:47:04Z", "company": "Stripe",
        "job_title": "Product Manager, Connected Account Onboarding Experiences — Stripe",
        "verdict": "confirmed"},
}


class OneJobOneApplicationCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = pathlib.Path(tmp.name) / "already-sent.json"
        path.write_text(json.dumps(LEDGER), encoding="utf-8")
        patch = mock.patch.object(apply_run, "sent_path", lambda: path)
        patch.start(); self.addCleanup(patch.stop)

    def applied(self, company, title):
        return apply_run.was_applied_to_role(company, title)

    def test_the_same_role_under_a_different_url_is_caught(self):
        """The Databricks duplicate, exactly as it happened."""
        self.assertIsNotNone(
            self.applied("Databricks",
                         "Business Development Representative — Databricks"))

    def test_the_employer_suffix_does_not_have_to_match(self):
        """The title arrives with and without the employer on the end
        depending on where the opening was found."""
        self.assertIsNotNone(
            self.applied("Databricks", "Business Development Representative"))

    def test_punctuation_and_case_do_not_make_it_a_new_job(self):
        self.assertIsNotNone(
            self.applied("databricks", "business development  representative!"))

    def test_a_DIFFERENT_role_at_the_same_employer_still_goes(self):
        """Databricks had two real jobs and both should be applied for. A
        guard that counted applications per COMPANY would have stopped the
        second, and stopped Stripe's second and GitLab's second too.

        The first draft of this test asserted that "Frontier AI Lab Account
        Executive" came back unmatched — which was wrong, because that job
        IS in the ledger; she applied to it on the 12th. The guard caught
        it correctly and the test was describing what I wanted rather than
        what the fixture said. The property worth holding is that a role
        NOBODY has applied for still goes, at an employer who already has
        an application.
        """
        self.assertIsNone(self.applied("Databricks", "Staff Engineer"))
        self.assertIsNone(
            self.applied("Databricks", "Senior Account Executive, Enterprise"))
        self.assertIsNone(self.applied("Stripe", "Account Executive, AI Sales"))

    def test_a_role_that_IS_in_the_ledger_is_caught_whichever_one(self):
        """Both of Databricks' applications are on file, so both titles
        match — this is the guard working, not a false positive."""
        for title in ("Business Development Representative",
                      "Frontier AI Lab Account Executive"):
            self.assertIsNotNone(self.applied("Databricks", title), title)

    def test_the_same_title_at_a_DIFFERENT_employer_still_goes(self):
        self.assertIsNone(
            self.applied("Snowflake", "Business Development Representative"))

    def test_nothing_to_compare_is_not_a_match(self):
        """A record with no company or no title must not silently match
        everything — failing closed here would stop the whole hunt."""
        self.assertIsNone(self.applied("", "Business Development Representative"))
        self.assertIsNone(self.applied("Databricks", ""))
        self.assertIsNone(self.applied("", ""))

    def test_the_url_guard_is_untouched(self):
        """The two questions are different and both are still asked."""
        self.assertIsNotNone(apply_run.was_sent(
            "https://boards.greenhouse.io/embed/job_app?for=stripe&token=8100000"))
        self.assertIsNone(apply_run.was_sent("https://example.com/nope"))


if __name__ == "__main__":
    unittest.main()
