"""A page with nothing to fill is not an application, and a link is kept whole.

2026-09-13. Two "applications" were staged with no field filled and nothing
asked, approved on the standing grant and pressed, and both failed at send
time with "could not find the button":

- Bond's posting had been taken down; Greenhouse answered "Sorry, but we
  can't find that page".
- Grainger's "Account Manager, Gov't" was read off a listing with the address
  cut at the apostrophe, onto a page with no form.
"""
from __future__ import annotations

import unittest

from aletheia import apply_run, company_sites, policy

import tests.test_apply_run as apply_base


class ALinkIsKeptWhole(unittest.TestCase):
    def test_an_apostrophe_inside_a_word_stays_in_the_address(self):
        page = ('<a href="https://jobs.grainger.com/job/SANTA-FE-SPRINGS-Account-Manager%2C-Gov\'t'
                '-CA-90670/1234/">Apply</a>')
        self.assertIn("Gov't-CA-90670/1234/", company_sites._URL.findall(page)[0])

    def test_a_single_quoted_attribute_still_ends_at_its_quote(self):
        page = "<a href='https://jobs.example.com/job/42'>Apply</a>"
        self.assertEqual(company_sites._URL.findall(page), ["https://jobs.example.com/job/42"])


class NothingToFill(apply_base.ApplyCase):
    def test_a_page_with_no_form_is_failed_not_staged_or_approved(self):
        url = "https://boards.greenhouse.io/embed/job_app?for=gone&token=1"
        with self.assertRaises(apply_run.ApplyError) as caught:
            apply_run.stage(url, reader=lambda _u: [],
                            filler=lambda *a, **k: self.fail("a page with no form was filled"))
        # Two checks can say it ("no application form on this page", "not an
        # application form"); the rule is that it is refused as not a form.
        self.assertIn("application form", str(caught.exception))
        records = [r for r in apply_run.all_runs() if r.get("url") == url]
        self.assertEqual([r["state"] for r in records], ["CLOSED"])
        self.assertEqual([r.get("closed_kind") for r in records], ["not-a-form"])
        self.assertFalse(any(str(a.get("id", "")).startswith(records[0]["id"])
                             for a in policy.all_approvals()),
                         "nothing to press, so nothing to approve")


if __name__ == "__main__":
    unittest.main()
