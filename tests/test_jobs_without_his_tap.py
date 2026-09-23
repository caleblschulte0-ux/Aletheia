"""His ruling, 2026-09-23: "Yes, this can apply to jobs without my
permission. In fact, that's like kind of the whole point of it."

The beat has spent a standing grant over `application.submit` since
2026-09-12, and nothing had ever created one - so every filled application
waited for a tap, silently, and 82 were waiting the night he said this.
Two things hold now: there is a door that creates the grant, at his
keyboard, with his words on it; and a missing grant is SAID, once, with the
command, instead of each application quietly waiting."""
from __future__ import annotations

import unittest
from unittest import mock

from aletheia import authority, runtime, standing


class TheJobsGrantCase(unittest.TestCase):
    def tearDown(self):
        standing.jobs_disable()

    def test_the_grant_is_spent_by_the_beats_own_check(self):
        self.assertIsNone(standing.jobs_active())
        grant = standing.jobs_enable(quote="this can apply to jobs without my permission")
        self.assertEqual(grant["capability_ids"], ["application.submit"])
        self.assertTrue(standing.jobs_status()["granted"])
        # The exact call the beat makes, and it now finds something.
        self.assertEqual(authority.satisfy("application.submit", "apply-1-submit"), grant["id"])
        self.assertEqual(standing.jobs_status()["uses_left"], standing.DEFAULT_JOB_USES - 1)
        # Twice is once.
        self.assertEqual(standing.jobs_enable()["id"], grant["id"])

    def test_his_words_are_on_the_grant(self):
        from aletheia import policy
        grant = standing.jobs_enable(quote="the whole point of it")
        self.assertEqual(policy.load(grant["approval_id"])["state"], "APPROVED")
        self.assertIn("the whole point of it", grant["note"])

    def test_revoked_is_revoked(self):
        standing.jobs_enable()
        self.assertTrue(standing.jobs_disable())
        self.assertIsNone(standing.jobs_active())
        self.assertIsNone(authority.satisfy("application.submit", "apply-2-submit"))
        self.assertFalse(standing.jobs_disable())

    def test_it_never_reaches_past_sending_applications(self):
        """The grant names one capability. `authority.allows` is what keeps a
        grant off anything high-risk; this checks the door only asks for
        the one thing."""
        grant = standing.jobs_enable()
        for other in ("email.send", "intent.execute.routine", "shopping.purchase"):
            with self.subTest(other=other):
                self.assertFalse(authority.allows(grant, other))

    def test_the_cli_answers(self):
        self.assertEqual(standing.main(["jobs", "status"]), 0)
        self.assertEqual(standing.main(["jobs", "on", "--quote", "send them"]), 0)
        self.assertTrue(standing.jobs_active())
        self.assertEqual(standing.main(["jobs", "off"]), 0)

    def test_what_she_says_is_the_state(self):
        self.assertIn("ask you before every application", standing.jobs_spoken())
        standing.jobs_enable()
        said = standing.jobs_spoken()
        self.assertIn("without asking", said)
        self.assertNotIn("application.submit", said)


class AMissingGrantIsSaidCase(unittest.TestCase):
    def tearDown(self):
        standing.jobs_disable()

    def test_said_once_with_the_command_when_there_is_no_grant(self):
        with mock.patch("aletheia.notifications.publish") as publish:
            runtime._say_the_grant_is_missing()
        publish.assert_called_once()
        title, body = publish.call_args[0][:2]
        self.assertIn("waiting for a tap", title)
        self.assertIn("python -m aletheia.standing jobs on", body)
        self.assertEqual(publish.call_args[1].get("dedupe_key"), "apply-grant-missing")

    def test_not_said_while_a_grant_exists(self):
        standing.jobs_enable()
        with mock.patch("aletheia.notifications.publish") as publish:
            runtime._say_the_grant_is_missing()
        publish.assert_not_called()

    def test_the_beats_action_id_is_one_the_claim_store_accepts(self):
        """`apply:<id>` was refused by `safe_id` (no colon allowed), so with a
        live grant the beat still sent nothing and said nothing."""
        standing.jobs_enable()
        record = {"id": "apply-7", "state": "AWAITING_YOU", "approval": "apply-7-submit",
                  "job_title": "Operations Analyst", "company": "Acme", "url": "https://x/7"}
        with mock.patch("aletheia.apply_run.all_runs", return_value=[record]), \
             mock.patch("aletheia.policy.load", return_value={"state": "PENDING"}), \
             mock.patch("aletheia.apply_run.waits_for_his_ok", return_value=""), \
             mock.patch("aletheia.apply_run.confirm") as confirm, \
             mock.patch("aletheia.apply_run.accept"), \
             mock.patch("aletheia.runtime._submit_in_its_own_process", return_value={"state": "SUBMITTED"}), \
             mock.patch("aletheia.notifications.publish"):
            runtime.send_approved_applications()
        confirm.assert_called_once()
        self.assertEqual(confirm.call_args[0][0], "apply-7")
        self.assertEqual(confirm.call_args[1].get("via"), "standing-grant")
        self.assertEqual(standing.jobs_status()["uses_left"], standing.DEFAULT_JOB_USES - 1)

    def test_the_beat_says_it_rather_than_passing_in_silence(self):
        record = {"id": "apply-9", "state": "AWAITING_YOU", "approval": "apply-9-submit",
                  "job_title": "Operations Analyst", "company": "Acme", "url": "https://x/9"}
        with mock.patch("aletheia.apply_run.all_runs", return_value=[record]), \
             mock.patch("aletheia.policy.load", return_value={"state": "PENDING"}), \
             mock.patch("aletheia.apply_run.waits_for_his_ok", return_value=""), \
             mock.patch("aletheia.notifications.publish") as publish:
            runtime.send_approved_applications()
        self.assertTrue(any("waiting for a tap" in c.args[0] for c in publish.call_args_list),
                        [c.args[0] for c in publish.call_args_list])


if __name__ == "__main__":
    unittest.main()
