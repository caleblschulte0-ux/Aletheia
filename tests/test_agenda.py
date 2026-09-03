"""Say what you want, she does it — and the refusals are real.

The operator: "this needs to be able to take any request I give it and
execute it except no spending money." So the tests that matter are the
ones on the word EXCEPT, plus the two refusals he did not ask for and
would have been furious to find missing: she cannot approve her own
requests, and she cannot lift her own kill switch.
"""
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import agenda, journal, mission, notifications, planner, policy


def plan_of(*commands, capabilities=(), blocked=()):
    steps = [planner.PlannedStep(i + 1, planner.EXECUTABLE, "ok", command=c)
             for i, c in enumerate(commands)]
    steps += [planner.PlannedStep(len(steps) + i + 1, planner.GAP, d)
              for i, d in enumerate(blocked)]
    return planner.Plan(request="r", summary="s", intent="plan", steps=steps,
                        required_capabilities=list(capabilities))


class AgendaCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        d = Path(self.tmp.name)
        env = mock.patch.dict(os.environ, {
            "ALETHEIA_PRIVATE_STATE": str(d),
            "ALETHEIA_MACHINE_KEY": str(d / "machine.key")})
        env.start(); self.addCleanup(env.stop)
        for target, attr, value in (
                (journal, "JOURNAL_PATH", d / "journal.jsonl"),
                (policy, "APPROVALS_DIR", d / "approvals"),
                (policy, "HALT_PATH", d / "halt.json"),
                (mission, "MISSION_PATH", d / "mission.json"),
                (notifications, "NOTICES_DIR", d / "notices")):
            p = mock.patch.object(target, attr, value)
            p.start(); self.addCleanup(p.stop)
        mission.start("anything", hours=2, actions=20)

    def go(self, plan, executor=None):
        ran = []
        executor = executor or (lambda cmd, fleet: ran.append(cmd) or
                                {"outcome": "done", "detail": "ok"})
        with mock.patch.object(planner, "compile", return_value=plan), \
             mock.patch.object(agenda, "load_fleet", return_value={}):
            record = agenda.run("do the thing", executor=executor)
        return record, ran


class MoneyIsTheLine(AgendaCase):
    def test_a_plan_needing_a_spending_capability_is_refused_whole(self):
        plan = plan_of({"kind": "note", "text": "x"},
                       capabilities=["purchase.execute"])
        with self.assertRaises(agenda.AgendaRefused):
            self.go(plan)

    def test_every_money_capability_is_refused(self):
        for cid in ("purchase.execute", "finance.transact", "reservation.book",
                    "subscription.cancel", "errand.run"):
            with self.subTest(capability=cid):
                with self.assertRaises(agenda.AgendaRefused):
                    agenda.refuse_money([cid])

    def test_nothing_runs_when_money_is_involved(self):
        plan = plan_of({"kind": "note", "text": "x"},
                       capabilities=["errand.run"])
        ran = []
        with self.assertRaises(agenda.AgendaRefused):
            self.go(plan, executor=lambda c, f: ran.append(c))
        self.assertEqual(ran, [], "refused before a single step executed")

    def test_there_is_no_flag_that_turns_money_back_on(self):
        """He drew this line; the code does not offer to redraw it."""
        source = (Path(__file__).parent.parent / "aletheia" / "agenda.py"
                  ).read_text(encoding="utf-8")
        for escape in ("allow_money", "force=", "override", "skip_money"):
            self.assertNotIn(escape, source, escape)


class SheCannotAuthorizeHerself(AgendaCase):
    """The hole this design nearly shipped with. `approve` is a real command
    kind — an agenda able to run it could file the approval for the purchase
    it is forbidden to make, then grant it, turning every other refusal in
    the module into a speed bump."""

    def test_approve_and_deny_are_refused(self):
        plan = plan_of({"kind": "approve", "id": "ap-1"},
                       {"kind": "deny", "id": "ap-2"})
        record, ran = self.go(plan)
        self.assertEqual(ran, [], "she must not decide her own approvals")
        self.assertEqual(len(record["refused"]), 2)

    def test_halt_and_resume_are_refused(self):
        plan = plan_of({"kind": "halt", "reason": "x"}, {"kind": "resume"})
        record, ran = self.go(plan)
        self.assertEqual(ran, [], "a kill switch she can lift is decoration")
        self.assertEqual(len(record["refused"]), 2)

    def test_recursive_and_standing_kinds_are_refused(self):
        plan = plan_of({"kind": "intent", "text": "do more"},
                       {"kind": "rule", "when": "x", "then": "y"},
                       {"kind": "dispatch", "repo": "r", "workflow": "w"})
        record, ran = self.go(plan)
        self.assertEqual(ran, [])
        self.assertEqual(len(record["refused"]), 3)

    def test_every_forbidden_kind_carries_a_stated_reason(self):
        for kind in agenda.FORBIDDEN_KINDS:
            self.assertIn(kind, agenda.REFUSAL_REASON,
                          "a refusal with no reason just gets re-argued")

    def test_a_refusal_is_said_out_loud_never_swallowed(self):
        plan = plan_of({"kind": "note", "text": "fine"},
                       {"kind": "approve", "id": "ap-1"})
        record, ran = self.go(plan)
        self.assertEqual(len(ran), 1, "the allowed step still ran")
        self.assertIn("would not", agenda.spoken(record))


