""""An application could not be sent" carried no way to say "try again"
(2026-09-23, the one-click walk): "Got it" was the notice's only control.
A failed send may be tried again on his tap - back to waiting with a fresh
approval, sent by the next beat - twice at most; then it needs his eyes."""
from __future__ import annotations

import unittest
from unittest import mock

from aletheia import agenda, apply_run, intercom, runtime


def _record(**over):
    base = {"id": "apply-3", "state": "FAILED", "approval": "apply-3-submit", "url": "https://x/3/apply",
            "steps": [{"action": "fill", "selector": "#name", "value": "Caleb"}],
            "company": "Acme", "job_title": "Ops", "failure": "the Submit button would not take a click"}
    base.update(over)
    return base


class RetryCase(unittest.TestCase):
    def test_back_to_waiting_with_a_fresh_approval_twice_at_most(self):
        record = _record()
        saved = {}
        with mock.patch("aletheia.apply_run.load_run", side_effect=lambda rid: dict(record)), \
             mock.patch("aletheia.apply_run._record_path", return_value="x"), \
             mock.patch("aletheia.stateio.write_json_atomic", side_effect=lambda p, v: saved.update(v)), \
             mock.patch("aletheia.apply_run.renew_approval") as renew, \
             mock.patch("aletheia.journal.append"):
            apply_run.retry("apply-3")
        self.assertEqual(saved["state"], "AWAITING_YOU")
        self.assertEqual(saved["retries"], 1)
        self.assertEqual(saved["failure_before"], "the Submit button would not take a click")
        renew.assert_called_once_with("apply-3")
        with mock.patch("aletheia.apply_run.load_run", return_value=_record(retries=2)):
            with self.assertRaises(apply_run.ApplyError):
                apply_run.retry("apply-3")
        with mock.patch("aletheia.apply_run.load_run", return_value=_record(state="SUBMITTED")):
            with self.assertRaises(apply_run.ApplyError):
                apply_run.retry("apply-3")

    def test_the_notice_carries_the_button_while_it_may_be_tried(self):
        self.assertEqual(runtime._retry_action(_record()),
                         {"label": "Try it again", "kind": "apply_retry", "args": {"which": "apply-3"}})
        self.assertIsNone(runtime._retry_action(_record(retries=2)))
        self.assertIsNone(runtime._retry_action(_record(steps=[])))

    def test_the_intercom_kind_and_its_words(self):
        with mock.patch("aletheia.apply_run.find", return_value=[_record()]), \
             mock.patch("aletheia.apply_run.retry", return_value=_record(state="AWAITING_YOU")) as retry:
            said = intercom.execute_command({"kind": "apply_retry", "which": "apply-3"}, {})
        retry.assert_called_once()
        self.assertIn("try", said.lower())
        self.assertIn("again", said)
        with mock.patch("aletheia.apply_run.find", return_value=[]):
            self.assertIn("don't have an application", intercom.execute_command({"kind": "apply_retry", "which": "nowhere"}, {}))

    def test_never_a_plan_step_or_a_missions(self):
        self.assertIn("apply_retry", intercom.PLANNER_FORBIDDEN)
        self.assertIn("apply_retry", agenda.FORBIDDEN_KINDS)


if __name__ == "__main__":
    unittest.main()
