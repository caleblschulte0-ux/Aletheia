"""Her work, asked about the way he asks.

"Is anything stuck" answers "say what's blocked and I'll list them", and
"what's blocked" went to the planner - a promise with no reader. "What's
in your queue", "what projects are you working on" and "what's next for
barkly" went the same way, while the work engine and the charters held
every answer.
"""
import unittest
from unittest import mock

from aletheia import plans, quick

INVENTORY = {"blocked": [{"title": "Barkly: choose the bundle id", "reason": "this step is Caleb's"},
                         {"title": "Fix the release check", "reason": "needs step #4 first"}],
             "blocked_total": 2,
             "executable_now": [{"title": "Get Barkly CI green"}], "executable_total": 1}

CHARTERS = [{"slug": "barkly", "title": "Barkly", "state": "open", "project": {"repo": "x"},
             "steps": [{"n": 1, "text": "Ship the playtest", "state": "done"},
                       {"n": 2, "text": "Get CI green", "state": "open"}]},
            {"slug": "holdco", "title": "Holdco platform", "state": "open", "project": {"repo": "y"},
             "steps": [{"n": 1, "text": "Pick the one offer", "state": "open", "owner": "caleb"}]},
            {"slug": "old", "title": "Old thing", "state": "done", "project": {"repo": "z"}, "steps": []}]


class HerQueue(unittest.TestCase):
    def setUp(self):
        p = mock.patch("aletheia.work_engine.inventory", return_value=INVENTORY)
        p.start()
        self.addCleanup(p.stop)

    def test_the_promise_has_its_reader(self):
        self.assertEqual(quick.match("what's blocked")[0], "work_blocked")
        said = quick.answer("what's blocked")
        self.assertTrue(said.startswith("2 things blocked."), said)
        self.assertIn("(yours)", said)
        self.assertIn("needs step #4 first", said)

    def test_the_queue(self):
        self.assertEqual(quick.answer("what's in your queue"),
                         "1 thing in my queue. Next up: Get Barkly CI green.")

    def test_empty_says_so(self):
        with mock.patch("aletheia.work_engine.inventory", return_value={}):
            self.assertEqual(quick.answer("what's blocked"), "Nothing is blocked.")


class HisProjects(unittest.TestCase):
    def setUp(self):
        p = mock.patch.object(plans, "all_plans", return_value=CHARTERS)
        p.start()
        self.addCleanup(p.stop)

    def test_open_projects_with_whose_next_step(self):
        said = quick.answer("what projects are you working on")
        self.assertTrue(said.startswith("2 projects:"), said)
        self.assertIn("Barkly (next, mine: Get CI green)", said)
        self.assertIn("Holdco platform (next, yours: Pick the one offer)", said)
        self.assertNotIn("Old thing", said)

    def test_the_next_step_of_one(self):
        self.assertEqual(quick.answer("what's next for barkly"), "Next on Barkly, and it's mine: Get CI green.")
        self.assertEqual(quick.answer("what's next for the holdco thing"),
                         "The next step on Holdco platform is yours: Pick the one offer.")

    def test_a_name_that_is_not_a_project_goes_on(self):
        self.assertIsNone(quick.answer("what's next for dinner"))


if __name__ == "__main__":
    unittest.main()
