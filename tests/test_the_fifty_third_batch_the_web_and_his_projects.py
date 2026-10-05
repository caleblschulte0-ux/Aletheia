"""Fifty-third sandbox batch, 2026-10-05: the web, the browser and his projects.

    > search for the best budget monitor   "I could not find anything matching ... I looked in Documents"
    > what's on hacker news                [5.5s] a model
    > what's the latest news               [4.7s] a model
    > what's next on barkly                [6.0s] a model
    > drop the recipe app project          [4.0s] a plan, an approval (the idea was still queued)
    > did you open any pull requests       "I haven't run a work session yet."
    > how many lines of code is aletheia   "Noted."
    > what's the latest commit on aletheia [8.5s] a model
"""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import autonomy, charters, intercom, quick, voice


class TheWeb(unittest.TestCase):
    def test_a_search_for_a_thing_that_is_not_a_file_is_the_web(self):
        self.assertEqual(voice.interpret("thea search for the best budget monitor")["command"],
                         {"kind": "research", "question": "the best budget monitor"})
        self.assertEqual(voice.interpret("thea google cheap flights to denver")["command"]["kind"], "research")
        self.assertEqual(voice.interpret("thea search for my resume")["command"]["kind"], "file_find")
        self.assertEqual(voice.interpret("thea what's on hacker news")["command"],
                         {"kind": "browse_read", "url": "https://news.ycombinator.com/"})
        self.assertIn("Which topic?", voice.interpret("thea what's the latest news")["say"])

    def test_a_question_is_never_a_code(self):
        d = voice.interpret("thea how many lines of code is aletheia")
        self.assertNotEqual(d["command"].get("kind"), "note")
        self.assertEqual(quick.match("how many lines of code is aletheia")[0], "code_size")
        self.assertRegex(quick.answer("how big is your codebase"), r"^About [\d,]+ lines of Python in \d+ modules")
        self.assertEqual(quick.match("what's the latest commit on aletheia")[0], "version")


class HisProjects(unittest.TestCase):
    def test_a_queued_idea_can_be_dropped_before_it_is_drafted(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(charters, "QUEUE_PATH", Path(tmp) / "asks.json"):
                intercom.execute_command({"kind": "project_new", "idea": "a recipe app"}, "q")
                self.assertEqual(len(charters.pending()), 1)
                d = voice.interpret("thea drop the recipe app project")
                self.assertEqual(d["command"]["kind"], "project_drop")
                self.assertTrue(d["command"]["project"].startswith("ask-"))
                self.assertEqual(intercom.execute_command(d["command"], "q"), "Dropped a recipe app before it was drafted.")
                self.assertEqual(charters.pending(), [])
                self.assertEqual(voice.interpret("thea drop the recipe app project")["command"]["kind"], "intent")

    def test_whats_next_on_a_charter(self):
        plan = {"slug": "barkly", "title": "Barkly", "state": "open", "project": {"repo": "x"},
                "steps": [{"n": 1, "text": "Get CI green", "state": "done", "owner": "thea"},
                          {"n": 2, "text": "Add sound effects", "state": "open", "owner": "caleb"}]}
        with mock.patch("aletheia.plans.all_plans", return_value=[plan]):
            d = voice.interpret("thea what's next on barkly")
        self.assertEqual(d["say"], "Next on Barkly: Add sound effects - that one's yours. 1 of 2 steps done.")

    def test_pull_requests_are_read_from_the_ledger(self):
        with mock.patch.object(autonomy, "recent", return_value=[]):
            self.assertIn("No pull requests opened in the last week", quick.answer("did you open any pull requests"))
        rows = [{"said": "opened a pull request on Barkly", "at": "2026-10-04T10:00:00Z", "consequence": "outward"}]
        with mock.patch.object(autonomy, "recent", return_value=rows):
            self.assertTrue(quick.answer("any prs this week").startswith("1 pull request in the last week: opened a pull request on Barkly"))


if __name__ == "__main__":
    unittest.main()
