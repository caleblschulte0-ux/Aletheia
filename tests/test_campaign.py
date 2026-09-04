"""Ten jobs, one sentence.

*"If I say apply to ten jobs with this resume I provided you, I need to
be able to do that."*

Every piece existed and none were joined: `applications` found postings
and handed back a folder, `apply_run` filled ONE form at ONE url he had
to supply himself, and `profile` knew him but nothing taught it from the
resume he named. Three good halves are not a thing that works.
"""
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import (apply_run, campaign, journal, policy, profile,
                      workspace)

RESUME = """Caleb Schulte
Austin, TX
caleblschulte0@gmail.com | (512) 555-0134
linkedin.com/in/caleb-schulte | github.com/caleblschulte0-ux
EXPERIENCE — built a pipeline."""

FORM_FIELDS = [
    {"selector": "#fn", "label": "First name", "name": "", "id": "fn",
     "tag": "input", "type": "text", "required": True, "value": ""},
    {"selector": "#em", "label": "Email address", "name": "", "id": "em",
     "tag": "input", "type": "email", "required": True, "value": ""},
    {"selector": "#cv", "label": "Resume/CV", "name": "", "id": "cv",
     "tag": "input", "type": "file", "required": True, "value": ""},
    {"selector": "#felony", "label": "Have you been convicted of a felony?",
     "name": "", "id": "felony", "tag": "select", "type": "select",
     "required": True, "value": "",
     "options": [{"value": "Yes", "text": "Yes"}, {"value": "No", "text": "No"}]},
    {"selector": "#cert", "label": "I certify the above is true.", "name": "",
     "id": "cert", "tag": "input", "type": "checkbox", "required": True,
     "value": ""},
]
POSTING_FIELDS = [{"selector": "#q", "label": "Search jobs", "name": "q",
                   "id": "q", "tag": "input", "type": "search",
                   "required": False, "value": ""}]


class CampaignCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        d = Path(self.tmp.name)
        self.ws = d / "ws"
        self.ws.mkdir()
        (self.ws / "resume.md").write_text(RESUME, encoding="utf-8")
        env = mock.patch.dict(os.environ, {"ALETHEIA_PRIVATE_STATE": str(d),
                                           "ALETHEIA_WORKSPACE": str(self.ws)})
        env.start(); self.addCleanup(env.stop)
        (d / "approvals").mkdir(); (d / "applications").mkdir()
        for target, attr, value in (
                (journal, "JOURNAL_PATH", d / "j.jsonl"),
                (policy, "APPROVALS_DIR", d / "approvals"),
                (policy, "HALT_PATH", d / "halt.json"),
                (profile, "path", lambda: d / "answers.json"),
                (apply_run, "staged_dir", lambda: d / "applications")):
            p = mock.patch.object(target, attr, value)
            p.start(); self.addCleanup(p.stop)
        self.opened = []

    def finder(self, n=3):
        return lambda q, limit=9: [
            {"url": f"https://board.example.com/job/{i}", "title": f"Role {i}"}
            for i in range(n)]

    def reader(self):
        return lambda src: ([{"url": s["url"], "title": s["title"],
                              "extract": "posting"} for s in src], [])

    def opener(self, apply_link=True):
        """A posting page with an Apply link, and the form behind it."""
        def open_page(url):
            self.opened.append(url)
            if "/apply/" in url:
                return list(FORM_FIELDS), []
            links = ([{"href": url.replace("/job/", "/apply/"),
                       "text": "Apply for this job"}] if apply_link else [])
            return list(POSTING_FIELDS), links
        return open_page

    def filler(self):
        def fake(url, steps, resume, shot):
            shot.parent.mkdir(parents=True, exist_ok=True)
            shot.write_bytes(b"png")
            return {"title": "Apply", "url": url}
        return fake

    def stager(self):
        filler = self.filler()
        opener = self.opener()

        def stage(url, **kw):
            return apply_run.stage(url, reader=lambda u: opener(u)[0],
                                   filler=filler, **kw)
        return stage

    def run_campaign(self, **kw):
        return campaign.run("engineer", finder=self.finder(),
                            reader=self.reader(), opener=self.opener(),
                            stager=self.stager(), **kw)


class OneSentenceDoesTheWholeThing(CampaignCase):
    def test_it_learns_him_from_the_resume_he_named(self):
        """He never types his own phone number to apply for a job."""
        out = self.run_campaign(count=3, resume="resume.md")
        self.assertIn("email", out["learned"])
        self.assertIn("phone", out["learned"])
        self.assertEqual(profile.answer("email"), "caleblschulte0@gmail.com")

    def test_it_follows_the_posting_to_the_actual_form(self):
        """A posting is a description with an Apply link on it. Nothing was
        following that link, so ten jobs met ten pages with no form."""
        self.run_campaign(count=2)
        self.assertTrue(any("/apply/" in u for u in self.opened))

    def test_a_posting_with_no_form_is_reported_not_silently_dropped(self):
        out = campaign.run("engineer", count=2, finder=self.finder(),
                           reader=self.reader(),
                           opener=self.opener(apply_link=False),
                           stager=self.stager())
        self.assertEqual(out["ready"] + out["blocked"], [])
        self.assertTrue(out["failed"])
        self.assertIn("no application form", out["failed"][0]["why"])

    def test_a_search_box_is_not_an_application_form(self):
        self.assertFalse(campaign._is_application_form(POSTING_FIELDS))
        self.assertTrue(campaign._is_application_form(FORM_FIELDS))

    def test_ten_is_the_ceiling(self):
        out = campaign.run("engineer", count=99, finder=self.finder(n=40),
                           reader=self.reader(), opener=self.opener(),
                           stager=self.stager())
        self.assertLessEqual(len(out["ready"]) + len(out["blocked"]),
                             campaign.MAX_JOBS)


