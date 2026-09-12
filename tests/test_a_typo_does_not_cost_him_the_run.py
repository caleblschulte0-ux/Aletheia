"""What she MISHEARD must not be the reason he gets nothing.

Live 2026-09-11. He said, out loud, to apply to a real job. It reached the
campaign as the role ``A1 real``, so she searched forty-four boards for a
job title that does not exist and stopped::

    CampaignError: no openings matched A1 real across 44 boards or a web search.

His ruling, the same evening: *"simple typos and mistakes like that cannot
affect ... like, this not always gonna be perfect."*

So a role he SAYS is a filter, never a requirement. When it matches
nothing, she falls back to what his resume is for - exactly as if he had
named no role - and she SAYS she did it. The saying is half the fix:
quietly applying to jobs he did not ask for would be worse than finding
none, and he can correct a job title in one sentence.

She still never invents a job title, and a widened search that also finds
nothing still fails honestly, naming both things she tried.
"""
from __future__ import annotations

import unittest
from unittest import mock

from aletheia import campaign

RESUME_ROLES = ["Account Executive", "Business Development Manager"]


def _opening(title="Account Executive", company="Northwind"):
    return {"title": title, "company": company,
            "apply_url": f"https://boards.x.co/{company.lower()}/apply",
            "posting_url": f"https://{company.lower()}.com/jobs/1",
            "found_by": ""}


class ATypoDoesNotCostHimTheRunCase(unittest.TestCase):
    def setUp(self):
        self.searched_for = []

        def searcher(roles, **kw):
            self.searched_for.append(list(roles))
            matched = [r for r in roles if r in RESUME_ROLES]
            return {"matches": [_opening()] if matched else [], "searched": 44}

        self.searcher = searcher
        self.staged = []

        def stager(url, resume="", extra=None, note=""):
            record = {"id": f"apply-{len(self.staged)}", "state": "AWAITING_YOU",
                      "url": url, "page_title": "Application"}
            self.staged.append(record)
            return record

        self.stager = stager
        patches = [
            mock.patch.object(campaign, "read_resume",
                              return_value=("Caleb_Schulte_Resume.pdf", "a resume")),
            mock.patch.object(campaign.profile, "learn_from_resume", return_value={}),
            mock.patch.object(campaign, "learn_more", return_value={}),
            mock.patch.object(campaign, "roles_for", return_value=list(RESUME_ROLES)),
            mock.patch.object(campaign.profile, "known",
                              return_value={"country": "United States"}),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def _run(self, role):
        return campaign.run(role, count=1, searcher=self.searcher, stager=self.stager,
                            draft_essays_too=False, json_think=False)

    def test_a_misheard_role_falls_back_to_what_the_resume_is_for(self):
        out = self._run("A1 real")
        self.assertEqual(len(out["ready"]), 1, "he gets an application, not an error")
        self.assertEqual(out["ignored_role"], "A1 real")
        self.assertEqual(out["roles"], RESUME_ROLES)
        self.assertEqual(self.searched_for, [["A1 real"], RESUME_ROLES],
                         "what he said is tried FIRST, and only then the resume")

    def test_she_says_that_she_ignored_what_she_heard(self):
        """A search widened in silence is a job applied to that he never named."""
        said = campaign.spoken(self._run("A1 real"))
        self.assertIn('Nothing matched "A1 real"', said)
        self.assertIn("Account Executive", said)
        self.assertIn("Tell me the job title", said)

    def test_a_role_that_works_is_used_and_nothing_is_widened(self):
        out = self._run("Account Executive")
        self.assertEqual(out["ignored_role"], "", "no fallback was needed")
        self.assertEqual(self.searched_for, [["Account Executive"]],
                         "his own words are not second-guessed when they work")
        self.assertNotIn("Nothing matched", campaign.spoken(out))

    def test_nothing_anywhere_still_fails_honestly(self):
        """The fallback is a second chance, not a way to always find something."""
        with mock.patch.object(campaign, "roles_for", return_value=["Underwater Welder"]):
            with self.assertRaises(campaign.CampaignError) as caught:
                self._run("A1 real")
        message = str(caught.exception)
        self.assertIn("A1 real", message)
        self.assertIn("Underwater Welder", message)
        self.assertIn("44 boards", message)

    def test_no_role_at_all_behaves_exactly_as_before(self):
        out = self._run("")
        self.assertEqual(out["ignored_role"], "")
        self.assertEqual(self.searched_for, [RESUME_ROLES])
        self.assertEqual(len(out["ready"]), 1)


if __name__ == "__main__":
    unittest.main()
