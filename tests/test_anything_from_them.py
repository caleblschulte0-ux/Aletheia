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


class ThreeMoreFromTheSecondSweep(unittest.TestCase):
    """"what did you apply to today", "how many did you send this week" and
    "are you up to date" (answered with when the code last changed) - the
    2026-09-23 night sweep, every frontier off."""

    def test_what_did_you_apply_to_today_is_the_records(self):
        self.assertEqual(quick.match("what did you apply to today")[0], "applied_to")
        self.assertEqual(quick.match("where did we apply this week")[0], "applied_to")

    def test_how_many_did_you_send_this_week_is_the_existing_count_by_date(self):
        """One implementation: the status shape already counts by date for
        "how many jobs did I apply to this week"; the elliptical "how many did
        you send this week" is the same question."""
        self.assertEqual(quick.match("how many did you send this week")[0], "status_of")
        self.assertEqual(quick.match("how many did you send this week")[1], "how many did you send this week")
        self.assertEqual(quick.match("how many applications did you send in total")[0], "status_of")


    def test_are_you_up_to_date_is_answered_yes_or_no(self):
        done = mock.Mock(returncode=0, stdout="2026-09-23T03:17:00+00:00\n")
        with mock.patch("aletheia.proc.run", return_value=done), \
             mock.patch("aletheia.running.version", return_value={"running_old_code": False, "behind_count": 0}):
            self.assertTrue(quick.answer("are you up to date").startswith("Yes. "))
        with mock.patch("aletheia.proc.run", return_value=done), \
             mock.patch("aletheia.running.version", return_value={"running_old_code": False, "behind_count": 3}):
            said = quick.answer("are you up to date")
            self.assertTrue(said.startswith("No. "), said)
            self.assertIn("3 newer changes", said)
        with mock.patch("aletheia.proc.run", return_value=done), \
             mock.patch("aletheia.running.version", return_value={"running_old_code": False, "behind_count": 0}):
            self.assertFalse(quick.answer("when did you last update").startswith("Yes"),
                             "a when-question is not answered yes or no")

    def test_whats_broken_in_the_fleet_is_the_alerts_shape(self):
        self.assertEqual(quick.match("what's broken in the fleet")[0], "alerts")
        self.assertEqual(quick.match("what is failing across the fleet")[0], "alerts")


if __name__ == "__main__":
    unittest.main()
