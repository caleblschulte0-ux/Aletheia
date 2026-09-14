"""Questions his facts already settle, answered without him.

2026-09-13, seventeen applications waiting on him, and his words: "it should
be able to answer some of these without me." Several were already on file or
plainly true, and each stopped for a reason in how the question was read:

- Lever ends a required label with "\\n✱" and Greenhouse with "*".
- A <select>'s options never travelled with its question, so Palantir's
  "how did you hear" and university list had nothing to choose between.
- "Yes, no restriction." beside "Yes, but I will need sponsorship" (Datadog),
  "(US) South Dakota" (Instacart) and "5+ years of experience" against a
  number (AlphaSense) were options no plain "Yes", "SD" or "7" matched.
- "Preferred First Name*" (Datadog) was read as "first name" and left empty.
- A job-alert signup ("Select how often (in days) to receive an alert:",
  Grainger) and an SMS opt-in (Epic) were treated as questions about him.
- A security clearance his resume does not show, the essential functions of
  the role, whether he ever worked at or applied to the employer, and which
  of Datadog's cities he is available in were never answered at all.
"""
from __future__ import annotations

import unittest
from unittest import mock

from aletheia import campaign, formfill, profile

KNOWN = {"first_name": "Caleb", "last_name": "Schulte", "city": "Hartford", "state": "SD",
         "country": "United States", "work_authorization": "Yes", "needs_sponsorship": "No",
         "willing_to_relocate": "Yes", "school": "University of South Dakota",
         "years_experience": "7"}


def field(selector, label, *, type_="text", required=True, choices=None, tag="input", options=None):
    row = {"selector": selector, "label": label, "type": type_, "tag": tag,
           "required": required, "name": "", "id": "", "value": ""}
    if choices is not None:
        row["choices"] = list(choices)
    if options is not None:
        row["options"] = [{"value": v, "text": t} for v, t in options]
    return row


def question(selector, label, choices=None, type_="text"):
    return {"selector": selector, "label": label, "required": True, "type": type_,
            "choices": list(choices or [])}


class TheMarksOnALabelAreNotTheQuestion(unittest.TestCase):
    def test_lever_and_greenhouse_marks_come_off(self):
        self.assertEqual(formfill._clean_label("Current location\n✱"), "Current location")
        self.assertEqual(formfill._clean_label("Preferred First Name*"), "Preferred First Name")
        self.assertEqual(formfill.match_field({"label": "Current location\n✱"}), "city")
        self.assertEqual(formfill.match_field(
            {"label": "Please tell us how you heard about this opportunity.\n✱"}), "heard_about")

    def test_a_stored_answer_is_found_under_its_mark(self):
        with mock.patch.object(profile, "_load_asked",
                               return_value={profile._asked_key("Do you have a valid passport?"):
                                             {"question": "Do you have a valid passport?", "value": "Yes"}}):
            self.assertEqual(profile.answer_for("Do you have a valid passport? *"), "Yes")


class OptionsInTheirOwnWords(unittest.TestCase):
    def test_his_yes_is_the_one_without_a_sponsorship_need(self):
        datadog = ["Yes, no restriction.", "Yes, but I will need sponsorship in the future.",
                   "No, I need sponsorship now."]
        self.assertEqual(formfill._best_option("Yes", datadog, KNOWN), "Yes, no restriction.")

    def test_a_state_behind_its_country(self):
        self.assertEqual(formfill._best_option("SD", ["(US) North Dakota", "(US) South Dakota"], KNOWN),
                         "(US) South Dakota")

    def test_a_number_of_years_lands_in_its_one_range(self):
        ranges = ["None, looking to get more experience", "1-2 years of experience",
                  "3-5 years of experience", "5+ years of experience"]
        self.assertEqual(formfill._best_option("7", ranges, KNOWN), "5+ years of experience")
        self.assertEqual(formfill._best_option("2", ranges, KNOWN), "1-2 years of experience")
        self.assertIsNone(formfill._best_option("5", ranges, KNOWN), "3-5 and 5+ both hold it")

    def test_words_employers_actually_used(self):
        self.assertEqual(formfill.match_field({"label": "Are you 18 years old or older?*"}), "over_18")
        self.assertEqual(formfill.match_field(
            {"label": "What annual base pay are you seeking (not including bonuses)?*"}), "desired_pay")
        self.assertEqual(formfill.match_field(
            {"label": "Please tell us how you heard about this opportunity.\n✱"}), "heard_about")
        self.assertIsNone(formfill.match_field(
            {"label": "If you heard about us through a referral, name the employee"}))

    def test_a_kind_of_experience_is_not_his_total_years(self):
        self.assertIsNone(formfill.match_field(
            {"label": "How many years of client facing experience do you have?*"}))
        self.assertEqual(formfill.match_field(
            {"label": "How many years of professional experience do you have?"}), "years_experience")


