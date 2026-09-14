"""The applications that still waited on him on the night of 2026-09-13.

His standing words: *"Just keep making this good. Keep making it work."* And
about essays, 2026-09-12: *"just have AI write it off the bat. It does not need
to check-in with me."*

Every label, option and posting sentence below is copied from a real record
that night (SpaceX, Samsara, Epic, Arcadia, Palantir, Spotify, Navan,
Anthropic, Renaissance, Acceleration Partners). The codes and the other
employers in the inbox are invented.
"""
from __future__ import annotations

import datetime as dt
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import apply_run, campaign, formfill, job_fit, journal, mail, policy, profile

AUTHORIZED = {"work_authorization": "Yes", "needs_sponsorship": "No"}
SPACEX_OPTIONS = [
    "I am authorized to work in the United States for any employer",
    "I am authorized to work in the United States for my present employer only",
    "I require sponsorship to work in the United States",
    "I am not authorized to work in the United States",
    "My status to work in the United States is unknown",
]
HIS_PAY = ("$100,000 minimum for a nationwide or remote role; $95,000 minimum for a "
           "role based in Sioux Falls, South Dakota.")
NO_QUOTAS = "cold calling, and jobs built around chasing quotas (quota-carrying roles)"


class AnAuthorizationListWithNoYesCase(unittest.TestCase):
    def test_spacex_gets_the_any_employer_sentence(self):
        self.assertEqual(formfill._best_option("Yes", SPACEX_OPTIONS, AUTHORIZED),
                         SPACEX_OPTIONS[0])

    def test_never_a_sponsorship_or_a_restricted_option(self):
        for known in ({"work_authorization": "Yes", "needs_sponsorship": "Yes"},
                      {"work_authorization": "Yes"}, {}):
            with self.subTest(known=known):
                self.assertIsNone(formfill._best_option("Yes", SPACEX_OPTIONS, known))
        self.assertIsNone(formfill.authorized_choice(SPACEX_OPTIONS[1:], AUTHORIZED))

    def test_citizenship_is_claimed_only_when_he_said_it(self):
        options = ["I am a U.S. citizen", "I am a lawful permanent resident",
                   "I am authorized to work but will require sponsorship"]
        with mock.patch.object(profile, "questions_on_file", return_value=[]):
            self.assertIsNone(formfill.authorized_choice(options, AUTHORIZED))
        with mock.patch.object(profile, "questions_on_file",
                               return_value=[{"question": "Which applies?", "value": "U.S. citizen"}]):
            self.assertEqual(formfill.authorized_choice(options, AUTHORIZED), "I am a U.S. citizen")
            # Citizen wording is preferred over the plain authorized one.
            self.assertEqual(formfill.authorized_choice(
                SPACEX_OPTIONS + ["I am a U.S. citizen"], AUTHORIZED), "I am a U.S. citizen")

    def test_the_stuck_record_is_answered_with_no_model(self):
        record = {"company": "SpaceX", "questions": [{
            "selector": "#question_36507227002", "required": True, "type": "text",
            "label": "Are you legally authorized to work in the United States?*",
            "choices": SPACEX_OPTIONS}]}
        with mock.patch.object(profile, "questions_on_file", return_value=[]):
            got = campaign.obvious_answers(record, "resume", known=AUTHORIZED, sent={})
        self.assertEqual(got, {"#question_36507227002": SPACEX_OPTIONS[0]})


