"""Twenty cards that wait the same way are one card, and each names its employer.

Live 2026-09-24 his page held "Show the other 19": twenty cards under
"What she's doing", every one titled "apply for this job - waiting -
pressed; the site did not say whether it went through - Nothing: it is
never pressed twice". Honest, seven screens tall, nothing to do on any of
them, and not one said which employer.
"""
from __future__ import annotations

import unittest

from aletheia import mission_browser as mb
from aletheia import mission_control as mc


class ACardNamesItsEmployer(unittest.TestCase):
    def test_the_employer_is_read_off_the_job_url(self):
        self.assertEqual(mb.employer_from_url("https://jobs.ashbyhq.com/notion/05e14247-17c4/application"), "Notion")
        self.assertEqual(mb.employer_from_url("https://salesforce.wd12.myworkdayjobs.com/en-US/External/job/x"), "Salesforce")
        self.assertEqual(mb.employer_from_url("https://boards.greenhouse.io/embed/job_app?for=spacex&token=8815840002"), "Spacex")
        self.assertEqual(mb.employer_from_url("https://jobs.lever.co/nitra/1f2e"), "Nitra")
        self.assertEqual(mb.employer_from_url("https://www.aptiv.com/en/jobs/search/J000698866"), "aptiv.com")
        self.assertEqual(mb.employer_from_url(""), "")

    def test_the_generic_goal_becomes_apply_at_the_employer_and_others_stay(self):
        self.assertEqual(mb.named_goal({"goal": "apply for this job",
                                        "start_url": "https://jobs.ashbyhq.com/notion/abc/application"}), "Apply at Notion")
        self.assertEqual(mb.named_goal({"goal": "find the Marcus Aurelius book", "start_url": "https://x.example"}),
                         "find the Marcus Aurelius book")


def _waiting(n: int, title: str = "apply for this job") -> dict:
    return mc.mission_card(id=f"browser:m{n}", type=mb.TYPE, title=f"{title} {n}", status="WAITING",
                           step="pressed; the site did not say whether it went through",
                           next="Nothing: it is never pressed twice. A reply, if one comes, reaches the record.",
                           updated=f"2026-09-24T0{n % 10}:00:00Z")


class AlikeWaitingCardsFoldIntoOne(unittest.TestCase):
    def test_three_or_more_alike_become_one_that_names_them(self):
        cards = [_waiting(i, "Apply at Employer") for i in range(6)]
        out = mc.order_missions(cards)
        self.assertEqual(len(out), 1)
        fold = out[0]
        self.assertEqual(fold["status"], "WAITING")
        self.assertEqual(fold["title"], "6 applications are waiting to hear back")
        self.assertIn("Apply at Employer 0", fold["step"])
        self.assertIn("and 2 more", fold["step"])
        self.assertEqual(fold["next"], cards[0]["next"])
        self.assertEqual(fold["needs"], [])

    def test_two_alike_stay_as_they_are(self):
        cards = [_waiting(1), _waiting(2)]
        self.assertEqual([c["id"] for c in mc.order_missions(cards)], ["browser:m2", "browser:m1"])

    def test_what_needs_him_or_is_stuck_or_moving_is_never_folded(self):
        needs = mc.mission_card(id="browser:n", type=mb.TYPE, title="Apply at Acme", status="NEEDS YOU",
                                needs=[{"said": "a human check", "blocking": True}], next="x")
        stuck = mc.mission_card(id="browser:s", type=mb.TYPE, title="Apply at Zeta", status="BLOCKED",
                                blockers=[{"said": "it stopped"}], next="x")
        running = mc.mission_card(id="browser:r", type=mb.TYPE, title="Apply at Beta", status="RUNNING", next="x")
        waiting = [_waiting(i) for i in range(3)]
        out = mc.order_missions([needs, stuck, running, *waiting])
        ids = [c["id"] for c in out]
        self.assertEqual(ids[:3], ["browser:n", "browser:s", "browser:r"])
        self.assertEqual(len(out), 4)
        self.assertTrue(ids[3].startswith("fold:"))

    def test_different_waits_are_different_folds(self):
        a = [_waiting(i) for i in range(3)]
        b = [mc.mission_card(id=f"task:t{i}", type="task", title=f"task {i}", status="WAITING",
                             next="Pick it up when what it waits on arrives.") for i in range(3)]
        out = mc.order_missions(a + b)
        self.assertEqual(len(out), 2)
        self.assertEqual(sorted(c["type"] for c in out), sorted([mb.TYPE, "task"]))


if __name__ == "__main__":
    unittest.main()