class ThePlanReadsWhatTheFormIs(unittest.TestCase):
    def plan(self, fields, **kw):
        with mock.patch.object(profile, "answer_for", return_value=""), \
             mock.patch.object(profile, "load", return_value={}):
            return formfill.plan(fields, answers=dict(KNOWN), **kw)

    def test_a_select_question_carries_its_options(self):
        palantir = field("select[name=q]", "Please tell us how you heard about this opportunity.\n✱",
                         tag="select", type_="select",
                         options=[("", "Select..."), ("1", "Employee referral"), ("2", "LinkedIn")])
        out = self.plan([palantir], found_on="")
        self.assertEqual(out["ask"][0]["choices"], ["Employee referral", "LinkedIn"])

    def test_a_school_not_listed_takes_the_option_the_list_names(self):
        palantir = field("select[name=u]", 'Which university did you last attend? Please select '
                         '"Other (School Not Listed)" if your school is not listed.\n✱',
                         tag="select", type_="select",
                         options=[("", "Select..."), ("a", "Stanford University"),
                                  ("o", "Other (School Not Listed)")])
        out = self.plan([palantir])
        self.assertEqual([(f["action"], f["value"]) for f in out["fill"]], [("select", "o")])

    def test_a_job_alert_widget_is_skipped_not_asked(self):
        grainger = field("#j_idt1586", "Select how often (in days) to receive an alert:", type_="number")
        out = self.plan([grainger])
        self.assertEqual(out["ask"], [])
        self.assertIn("job-alert", out["skipped"][0]["why"])

    def test_a_text_message_opt_in_is_no_not_his_phone(self):
        epic = field("#sms", "SMS Consent: Do you agree to receive mobile (text) messages from us "
                     "in relation to this job application? Y/N", choices=["Yes", "No"])
        out = self.plan([epic])
        self.assertEqual([(f["value"], f["profile_field"]) for f in out["fill"]],
                         [("No", "message_opt_in")])

    def test_preferred_first_name_is_his_first_name(self):
        datadog = field("#pref", "Preferred First Name*")
        out = self.plan([datadog])
        self.assertEqual([(f["value"], f["profile_field"]) for f in out["fill"]],
                         [("Caleb", "preferred_name")])

    def test_his_stored_answer_fills_a_select(self):
        gpa = field("select[name=g]", "GPA (Undergraduate)*", tag="select", type_="select",
                    options=[("", "Select"), ("32", "3.2 out of 4.0"), ("33", "3.3 out of 4.0")])
        with mock.patch.object(profile, "answer_for", return_value="3.2"), \
             mock.patch.object(profile, "load", return_value={}):
            out = formfill.plan([gpa], answers=dict(KNOWN))
        self.assertEqual([(f["action"], f["value"]) for f in out["fill"]], [("select", "32")])


class ADeclineOnlyWhenHeDeclined(unittest.TestCase):
    CHOICES = ["Yes", "No", "I don't wish to answer"]
    LABEL = "I identify as a first-generation professional (please select one):*"

    def test_his_own_answer_wins(self):
        with mock.patch.object(profile, "answer_for", return_value="No"), \
             mock.patch.object(profile, "load",
                               return_value={"self_id_decline": {"value": "Decline", "source": "operator"}}):
            out = formfill.plan([field("#fg", self.LABEL, choices=self.CHOICES)], answers=dict(KNOWN))
        self.assertEqual([f["value"] for f in out["fill"]], ["No"])

    def test_his_decline_is_used_when_he_never_answered_it(self):
        with mock.patch.object(profile, "answer_for", return_value=""), \
             mock.patch.object(profile, "load",
                               return_value={"self_id_decline": {"value": "Decline", "source": "operator"}}):
            out = formfill.plan([field("#fg", self.LABEL, choices=self.CHOICES)], answers=dict(KNOWN))
        self.assertEqual([f["value"] for f in out["fill"]], ["I don't wish to answer"])

    def test_silence_is_still_silence(self):
        with mock.patch.object(profile, "answer_for", return_value=""), \
             mock.patch.object(profile, "load", return_value={}):
            out = formfill.plan([field("#fg", self.LABEL, choices=self.CHOICES)], answers=dict(KNOWN))
        self.assertEqual(out["fill"], [])
        self.assertFalse(formfill.is_never_autofill({"label": self.LABEL, "choices": self.CHOICES}))