class TheListedSalaryRangeCase(unittest.TestCase):
    RECORD = {"company": "Samsara", "url": "https://boards.greenhouse.io/embed/job_app?for=samsara&token=1",
              "questions": [{"selector": "#question_67179396", "required": True, "type": "text",
                             "label": "Do you accept the listed salary range for this position?*",
                             "choices": ["Yes", "No"]}]}

    def answer(self, posting, pay=HIS_PAY):
        return campaign.obvious_answers(self.RECORD, "resume", known={"desired_pay": pay}, sent={},
                                        describe=lambda job: posting).get("#question_67179396")

    def test_a_range_reaching_his_minimum_is_yes(self):
        self.assertEqual(self.answer("Annual Base Salary $106,802.50 – $161,550 USD Total Rewards"), "Yes")
        # What jobs.posting_text really hands back for Samsara: escaped twice.
        self.assertEqual(self.answer("Annual Base Salary $106,802.50 &mdash; $161,550 USD"), "Yes")
        self.assertEqual(self.answer("The range is $90k - $140k."), "Yes")

    def test_a_range_wholly_below_every_minimum_is_no(self):
        self.assertEqual(self.answer("Annual Base Salary $60,000 - $80,000"), "No")

    def test_between_his_two_minimums_or_no_range_stays_his(self):
        self.assertIsNone(self.answer("Annual Base Salary $80,000 - $98,000"))
        self.assertIsNone(self.answer("Competitive pay and a $2,000 - $5,000 signing bonus."))
        self.assertIsNone(self.answer(""))
        self.assertIsNone(self.answer("Annual Base Salary $106,802 – $161,550", pay=""))


INBOX = [
    ("Mon, 14 Sep 2026 03:13:03 +0000", "Security code for your application to EPIC Brokers", "epicCD01"),
    ("Mon, 14 Sep 2026 03:09:28 +0000", "Security code for your application to Northwind Insurance", "nwCODE02"),
    ("Mon, 14 Sep 2026 03:05:53 +0000", "Security code for your application to Epic Games", "gameCD03"),
]


class CodeTransport:
    def fetch_unread(self, limit):
        return [{"date": d, "subject": s, "message_id": c} for d, s, c in INBOX]

    def fetch_body(self, message_id):
        return {"text": "Copy and paste this code into the security code field on your "
                        f"application: {message_id}"}


class TheEmployerByEveryNameCase(unittest.TestCase):
    EPIC = {"company": "Epic Insurance Brokers and Consultants",
            "page_title": "Job Application for Assistant Account Manager- P&C at EPIC Brokers",
            "url": "https://boards.greenhouse.io/embed/job_app?for=edgewoodpartnersinsurancecenter&token=8760820002"}

    def setUp(self):
        for target, name, value in ((mail, "SmtpImapTransport", CodeTransport),
                                    (apply_run, "CODE_WAIT_TRIES", 1),
                                    (apply_run, "CODE_WAIT_S", 0)):
            p = mock.patch.object(target, name, value); p.start(); self.addCleanup(p.stop)

    def test_the_record_names_all_three(self):
        self.assertEqual(apply_run.employer_names(self.EPIC),
                         ["Epic Insurance Brokers and Consultants", "EPIC Brokers",
                          "edgewoodpartnersinsurancecenter"])

    def test_epics_code_is_found_by_the_name_greenhouse_used(self):
        self.assertEqual(apply_run._emailed_code(self.EPIC["company"]), "")   # the old lookup
        clicked = dt.datetime(2026, 9, 14, 3, 13, 2, tzinfo=dt.timezone.utc).timestamp()
        self.assertEqual(apply_run._emailed_code(apply_run.employer_names(self.EPIC), since=clicked),
                         "epicCD01")

    def test_a_board_name_is_the_whole_run_of_words(self):
        self.assertTrue(apply_run.names_the_employer(
            "Security code for your application to Edgewood Partners Insurance Center",
            "edgewoodpartnersinsurancecenter"))
        self.assertFalse(apply_run.names_the_employer(
            "Security code for your application to Edgewood Partners", "edgewoodpartnersinsurancecenter"))
        self.assertTrue(apply_run.names_the_employer(
            "Security code for your application to Epic Insurance Brokers & Consultants",
            "Epic Insurance Brokers and Consultants"))

    def test_one_employer_still_never_gets_anothers_code(self):
        other = {"company": "Epic Systems", "page_title": "Job Application for Analyst at Epic Systems",
                 "url": "https://boards.greenhouse.io/embed/job_app?for=epicsystems&token=1"}
        self.assertEqual(apply_run._emailed_code(apply_run.employer_names(other)), "")
        self.assertFalse(apply_run.names_the_employer(
            "Security code for your application to Epic Games", "EPIC Brokers"))


