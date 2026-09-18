"""The consequence model: what DOING a tool costs, as data on its descriptor.

His continuity brief, Part III item 10: "Move from 'reads autonomous, writes ask
Caleb' toward consequence-based authority ... Money, binding commitments,
destructive operations, outward communications and authority changes keep their
approval rules. Do not weaken existing safety."

So the classification is held here, and the two halves of it are held
separately, because they fail in opposite directions:

- **Every kind has an HONEST consequence.** Not "every kind has a value" - a
  value is free. Anything that reaches somebody else, cannot be taken back, or
  decides something is outward, and the derivation is checked against the sets
  it was derived from rather than against itself.
- **The outward set is never empty**, and always contains the money, the
  sending, the publishing, the deleting, the account and the authority. An empty
  outward set would make every test below pass and every gate useless, which is
  exactly the shape of a mistake nobody notices.
"""
from __future__ import annotations

import unittest

from aletheia import agent_session as s
from aletheia import intercom, planner, tools


class EveryToolHasAnHonestConsequence(unittest.TestCase):
    def setUp(self):
        self.catalog = tools.catalog(fresh=True)

    def test_every_tool_carries_one_of_the_three(self):
        for name, tool in self.catalog.items():
            with self.subTest(tool=name):
                self.assertIn(tool.consequence, tools.CONSEQUENCES, name)

    def test_the_outward_set_is_never_empty(self):
        outward = {n for n, t in self.catalog.items() if t.consequence == tools.OUTWARD}
        self.assertTrue(outward, "an empty outward set makes every gate below a no-op")
        self.assertGreater(len(outward), 20, sorted(outward))

    def test_the_outward_set_always_holds_the_money(self):
        """The one permanent rule, as a classification. `planner.SPENDING_KINDS`
        is the same list the plan-time gate refuses on."""
        spending = set(planner.SPENDING_KINDS) & set(self.catalog)
        self.assertTrue(spending, "the check needs a subject")
        for kind in spending:
            self.assertEqual(self.catalog[kind].consequence, tools.OUTWARD, kind)

    def test_sending_publishing_deleting_accounts_and_authority_are_outward(self):
        cases = {
            "sending": ("email_draft", "message_send", "thread_send", "meet", "thread.send"),
            "publishing": ("issue", "dispatch"),
            "deleting for good": ("forget",),
            "an account of his": ("chatgpt_on",),
            "authority": ("approve", "deny", "resume", "halt", "rule",
                          "study_decide", "study_confirm", "mission_confirm"),
            "a pull request or a browser on a real site": ("browser.act", "browser.pursue",
                                                           "apply_campaign"),
        }
        for what, names in cases.items():
            for name in names:
                with self.subTest(what=what, tool=name):
                    self.assertEqual(self.catalog[name].consequence, tools.OUTWARD, name)

    def test_everything_in_the_always_set_really_is_outward(self):
        for name in tools.OUTWARD_ALWAYS:
            with self.subTest(tool=name):
                self.assertIn(name, self.catalog, f"{name} is named but is not a tool")
                self.assertEqual(self.catalog[name].consequence, tools.OUTWARD, name)

    def test_a_world_tier_tool_is_never_reversible(self):
        for name, tool in self.catalog.items():
            if tool.risk == intercom.TIER_WORLD:
                with self.subTest(tool=name):
                    self.assertEqual(tool.consequence, tools.OUTWARD, name)

    def test_the_explicit_table_only_names_real_tools_and_real_values(self):
        for name, said in tools.CONSEQUENCE_OF.items():
            with self.subTest(tool=name):
                self.assertIn(name, self.catalog, f"{name} is overridden but is not a tool")
                self.assertIn(said, tools.CONSEQUENCES)

    def test_the_derivation_fails_closed(self):
        """A tier nobody recognises, a store nobody declared: outward."""
        self.assertEqual(tools.derive_consequence(name="x.y", risk="something-new",
                                                  touches=("mystery",), destructive=False, kind=None),
                         tools.OUTWARD)

    def test_what_reaches_him_and_nobody_else_is_its_own_answer(self):
        """His own list: a notification, a journal line, a calendar HOLD in her
        own store. None of them is local, and none of them is outward."""
        for name in ("notify_operator", "note", "calendar_hold", "remind_at"):
            with self.subTest(tool=name):
                self.assertEqual(self.catalog[name].consequence, tools.VISIBLE_TO_HIM, name)

    def test_the_brief_s_own_reversible_examples_are_reversible(self):
        """"temporary local workspaces, fixing a project in a branch, drafts,
        tasks, internal project state, rescheduling its own queued work, notes,
        running tests, preparing PRs"."""
        for name in ("task_new", "task_status", "thread_draft", "repo.propose_patch",
                     "repo.try_patch", "file_write", "plan_step", "doc_make", "remember"):
            with self.subTest(tool=name):
                self.assertIn(self.catalog[name].consequence, tools.UNATTENDED, name)


