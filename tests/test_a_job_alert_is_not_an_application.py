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

from aletheia import apply_run, campaign, formfill, policy

import tests.test_apply_run as apply_base


def _f(selector, label, type_="text", *, required=False, tag="input", name="", id_="",
       options=None, **extra):
    row = {"selector": selector, "label": label, "type": type_, "tag": tag,
           "required": required, "name": name, "id": id_, "value": ""}
    if options is not None:
        row["options"] = [{"value": o, "text": o} for o in options]
    row.update(extra)
    return row


#: Spectrum's posting page, 2026-09-13 (apply-3d1ef64e): "Sign up for job
#: alerts", staged as the application for "National Account Manager, Federal
#: Government". It DOES offer a resume - an optional one, name="Resume".
SPECTRUM = [
    _f("#search-keyword-d128a4f9af", "keyword", "search", id_="search-keyword-d128a4f9af"),
    _f("#search-location-d128a4f9af", "location", id_="search-location-d128a4f9af"),
    _f("#fn", "First Name*", required=True),
    _f("#ln", "Last Name*", required=True),
    _f("#em", "Email Address*", "email", required=True),
    _f("#form-field-02486c4e39", "Are you a member of the military community?", "select",
       tag="select", id_="form-field-02486c4e39",
       options=["No", "Yes, Currently Serving", "Yes, Veteran", "Yes, Military Spouse"]),
    _f("#form-field-0920491ce9-category", "Job Category", "select", tag="select",
       id_="form-field-0920491ce9-category",
       options=["Account Management", "Accounting and Finance", "Administrative"]),
    _f("#form-field-0920491ce9-location", "Location", "select", tag="select",
       id_="form-field-0920491ce9-location", options=["Ada, Michigan", "Akron, Ohio"]),
    _f("#form-field-bf06f0d883", "Upload resume (optional)", "file", name="Resume",
       id_="form-field-bf06f0d883"),
    _f("#custom-224489-0-1", "Yes", "radio", required=True, question="Spectrum employee *",
       option="Yes", group="Spectrum employee *"),
    _f("#custom-224489-1-1", "No", "radio", required=True, question="Spectrum employee *",
       option="No", group="Spectrum employee *"),
    _f("#ce", "Confirm Email", "email"),
    _f("#plyr-seek-1244", "Seek", "range"),
    _f("#plyr-volume-1244", "Volume", "range"),
    _f("#form-type-716044a978", "FormType", "hidden"),
]

#: A Greenhouse application that happens to ask for the email twice.
GREENHOUSE = [
    _f("#first_name", "First Name*", required=True),
    _f("#last_name", "Last Name*", required=True),
    _f("#email", "Email*", "email", required=True),
    _f("#confirm_email", "Confirm Email*", "email", required=True),
    _f("#phone", "Phone*", "tel", required=True),
    _f("#resume", "Resume/CV*", "file", name="resume"),
    _f("#linkedin", "LinkedIn Profile", name="job_application[answers][linkedin]"),
]

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


class ATalentNetworkSignupIsNotAnApplication(unittest.TestCase):
    """One predicate, `formfill.is_signup_list`, for the campaign and for stage."""

    def test_spectrums_job_alert_signup_is_a_signup_despite_first_name(self):
        self.assertTrue(formfill.is_signup_list(SPECTRUM))
        self.assertFalse(campaign._is_application_form(SPECTRUM),
                         "'First Name' used to defeat this check")

    def test_the_old_job_alert_fixture_is_still_one(self):
        self.assertTrue(formfill.is_signup_list(JOB_ALERT))

    def test_a_greenhouse_application_with_a_confirm_email_box_is_an_application(self):
        self.assertFalse(formfill.is_signup_list(GREENHOUSE))
        self.assertTrue(campaign._is_application_form(GREENHOUSE))

    def test_a_resume_he_must_give_means_an_application_whatever_else_it_asks(self):
        bare = [_f("#fn", "First Name"), _f("#em", "Email", "email"),
                _f("#ce", "Confirm Email", "email"), _f("#cat", "Job Category", "select", tag="select"),
                _f("#cv", "Resume/CV", "file", required=True)]
        self.assertFalse(formfill.is_signup_list(bare))
        marked = [dict(f, required=False, label="Resume/CV ✱") if f["type"] == "file" else f
                  for f in bare]
        self.assertFalse(formfill.is_signup_list(marked), "Lever marks it with a star")

    def test_an_optional_resume_without_confirm_email_is_not_called_a_list(self):
        form = [_f("#fn", "First Name"), _f("#em", "Email", "email"),
                _f("#cat", "Areas of Interest", "select", tag="select"),
                _f("#cv", "Upload resume (optional)", "file")]
        self.assertFalse(formfill.is_signup_list(form))

    def test_a_page_with_nothing_is_not_a_signup(self):
        self.assertFalse(formfill.is_signup_list([]))
        self.assertFalse(formfill.is_signup_list([_f("#h", "FormType", "hidden")]))


class StageRefusesASignup(apply_base.ApplyCase):
    URL = "https://jobs.spectrum.com/job/-/-/4673/100495159936?utm_campaign=brand"

    def test_it_is_recorded_as_failed_with_the_reason_and_nothing_is_filled(self):
        with self.assertRaises(apply_run.ApplyError) as caught:
            apply_run.stage(self.URL, reader=lambda _u: [dict(f) for f in SPECTRUM],
                            filler=lambda *a, **k: self.fail("a signup was filled"))
        self.assertIn("a talent-network / job-alert signup, not an application",
                      str(caught.exception))
        records = [r for r in apply_run.all_runs() if r.get("url") == self.URL]
        self.assertEqual([r["state"] for r in records], ["FAILED"])
        self.assertEqual(records[0]["failure"],
                         "a talent-network / job-alert signup, not an application")
        self.assertFalse(any(str(a.get("id", "")).startswith(records[0]["id"])
                             for a in policy.all_approvals()))

    def test_a_real_application_with_confirm_email_is_still_staged(self):
        url = "https://boards.greenhouse.io/example/jobs/1"

        def filler(url, steps, resume, shot):
            return {"title": "Apply", "url": url}
        out = apply_run.stage(url, reader=lambda _u: [dict(f) for f in GREENHOUSE],
                              filler=filler)
        self.assertIn(out["state"], ("NEEDS_YOU", "AWAITING_YOU"))


if __name__ == "__main__":
    unittest.main()
