"""The night of 2026-09-12: thirty-five applications stopped on questions she had the answers to.

His words the next morning: *"I'm at least eighteen. I currently live in
South Dakota. Like I said, I'm willing to move. ... I should be able to get
all that information from my resume, or you should know it already, or you
should be able to handle those."*

Every label and option below is copied from a real stuck application that
night. What they had in common, by count:

- 17 were DROPDOWNS SHE HAD ANSWERED WRONG. She planned "SD" for a State
  list that says "South Dakota", "Hartford" for "In what cities are you
  available to work?", his phone number for "I have experience picking up
  the phone...". No option matched, nothing was chosen - rightly - and the
  page then complained with no selector and no options, so neither the model
  nor he could ever answer it. (`apply_run._unpicked`)
- 6 were "how did you hear about this job", which she knows: she found it.
- 5 were protected questions whose answers he gave on the 12th, worded in a
  dialect the matcher did not read.
- the rest: age, salary worded in the plural, dates of a past job read as a
  notice period, and runs where the model was out and nothing else thought.
"""
from __future__ import annotations

import unittest
from unittest import mock

from aletheia import apply_run, campaign, formfill, profile

HIS_WORDS = {
    "veteran_status": {"value": "I am not a protected veteran", "source": "operator"},
    "disability_status": {"value": "No", "source": "operator"},
    "self_id_decline": {"value": "Decline", "source": "operator"},
    "race": {"value": "White", "source": "operator"},
    "gender": {"value": "Male", "source": "operator"},
}


def field(selector, label, *, type_="text", required=True, choices=None, tag="input"):
    row = {"selector": selector, "label": label, "type": type_, "tag": tag,
           "required": required, "name": "", "id": "", "value": ""}
    if choices is not None:
        row["choices"] = list(choices)
    return row


class WordsThatAreNotThatFactCase(unittest.TestCase):
    def key(self, label):
        return formfill.match_field({"label": label})

    def test_a_sentence_about_himself_is_not_his_phone_or_his_start_date(self):
        self.assertIsNone(self.key("I have experience picking up the phone and calling new leads.*"))
        self.assertIsNone(self.key("I'm willing and able to commute by my start date to the "
                                   "Austin, TX area and work in an office"))

    def test_the_dates_of_a_past_job_are_not_when_he_can_start(self):
        for label in ("Start date month*", "End date month*", "End date year*"):
            self.assertNotEqual(self.key(label), "notice_period", label)
        self.assertEqual(self.key("Earliest start date*"), "notice_period")

    def test_a_middle_name_is_not_his_whole_name(self):
        self.assertIsNone(self.key("What is your legal middle name (optional)?"))

    def test_which_places_is_not_where_he_lives(self):
        self.assertIsNone(self.key("In what cities are you available to work?*"))
        self.assertIsNone(self.key("In what countries do you have the unrestricted right to work?*"))

    def test_the_united_states_is_still_one_place(self):
        self.assertEqual(self.key("Are you legally authorized to work in the United States?*"),
                         "work_authorization")
        self.assertEqual(self.key("Are you legally authorised to work full-time in the "
                                  "country where this job is based?*"), "work_authorization")

    def test_where_he_lives_is_still_his_state(self):
        self.assertEqual(self.key("State*"), "state")
        self.assertEqual(self.key("Which state or province do you currently live in?*"), "state")

    def test_the_tools_he_uses_answer_only_which_tool(self):
        """Replaying the stuck records found these three getting "Claude and
        ChatGPT": a yes, one of a list's options, and an essay."""
        self.assertEqual(self.key("What AI tool / LLM are you most familiar with?*"), "ai_tools")
        self.assertIsNone(self.key("When faced with a problem or a task, do you ask an AI tool "
                                   "for input and feedback to help you get started?*"))
        self.assertIsNone(self.key("Which of the following best describes how you use AI "
                                   "tools today?*"))
        self.assertIsNone(self.key("Please describe how you use LLMs or AI tools in your "
                                   "research or work today*"))

    def test_current_location_is_where_he_lives(self):
        self.assertEqual(self.key("Current location\n✱"), "city")

    def test_his_age_his_pay_and_where_he_heard(self):
        self.assertEqual(self.key("Are you at least 18 years of age?*"), "over_18")
        self.assertEqual(self.key("What are your salary expectations?*"), "desired_pay")
        self.assertEqual(self.key("What is your expected compensation range for this position?*"),
                         "desired_pay")
        self.assertEqual(self.key("How did you first learn about Affirm as an employer? *"),
                         "heard_about")
        self.assertEqual(self.key("Where have you learned about Samsara? Select all that apply.*"),
                         "heard_about")


