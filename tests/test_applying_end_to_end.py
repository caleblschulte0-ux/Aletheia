"""Applying to jobs, end to end, from whatever resume he gives.

    "tonight when I ask this to apply to jobs for me it needs to be able to
    do it end to end"
    "everything should be fluid ... it'll listen to the résumé I give and
    apply to jobs based off of that ... don't hardcode this stuff"
                                                            — 2026-09-10

The first live run that afternoon, against two real Stripe applications,
staged nothing. These hold the fixes:

- the resume used is the first one that READS (the PDF did not);
- a resume teaches the profile its title, employer, school and degree;
- no role is required - the roles come from the resume;
- openings come from the configured boards and from a web search;
- a form's own required questions his facts settle are answered from them,
  and protected or legal ones never are;
- READY is the count, and it runs in its own process.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import (applications, apply_run, campaign, intercom, jobs, profile,
                      voice, workspace)

RESUME = ("Caleb Schulte\nHartford, SD 57033\ncaleb@example.invalid\n"
          "EDUCATION\nB.B.A. Business Administration, University of South Dakota, May 2025\n"
          "PROFESSIONAL EXPERIENCE\nPartner Management Processing Specialist, "
          "Expansion Capital Group, Oct 2025-Present\n" + "Processed partner deals. " * 20)


class PrivateProfile(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        for target, name, value in ((profile, "path", lambda: root / "answers.json"),
                                    (campaign, "LOCK_PATH", root / "running.json"),
                                    (campaign, "RUN_DIR", root)):
            patch = mock.patch.object(target, name, value)
            patch.start()
            self.addCleanup(patch.stop)
        self.root = root


class TheResumeThatReadsCase(PrivateProfile):
    def test_an_unreadable_pdf_gives_way_to_the_docx_beside_it(self):
        pdf, docx = self.root / "resume.pdf", self.root / "resume.docx"
        pdf.write_bytes(b"%PDF"), docx.write_bytes(b"PK")

        def read(path, anywhere=False):
            if str(path).endswith(".pdf"):
                raise ValueError("mostly unreadable characters")
            return {"text": RESUME}
        with mock.patch.object(applications, "find_resume", return_value=str(pdf)), \
             mock.patch.object(workspace, "read", side_effect=read):
            path, text = campaign.read_resume("")
        self.assertEqual(Path(path).name, "resume.docx")
        self.assertIn("University of South Dakota", text)

    def test_nothing_readable_is_said_plainly(self):
        pdf = self.root / "resume.pdf"
        pdf.write_bytes(b"%PDF")
        with mock.patch.object(applications, "find_resume", return_value=str(pdf)), \
             mock.patch.object(workspace, "read", side_effect=ValueError("unreadable")), \
             mock.patch("aletheia.files.find", return_value=[]):
            with self.assertRaises(campaign.CampaignError):
                campaign.read_resume("")


class WhatTheResumeTeachesCase(PrivateProfile):
    def think(self, value):
        return lambda system, text, **kw: kw["validator"](dict(value))

    def test_title_employer_school_and_degree_are_learned(self):
        learned = campaign.learn_more(RESUME, think=self.think({
            "current_title": "Partner Management Processing Specialist",
            "current_employer": "Expansion Capital Group",
            "school": "University of South Dakota", "degree": "B.B.A.",
            "state": "SD"}))
        self.assertEqual(profile.known()["current_employer"], "Expansion Capital Group")
        self.assertEqual(profile.known()["country"], "United States")
        self.assertIn("school", learned)

    def test_a_letter_spaced_name_is_read_by_the_model_not_split_by_spaces(self):
        spaced = "CALEB SCHU LTE\nCaleblschulte0@gmail.com\n"
        profile.learn_from_resume(spaced)
        campaign.learn_more(spaced, think=self.think({
            "first_name": "Caleb", "last_name": "Schulte", "legal_name": "Caleb Schulte"}))
        self.assertEqual((profile.known()["first_name"], profile.known()["last_name"]),
                         ("Caleb", "Schulte"))

    def test_the_sensitive_fields_are_never_read_off_a_page(self):
        campaign.learn_more(RESUME, think=self.think({
            "work_authorization": "Yes", "needs_sponsorship": "No", "desired_pay": "90000"}))
        for field in ("work_authorization", "needs_sponsorship", "desired_pay"):
            self.assertNotIn(field, profile.known())

    def test_what_he_said_outranks_what_she_read(self):
        profile.set_answer("current_title", "Director", source="operator")
        campaign.learn_more(RESUME, think=self.think({"current_title": "Specialist"}))
        self.assertEqual(profile.known()["current_title"], "Director")

    def test_no_role_the_roles_come_from_the_resume(self):
        roles = campaign.roles_for(RESUME, think=lambda s, t, **kw: kw["validator"](
            {"roles": ["Partner Manager", "Operations Analyst", "partner manager"]}))
        self.assertEqual(roles, ["Partner Manager", "Operations Analyst"])


def a_record(**over):
    record = {"id": "apply-1", "state": "NEEDS_YOU", "url": "https://x/apply", "job_title": "Ops — Stripe",
              "questions": [
                  {"selector": "#country", "label": "Country*", "required": True, "type": "text"},
                  {"selector": "#stripe", "label": "Have you ever been employed by Stripe?*",
                   "required": True, "type": "text"},
                  {"selector": "#where", "label": "Countries you anticipate working in",
                   "required": True, "type": "checkbox", "choices": ["Canada", "United States"]},
                  {"selector": "#felony", "label": "Have you been convicted of a felony?*",
                   "required": True, "type": "text"},
                  {"selector": "#gender", "label": "Gender", "required": False, "type": "text"},
              ]}
    record.update(over)
    return record


class AnsweringFromHisFactsCase(PrivateProfile):
    def test_what_the_facts_settle_is_answered_and_the_rest_is_not(self):
        seen = {}

        def think(system, text, **kw):
            seen["questions"] = [q["selector"] for q in kw["context"]["questions"]]
            return kw["validator"]({"answers": [
                {"selector": "#country", "answer": "United States"},
                {"selector": "#stripe", "answer": "No"},
                {"selector": "#where", "answer": ["United States"]},
                {"selector": "#felony", "answer": "No"},          # never his to have answered
                {"selector": "#where", "answer": "Mars"},         # not one of its choices
            ]})
        answers = campaign.answer_from_facts(a_record(), RESUME, think=think)
        self.assertNotIn("#felony", seen["questions"])
        self.assertNotIn("#gender", seen["questions"])
        self.assertEqual(answers["#country"], "United States")
        self.assertEqual(answers["#stripe"], "No")
        self.assertNotIn("#felony", answers)

    def test_how_she_found_the_job_is_a_fact_she_answers_from(self):
        """"How did you hear about this job?" blocked most forms live
        2026-09-10, and she knows the answer: she found it."""
        seen = {}

        def think(system, text, **kw):
            seen.update(kw["context"])
            return kw["validator"]({"answers": []})
        campaign.answer_from_facts(a_record(found_on="the company's own careers page"),
                                   RESUME, think=think)
        self.assertEqual(seen["found_this_job_on"], "the company's own careers page")
        self.assertIn("found_this_job_on", campaign.ANSWER_BRIEF)

    def test_no_model_answers_nothing(self):
        self.assertEqual(campaign.answer_from_facts(a_record(), RESUME, think=False), {})


class ReadyIsTheCountCase(PrivateProfile):
    def test_it_keeps_going_until_the_number_he_asked_for_is_ready(self):
        pages = {"matches": [{"apply_url": f"https://x/{i}", "title": f"Job {i}", "company": f"Co {i}"}
                             for i in range(6)], "searched": 3}
        states = iter(["NEEDS_YOU", "NEEDS_YOU", "AWAITING_YOU", "NEEDS_YOU", "AWAITING_YOU", "AWAITING_YOU"])
        calls = []

        def stager(url, resume="", note="", extra=None):
            calls.append((url, extra))
            if extra:   # the answered restage of a blocked form comes back ready
                return {"id": url, "url": url, "state": "AWAITING_YOU", "questions": []}
            return {"id": url, "url": url, "state": next(states),
                    "questions": [{"selector": "#q", "label": "Country*", "required": True, "type": "text"}]}

        def json_think(system, text, **kw):
            if system is campaign.ANSWER_BRIEF:
                return {"answers": {}}          # nothing settled: stays blocked
            return kw["validator"]({"roles": ["Operations"]} if "job titles" in system else {})
        with mock.patch.object(campaign, "read_resume", return_value=("resume.docx", RESUME)), \
             mock.patch.object(apply_run, "all_runs", return_value=[]):
            out = campaign.run("", count=2, stager=stager, json_think=json_think,
                               searcher=lambda roles, **kw: pages, draft_essays_too=False)
        self.assertEqual(out["roles"], ["Operations"])
        self.assertEqual(len(out["ready"]), 2)
        self.assertEqual(len(out["blocked"]), 3)


class OneEmployerDoesNotTakeEveryTryCase(PrivateProfile):
    def test_a_few_per_company_then_the_next_employer(self):
        """Live 2026-09-10 all eight tries were Stripe."""
        pages = {"matches": [{"apply_url": f"https://x/s{i}", "title": f"Job {i}",
                              "company": "Stripe"} for i in range(8)]
                            + [{"apply_url": "https://x/other", "title": "Job",
                                "company": "Other"}], "searched": 1}
        tried = []

        def stager(url, resume="", note="", extra=None):
            tried.append(url)
            return {"id": url, "url": url, "state": "NEEDS_YOU", "questions": []}
        with mock.patch.object(campaign, "read_resume", return_value=("resume.docx", RESUME)),              mock.patch.object(apply_run, "all_runs", return_value=[]):
            campaign.run("Operations", count=2, stager=stager, json_think=False,
                         searcher=lambda roles, **kw: pages, draft_essays_too=False)
        self.assertEqual(sum("/s" in u for u in tried), campaign.PER_COMPANY)
        self.assertIn("https://x/other", tried)


class AFactGoesOnlyWhereItIsAskedForCase(unittest.TestCase):
    """Live 2026-09-10, once his title, employer, school and city were on
    file, a keyword anywhere in a question put them into it."""

    def match(self, label, **field):
        return campaign.formfill.match_field({"label": label, **field})

    def test_the_questions_that_got_his_facts_live_get_nothing(self):
        for label in (
                "Have you previously been employed by Coinbase in any capacity?*",
                "Are you a current government official or were you a government official?*",
                "To your knowledge, do you or a close relative currently hold a position?*",
                "To your knowledge, were you referred to this position by a school?*",
                "Do you accept the listed salary range for this position?*",
                "I confirm that I reside in the United States*"):
            self.assertIsNone(self.match(label), label)

    def test_what_filled_correctly_still_does(self):
        self.assertEqual(self.match("What is your current or previous job title?*"), "current_title")
        self.assertEqual(self.match("Who is your current or previous employer?*"), "current_employer")
        self.assertEqual(self.match("Company name*"), "current_employer")
        self.assertEqual(self.match("Location (City)*"), "city")
        self.assertEqual(self.match("School*"), "school")
        self.assertEqual(self.match("Are you legally authorized to work in the United States?*"),
                         "work_authorization")
        self.assertEqual(self.match("Will you now or in the future require sponsorship?*"),
                         "needs_sponsorship")
        self.assertEqual(self.match("Are you willing to relocate?"), "willing_to_relocate")
        self.assertEqual(self.match("", name="email", id="email"), "email")


class OnlyRealQuestionsReachHimCase(PrivateProfile):
    def test_a_search_box_and_a_captcha_are_not_questions(self):
        record = a_record(questions=[
            {"selector": "#s", "label": "Search", "required": False, "type": "search"},
            {"selector": "#g", "label": "g-recaptcha-response", "required": False,
             "type": "textarea"},
            {"selector": "#li", "label": "LinkedIn Profile*", "required": True, "type": "text"}])
        with mock.patch.object(apply_run, "all_runs",
                               side_effect=lambda state: [record] if state == "NEEDS_YOU" else []):
            labels = [q["label"] for q in campaign.open_questions()]
        self.assertEqual(labels, ["LinkedIn Profile*"])


class HisNameIsNotGuessedFromSpacingCase(PrivateProfile):
    def test_a_letter_spaced_title_is_not_a_wrong_last_name(self):
        """His own .docx title is CALEB, SCHU, LTE in separate runs with spaces."""
        out = profile.learn_from_resume(
            "CALEB SCHU LTE\nHartford, SD 57033\nCaleblschulte0@gmail.com\n")
        self.assertNotIn("last_name", out)
        self.assertNotEqual(profile.answer("last_name"), "LTE")
        self.assertEqual(out["email"], "Caleblschulte0@gmail.com")
        self.assertEqual(out["postal_code"], "57033")

    def test_a_clean_capitals_name_is_written_as_a_person_writes_it(self):
        out = profile.learn_from_resume("JANE O'BRIEN\njane@example.com\n")
        self.assertEqual((out["first_name"], out["last_name"]), ("Jane", "O'Brien"))


class InItsOwnProcessCase(PrivateProfile):
    def test_it_starts_and_comes_straight_back(self):
        spawned = []
        out = campaign.start("", count=7, spawner=lambda args: spawned.append(args) or 4242)
        self.assertTrue(out["started"])
        self.assertIn("--notify", spawned[0])
        self.assertNotIn("--role", spawned[0])
        self.assertIn("jobs that fit your resume", campaign.started_words(out))

    def test_one_at_a_time(self):
        campaign.start("", count=3, spawner=lambda args: 1)
        again = campaign.start("", count=3, spawner=lambda args: self.fail("spawned twice"))
        self.assertFalse(again["started"])

    def test_a_dead_run_does_not_hold_the_lock_forever(self):
        old = (dt.datetime.now(dt.timezone.utc) - campaign.STALE_LOCK - dt.timedelta(minutes=1))
        campaign.LOCK_PATH.write_text(json.dumps({"started_at": old.isoformat()}), encoding="utf-8")
        self.assertIsNone(campaign.running())

    def test_a_rehearsal_starts_nothing(self):
        with mock.patch.dict(os.environ, {intercom.REHEARSAL: "1"}), \
             mock.patch.object(campaign, "start", side_effect=AssertionError("started")):
            said = intercom.execute_command({"kind": "apply_campaign"}, {})
        self.assertIn("rehearsal", said)

    def test_his_answer_matches_the_question_by_what_it_asks(self):
        held = [{"label": "Are you willing to relocate?*", "required": True,
                 "why": "", "selectors": {"apply-1": "#reloc"}, "jobs": ["https://x"]}]
        with mock.patch.object(campaign, "open_questions", return_value=held), \
             mock.patch.object(campaign, "answer_all", return_value={"ready": [], "blocked": []}) as apply:
            out = campaign.answer_one("the relocate one", "yes")
            self.assertEqual(out["matched"], "Are you willing to relocate?*")
            apply.assert_called_once_with({"Are you willing to relocate?*": "yes"}, stager=None)
            self.assertIsNone(campaign.answer_one("what time is lunch", "noon")["matched"])


class HeSaysApplyCase(unittest.TestCase):
    def cmd(self, said):
        return (voice._interpret(said) or {}).get("command") or {}

    def test_the_sentences(self):
        self.assertEqual(self.cmd("apply to jobs for me"), {"kind": "apply_campaign", "count": 5})
        self.assertEqual(self.cmd("apply to 10 jobs"), {"kind": "apply_campaign", "count": 10})
        got = self.cmd("apply to three operations jobs")
        self.assertEqual((got["count"], got["role"]), (3, "operations"))
        self.assertEqual(self.cmd("apply to some remote jobs with my resume")["where"], "remote")
        self.assertEqual(self.cmd("hey thea, apply for jobs for me"), {"kind": "apply_campaign", "count": 5})

    def test_the_questions_about_applications_are_still_questions(self):
        self.assertEqual(self.cmd("what jobs have i applied to").get("kind"), "applications")

    def test_role_is_optional_in_the_grammar(self):
        self.assertEqual(intercom.KIND_ARGS["apply_campaign"][0], set())


class FindingOpeningsAnywhereCase(unittest.TestCase):
    def test_every_role_is_scored_and_the_best_fit_wins(self):
        board_jobs = [{"title": "Partner Manager", "company": "A", "location": "Remote",
                       "apply_url": "u1"},
                      {"title": "Staff Software Engineer", "company": "B", "location": "",
                       "apply_url": "u2"},
                      {"title": "Operations Analyst", "company": "C", "location": "",
                       "apply_url": "u3"}]
        with mock.patch.object(jobs, "boards", return_value=[{"provider": "greenhouse", "token": "t"}]):
            out = jobs.search_many(["Partner Manager", "Operations Analyst"],
                                   fetcher=lambda board: board_jobs, limit=5)
        self.assertEqual({j["apply_url"] for j in out["matches"]}, {"u1", "u3"})

    def test_a_web_search_finds_boards_nobody_configured(self):
        page = {"links": [
            {"href": "https://boards.greenhouse.io/acme/jobs/12345", "text": "Operations Lead - Acme"},
            {"href": "https://jobs.lever.co/widgetco/0f8fad5b-d9cb-469f-a165-70867728950e", "text": "Ops"},
            {"href": "https://www.linkedin.com/jobs/view/1", "text": "not a public form"},
        ]}
        found = jobs.discover_openings(["Operations"], limit=5, http=lambda q: page)
        urls = [j["apply_url"] for j in found]
        self.assertIn("https://boards.greenhouse.io/embed/job_app?for=acme&token=12345", urls)
        self.assertIn("https://jobs.lever.co/widgetco/0f8fad5b-d9cb-469f-a165-70867728950e/apply", urls)
        self.assertEqual(len(urls), 2)


if __name__ == "__main__":
    unittest.main()
