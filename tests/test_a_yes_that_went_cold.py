"""On his PC, 2026-09-23, seven filled applications sat AWAITING_YOU with
EXPIRED approvals while the beat spent a grant use on each of them every
beat and then failed to confirm: eleven claims on the grant, nothing sent.
A yes that went cold is asked again - a fresh approval bound to the same
page and steps - and only then is the grant spent. A no is never spent on."""
from __future__ import annotations

import unittest
from unittest import mock

from aletheia import apply_run, runtime, standing


class RenewalCase(unittest.TestCase):
    def test_a_fresh_approval_binds_the_same_steps(self):
        record = {"id": "apply-7", "state": "AWAITING_YOU", "approval": "apply-7-submit",
                  "url": "https://x/7/apply", "steps": [{"action": "fill", "selector": "#name", "value": "Caleb"}],
                  "company": "Acme", "job_title": "Ops"}
        requested = {}
        with mock.patch("aletheia.apply_run.load_run", return_value=dict(record)), \
             mock.patch("aletheia.apply_run._record_path", return_value="x"), \
             mock.patch("aletheia.stateio.write_json_atomic") as write, \
             mock.patch("aletheia.policy.request", side_effect=lambda aid, action, **kw: requested.update({"id": aid, "action": action, **kw})), \
             mock.patch("aletheia.journal.append"):
            new_id = apply_run.renew_approval("apply-7")
        self.assertEqual(new_id, "apply-7-submit-r1")
        from aletheia import browse
        self.assertEqual(requested["action"], browse.approval_action(record["url"], record["steps"]))
        self.assertEqual(requested["capability"], "application.submit")
        saved = write.call_args[0][1]
        self.assertEqual(saved["approval"], "apply-7-submit-r1")
        self.assertEqual(saved["approval_renewals"], 1)

    def test_one_that_already_went_is_never_renewed(self):
        with mock.patch("aletheia.apply_run.load_run", return_value={"id": "apply-8", "state": "SUBMITTED"}):
            with self.assertRaises(apply_run.ApplyError):
                apply_run.renew_approval("apply-8")


class TheBeatCase(unittest.TestCase):
    def tearDown(self):
        standing.jobs_disable()

    def _beat(self, state, renewed_state="PENDING"):
        record = {"id": "apply-9", "state": "AWAITING_YOU", "approval": "apply-9-submit",
                  "job_title": "Operations Analyst", "company": "Acme", "url": "https://x/9"}
        states = {"apply-9-submit": {"state": state}, "apply-9-submit-r1": {"state": renewed_state}}
        seen = {"renewed": 0, "confirmed": [], "claims_before": 0, "claims_after": 0}

        def renew(run_id):
            seen["renewed"] += 1
            record["approval"] = "apply-9-submit-r1"
            return "apply-9-submit-r1"

        grant = standing.jobs_enable()
        from aletheia import authority
        seen["claims_before"] = len(authority._claims(grant["id"]))
        with mock.patch("aletheia.apply_run.all_runs", return_value=[record]), \
             mock.patch("aletheia.apply_run.load_run", side_effect=lambda rid: dict(record)), \
             mock.patch("aletheia.policy.load", side_effect=lambda aid: dict(states[aid])), \
             mock.patch("aletheia.apply_run.waits_for_his_ok", return_value=""), \
             mock.patch("aletheia.apply_run.renew_approval", side_effect=renew), \
             mock.patch("aletheia.apply_run.confirm", side_effect=lambda rid, **kw: seen["confirmed"].append((rid, kw))), \
             mock.patch("aletheia.apply_run.accept"), \
             mock.patch("aletheia.runtime._submit_in_its_own_process", return_value={"state": "SUBMITTED"}), \
             mock.patch("aletheia.notifications.publish"):
            runtime.send_approved_applications()
        seen["claims_after"] = len(authority._claims(grant["id"]))
        return seen

    def test_an_expired_yes_is_renewed_then_sent_on_the_grant(self):
        seen = self._beat("EXPIRED")
        self.assertEqual(seen["renewed"], 1)
        self.assertEqual([c[0] for c in seen["confirmed"]], ["apply-9"])
        self.assertEqual(seen["claims_after"] - seen["claims_before"], 1)

    def test_a_no_is_never_spent_on(self):
        seen = self._beat("DENIED")
        self.assertEqual(seen["renewed"], 0)
        self.assertEqual(seen["confirmed"], [])
        self.assertEqual(seen["claims_after"], seen["claims_before"])


if __name__ == "__main__":
    unittest.main()