class ConsequenceIsNotPermission(unittest.TestCase):
    """The two axes are separate, and BOTH have to say yes."""

    def setUp(self):
        self.catalog = tools.catalog(fresh=True)

    def test_a_reversible_tool_his_policy_names_still_waits(self):
        tool = self.catalog["repo.try_patch"]
        self.assertIn(tool.consequence, tools.UNATTENDED)
        self.assertEqual(tool.approval, "operator_once")
        self.assertFalse(tools.runs_unattended(tool))

    def test_an_outward_tool_with_no_policy_still_never_runs_unattended(self):
        fake = tools.declare("x.outward", description="x", input_schema={},
                             handler=lambda a: {}, capability="c",
                             risk=intercom.TIER_WORLD, writes=("somewhere",))
        self.assertEqual(fake.approval, "none")
        self.assertEqual(fake.consequence, tools.OUTWARD)
        self.assertFalse(tools.runs_unattended(fake))

    def test_the_registry_wins_over_the_descriptor(self):
        tool = self.catalog["task_new"]
        self.assertEqual(tools.approval_of(tool), "none")
        self.assertEqual(tools.approval_of(tool, {"approval_policy": "operator_always"}),
                         "operator_always")


class WhatTheLocalModelIsOffered(unittest.TestCase):
    def setUp(self):
        self.catalog = tools.catalog(fresh=True)

    def test_every_writer_offered_locally_is_reversible(self):
        for kind in tools.LOCAL_MODEL_WRITES:
            with self.subTest(kind=kind):
                self.assertIn(kind, self.catalog, f"{kind} is offered but is not a kind")
                self.assertIn(self.catalog[kind].consequence, tools.UNATTENDED, kind)

    def test_nothing_outward_is_offered_to_the_local_model_that_would_run(self):
        broker = s.Broker(self.catalog, audience="local", halted=lambda: False)
        for row in tools.for_model("local")["tools"]:
            tool = self.catalog[row["name"]]
            with self.subTest(tool=row["name"]):
                if tool.consequence == tools.OUTWARD:
                    args = {k: "x" for k in tool.input_schema.get("required") or []}
                    self.assertNotEqual(broker.check(s.ToolRequest(tool.name, args)).verdict, s.RUN)


class TheBrokerDecidesOnConsequence(unittest.TestCase):
    """The three behaviours he named: a draft runs, a send waits, a published
    pull request waits."""

    def setUp(self):
        self.catalog = tools.catalog(fresh=True)
        self.broker = s.Broker(self.catalog, audience="all", halted=lambda: False,
                               session="agent-test")

    def check(self, name, args):
        return self.broker.check(s.ToolRequest(name, args))

    def test_a_draft_runs(self):
        self.assertEqual(self.check("thread_draft", {"to": "the landlord", "body": "hello"}).verdict,
                         s.RUN)

    def test_a_note_and_a_task_run(self):
        self.assertEqual(self.check("note", {"text": "he mentioned the tour"}).verdict, s.RUN)
        self.assertEqual(self.check("task_new", {"id": "t1", "description": "call back"}).verdict, s.RUN)

    def test_a_send_is_handed_off(self):
        decision = self.check("thread_send", {"thread": "t1"})
        self.assertEqual(decision.verdict, s.HANDOFF)
        self.assertTrue(decision.permanent)

    def test_publishing_a_pull_request_is_handed_off(self):
        """`repo.try_patch` prepares one; it is reversible and still his."""
        decision = self.check("repo.try_patch", {"proposal": "patch-1"})
        self.assertEqual(decision.verdict, s.HANDOFF)
        self.assertIn("approval", decision.reason)

    def test_an_issue_on_his_repository_is_handed_off(self):
        self.assertEqual(self.check("issue", {"repo": "fleet", "title": "t", "body": "b"}).verdict,
                         s.HANDOFF)

    def test_spending_is_still_refused_rather_than_handed_off(self):
        decision = self.check("web_task", {"goal": "buy the monitor"})
        self.assertEqual(decision.verdict, s.REFUSED)
        self.assertIn("spend money", decision.reason)

    def test_she_cannot_approve_her_own_work(self):
        for name in ("approve", "deny", "resume"):
            with self.subTest(tool=name):
                self.assertEqual(self.check(name, {}).verdict, s.REFUSED)


if __name__ == "__main__":
    unittest.main()