class WithNoModelAtAll(unittest.TestCase):
    def answers(self, record, resume="Business Development Associate at Expansion Capital Group", sent=None):
        with mock.patch.object(profile, "answer_for", return_value=""), \
             mock.patch.object(profile, "load", return_value={}):
            return campaign.obvious_answers(record, resume, known=dict(KNOWN), sent=sent or {})

    def test_spacex(self):
        clearances = ["Top Secret SCI with Polygraph", "Top Secret", "Secret", "Expired Clearance",
                      "Never held a clearance", "Do not wish to disclose"]
        record = {"company": "SpaceX", "questions": [
            question("#c", "Active Security Clearance(s)*", clearances),
            question("#e", "Can you perform all of the essential functions of this role with or "
                           "without reasonable accommodations?*", ["Yes", "No"])]}
        self.assertEqual(self.answers(record), {"#c": "Never held a clearance", "#e": "Yes"})

    def test_a_clearance_on_his_resume_is_never_denied(self):
        record = {"company": "SpaceX", "questions": [
            question("#c", "Active Security Clearance(s)*", ["Secret", "Never held a clearance"])]}
        self.assertEqual(self.answers(record, resume="Held an active Secret clearance"), {})

    def test_navan_never_and_then_applied(self):
        label = ("Have you ever been employed by, applied to, or are you currently employed by "
                 "Navan or any of its affiliated or group companies (Reed & Mackay)?*")
        record = {"company": "Navan", "url": "https://x/2", "questions": [question("#n", label, ["Yes", "No"])]}
        self.assertEqual(self.answers(record), {"#n": "No"})
        sent = {"https://x/1": {"company": "Navan", "job_title": "Account Manager"}}
        self.assertEqual(self.answers(record, sent=sent), {"#n": "Yes"})

    def test_datadog_authorization_and_the_jobs_own_city(self):
        cities = ["Amsterdam", "Boston", "Chicago", "Denver", "New York City"]
        record = {"company": "Datadog", "job_title": "Customer Success Manager - Boston — Datadog",
                  "questions": [
                      question("#a", "Are you legally authorised to work full-time in the country "
                                     "where this job is based?*",
                               ["Yes, no restriction.", "Yes, but I will need sponsorship in the future.",
                                "No, I need sponsorship now."]),
                      question("#c", "In what cities are you available to work?*", cities)]}
        self.assertEqual(self.answers(record), {"#a": "Yes, no restriction.", "#c": "Boston"})

    def test_a_question_he_answered_once_elsewhere(self):
        record = {"company": "Flexport", "questions": [
            question("#p", "Do you have a valid passport? *", ["Yes", "No"]),
            question("#g", "GPA (Undergraduate)*", ["Not applicable/Do not recall", "3.2 out of 4.0"])]}
        told = {"Do you have a valid passport? *": "Yes", "GPA (Undergraduate)*": "3.2"}
        with mock.patch.object(profile, "answer_for", side_effect=lambda q: told.get(q, "")), \
             mock.patch.object(profile, "load", return_value={}):
            got = campaign.obvious_answers(record, "", known=dict(KNOWN), sent={})
        # The label reaches the store without its mark.
        self.assertEqual(got, {})
        told = {"Do you have a valid passport?": "Yes", "GPA (Undergraduate)": "3.2"}
        with mock.patch.object(profile, "answer_for", side_effect=lambda q: told.get(q, "")), \
             mock.patch.object(profile, "load", return_value={}):
            got = campaign.obvious_answers(record, "", known=dict(KNOWN), sent={})
        self.assertEqual(got, {"#p": "Yes", "#g": "3.2 out of 4.0"})

    def test_a_two_word_employee_question(self):
        record = {"company": "Spectrum", "questions": [question("#s", "Spectrum employee", ["Yes", "No"])]}
        self.assertEqual(self.answers(record), {"#s": "No"})
        self.assertEqual(self.answers(record, resume="Account Manager, Spectrum, 2020-2022"), {"#s": "Yes"})

    def test_what_stays_his(self):
        record = {"company": "Samsara", "questions": [
            question("#s", "Do you accept the listed salary range for this position?*", ["Yes", "No"]),
            question("#r", "Please describe your academic background in the sciences.*", type_="textarea")]}
        self.assertEqual(self.answers(record), {})

    def test_the_model_is_not_asked_what_needs_no_model(self):
        record = {"company": "SpaceX", "questions": [
            question("#e", "Can you perform all of the essential functions of this role?*", ["Yes", "No"])]}
        asked = []
        with mock.patch.object(profile, "answer_for", return_value=""), \
             mock.patch.object(profile, "load", return_value={}), \
             mock.patch.object(profile, "known", return_value=dict(KNOWN)):
            got = campaign.answer_from_facts(record, "resume", think=lambda *a, **k: asked.append(1))
        self.assertEqual(got, {"#e": "Yes"})
        self.assertEqual(asked, [])


if __name__ == "__main__":
    unittest.main()