class ItActuallyDoesTheWork(AgendaCase):
    def test_a_multi_step_request_runs_every_allowed_step(self):
        plan = plan_of({"kind": "note", "text": "a"},
                       {"kind": "task_new", "description": "b"},
                       {"kind": "remember", "text": "c"})
        record, ran = self.go(plan)
        self.assertEqual(len(ran), 3)
        self.assertEqual(record["succeeded"], 3)
        self.assertEqual(record["failed"], 0)

    def test_one_failing_step_does_not_abandon_the_rest(self):
        calls = []

        def flaky(cmd, fleet):
            calls.append(cmd)
            if len(calls) == 1:
                raise RuntimeError("that one broke")
            return {"outcome": "done", "detail": "ok"}

        plan = plan_of({"kind": "note", "text": "a"},
                       {"kind": "note", "text": "b"},
                       {"kind": "note", "text": "c"})
        record, _ = self.go(plan, executor=flaky)
        self.assertEqual(len(calls), 3, "it carried on")
        self.assertEqual(record["failed"], 1)
        self.assertEqual(record["succeeded"], 2)

    def test_the_work_is_charged_to_the_mission_budget(self):
        before = mission.status()["used"]
        self.go(plan_of({"kind": "note", "text": "a"}))
        self.assertEqual(mission.status()["used"], before + 1)

    def test_blocked_planner_steps_are_reported_not_hidden(self):
        plan = plan_of({"kind": "note", "text": "a"}, blocked=["needs a camera"])
        record, _ = self.go(plan)
        self.assertTrue(record["refused"])


class ItStopsWhenToldTo(AgendaCase):
    def test_halt_before_a_run_prevents_everything(self):
        policy.halt("stop", via="test")
        ran = []
        with self.assertRaises(policy.Halted):
            self.go(plan_of({"kind": "note", "text": "a"}),
                    executor=lambda c, f: ran.append(c))
        self.assertEqual(ran, [])

    def test_halt_mid_plan_stops_at_the_next_step(self):
        calls = []

        def halting(cmd, fleet):
            calls.append(cmd)
            policy.halt("enough", via="test")
            return {"outcome": "done"}

        plan = plan_of({"kind": "note", "text": "a"}, {"kind": "note", "text": "b"},
                       {"kind": "note", "text": "c"})
        with self.assertRaises(policy.Halted):
            self.go(plan, executor=halting)
        self.assertEqual(len(calls), 1,
                         "a twenty-minute agenda that checks the switch once "
                         "keeps going for nineteen minutes after he says stop")

    def test_without_a_mission_it_refuses_rather_than_assuming(self):
        mission.stop()
        with mock.patch.object(planner, "compile",
                               return_value=plan_of({"kind": "note", "text": "a"})), \
             mock.patch.object(agenda, "load_fleet", return_value={}):
            with self.assertRaises(agenda.AgendaError):
                agenda.run("do it", executor=lambda c, f: None)

    def test_a_runaway_plan_is_refused(self):
        plan = plan_of(*[{"kind": "note", "text": str(i)} for i in range(40)])
        with self.assertRaises(agenda.AgendaError):
            self.go(plan)

    def test_a_request_must_be_bounded(self):
        for bad in ("", "   ", "x" * 5000):
            with self.subTest(bad=bad[:12]):
                with self.assertRaises(ValueError):
                    agenda.run(bad, executor=lambda c, f: None)


if __name__ == "__main__":
    unittest.main()


class SheCanProduceAndObserve(AgendaCase):
    """The two gaps closed together: she could think but not hand him
    anything, and she could not see his desktop through the agenda at all."""

    def test_the_file_kinds_are_reachable_from_an_agenda(self):
        from aletheia import intercom
        for kind in ("file_write", "file_edit", "file_read", "file_list"):
            with self.subTest(kind=kind):
                self.assertIn(kind, intercom.KIND_ARGS)
                self.assertNotIn(kind, agenda.FORBIDDEN_KINDS)
                self.assertIn(kind, intercom.LOCAL_KINDS,
                              "the workspace is on his PC; Actions cannot see it")

    def test_writing_a_file_is_routine_not_world_touching(self):
        """Local, and reversible because every write keeps the previous
        version — that is what makes it routine rather than world-touching."""
        from aletheia import intercom
        self.assertEqual(intercom.tier("file_write"), intercom.TIER_ROUTINE)
        self.assertEqual(intercom.tier("file_read"), intercom.TIER_READ)

    def test_a_write_plan_runs_end_to_end_through_an_agenda(self):
        plan = plan_of({"kind": "file_write", "path": "notes.md", "text": "hi"},
                       {"kind": "file_edit", "path": "notes.md",
                        "find": "hi", "replace": "hello"})
        record, ran = self.go(plan)
        self.assertEqual(len(ran), 2)
        self.assertEqual(record["succeeded"], 2)

    def test_desktop_observation_is_reachable_but_mutation_is_not(self):
        from aletheia import computer, intercom
        self.assertEqual(intercom.tier("computer_observe"), intercom.TIER_READ)
        self.assertNotIn("computer_observe", agenda.FORBIDDEN_KINDS)
        # ...and the mutating half still refuses without an approval
        for action in ("invoke", "set_text", "close_window", "open_app"):
            with self.subTest(action=action):
                self.assertNotIn(action, computer.OBSERVE_ACTIONS)

    def test_observing_refuses_a_mutating_step_rather_than_filtering_it(self):
        """A caller that asked to click and was quietly given a screenshot
        would report success for work that never happened."""
        from aletheia import computer
        with self.assertRaises(computer.ApprovalRequired):
            computer.observe([{"action": "list_windows"},
                              {"action": "close_window",
                               "window": {"title": "Notepad"}}],
                             backend=mock.Mock())
