"""The hierarchy, asserted rather than described.

Every test here is one question: can a worker end up with authority
nobody gave it? The runtime is only worth having if the answer stays no
under delegation, under editing, under restart, and under a webpage
telling an agent what to do.
"""
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import agents, contracts, journal, policy


class RuntimeCase(unittest.TestCase):
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

    def some_capabilities(self, count=3):
        """Real registry ids an agent is actually allowed to hold."""
        return agents.root_record()["capabilities"][:count]


class LifecycleCase(RuntimeCase):
    def test_an_agent_is_created_ready_and_survives_a_restart(self):
        held = self.some_capabilities()
        agents.spawn("barkly", name="Barkly Engineer", mission="ship it",
                     capabilities=held, agent_type="project", project="barkly")
        # "Restart": nothing cached, read it back off disk the way a new
        # process would. A worker whose identity lives in a vendor's chat
        # window is exactly what this runtime exists to replace.
        again = agents.load("barkly")
        self.assertEqual(again["status"], "READY")
        self.assertEqual(again["mission"], "ship it")
        self.assertEqual(again["capabilities"], held)
        self.assertEqual(again["type"], "project")

    def test_every_status_is_one_the_repo_already_had(self):
        """No second vocabulary. `contracts.TASK_STATES` is finer than one."""
        held = self.some_capabilities()
        agents.spawn("a", name="A", mission="m", capabilities=held)
        for state in ("RUNNING", "WAITING_OPERATOR", "BLOCKED", "COMPLETED"):
            self.assertIn(state, contracts.TASK_STATES)
            self.assertEqual(agents.set_status("a", state)["status"], state)
        with self.assertRaises(agents.AgentError):
            agents.set_status("a", "thinking about it")

    def test_pause_stops_work_and_resume_starts_it(self):
        held = self.some_capabilities()
        agents.spawn("a", name="A", mission="m", capabilities=held)
        agents.pause("a")
        with self.assertRaises(agents.NotPermitted):
            agents.require("a", held[0])
        agents.resume("a")
        agents.require("a", held[0])            # no raise

    def test_a_finished_agent_does_no_more_work(self):
        held = self.some_capabilities()
        agents.spawn("a", name="A", mission="m", capabilities=held)
        agents.archive("a")
        with self.assertRaises(agents.NotPermitted):
            agents.require("a", held[0])

    def test_an_agent_without_a_mission_is_refused(self):
        with self.assertRaises(agents.AgentError):
            agents.spawn("a", name="A", mission="   ", capabilities=[])


class TheFloorNoAgentGoesUnderCase(RuntimeCase):
    def test_no_agent_may_hold_a_capability_that_reaches_him(self):
        """Spending, sending, binding, destroying — never, at any depth.

        These are the operator_always and high-risk entries, and the
        predicate is the same one that refuses standing grants.
        """
        for forbidden in ("message.send", "email.send", "purchase.execute",
                          "finance.transact", "computer.control",
                          "reservation.book", "errand.run"):
            with self.subTest(capability=forbidden):
                self.assertNotIn(forbidden, agents.root_record()["capabilities"])
                with self.assertRaises(agents.NotPermitted):
                    agents.spawn("x", name="X", mission="m",
                                 capabilities=[forbidden])
                self.assertFalse(agents.exists("x"), "a refused spawn left a record")

    def test_the_floor_is_computed_from_the_registry_not_remembered(self):
        """A capability that becomes high-risk tomorrow leaves every agent.

        The root's set is derived on every read, so tightening the
        registry narrows existing agents rather than only new ones.
        """
        held = self.some_capabilities(1)
        agents.spawn("a", name="A", mission="m", capabilities=held)
        self.assertTrue(agents.permits("a", held[0]))
        with mock.patch("aletheia.authority.delegable",
                        lambda cid: cid != held[0]):
            self.assertFalse(agents.permits("a", held[0]))
            with self.assertRaises(agents.NotPermitted):
                agents.require("a", held[0])


class AChildIsASubsetCase(RuntimeCase):
    def test_a_child_cannot_be_given_what_the_parent_lacks(self):
        root_caps = self.some_capabilities(3)
        agents.spawn("parent", name="P", mission="m", capabilities=root_caps[:1])
        with self.assertRaises(agents.NotPermitted):
            agents.spawn("child", name="C", mission="m", parent="parent",
                         capabilities=root_caps[:2])
        self.assertFalse(agents.exists("child"))

    def test_permission_laundering_through_a_grandchild_fails(self):
        """A -> B -> C, where C asks for what A had and B never got."""
        caps = self.some_capabilities(3)
        agents.spawn("a", name="A", mission="m", capabilities=caps[:3])
        agents.spawn("b", name="B", mission="m", parent="a", capabilities=caps[:1])
        with self.assertRaises(agents.NotPermitted):
            agents.spawn("c", name="C", mission="m", parent="b",
                         capabilities=caps[:2])

    def test_delegation_stops_at_the_depth_limit(self):
        caps = self.some_capabilities(1)
        parent = agents.ROOT
        for i in range(agents.MAX_DEPTH):
            agents.spawn(f"d{i}", name=f"D{i}", mission="m",
                         parent=parent, capabilities=caps)
            parent = f"d{i}"
        with self.assertRaises(agents.AgentError):
            agents.spawn("toodeep", name="X", mission="m", parent=parent,
                         capabilities=caps)

    def test_a_parent_cannot_have_unbounded_children(self):
        caps = self.some_capabilities(1)
        for i in range(agents.MAX_CHILDREN):
            agents.spawn(f"c{i}", name=f"C{i}", mission="m", capabilities=caps)
        with self.assertRaises(agents.AgentError):
            agents.spawn("one-too-many", name="X", mission="m", capabilities=caps)