class HeAnswersTheSameQuestionOnce(CampaignCase):
    """Ten applications ask the same three or four unanswerable things.
    Asking him thirty times is not automation, it is a worse form."""

    def test_the_questions_are_gathered_across_every_job(self):
        out = self.run_campaign(count=3)
        self.assertEqual(len(out["blocked"]), 3)
        labels = {q["label"] for q in out["questions"]}
        self.assertIn("Have you been convicted of a felony?", labels)
        felony = next(q for q in out["questions"]
                      if q["label"].startswith("Have you"))
        self.assertEqual(len(felony["jobs"]), 3, "asked once, not three times")

    def test_a_blocked_application_is_SAVED_or_the_questions_vanish(self):
        """The first version returned the blocked state and wrote nothing,
        so ten applications waiting on the same three questions left no
        trace to collect them from: it asked him nothing and produced
        nothing."""
        self.run_campaign(count=2)
        self.assertEqual(len(apply_run.all_runs("NEEDS_YOU")), 2)

    def test_one_answer_unblocks_every_job_that_asked(self):
        self.run_campaign(count=3)
        out = campaign.answer_all(
            {"Have you been convicted of a felony?": "No",
             "I certify the above is true.": True},
            stager=self.stager())
        self.assertEqual(len(out["ready"]), 3)
        self.assertEqual(out["blocked"], [])
        for record in out["ready"]:
            filled = {f["label"]: f["value"] for f in record["filled"]}
            self.assertEqual(filled["Have you been convicted of a felony?"], "No")

    def test_answering_again_does_not_leave_a_second_copy_waiting(self):
        self.run_campaign(count=2)
        campaign.answer_all({"Have you been convicted of a felony?": "No",
                             "I certify the above is true.": True},
                            stager=self.stager())
        self.assertEqual(len(apply_run.all_runs("AWAITING_YOU")), 2)
        self.assertEqual(len(apply_run.all_runs("NEEDS_YOU")), 0)

    def test_the_same_question_on_two_sites_is_one_question(self):
        """`#felony` on one site and `#q_88213` on another are the same
        question, keyed on what it ASKS."""
        a = campaign._question_key({"label": "Have you been convicted of a felony?"})
        b = campaign._question_key({"label": "Have you been  convicted of a FELONY?"})
        self.assertEqual(a, b)

    def test_an_answer_matching_no_question_is_reported_not_dropped(self):
        self.run_campaign(count=1)
        out = campaign.answer_all({"What is your favourite colour?": "green"},
                                  stager=self.stager())
        self.assertEqual(out["unmatched"], ["What is your favourite colour?"])


class NothingIsSentHere(CampaignCase):
    def test_every_ready_application_waits_on_its_own_approval(self):
        self.run_campaign(count=2)
        out = campaign.answer_all({"Have you been convicted of a felony?": "No",
                                   "I certify the above is true.": True},
                                  stager=self.stager())
        for record in out["ready"]:
            self.assertEqual(policy.load(record["approval"])["state"], "PENDING")
        self.assertIn("Nothing has been sent", campaign.spoken(out))

    def test_the_module_never_presses_submit(self):
        source = (Path(__file__).parent.parent / "aletheia" / "campaign.py"
                  ).read_text(encoding="utf-8")
        body = source.split('"""', 2)[2]
        for reach in ("apply_run.submit", "apply_run.confirm", "page.click"):
            self.assertNotIn(reach, body, reach)

    def test_a_halt_stops_it_before_it_searches(self):
        policy.halt("stop", via="test")
        touched = []
        with self.assertRaises(Exception):
            campaign.run("engineer", finder=lambda q, limit=9:
                         touched.append(1) or [], reader=self.reader(),
                         opener=self.opener(), stager=self.stager())
        self.assertEqual(touched, [])

    def test_he_can_just_say_it(self):
        from aletheia import intercom, planner
        self.assertIn("apply_campaign", intercom.KIND_ARGS)
        self.assertIn("apply_campaign", intercom.LOCAL_KINDS)
        self.assertIn("apply_campaign(", planner.grammar_brief())
        note = intercom.KIND_NOTES["apply_campaign"]
        self.assertIn("THE ONE TO USE", note)
        self.assertIn("submits nothing", note.casefold())


if __name__ == "__main__":
    unittest.main()
