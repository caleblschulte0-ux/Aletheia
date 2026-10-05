"""Twenty-first sandbox batch, 2026-10-05: the hunt's records and the projects.

    > what jobs have you applied to              [8.1s] a model
    > did anything come back from employers      [5.0s] the inbox, not the records
    > don't apply to recruiters                  "I'll leave out anything in sales; recruiters."
    > what have I told you not to apply to       [4.5s] a model
    > what roles are you going after             "... not anything in sales; recruiters."
    > what's the best job you found today        [5.0s] a model
    > what's barkly up to / whose turn is it     [5.0s] "I don't know what Barkly is"
    > what's my resume say                       [4.0s] a model
"""
import unittest
from unittest import mock

from aletheia import profile, quick

PLAN = {"slug": "barkly", "title": "Barkly", "state": "open", "project": {"repo": "x"},
        "steps": [{"n": 1, "text": "Add sound effects", "state": "done", "owner": "aletheia"},
                  {"n": 2, "text": "Record the trailer", "state": "todo", "owner": "operator"}]}


class TheHuntsRecords(unittest.TestCase):
    def test_the_sentences_reach_the_records(self):
        self.assertEqual(quick.match("what jobs have you applied to"), ("applied_to", ""))
        self.assertEqual(quick.match("did anything come back from employers"), ("replies", ""))
        self.assertEqual(quick.match("what have i told you not to apply to"), ("work_wants", ""))
        self.assertEqual(quick.match("what's blocked on me"), ("waiting", ""))

    def test_a_steering_list_is_said_as_a_list(self):
        with mock.patch("aletheia.profile.known", return_value={"work_not_wanted": "anything in sales; recruiters",
                                                                 "work_wanted": "remote work"}):
            self.assertEqual(quick.answer("what have i told you not to apply to"),
                             "You want remote work. You won't do anything in sales or recruiters.")
            said = quick.answer("what roles are you going after")
        self.assertIn("You won't do anything in sales or recruiters", said)
        self.assertNotIn("sales; recruiters", said)

    def test_the_receipt_names_the_new_one_and_what_it_joins(self):
        with mock.patch("aletheia.profile.answer", return_value="anything in sales"), \
             mock.patch("aletheia.profile.set_answer") as kept:
            said = profile.steer_by("work_not_wanted", "recruiters")
        self.assertEqual(said, "From now on I'll leave out recruiters, along with anything in sales.")
        self.assertEqual(kept.call_args[0][1], "anything in sales; recruiters")

    def test_the_best_today_is_the_summarys_standouts(self):
        summary = {"discovered": 12, "qualified": 3,
                   "outliers": [{"title": "Account Manager", "company": "Acme", "value": 9}],
                   "best": [{"title": "CSM", "company": "Globex", "value": 7}]}
        with mock.patch("aletheia.job_discovery.today", return_value=summary):
            self.assertEqual(quick.answer("what's the best job you found today"),
                             "The best today, in order: Account Manager at Acme and CSM at Globex.")
        with mock.patch("aletheia.job_discovery.today", return_value=None):
            self.assertEqual(quick.answer("any good jobs today"), "I have not gone looking for jobs yet today.")

    def test_the_resume_is_described_not_invented(self):
        with mock.patch("aletheia.campaign.read_resume", return_value=("/x/resume.docx", "Pat Example\nAccount manager with ten years\n")), \
             mock.patch("aletheia.campaign.roles_remembered", return_value=["Account Manager"]):
            said = quick.answer("what's my resume say")
        self.assertEqual(said, "Your resume is resume.docx, about 7 words. It reads as a resume for Account Manager. It opens: 'Pat Example'.")
        with mock.patch("aletheia.campaign.read_resume", side_effect=OSError("none")):
            self.assertTrue(quick.answer("what's on my resume").startswith("I can't find a resume on this PC"))


class AProjectByName(unittest.TestCase):
    def test_a_charter_says_where_it_stands_and_whose_turn(self):
        with mock.patch("aletheia.plans.all_plans", return_value=[PLAN]), \
             mock.patch("aletheia.plans.is_charter", return_value=True):
            self.assertEqual(quick.answer("what's barkly up to"),
                             "Barkly: 1 of 2 steps done. Next is step 2, Record the trailer - that one's yours.")
            self.assertEqual(quick.answer("whose turn is it on barkly"), quick.answer("what's barkly up to"))
            missing = quick.answer("what's holdco up to")
        self.assertTrue(missing.startswith("I don't have a project called holdco on record."), missing)
        self.assertIn("new project: holdco", missing)

    def test_the_weather_and_her_own_doing_are_not_projects(self):
        self.assertEqual(quick.match("what's the weather doing")[0], "weather")
        self.assertEqual(quick.match("what are you up to")[0], "doing")


if __name__ == "__main__":
    unittest.main()