class TheResumeLandedCase(unittest.TestCase):
    class Page:
        def __init__(self, states):
            self.states = list(states)

        def evaluate(self, script, *args):
            if script == apply_run.UPLOAD_SETTLED_JS:
                return self.states.pop(0) if len(self.states) > 1 else self.states[0]
            return False

        def wait_for_timeout(self, ms):
            pass

    def test_lever_saying_success_after_the_box_empties_has_landed(self):
        """Arcadia: the picture showed "Success!" and the run said it never finished."""
        self.assertTrue(apply_run._resume_landed(self.Page(["empty", "empty", "held"]), "C:/r/cv.pdf"))

    def test_a_page_still_working_never_has(self):
        self.assertFalse(apply_run._resume_landed(self.Page(["working"]), "C:/r/cv.pdf"))
        self.assertFalse(apply_run._resume_landed(self.Page(["empty"]), "C:/r/cv.pdf"))

    def test_its_words_at_work_outrank_its_verdict(self):
        js = apply_run.UPLOAD_SETTLED_JS
        self.assertLess(js.index("analyzing"), js.index("resume-upload-success"))
        self.assertIn("auto-read resume", js)


class LeversLocationTypeaheadCase(unittest.TestCase):
    def test_it_is_driven_as_a_dropdown(self):
        self.assertIn("location-input", formfill.COMBOBOX_JS)
        for js in (formfill.VISIBLE_OPTIONS_JS, formfill.FIND_OPTION_JS):
            self.assertIn(".dropdown-location", js)

    def test_the_first_suggestion_in_his_city_and_state_is_his(self):
        known = {"city": "Hartford", "state": "SD"}
        offered = ["Hartford, CT, USA", "Hartford, SD, USA", "Hartford, South Dakota 57033, USA",
                   "Hartford, WI, USA"]
        self.assertEqual(formfill._best_option("Hartford", offered, known), "Hartford, SD, USA")
        self.assertIsNone(formfill._best_option("Hartford", ["Hartford, CT, USA"], known))


NAV_JUNK = [{"selector": f"#nav{i}", "label": label, "name": "", "id": "", "tag": "input",
             "type": "checkbox", "required": False, "value": ""}
            for i, label in enumerate(["Toggle navigation menu", "Platform", "Travel", "Solutions",
                                       "nav-group-toggle-0", "nav-group-toggle-1", "nav-group-toggle-2",
                                       "Resources", "Customers", "Cookie list search", "label",
                                       "Company news", "Press"])]
NAVAN_EMPLOYED = {"selector": "#question_navan", "label": (
    "Have you ever been employed by, applied to, or are you currently employed by Navan or any "
    "of its affiliated or group companies (Reed & Mackay)?*"), "name": "", "id": "", "tag": "input",
    "type": "text", "required": True, "value": "", "choices": ["Yes", "No"]}


class TheOneRequiredQuestionIsShownCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        d = Path(self.tmp.name)
        env = mock.patch.dict(os.environ, {"ALETHEIA_PRIVATE_STATE": str(d)})
        env.start(); self.addCleanup(env.stop)
        (d / "approvals").mkdir()
        (d / "applications").mkdir()
        for target, attr, value in (
                (journal, "JOURNAL_PATH", d / "j.jsonl"),
                (policy, "APPROVALS_DIR", d / "approvals"),
                (policy, "HALT_PATH", d / "halt.json"),
                (profile, "path", lambda: d / "answers.json"),
                (apply_run, "staged_dir", lambda: d / "applications")):
            p = mock.patch.object(target, attr, value); p.start(); self.addCleanup(p.stop)

    def test_navan_lists_the_required_question_first_and_it_is_answered(self):
        form = NAV_JUNK + [NAVAN_EMPLOYED]
        record = apply_run.stage("https://navan.com/careers/openings?gh_jid=8160538",
                                 reader=lambda url: list(form))
        self.assertEqual(record["state"], "NEEDS_YOU")
        self.assertLessEqual(len(record["questions"]), apply_run.MAX_QUESTIONS_SHOWN)
        self.assertEqual(record["questions"][0]["selector"], "#question_navan")
        record["company"] = "Navan"
        self.assertEqual(campaign.obvious_answers(record, "Expansion Capital Group", known={}, sent={}),
                         {"#question_navan": "No"})


