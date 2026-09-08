"""The door, and what cannot get through it.

`require()` existing and nothing calling it makes it documentation. This
is the test that the runtime actually enforces its own hierarchy when
work runs, rather than only when an agent is written down.
"""
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import agents, journal, outcomes, policy, workspaces


class ActCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        d = Path(self.tmp.name)
        env = mock.patch.dict(os.environ, {"ALETHEIA_PRIVATE_STATE": str(d)})
        env.start()
        self.addCleanup(env.stop)
        for patch in (mock.patch.object(journal, "JOURNAL_PATH", d / "j.jsonl"),
                      mock.patch.object(policy, "APPROVALS_DIR", d / "approvals"),
                      mock.patch.object(policy, "HALT_PATH", d / "halt.json")):
            patch.start()
            self.addCleanup(patch.stop)
        self.cap = agents.reading_scope()[0]
        agents.spawn("reader", name="Reader", mission="look at things",
                     capabilities=[self.cap])
        self.ran = []

    def runner(self, command, quote):
        self.ran.append(command)
        return "did the thing"


class TheDoorHoldsCase(ActCase):
    def test_a_permitted_read_runs_and_leaves_a_receipt(self):
        out = agents.act("reader", {"kind": "tasks"}, capability=self.cap,
                         quote="what is on the list", runner=self.runner)
        self.assertEqual(len(self.ran), 1)
        receipt = outcomes.load(out["action_id"])
        self.assertEqual(receipt["capability"], self.cap)
        self.assertEqual(receipt["requested_by"], "agent:reader")
        self.assertEqual(receipt["attempts"][-1]["outcome"], "SUCCEEDED")
        # Running it is not evidence it worked (§30): the receipt waits
        # for verification rather than declaring victory.
        self.assertEqual(receipt["status"], "AWAITING_VERIFICATION")
        # ...and the worker remembers it did it.
        self.assertEqual(len(workspaces.load("reader")["transcript"]), 1)

    def test_a_capability_it_does_not_hold_is_refused(self):
        other = agents.reading_scope()[1]
        with self.assertRaises(agents.NotPermitted):
            agents.act("reader", {"kind": "tasks"}, capability=other,
                       runner=self.runner)
        self.assertEqual(self.ran, [], "it ran anyway")

    def test_a_world_tier_kind_is_refused_whatever_it_holds(self):
        """The floor, at the moment of acting.

        Even an agent somehow holding the capability may not run a kind
        that reaches another person. Sending stops for him every time.
        """
        with self.assertRaises(agents.NotPermitted) as caught:
            agents.act("reader", {"kind": "message_send", "to": "x",
                                  "body": "y"},
                       capability=self.cap, runner=self.runner)
        self.assertIn("stops for him", str(caught.exception))
        self.assertEqual(self.ran, [])

    def test_the_kill_switch_closes_the_door(self):
        with mock.patch("aletheia.policy.halted", lambda: {"reason": "stop"}):
            with self.assertRaises(agents.NotPermitted):
                agents.act("reader", {"kind": "tasks"}, capability=self.cap,
                           runner=self.runner)
        self.assertEqual(self.ran, [])

    def test_a_paused_agent_does_no_work(self):
        agents.pause("reader")
        with self.assertRaises(agents.NotPermitted):
            agents.act("reader", {"kind": "tasks"}, capability=self.cap,
                       runner=self.runner)
        self.assertEqual(self.ran, [])

    def test_a_failure_is_recorded_rather_than_swallowed(self):
        def boom(command, quote):
            raise RuntimeError("the store was unreadable")

        with self.assertRaises(RuntimeError):
            agents.act("reader", {"kind": "tasks"}, capability=self.cap,
                       runner=boom)
        self.assertEqual(agents.load("reader")["status"], "FAILED_RETRYABLE")
        rows = outcomes.all_actions()
        self.assertTrue(any(a["attempts"][-1]["outcome"] == "FAILED_RETRYABLE"
                            for a in rows if a["attempts"]), rows)

    def test_a_command_with_no_kind_is_not_a_command(self):
        with self.assertRaises(agents.AgentError):
            agents.act("reader", {}, capability=self.cap, runner=self.runner)


class TheStartingScopeCase(ActCase):
    def test_a_worker_created_by_a_sentence_can_only_look(self):
        """It held an EMPTY list before: intercom kinds passed where
        registry capability ids were wanted, so every one was dropped."""
        scope = agents.reading_scope()
        self.assertGreater(len(scope), 10, "the starting scope is empty again")
        for dangerous in ("message.send", "email.send", "purchase.execute",
                          "computer.control", "finance.transact"):
            self.assertNotIn(dangerous, scope)

    def test_it_is_derived_from_the_registry_not_a_hand_kept_list(self):
        """A read capability added tomorrow is in scope tomorrow."""
        from aletheia import capabilities
        reg = capabilities.load_registry()["capabilities"]
        expected = {c["id"] for c in reg if c["risk_class"] == "read"}
        self.assertEqual(set(agents.reading_scope()), expected)


if __name__ == "__main__":
    unittest.main()
