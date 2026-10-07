"""An employer's next step can be a TASK: an online assessment, a recorded
one-way video, a skills test. These carry a deadline and nobody chases
them, so a missed one is a silent rejection. Before this, one was filed
as an acknowledgement, or (a one-way "video interview") sent down the
scheduling path to be answered with times. Now he hears it urgently, with
the link, and she does not answer it.
"""
from __future__ import annotations

import unittest

from aletheia import runtime
from tests import test_a_polite_subject_is_not_an_answer as polite

an_event = polite.an_event


class AnAssessmentIsHisToDo(polite.APoliteSubjectIsRead):
    # Reuse the fixture only; the inherited tests already run in their own class.
    for name in [n for n in dir(polite.APoliteSubjectIsRead) if n.startswith("test_")]:
        locals()[name] = None
    del name

    def _urgent(self):
        return [p for p in self.published if p[2].get("priority") == "URGENT"]

    def test_a_hirevue_link_under_a_thank_you_reaches_him_with_the_link(self):
        self.bodies["<m@x>"] = ("Hi Caleb, thank you for applying to Klaviyo. As a next step, please "
                                "record your answers here: https://app.hirevue.com/interviews/abc123 within 5 days.")
        out = runtime._job_reply(an_event("Thank you for applying to Klaviyo"))
        self.assertEqual(out["outcome"], "assessment")
        self.assertEqual(self.heard, [("apply-klaviyo", "noted")])
        title, body, kw = self._urgent()[0]
        self.assertEqual(title, "Klaviyo sent you an assessment")
        self.assertIn("https://app.hirevue.com/interviews/abc123", body)
        self.assertEqual(self.considered, [], "a task is never answered with times")

    def test_a_one_way_video_interview_is_not_scheduled(self):
        self.bodies["<m@x>"] = ("Hi Caleb, Klaviyo invites you to a one-way video interview. "
                                "Complete it at your convenience in the next week.")
        out = runtime._job_reply(an_event("Your Klaviyo video interview invitation"))
        self.assertEqual(out["outcome"], "assessment")
        self.assertEqual(self.considered, [])
        self.assertEqual(len(self._urgent()), 1)

    def test_an_assessment_subject_is_enough(self):
        out = runtime._job_reply(an_event("Klaviyo: Next step - Online Assessment"))
        self.assertEqual(out["outcome"], "assessment")

    def test_a_rejection_that_mentions_assessment_is_a_rejection(self):
        self.bodies["<m@x>"] = ("Thank you for applying to Klaviyo. After careful assessment of your "
                                "application, we have decided to move forward with other candidates.")
        out = runtime._job_reply(an_event("Thank you for applying to Klaviyo"))
        self.assertEqual(out["outcome"], "rejected")
        self.assertEqual(self._urgent(), [])

    def test_boilerplate_about_the_process_is_still_an_acknowledgement(self):
        self.bodies["<m@x>"] = ("Thanks for applying to Klaviyo! Our team will review your application "
                                "and be in touch about next steps.")
        out = runtime._job_reply(an_event("Thank you for applying to Klaviyo"))
        self.assertEqual(out["outcome"], "acknowledgement")
        self.assertEqual(self._urgent(), [])

    def test_a_real_interview_ask_still_goes_to_scheduling(self):
        self.bodies["<m@x>"] = "Hi Caleb, we'd love to schedule an interview. What times work this week?"
        out = runtime._job_reply(an_event("Interview with Klaviyo"))
        self.assertEqual(out["outcome"], "wants_time")
        self.assertEqual(len(self.considered), 1)


if __name__ == "__main__":
    unittest.main()
