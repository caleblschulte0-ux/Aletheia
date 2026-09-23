"""From the 2026-09-23 night sweep with every frontier off: "give me a status
update" and "did I get any rejections" waited two minutes; "plan my day"
planned "Plan your day" as a step; "how am I doing on the job hunt" waited
two minutes for a shape that already existed under other words; "how many
interviews do I have" was her own model saying "nothing tracked" about a
store that tracks exactly that."""
from __future__ import annotations

import unittest
from unittest import mock

from aletheia import quick


class StatusCase(unittest.TestCase):
    def test_a_status_is_every_store_in_one_breath(self):
        with mock.patch("aletheia.running.snapshot", return_value={"parts": []}), \
             mock.patch("aletheia.running.all_well", return_value=True), \
             mock.patch("aletheia.needs_you.items", return_value=[{"what": "x"}, {"what": "y"}]), \
             mock.patch("aletheia.quick._job_hunt", return_value="3 applications sent today."), \
             mock.patch("aletheia.quick._agenda", return_value="Nothing on your calendar today."), \
             mock.patch("aletheia.quick._tasks", return_value="2 tasks open. Next: call the plumber."):
            for said in ("give me a status update", "catch me up", "how are things", "sitrep"):
                with self.subTest(said=said):
                    out = quick.answer(said)
                    self.assertEqual(out, "Everything's running. 2 things need you. 3 applications sent today. "
                                          "Nothing on your calendar today. 2 tasks open. Next: call the plumber.")

    def test_something_wrong_leads_with_the_health_line(self):
        with mock.patch("aletheia.running.snapshot", return_value={"parts": []}), \
             mock.patch("aletheia.running.all_well", return_value=False), \
             mock.patch("aletheia.running.headline", return_value="I'm running but halted."), \
             mock.patch("aletheia.needs_you.items", return_value=[]), \
             mock.patch("aletheia.quick._job_hunt", return_value=None), \
             mock.patch("aletheia.quick._agenda", return_value=None), \
             mock.patch("aletheia.quick._tasks", return_value="Nothing open on your task list."):
            self.assertEqual(quick.answer("give me a status update"), "I'm running but halted. Nothing needs you.")


class FocusCase(unittest.TestCase):
    def test_first_what_needs_him_then_what_is_due(self):
        with mock.patch("aletheia.needs_you.items", return_value=[{"what": "Approve the Datadog application"}]), \
             mock.patch("aletheia.quick._tasks", return_value="1 task open. Next: call the plumber."), \
             mock.patch("aletheia.quick._agenda", return_value="Dentist at 3 pm."):
            for said in ("what should I focus on today", "plan my day", "what's the most important thing"):
                with self.subTest(said=said):
                    out = quick.answer(said)
                    self.assertTrue(out.startswith("First, 1 thing needs you - the first is Approve the Datadog"), out)
                    self.assertIn("call the plumber", out)
                    self.assertIn("Dentist", out)

    def test_a_clear_day_says_so(self):
        with mock.patch("aletheia.needs_you.items", return_value=[]), \
             mock.patch("aletheia.quick._tasks", return_value="Nothing open on your task list."), \
             mock.patch("aletheia.quick._agenda", return_value="Nothing on your calendar today."):
            self.assertIn("the day is yours", quick.answer("what should I do today"))


class OutcomesCase(unittest.TestCase):
    ROWS = [{"id": "a", "company": "Datadog", "outcomes": [{"outcome": "interview"}]},
            {"id": "b", "company": "Vanta", "outcome": "rejected", "outcomes": [{"outcome": "rejected"}]},
            {"id": "c", "company": "Brex", "state": "REJECTED"},
            {"id": "d", "company": "Ramp", "outcomes": [{"outcome": "interview"}]}]

    def test_interviews_rejections_and_offers_are_counted_from_the_records(self):
        with mock.patch("aletheia.apply_run.all_runs", return_value=self.ROWS):
            self.assertEqual(quick.answer("how many interviews do I have"), "2 interviews on record: Datadog and Ramp.")
            self.assertEqual(quick.answer("did I get any rejections"), "2 rejections on record: Vanta and Brex.")
            self.assertEqual(quick.answer("any offers"), "No offers on record.")
            self.assertEqual(quick.answer("who rejected me"), "2 rejections on record: Vanta and Brex.")
            self.assertEqual(quick.answer("who wants to interview me")
                             if quick.match("who wants to interview me") else quick.answer("who wants an interview"),
                             "2 interviews on record: Datadog and Ramp.")

    def test_the_job_hunt_in_other_words(self):
        with mock.patch("aletheia.quick._job_hunt", return_value="No applications today.") as hunt:
            for said in ("how am I doing on the job hunt", "how's my job search coming along"):
                with self.subTest(said=said):
                    self.assertEqual(quick.answer(said), "No applications today.")
        self.assertTrue(hunt.called)


if __name__ == "__main__":
    unittest.main()
