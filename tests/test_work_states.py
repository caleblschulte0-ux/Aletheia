"""The continuity vocabulary is one closed set, and rule 3 is checkable."""
import unittest

from aletheia import contracts, reasoning_gateway, work_states as ws


class TheVocabulary(unittest.TestCase):
    def test_contracts_re_exports_the_same_objects(self):
        self.assertIs(contracts.WORK_STATES, ws.WORK_STATES)
        self.assertIs(contracts.REQUIREMENTS, ws.REQUIREMENTS)

    def test_the_gateway_policies_are_the_reasoning_classes(self):
        self.assertEqual(reasoning_gateway.POLICIES, ws.REASONING_CLASSES)

    def test_every_requirement_has_a_blocked_state(self):
        self.assertEqual(set(ws.BLOCKED_BY), ws.REQUIREMENTS)
        self.assertTrue(set(ws.BLOCKED_BY.values()) <= ws.WORK_WAITING)

    def test_every_gap_outcome_leaves_a_state(self):
        self.assertEqual(set(ws.GAP_STATE), ws.GAP_OUTCOMES)
        self.assertTrue(set(ws.GAP_STATE.values()) <= ws.WORK_STATES)

    def test_a_waiting_item_without_reason_or_next_is_refused(self):
        self.assertTrue(ws.problems({"state": ws.BLOCKED_MODEL}))
        self.assertEqual(ws.problems({"state": ws.BLOCKED_MODEL, "reason": "Claude resting",
                                      "next": "retry after reset"}), [])

    def test_retry_later_needs_a_not_before(self):
        item = {"state": ws.RETRY_LATER, "reason": "r", "next": "n"}
        self.assertIn("RETRY_LATER needs a not_before", ws.problems(item))

    def test_an_unknown_requirement_is_refused(self):
        self.assertTrue(ws.problems({"state": ws.READY, "requires": ["telepathy"]}))


if __name__ == "__main__":
    unittest.main()
