"""Night sweep 2026-09-23, every frontier off: "anything from Vanta" went to
a planner nobody could run. The application's own record is the answer, and
"did Vanta reply" is the same question."""
import unittest
from unittest import mock

from aletheia import quick


class AnythingFromThemCase(unittest.TestCase):
    def test_the_shapes_are_claimed_with_the_employer(self):
        for said, who in (("anything from Vanta", "vanta"), ("anything back from vanta yet", "vanta"),
                          ("any word from Datadog", "datadog"), ("heard anything from Ramp?", "ramp"),
                          ("have you heard back from Stripe", "stripe"), ("did we hear back from Nitra", "nitra"),
                          ("did Vanta reply", "vanta"), ("has Datadog responded yet", "datadog"),
                          ("has the Ramp one gotten back to me", "ramp one")):
            with self.subTest(said=said):
                found = quick.match(said)
                self.assertIsNotNone(found, f"{said!r} should be claimed")
                self.assertEqual(found[0], "opportunity_loose")
                self.assertEqual(found[1].casefold(), who)

    def test_the_record_answers_and_nothing_matching_stays_with_a_model(self):
        rec = {"id": "apply-1", "state": "SUBMITTED", "company": "Vanta", "job_title": "CSM",
               "submitted_at": "2026-09-23T06:00:00Z"}
        with mock.patch("aletheia.pursuit.search", return_value=[]), \
             mock.patch("aletheia.apply_run.find", side_effect=lambda w: [rec] if "vanta" in w.casefold() else []), \
             mock.patch("aletheia.apply_run.describe", return_value="CSM at Vanta"):
            said = quick.answer("anything from Vanta")
            self.assertTrue(said and said.startswith("CSM at Vanta"), said)
            self.assertIsNone(quick.answer("anything from the plumber"))


if __name__ == "__main__":
    unittest.main()
