"""A posting page's job-alert signup is not the application.

2026-09-13. Two Palo Alto Networks postings on jobs.paloaltonetworks.com (a
Radancy careers site) were staged from the page's own "Job Alert" form -
Email, Confirm Email, Category, Location, and a keyword search - approved on
the grant, and failed at Submit with "could not find the button that submits
this form". The real application was behind "Apply Now", on Workday, which
wants an account. Nothing was sent, but a batch slot and a grant use went on
a newsletter signup.
"""
from __future__ import annotations

import unittest

from aletheia import campaign

JOB_ALERT = [
    {"label": "Keywords", "type": "search", "name": "k"},
    {"label": "Location", "type": "text", "name": "search-location"},
    {"label": "Email", "type": "email", "name": "email"},
    {"label": "Confirm Email", "type": "email", "name": "confirmemail"},
    {"label": "Category", "type": "text", "name": "category"},
    {"label": "Location", "type": "text", "name": "location"},
    {"label": "Job alert frequency", "type": "select", "name": "alert-frequency"},
    {"label": "", "type": "text", "name": "orgIds"},
]
WORKDAY = ("https://paloaltonetworks.wd5.myworkdayjobs.com/panwexternalcareers/job/"
           "Seattle-United-States-of-America/Major-Account-Manager_JR-020630/apply")
POSTING = "https://jobs.paloaltonetworks.com/job/-/-/47263/98541813552"


class AJobAlertIsNotAnApplication(unittest.TestCase):
    def test_the_signup_form_is_not_read_as_an_application(self):
        self.assertFalse(campaign._is_application_form(JOB_ALERT))

    def test_a_real_application_is_still_one(self):
        form = [{"label": "First Name", "type": "text"}, {"label": "Email", "type": "email"},
                {"label": "Phone", "type": "tel"}, {"label": "Resume/CV", "type": "file"}]
        self.assertTrue(campaign._is_application_form(form))

    def test_apply_now_to_an_account_system_wins_and_is_not_opened(self):
        opened = []

        def opener(url):
            opened.append(url)
            if url == POSTING:
                return JOB_ALERT, [{"text": "Apply Now", "href": WORKDAY},
                                   {"text": "Join Talent Community", "href": "/en/talent"}]
            raise AssertionError(f"opened {url}")
        target, fields = campaign._application_url(POSTING, opener=opener)
        self.assertEqual(target, WORKDAY)
        self.assertEqual(fields, [])
        self.assertEqual(opened, [POSTING], "the account site is left to the account path")


if __name__ == "__main__":
    unittest.main()