class ChoosingTheOptionThatSaysItCase(unittest.TestCase):
    def test_a_state_code_is_the_state(self):
        self.assertEqual(formfill._best_option("SD", ["North Dakota", "South Dakota", "Texas"]),
                         "South Dakota")

    def test_his_pay_lands_in_the_range_that_holds_it(self):
        ranges = ["$70,000 - $79,999", "$80,000 - $89,999", "$90,000 - $99,999",
                  "$100,000 - $109,999", "$110,000+"]
        said = ("$100,000 minimum for a nationwide or remote role; $95,000 minimum "
                "for a role based in Sioux Falls, South Dakota.")
        self.assertEqual(formfill._best_option(said, ranges), "$100,000 - $109,999")
        self.assertIsNone(formfill._money_choice(said, ["$90,000 - $120,000",
                                                        "$100,000 - $130,000"]),
                          "two ranges hold it: that is a guess, and she does not guess")

    def test_a_select_menu_reads_a_range_too(self):
        menu = {"options": [{"value": "a", "text": "$90,000 - $99,999"},
                            {"value": "b", "text": "$100,000 - $109,999"}]}
        self.assertEqual(formfill._option_for(menu, "$100,000 minimum"), "b")


class HowHeHeardCase(unittest.TestCase):
    def test_she_found_it_on_the_careers_page(self):
        brex = ["Career Page", "Referral", "LinkedIn", "Social Media (Instagram, X)",
                "Glassdoor", "RepVue"]
        self.assertEqual(formfill.heard_about_answer("the company's own careers page", brex),
                         "Career Page")

    def test_never_a_person_or_a_network_she_did_not_use(self):
        gusto = ["LinkedIn", "Glassdoor", "Indeed", "Facebook", "Built In Colorado",
                 "News Article"]
        self.assertIsNone(formfill.heard_about_answer("the company's own careers page", gusto))

    def test_a_typed_box_gets_the_words(self):
        self.assertEqual(formfill.heard_about_answer("the company's own careers page"),
                         "The company's careers page")
        self.assertEqual(formfill.heard_about_answer("a web search"), "An online job search")
        self.assertIsNone(formfill.heard_about_answer(""))

    def test_plan_answers_it_from_where_she_found_the_job(self):
        brex = field("#heard", "How did you hear about us?*",
                     choices=["Career Page", "Referral", "LinkedIn"])
        out = formfill.plan([brex], answers={}, found_on="the company's own careers page")
        self.assertEqual([(f["selector"], f["value"]) for f in out["fill"]],
                         [("#heard", "Career Page")])
        self.assertEqual(out["ask"], [])

    def test_without_knowing_where_it_asks_as_before(self):
        brex = field("#heard", "How did you hear about us?*", choices=["Career Page", "Referral"])
        out = formfill.plan([brex], answers={})
        self.assertEqual([a["selector"] for a in out["ask"]], ["#heard"])