ACCELERATION = (
    "We're looking for an Account Executive to manage and convert inbound demand for our Affiliate "
    "and Influencer Marketing Services. This is an operational, full-cycle closing role: our "
    "marketing team generates the leads, and you qualify, route, and run the sales process on the "
    "opportunities that come to you, taking deals under $250K in annual contract value from first "
    "conversation through signed contract yourself. This is not a prospecting or outbound role.")
ACV_QUESTION = ("What is the largest annual contract value (ACV) deal you have personally closed "
                "end-to-end, including building the strategic pitch yourself, without a dedicated")


class ClosingDealsIsChasingQuotaCase(unittest.TestCase):
    KNOWN = {"work_not_wanted": NO_QUOTAS}

    def test_the_posting_is_refused(self):
        self.assertTrue(job_fit.closes_deals(ACCELERATION))
        self.assertIn("closing sales deals",
                      job_fit.hard_reason("Account Executive", ACCELERATION, known=self.KNOWN))

    def test_the_form_question_closes_a_waiting_record(self):
        record = {"company": "Acceleration Partners", "job_title": "Account Executive — Acceleration Partners",
                  "fit": {"realistic": True, "by": "model"},
                  "questions": [{"label": ACV_QUESTION, "required": True, "type": "textarea"}]}
        self.assertIn("closing sales deals", job_fit.quick_reason(record, known=self.KNOWN))
        self.assertEqual(job_fit.quick_reason(record, known={}), "", "only when he said so")

    def test_work_that_is_not_closing_is_left_alone(self):
        for text in ("Partner with Sales to support renewals and drive adoption across your book.",
                     "Structure deals with ISO partners and keep the pipeline data clean.",
                     "Coordinate contract reviews with legal and finance."):
            with self.subTest(text=text):
                self.assertFalse(job_fit.closes_deals(text))
        clearance = {"job_title": "Business Operations Analyst — SpaceX",
                     "questions": [{"label": "Active Security Clearance(s)*"}]}
        self.assertEqual(job_fit.quick_reason(clearance, known=self.KNOWN), "")


class EssaysAreWrittenHonestlyCase(unittest.TestCase):
    def record(self, label):
        return {"url": "https://x", "job_title": "Partnership Manager, AI for Science — Anthropic",
                "questions": [{"selector": "#q", "type": "textarea", "required": True, "label": label}]}

    def test_the_brief_answers_a_background_he_does_not_have_with_the_one_he_does(self):
        flat = " ".join(campaign.ESSAY_BRIEF.split())
        self.assertIn("STILL ANSWERED", flat)
        self.assertIn("Never claim the thing he does not have", flat)
        self.assertIn("CANNOT WRITE", flat)
        self.assertNotIn("For anything else his resume does not support", flat)

    def test_his_ai_tools_reach_the_writer(self):
        seen = {}

        def think(prompt, resume, **kw):
            seen["prompt"] = prompt
            return "I use Claude and ChatGPT in my daily work."
        with mock.patch.object(profile, "known", return_value={"ai_tools": "Claude and ChatGPT",
                                                               "desired_pay": "secret"}):
            got = campaign.draft_essays(self.record(
                "Please describe how use use LLMs or AI tools in your research or work today*"),
                "RESUME", think=think)
        self.assertEqual(got, {"#q": "I use Claude and ChatGPT in my daily work."})
        self.assertIn("ai_tools: Claude and ChatGPT", seen["prompt"])
        self.assertNotIn("secret", seen["prompt"], "only the facts meant for essays travel")

    def test_a_figure_that_is_nowhere_still_comes_back_blank(self):
        got = campaign.draft_essays(self.record(ACV_QUESTION), "RESUME",
                                    think=lambda *a, **k: "CANNOT WRITE")
        self.assertEqual(got, {})


if __name__ == "__main__":
    unittest.main()
