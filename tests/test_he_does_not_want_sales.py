"""The kind of work is his to say, and the resume does not get to overrule it.

2026-09-13. His resume reads as sales and business development, so every
role she derived from it was sales: Account Executive, SDR, BDR. Twenty-odd
applications went out overnight, and two more the morning after the fixes,
before he said: *"definitely don't wanna do sales. Definitely no cold
calling."* and *"there's no reason she needs to be avoiding operations."*

What he wants and will not do live in his profile, in his words
(`work_wanted`, `work_not_wanted`), and three places read them: the roles
she hunts for, the rules that close a job before a form is opened, and the
model that reads a posting. Nothing here names sales as HIS preference;
with nothing on file, a sales job is judged the way it was before.
"""
from __future__ import annotations

import unittest
from unittest import mock

from aletheia import campaign, job_fit, profile

NO_SALES = {
    "work_wanted": "operations, business operations, analyst, project coordination, "
                   "customer success, account management, partnerships",
    "work_not_wanted": "sales (account executive, SDR, BDR, inside sales) and anything "
                       "with cold calling, outbound prospecting or a new-business quota",
}


class SalesTitlesAreClosedWhenHeSaysSo(unittest.TestCase):
    def reason(self, title, text="", known=NO_SALES):
        return job_fit.hard_reason(title, text, known=known)

    def test_selling_titles_are_refused(self):
        for title in ("Account Executive, Commercial", "Sales Development Representative",
                      "Inside Sales Representative", "Business Development Representative",
                      "Corporate Account Executive", "Activation Sales Development Representative I",
                      "Sales Associate"):
            self.assertIn("sales", self.reason(title), title)

    def test_the_work_he_wants_is_not(self):
        for title in ("Sales Operations Analyst", "Revenue Operations Specialist",
                      "Customer Success Manager", "Account Manager", "Partner Manager",
                      "Business Operations Associate", "Salesforce Administrator",
                      "Operations Coordinator"):
            self.assertEqual(self.reason(title), "", title)

    def test_cold_calling_in_the_duties_closes_a_friendly_title(self):
        self.assertIn("cold calling", self.reason(
            "Account Manager", "You will make 60+ calls per day, cold calling local businesses."))
        self.assertIn("quota", self.reason(
            "Partnerships Associate", "This is a quota-carrying role focused on new logos."))
        self.assertEqual(self.reason(
            "Account Manager", "Own relationships with existing clients and renewals."), "")

    def test_nothing_on_file_changes_nothing(self):
        self.assertEqual(self.reason("Account Executive", known={}), "")

    def test_a_record_is_checked_against_his_profile_without_being_handed_it(self):
        with mock.patch.object(profile, "known", return_value=NO_SALES):
            self.assertIn("sales", job_fit.quick_reason(
                {"job_title": "Commercial Account Executive, Greenfield — Vercel",
                 "company": "Vercel"}))


# Later the same day he let up: *"the business development ... I'm fine
# doing that. I just don't want to cold calling or ... have to hit quotas ...
# the only harder rules, no cold calling, and ... I'm not trying to chase
# quotas all day."*
NO_COLD_CALLS_OR_QUOTAS = {
    "work_wanted": "business development, partnerships, account management, customer "
                   "success, operations; sales-adjacent roles are fine",
    "work_not_wanted": "cold calling, and jobs built around chasing quotas (quota-carrying roles)",
}


class OnlyColdCallingAndQuotasAreHardLines(unittest.TestCase):
    def reason(self, title, text=""):
        return job_fit.hard_reason(title, text, known=NO_COLD_CALLS_OR_QUOTAS)

    def test_a_business_development_title_is_fine_on_its_own(self):
        for title in ("Business Development Manager", "Business Development Associate",
                      "Account Executive", "Partnerships Manager"):
            self.assertEqual(self.reason(title), "", title)

    def test_quota_language_in_the_duties_closes_it(self):
        for text in ("Consistently meet or exceed quarterly quota.",
                     "Track record of 110% quota attainment.",
                     "You will own a monthly quota for new bookings.",
                     "Achieve and exceed your individual quota."):
            self.assertIn("quota", self.reason("Business Development Manager", text), text)

    def test_a_job_that_says_there_is_no_quota_is_not(self):
        for text in ("This is a non-quota role focused on partner success.",
                     "No quota - you support existing partners.",
                     "There is not a sales quota attached to this position."):
            self.assertEqual(self.reason("Partnerships Manager", text), "", text)

    def test_cold_calling_is_still_a_hard_line(self):
        self.assertIn("cold calling", self.reason(
            "Business Development Associate", "Cold calling prospects is 60% of the day."))


class TheModelHearsWhatHeSaid(unittest.TestCase):
    def test_the_fit_judgment_is_given_his_words(self):
        seen = {}

        def think(brief, text, *, context, validator, **_):
            seen.update(context)
            return validator({"realistic": True, "why": "fine"})
        job_fit.judge("Customer Success Manager", "Acme", "posting", "resume",
                      think=think, known=NO_SALES)
        self.assertEqual(seen["he_will_not_do"], NO_SALES["work_not_wanted"])
        self.assertEqual(seen["he_wants"], NO_SALES["work_wanted"])

    def test_the_brief_no_longer_decides_his_line_of_work_for_him(self):
        self.assertNotIn("IS his line of work", job_fit.FIT_BRIEF)
        self.assertIn("he_will_not_do", job_fit.FIT_BRIEF)


class TheRolesSheHuntsForAreHisKindOfWork(unittest.TestCase):
    def test_roles_carry_his_words_and_lose_a_sales_title_the_model_slips_in(self):
        seen = {}

        def think(brief, text, *, validator, context=None, **_):
            seen.update(context or {})
            return validator({"roles": ["Account Executive", "Operations Analyst",
                                        "Customer Success Manager"]})
        with mock.patch.object(profile, "known", return_value=NO_SALES):
            roles = campaign.roles_for("resume text", think=think)
        self.assertEqual(roles, ["Operations Analyst", "Customer Success Manager"])
        self.assertEqual(seen["he_will_not_do"], NO_SALES["work_not_wanted"])
        self.assertIn("he_will_not_do", campaign.ROLES_BRIEF)

    def test_a_sales_title_is_not_the_fallback_either(self):
        known = {**NO_SALES, "current_title": "Account Executive"}
        with mock.patch.object(profile, "known", return_value=known):
            with self.assertRaises(campaign.CampaignError):
                campaign.roles_for("resume text", think=False)


if __name__ == "__main__":
    unittest.main()