class TheAnswersHeAlreadyGaveCase(unittest.TestCase):
    def setUp(self):
        patch = mock.patch.object(profile, "load", return_value=dict(HIS_WORDS))
        patch.start()
        self.addCleanup(patch.stop)

    def test_protected_veteran_status_in_twilios_words(self):
        twilio = ["I am not a protected veteran",
                  "I identify as one or more of the classifications of a protected veteran",
                  "I identify as a veteran but not a protected veteran",
                  "I don't wish to answer"]
        self.assertEqual(formfill.declared_choice("Protected Veteran Status*", twilio),
                         "I am not a protected veteran")

    def test_military_status_in_robinhoods_words(self):
        robinhood = ["I am on active duty", "I am part of the national guard or on reserve",
                     "I have never served in the military", "I identify as a protected veteran",
                     "I identify as a non-protected veteran", "I don't wish to answer"]
        self.assertEqual(formfill.declared_choice("What is your military status?*", robinhood),
                         "I have never served in the military")

    def test_a_question_that_names_nothing_is_read_by_its_options(self):
        chime = ["Cisgender", "Transgender", "I prefer to self-describe", "I don't wish to answer"]
        self.assertEqual(formfill.category_of("I identify as:*", chime), "self_id_decline")
        out = formfill.plan([field("#iam", "I identify as:*", choices=chime)], answers={})
        self.assertEqual([f["value"] for f in out["fill"]], ["I don't wish to answer"])

    def test_a_list_of_races_under_a_label_that_says_self_identify(self):
        races = ["American Indian or Alaska Native", "Asian", "Black or African American",
                 "Hispanic or Latino", "White", "I prefer not to disclose"]
        label = "Please take a moment to self identify. It is entirely voluntary."
        self.assertEqual(formfill.category_of(label, races), "race")
        boxes = [dict(field(f"#r{i}", race, type_="checkbox", required=False),
                      group="q_race", question=label, option=race)
                 for i, race in enumerate(races)]
        out = formfill.plan(boxes, answers={})
        self.assertEqual([f["value"] for f in out["fill"]], ["White"])

    def test_white_in_the_words_leaflink_uses(self):
        leaflink = ["American Indian or Alaskan Native", "Asian or Pacific Islander", "Caucasian",
                    "Hispanic or Latin or Spanish Origin", "Black or African American",
                    "Two or More Races", "Prefer to Not Disclose", "Other"]
        label = "Please take a moment to self identify. It is entirely voluntary."
        self.assertEqual(formfill.declared_choice(label, leaflink), "Caucasian")

    def test_options_never_make_a_gender_list_into_a_decline(self):
        self.assertEqual(formfill.category_of("How would you describe yourself?",
                                              ["Man", "Woman", "Transgender", "Non-binary"]), "")

    def test_a_protected_question_is_protected_by_its_options_too(self):
        self.assertTrue(formfill.is_never_autofill(
            {"label": "I identify as:*", "choices": ["Cisgender", "Transgender"]}))


class AnsweredOnceIsAnsweredForBoxesCase(unittest.TestCase):
    def test_a_checkbox_list_reads_the_answer_he_gave_before(self):
        label = ("If you selected a response to the prior question other than none of the "
                 "above, please confirm whether any of the following also applies to you.")
        options = ["U.S. citizen", "U.S. permanent resident", "None of the above"]
        boxes = [dict(field(f"#c{i}", o, type_="checkbox", required=False),
                      group="q_export", question=label, option=o)
                 for i, o in enumerate(options)]
        with mock.patch.object(profile, "answer_for", return_value="U.S. citizen"):
            out = formfill.plan(boxes, answers={})
        self.assertEqual([(f["selector"], f["value"]) for f in out["fill"]],
                         [("#c0", "U.S. citizen")])


class AnAnswerForThisBoxLandsInThisBoxCase(unittest.TestCase):
    def test_an_answer_on_this_form_outranks_the_profile(self):
        state = field("#state", "State*", choices=["North Dakota", "South Dakota"])
        answers = {"state": "SD", "#state": "South Dakota"}
        out = formfill.plan([state], answers=answers)
        self.assertEqual(out["fill"], [])
        done = formfill.apply_answers(out, [state], {"#state": "South Dakota"})
        self.assertEqual(done["steps"], [{"action": "type", "selector": "#state",
                                          "value": "South Dakota"}])
        self.assertEqual(out["ask"], [])