class StopEverythingCase(RuntimeCase):
    def test_killing_a_parent_kills_everything_under_it(self):
        """A killed parent whose child keeps working is the runaway."""
        caps = self.some_capabilities(1)
        agents.spawn("a", name="A", mission="m", capabilities=caps)
        agents.spawn("b", name="B", mission="m", parent="a", capabilities=caps)
        agents.spawn("c", name="C", mission="m", parent="b", capabilities=caps)
        agents.kill("a")
        for who in ("a", "b", "c"):
            self.assertEqual(agents.load(who)["status"], "CANCELLED", who)

    def test_stop_everything_stops_every_agent(self):
        caps = self.some_capabilities(1)
        for i in range(3):
            agents.spawn(f"a{i}", name=f"A{i}", mission="m", capabilities=caps)
        agents.kill_all()
        self.assertTrue(all(a["status"] == "CANCELLED" for a in agents.all_agents()))

    def test_the_kill_switch_is_above_the_whole_runtime(self):
        """"Halt" stops every agent at its next step, mid-assignment or not."""
        caps = self.some_capabilities(1)
        agents.spawn("a", name="A", mission="m", capabilities=caps)
        agents.set_status("a", "RUNNING")
        agents.require("a", caps[0])                       # fine while running
        with mock.patch("aletheia.policy.halted",
                        lambda: {"reason": "he said stop"}):
            with self.assertRaises(agents.NotPermitted):
                agents.require("a", caps[0])
        agents.require("a", caps[0])                       # and back after resume


class AdversarialCase(RuntimeCase):
    """The brief's §30. Each of these is a thing that must simply not work."""

    def test_an_agent_cannot_widen_itself_by_editing_its_own_record(self):
        """The record on disk is a claim; the registry is the authority."""
        caps = self.some_capabilities(1)
        agents.spawn("a", name="A", mission="m", capabilities=caps)
        record = agents.load("a")
        record["capabilities"] = ["message.send", "purchase.execute"]
        agents._path("a").write_text(__import__("json").dumps(record),
                                     encoding="utf-8")
        self.assertEqual(agents.holds("a"), set(),
                         "an edited record bought authority")
        with self.assertRaises(agents.NotPermitted):
            agents.require("a", "message.send")

    def test_a_webpage_telling_an_agent_to_grant_itself_something_does_nothing(self):
        """There is no self-grant call to reach.

        Prompt injection works by persuading a model. It cannot help here
        because permission is not something an agent asks the runtime
        for in words — the only way in is `spawn`, which is bounded by
        the parent, and the runtime exposes nothing an agent could call
        to widen itself.
        """
        for forbidden_call in ("grant", "widen", "escalate", "allow",
                               "set_capabilities", "add_capability"):
            self.assertFalse(hasattr(agents, forbidden_call),
                             f"agents.{forbidden_call} is a way up the hierarchy")

    def test_an_agent_cannot_turn_the_kill_switch_off(self):
        """Not by capability, because no agent may hold the controls."""
        for control in ("halt", "resume"):
            self.assertNotIn(control, agents.root_record()["capabilities"])

    def test_a_cyclic_parent_chain_on_disk_is_refused_not_followed(self):
        """Two records pointing at each other must not spin forever."""
        caps = self.some_capabilities(1)
        agents.spawn("a", name="A", mission="m", capabilities=caps)
        agents.spawn("b", name="B", mission="m", parent="a", capabilities=caps)
        record = agents.load("a")
        record["parent"] = "b"
        agents._path("a").write_text(__import__("json").dumps(record),
                                     encoding="utf-8")
        with self.assertRaises(agents.AgentError):
            agents.depth("b")


class WhatAreTheyDoingCase(RuntimeCase):
    def test_the_roster_reads_out_loud_and_is_not_a_log(self):
        caps = self.some_capabilities(1)
        agents.spawn("barkly", name="Barkly Engineer",
                     mission="fixing the onboarding bug", capabilities=caps,
                     agent_type="project", project="barkly")
        agents.set_status("barkly", "RUNNING")
        said = agents.spoken_roster()
        self.assertIn("Barkly Engineer", said)
        self.assertIn("running", said)
        for forbidden in ("_", "{", "[", "agent-"):
            self.assertNotIn(forbidden, said, f"{forbidden!r} is not sayable")

    def test_with_nothing_running_it_says_so_rather_than_nothing(self):
        self.assertEqual(agents.spoken_roster(), "No workers running.")

    def test_finished_workers_leave_the_roster(self):
        caps = self.some_capabilities(1)
        agents.spawn("a", name="A", mission="m", capabilities=caps)
        agents.archive("a")
        self.assertEqual(agents.spoken_roster(), "No workers running.")


if __name__ == "__main__":
    unittest.main()
