"""Ninth sandbox batch, 2026-10-05, frontier on:

    > put a hold on monday at 10 for the dentist
      I can't find free time around travel, pencil in a tentative hold on the
      calendar, propose and confirm times, and wake deadlines before they are
      due yet. I've put it on the build list. What I can do: here's what I'd
      do: Hold Monday at 10 in the morning for the dentist. ...

The model named calendar.hold as a gap beside the step that USES it;
calendar.hold is EXPERIMENTAL, so the gate kept the gap, and the registry's
description was read out as a thing she lacks, in front of the plan that
does it. Also from the batch: "what's pending" read the raw reason
('operator said: "spoken to the wall: ..."'), and one denial was two lines
("Refused: ... — denied by voice" and "Denied: ...").
"""
import unittest
from unittest import mock

from aletheia import intents, planner, policy, quick


def _record(steps):
    return {"id": "intent-x", "state": "PROPOSED", "summary": "Hold Monday at 10 for the dentist",
            "steps": steps, "gap_tasks": ["verify-calendar-hold"]}


class AnExperimentalGapBesideARealStep(unittest.TestCase):
    def test_the_real_step_is_offered_and_the_gap_is_not_announced(self):
        steps = [{"n": 1, "status": planner.EXECUTABLE, "command": {"kind": "calendar_hold"},
                  "detail": "Hold Monday at 10 for the dentist"},
                 {"n": 2, "status": planner.GAP, "capability": "calendar.hold", "detail": "EXPERIMENTAL"}]
        with mock.patch("aletheia.capabilities.get", return_value={"id": "calendar.hold", "status": "EXPERIMENTAL",
                                                                    "description": "Find free time around travel"}):
            said = intents.spoken(_record(steps))
        self.assertNotIn("I can't", said)
        self.assertNotIn("build list", said)
        self.assertIn("Hold Monday at 10 for the dentist", said)

    def test_alone_it_is_i_can_try_not_i_cant(self):
        steps = [{"n": 1, "status": planner.GAP, "capability": "calendar.hold", "detail": "EXPERIMENTAL"}]
        with mock.patch("aletheia.capabilities.get", return_value={"id": "calendar.hold", "status": "EXPERIMENTAL",
                                                                    "description": "Find free time around travel"}):
            said = intents.spoken(_record(steps))
        self.assertTrue(said.startswith("I can try to"), said)
        self.assertNotIn("I can't", said)

    def test_a_real_gap_is_still_said_first(self):
        steps = [{"n": 1, "status": planner.EXECUTABLE, "command": {"kind": "note"}, "detail": "Note it"},
                 {"n": 2, "status": planner.GAP, "capability": "finance.transact", "detail": "NOT_BUILT"}]
        with mock.patch("aletheia.capabilities.get", return_value={"id": "finance.transact", "status": "NOT_BUILT",
                                                                    "description": "Move money, pay bills or trade assets"}):
            said = intents.spoken(_record(steps))
        self.assertTrue(said.startswith("I can't"), said)
        self.assertIn("What I can do:", said)


class HisNoIsDenied(unittest.TestCase):
    def test_the_decision_line_says_denied(self):
        with mock.patch("aletheia.policy.load", return_value={"id": "ap-1", "state": "PENDING"}), \
             mock.patch("aletheia.policy.save"), \
             mock.patch("aletheia.voice.approval_label", return_value="Hold Monday at 10"), \
             mock.patch("aletheia.journal.append") as appended:
            policy.decide("ap-1", "DENIED", via="voice", because="denied by voice")
        line = appended.call_args[0][2]
        self.assertTrue(line.startswith("Denied: Hold Monday at 10"), line)


class WhatIsPendingIsTheLabel(unittest.TestCase):
    def test_the_first_pending_is_said_by_its_label(self):
        rows = [{"id": "ap-1", "state": "PENDING", "reason": 'operator said: "spoken to the wall: thea put a hold"'}]
        with mock.patch("aletheia.policy.all_approvals", return_value=rows), \
             mock.patch("aletheia.voice.approval_label", return_value="Hold Monday at 10 for the dentist"):
            said = quick._approvals()
        self.assertEqual(said, "1 approval pending. The first: Hold Monday at 10 for the dentist.")
        self.assertNotIn("spoken to the wall", said)


if __name__ == "__main__":
    unittest.main()
