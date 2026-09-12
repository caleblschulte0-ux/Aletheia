"""An application is a thing with a life, not a form that was filled once.

His words, 2026-09-11: *"That's smart it should track the application as
well not just apply"*. Two defects were in the way:

- the campaign knew the job title, the employer, the posting link and where
  it found the job, set them on the record it was holding, and never wrote
  them back — so every saved application knew the form's URL and nothing
  about the job;
- nothing could record what an employer then did about it.
"""
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import apply_run, campaign, journal, stateio


class Tracked(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        d = Path(self.tmp.name)
        env = mock.patch.dict(os.environ, {"ALETHEIA_PRIVATE_STATE": str(d)})
        env.start()
        self.addCleanup(env.stop)
        p = mock.patch.object(journal, "JOURNAL_PATH", d / "j.jsonl")
        p.start()
        self.addCleanup(p.stop)

    def staged(self, run_id="apply-1", **fields):
        record = {"id": run_id, "state": "AWAITING_YOU", "url": "https://boards.x.co/form",
                  "page_title": "Application", "staged_at": stateio.utcnow(), **fields}
        apply_run.staged_dir().mkdir(parents=True, exist_ok=True)
        stateio.write_json_atomic(apply_run._record_path(run_id), record)
        return record

    # ---- what the job was --------------------------------------------

    def test_the_job_is_written_onto_the_saved_record(self):
        self.staged()
        campaign._keep_the_job({"id": "apply-1"},
                               {"title": "Account Executive", "company": "Tebra",
                                "url": "https://boards.x.co/form",
                                "posting": "https://tebra.com/jobs/1",
                                "found_on": "the company's own careers page"})
        saved = apply_run.load_run("apply-1")
        self.assertEqual(saved["job_title"], "Account Executive")
        self.assertEqual(saved["company"], "Tebra")
        self.assertEqual(saved["posting"], "https://tebra.com/jobs/1")
        self.assertEqual(saved["found_on"], "the company's own careers page")
        self.assertEqual(saved["state"], "AWAITING_YOU", "nothing else was touched")

    def test_a_record_that_is_not_on_disk_still_reports_its_job(self):
        held = campaign._keep_the_job({"id": "never-staged"},
                                      {"title": "SDR", "company": "Gong",
                                       "url": "https://x.co/f"})
        self.assertEqual(held["job_title"], "SDR")
        self.assertEqual(held["company"], "Gong")

    def test_it_keeps_only_what_an_application_record_keeps(self):
        self.staged()
        with self.assertRaises(apply_run.ApplyError):
            apply_run.remember("apply-1", state="SUBMITTED")
        self.assertEqual(apply_run.load_run("apply-1")["state"], "AWAITING_YOU")

    def test_naming_one_reads_like_a_person(self):
        self.assertEqual(
            apply_run.describe({"job_title": "Account Executive", "company": "Tebra"}),
            "Account Executive at Tebra")
        self.assertEqual(
            apply_run.describe({"job_title": "Tebra — Account Executive", "company": "Tebra"}),
            "Tebra — Account Executive", "never Tebra at Tebra")
        self.assertEqual(apply_run.describe({"page_title": "Job Application"}), "Job Application")
        self.assertEqual(apply_run.describe({"url": "https://boards.x.co/1"}),
                         "https://boards.x.co/1")

    # ---- what happened next ------------------------------------------

    def test_he_can_say_what_an_employer_did(self):
        self.staged(job_title="Account Executive", company="Tebra")
        apply_run.mark("apply-1", "replied", note="asked for a screening call")
        record = apply_run.mark("apply-1", "interview", note="Tuesday 10am")
        self.assertEqual(record["outcome"], "interview")
        self.assertEqual([o["outcome"] for o in record["outcomes"]], ["replied", "interview"])
        self.assertEqual(record["outcomes"][0]["note"], "asked for a screening call")
        self.assertTrue(record["outcomes"][1]["at"], "every outcome is dated")
        self.assertEqual(apply_run.load_run("apply-1")["outcome"], "interview")

    def test_an_outcome_she_does_not_understand_is_refused(self):
        self.staged()
        with self.assertRaises(apply_run.ApplyError):
            apply_run.mark("apply-1", "maybe someday")
        self.assertNotIn("outcome", apply_run.load_run("apply-1"))

    def test_the_outcome_is_journaled_so_it_shows_in_what_she_did(self):
        self.staged(job_title="Account Executive", company="Tebra")
        apply_run.mark("apply-1", "rejected")
        self.assertTrue(any("rejected" in str(e.get("text")) for e in journal.entries()))

    # ---- two answers, one form ----------------------------------------

    def test_a_second_answer_does_not_drop_the_first(self):
        """Live 2026-09-11: a form asking two things could never be finished.
        His "yes" to the certification was staged, his LinkedIn re-staged
        without it, and the form was blocked on the certification again."""
        form = [{"selector": "#certify", "label": "I certify the above is true.",
                 "name": "", "id": "certify", "tag": "input", "type": "checkbox",
                 "required": True, "value": ""},
                {"selector": "#li", "label": "LinkedIn profile", "name": "", "id": "li",
                 "tag": "input", "type": "text", "required": True, "value": ""},
                {"selector": "#em", "label": "Email address", "name": "", "id": "em",
                 "tag": "input", "type": "email", "required": True, "value": ""}]
        captured = []

        def filler(url, steps, resume, shot):
            captured.append(list(steps))
            return {"title": "Apply", "blocking": [], "resume_attached": True, "chosen": {}}

        with mock.patch.object(apply_run.formfill, "read_form", return_value=form), \
             mock.patch.object(apply_run.profile, "known",
                               return_value={"email": "caleblschulte0@gmail.com"}):
            first = apply_run.stage("https://boards.x.co/form", extra={"#certify": "Yes"},
                                    filler=filler)
            self.assertEqual(first["state"], "NEEDS_YOU", "his LinkedIn is still missing")
            second = apply_run.stage("https://boards.x.co/form",
                                     extra={"#li": "https://linkedin.com/in/caleb"},
                                     filler=filler)
        self.assertEqual(second["state"], "AWAITING_YOU",
                         "both of his answers were applied, so nothing blocks it")
        selectors = {step["selector"] for step in captured[-1]}
        self.assertIn("#certify", selectors, "the tick he gave first still goes on")
        self.assertIn("#li", selectors)
        self.assertEqual(apply_run.load_run(second["id"])["answers_given"],
                         {"#certify": "Yes", "#li": "https://linkedin.com/in/caleb"})

    def test_answering_a_question_does_not_throw_away_the_job(self):
        """Staging rebuilds the record from the form, so answering a question
        used to strip the job title, employer and posting the campaign had
        attached — and the tracker fell back to naming it after the form's
        page title (live 2026-09-11)."""
        # The blocker is one that is ALWAYS his: since 2026-09-12 routine
        # paperwork (privacy consents, accuracy certifications) is ticked,
        # but a declaration about whether AI wrote the application never is.
        form = [{"selector": "#certify", "label": "AI Policy for Application*",
                 "name": "", "id": "certify", "tag": "input", "type": "checkbox",
                 "required": True, "value": ""},
                {"selector": "#em", "label": "Email address", "name": "", "id": "em",
                 "tag": "input", "type": "email", "required": True, "value": ""},
                {"selector": "#fn", "label": "First name", "name": "", "id": "fn",
                 "tag": "input", "type": "text", "required": True, "value": ""}]

        def filler(url, steps, resume, shot):
            return {"title": "Job Application", "blocking": [], "resume_attached": True,
                    "chosen": {}}

        with mock.patch.object(apply_run.formfill, "read_form", return_value=form), \
             mock.patch.object(apply_run.profile, "known",
                               return_value={"email": "caleblschulte0@gmail.com",
                                             "first_name": "Caleb"}):
            blocked = apply_run.stage("https://boards.x.co/form", filler=filler)
            self.assertEqual(blocked["state"], "NEEDS_YOU")
            campaign._keep_the_job(blocked, {"title": "Account Executive", "company": "Tebra",
                                             "url": "https://boards.x.co/form",
                                             "posting": "https://tebra.com/jobs/1"})
            ready = apply_run.stage("https://boards.x.co/form", extra={"#certify": "Yes"},
                                    filler=filler)
        self.assertEqual(ready["state"], "AWAITING_YOU")
        saved = apply_run.load_run(ready["id"])
        self.assertEqual(saved["job_title"], "Account Executive")
        self.assertEqual(saved["company"], "Tebra")
        self.assertEqual(saved["posting"], "https://tebra.com/jobs/1")
        self.assertEqual(apply_run.describe(saved), "Account Executive at Tebra")

    # ---- asked once, never again --------------------------------------

    def test_an_answer_that_fits_no_field_is_still_known_next_time(self):
        """His words: "if it don't know somthing about me it can ask 1 time
        after that it should know". The long tail of form questions fits none
        of her fields, so his answer was used once and the next employer
        asked again."""
        from aletheia import formfill, profile
        asked = {"selector": "#shift", "label": "What is your preferred shift?",
                 "name": "", "id": "shift", "tag": "input", "type": "text",
                 "required": True, "value": ""}
        self.assertIsNone(formfill.match_field(asked), "no field of hers answers this")
        first = formfill.plan([asked])
        self.assertEqual([q["label"] for q in first["ask"]], ["What is your preferred shift?"])

        profile.remember_question("What is your preferred shift?", "Days")

        # the same question, worded the way another employer words it
        elsewhere = dict(asked, selector="#ps", id="ps",
                         label="Please tell us your preferred shift")
        second = formfill.plan([elsewhere])
        self.assertEqual(second["ask"], [], "she does not ask him twice")
        self.assertEqual([(f["selector"], f["value"]) for f in second["fill"]],
                         [("#ps", "Days")])
        self.assertEqual(profile.answer_for("preferred shift?"), "Days")

    def test_answering_keeps_the_open_question_and_not_the_one_job_one(self):
        """`answer_all` is the door his answers come through. What fits a
        field of hers is set as a fact there; what fits none is kept as an
        answer to that question — except "how did you hear about this role",
        which is true of one job and a lie on the next."""
        from aletheia import campaign, profile
        with mock.patch.object(campaign, "open_questions", return_value=[]), \
             mock.patch.object(campaign.apply_run, "all_runs", return_value=[]):
            campaign.answer_all({"What is your preferred shift?": "Days",
                                 "How did you hear about this role?": "A friend",
                                 "I certify the above is true.": "Yes"})
        self.assertEqual(profile.answer_for("What is your preferred shift?"), "Days")
        self.assertEqual(profile.answer_for("How did you hear about this role?"), "",
                         "true of one job, a lie on the next")
        self.assertEqual(profile.answer_for("I certify the above is true."), "",
                         "a declaration is his on every form")

    def test_a_declaration_is_never_kept_for_the_next_form(self):
        """Ticking "I certify this is true" on one employer's form is not
        consent to tick it on another's — his own standing rule."""
        from aletheia import profile
        for question in ("I certify that the information above is true.",
                         "Are you Hispanic or Latino?",
                         "I agree to the terms and conditions"):
            with self.subTest(question=question):
                self.assertIsNone(profile.remember_question(question, "Yes"))
                self.assertEqual(profile.answer_for(question), "")

    def test_what_he_was_asked_once_can_be_read_back(self):
        from aletheia import profile
        profile.remember_question("How many years selling into healthcare?", "Four")
        rows = profile.questions_on_file()
        self.assertEqual([(r["question"], r["value"]) for r in rows],
                         [("How many years selling into healthcare?", "Four")])
        self.assertTrue(rows[0]["at"])

    # ---- finding the one he means -------------------------------------

    def test_he_names_an_employer_not_an_id(self):
        self.staged("apply-1", job_title="Account Executive", company="Tebra")
        self.staged("apply-2", job_title="SDR", company="Gong")
        self.assertEqual([r["id"] for r in apply_run.find("tebra")], ["apply-1"])
        self.assertEqual([r["id"] for r in apply_run.find("sdr")], ["apply-2"])
        self.assertEqual([r["id"] for r in apply_run.find("apply-2")], ["apply-2"])
        self.assertEqual(apply_run.find("a company he never applied to"), [])
        self.assertEqual(apply_run.find(""), [])


if __name__ == "__main__":
    unittest.main()