class ADropdownThatChoseNothingIsAQuestionCase(unittest.TestCase):
    FIELDS = [field("#state", "State*", choices=["North Dakota", "South Dakota"]),
              field("#cities", "In what cities are you available to work?*",
                    choices=["Boston", "Remote"]),
              field("#optional", "Preferred office", required=False, choices=["A", "B"])]

    def test_it_comes_back_with_its_selector_and_its_options(self):
        fill = [{"selector": "#state", "label": "State*", "value": "SD"},
                {"selector": "#optional", "label": "Preferred office", "value": "C"}]
        stopped = [{"label": "State*", "why": "Please fill out this field.", "required": True}]
        missed, rest = apply_run._unpicked(fill, {"#state": "", "#optional": ""},
                                           self.FIELDS, stopped)
        self.assertEqual([(q["selector"], q["choices"]) for q in missed],
                         [("#state", ["North Dakota", "South Dakota"])])
        self.assertEqual(rest, [], "the page's complaint about it is the same question")

    def test_a_complaint_with_no_selector_is_given_the_field_it_names(self):
        stopped = [{"label": "In what cities are you available to work?*",
                    "why": "Please fill out this field.", "required": True}]
        missed, rest = apply_run._unpicked([], {}, self.FIELDS, stopped)
        self.assertEqual(missed, [])
        self.assertEqual(rest[0]["selector"], "#cities")
        self.assertEqual(rest[0]["choices"], ["Boston", "Remote"])

    def test_the_model_is_now_shown_it(self):
        record = {"id": "apply-x", "url": "https://x", "job_title": "AE",
                  "questions": [{"selector": "#state", "label": "State*", "required": True,
                                 "type": "text", "choices": ["North Dakota", "South Dakota"]}]}
        seen = {}

        def think(system, text, **kw):
            seen["questions"] = [q["selector"] for q in kw["context"]["questions"]]
            return kw["validator"]({"answers": [{"selector": "#state", "answer": "South Dakota"}]})
        self.assertEqual(campaign.answer_from_facts(record, "resume", think=think),
                         {"#state": "South Dakota"})
        self.assertEqual(seen["questions"], ["#state"])


class LeverSaysSuccessNotTheFilenameCase(unittest.TestCase):
    class Page:
        def __init__(self, upload_state):
            self.upload_state = upload_state

        def evaluate(self, script, *args):
            return self.upload_state if script == apply_run.UPLOAD_SETTLED_JS else False

    def test_a_held_file_on_a_page_at_rest_has_landed(self):
        self.assertTrue(apply_run._resume_landed(self.Page("held"), "C:/r/resume.pdf", wait_ms=0))

    def test_a_page_still_working_has_not(self):
        self.assertFalse(apply_run._resume_landed(self.Page("working"), "C:/r/resume.pdf",
                                                  wait_ms=0))
        self.assertFalse(apply_run._resume_landed(self.Page("empty"), "C:/r/resume.pdf",
                                                  wait_ms=0))


class WhenClaudeIsOutSheStillAnswersCase(unittest.TestCase):
    def test_the_short_answers_walk_the_ladder_to_her_own_model(self):
        from aletheia import local_model_pool, model_pool_config, reasoner
        questions = {"#gusto": {"label": "Have you ever worked at Gusto?*", "choices": ["Yes", "No"]}}
        validator = campaign._answers_validator(questions)

        class Run:
            output = validator({"answers": [{"selector": "#gusto", "answer": "No"}]})
        with mock.patch.object(reasoner, "subscription_json",
                               side_effect=reasoner.ReasonerUnavailable("out of session")), \
             mock.patch.object(model_pool_config, "enabled", return_value=True), \
             mock.patch.object(local_model_pool, "reachable", return_value=True), \
             mock.patch.object(local_model_pool, "auto_json", return_value=Run()) as local:
            got = campaign._any_model_answers("brief", "resume", context={},
                                              validator=validator, max_context_bytes=1024)
        self.assertEqual(got, {"answers": {"#gusto": "No"}})
        self.assertIs(local.call_args.kwargs["validator"], validator,
                      "her own model's answer passes the same validator")


class WaitingApplicationsAreReadAgainCase(unittest.TestCase):
    def test_what_waited_on_old_facts_is_staged_with_new_ones(self):
        waiting = [{"id": "apply-1", "state": "NEEDS_YOU", "url": "https://x/1",
                    "resume": "C:/r.pdf", "found_on": "the company's own careers page"}]
        calls = []

        def stager(url, **kw):
            calls.append((url, kw))
            return {"id": "apply-1", "url": url, "state": "AWAITING_YOU", "questions": []}
        with mock.patch.object(apply_run, "all_runs",
                               side_effect=lambda state=None: waiting if state == "NEEDS_YOU" else []), \
             mock.patch.object(campaign, "read_resume", return_value=("C:/r.pdf", "resume text")), \
             mock.patch.object(campaign.policy, "ensure_not_halted"), \
             mock.patch.object(campaign.journal, "append"):
            out = campaign.retry_waiting(stager=stager, json_think=False, writer=False)
        self.assertEqual(len(out["ready"]), 1)
        self.assertEqual(calls[0][1]["found_on"], "the company's own careers page")
        self.assertEqual(out["submitted"], 0)


if __name__ == "__main__":
    unittest.main()
