"""The goal loop: persistent, bounded, and never wider than an agenda.

Written 2026-09-02 when the operator said sixteen working commands were
not the point — "i need to know i can ask this anything and it will do it
or route it to the right place". The loop is the missing shape; these
tests are the bounds that keep it from being a runaway.
"""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import agenda, journal, mission, notifications, planner, policy, pursue

FLEET = {"repos": []}


def step(n, kind, **args):
    return planner.PlannedStep(n, planner.EXECUTABLE, "ok", command={"kind": kind, **args})


def plan(*steps, intent="plan", summary="s"):
    p = planner.Plan(request="r", summary=summary, intent=intent)
    p.steps = list(steps)
    return p


class Fixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        d = Path(self.tmp.name)
        env = mock.patch.dict(os.environ, {"ALETHEIA_PRIVATE_STATE": str(d)})
        env.start(); self.addCleanup(env.stop)
        for target, attr, value in (
                (journal, "JOURNAL_PATH", d / "journal.jsonl"),
                (policy, "HALT_PATH", d / "halt.json"),
                (notifications, "NOTICES_DIR", d / "notices")):
            p = mock.patch.object(target, attr, value)
            p.start(); self.addCleanup(p.stop)
        for name, value in (("covers", {"kind": "anything"}), ("active", None)):
            p = mock.patch.object(mission, name, return_value=value)
            p.start(); self.addCleanup(p.stop)
        p = mock.patch.object(mission, "note", return_value=None)
        p.start(); self.addCleanup(p.stop)

    def run_goal(self, plans, executor=None, **kw):
        """Drive the loop with a scripted sequence of compiled plans."""
        self.compiled = []
        seq = list(plans)

        def compile_(request, **kwargs):
            self.compiled.append(request)
            return seq.pop(0) if seq else plan(intent="answer", summary="all done")

        self.ran = []

        def default_executor(command, fleet, **kwargs):
            self.ran.append(command)
            return f"did {command['kind']}"

        with mock.patch.object(planner, "compile", side_effect=compile_):
            return pursue.pursue("get it done", fleet=FLEET,
                                 executor=executor or default_executor, **kw)


class ItKeepsGoingCase(Fixture):
    def test_it_works_across_rounds_and_stops_when_the_planner_answers(self):
        record = self.run_goal([
            plan(step(1, "note", text="look")),
            plan(step(1, "note", text="act")),
            plan(intent="answer", summary="the video is trimmed"),
        ])
        self.assertEqual(record["state"], pursue.DONE)
        self.assertEqual(record["answer"], "the video is trimmed")
        self.assertEqual(len(record["rounds"]), 2)
        self.assertEqual(record["steps_succeeded"], 2)

    def test_what_happened_is_fed_into_the_next_round(self):
        self.run_goal([plan(step(1, "note", text="x")),
                       plan(intent="answer", summary="done")])
        self.assertNotIn("already done toward this", self.compiled[0])
        self.assertIn("already done toward this", self.compiled[1])
        self.assertIn("note: done", self.compiled[1])

    def test_a_failed_step_is_reported_to_the_next_round_not_hidden(self):
        calls = {"n": 0}

        def flaky(command, fleet, **kw):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("file is locked")
            return "worked"

        record = self.run_goal([plan(step(1, "note", text="a")),
                                plan(step(1, "note", text="b")),
                                plan(intent="answer", summary="ok")],
                               executor=flaky)
        self.assertEqual(record["state"], pursue.DONE)
        self.assertIn("RuntimeError: file is locked", self.compiled[1])


class ItStopsCase(Fixture):
    def test_a_repeated_command_stops_the_loop(self):
        same = lambda: plan(step(1, "note", text="same"))
        record = self.run_goal([same(), same(), same()])
        self.assertEqual(record["state"], pursue.STALLED)
        self.assertIn("repeated note", record["note"])
        self.assertEqual(len(self.ran), 1, "the repeat never ran a second time")

    def test_two_barren_rounds_in_a_row_stop_it_but_one_does_not(self):
        def broken(command, fleet, **kw):
            raise RuntimeError("nope")
        record = self.run_goal([plan(step(1, "note", text="a")),
                                plan(step(1, "note", text="b")),
                                plan(step(1, "note", text="c"))],
                               executor=broken)
        self.assertEqual(record["state"], pursue.STALLED)
        self.assertIn("achieved nothing", record["note"])
        self.assertEqual(len(record["rounds"]), 2, "one failure is not a dead end")

    def test_a_question_goes_back_to_him_with_the_question(self):
        record = self.run_goal([plan(intent="clarify", summary="which resume?")])
        self.assertEqual(record["state"], pursue.NEEDS_OPERATOR)
        self.assertEqual(record["note"], "which resume?")
        self.assertIn("which resume?", pursue.spoken(record))

    def test_a_capability_gap_is_named_rather_than_worked_around(self):
        gap = planner.PlannedStep(1, planner.GAP, "NOT_BUILT", capability="message.send")
        record = self.run_goal([plan(gap)])
        self.assertEqual(record["state"], pursue.BLOCKED)
        self.assertIn("message.send", record["note"])

    def test_rounds_are_bounded(self):
        forever = [plan(step(1, "note", text=str(i))) for i in range(pursue.MAX_ROUNDS)]
        record = self.run_goal(forever, rounds=3)
        self.assertEqual(record["state"], pursue.EXHAUSTED)
        self.assertEqual(len(record["rounds"]), 3)

    def test_the_total_step_ceiling_holds(self):
        with mock.patch.object(pursue, "MAX_STEPS_TOTAL", 2):
            record = self.run_goal([
                plan(step(1, "note", text="a"), step(2, "note", text="b")),
                plan(step(1, "note", text="c")),
            ])
        self.assertEqual(record["steps_run"], 2)
        self.assertEqual(record["state"], pursue.EXHAUSTED)


class ItIsNoWiderThanAnAgendaCase(Fixture):
    def test_money_is_refused_in_a_loop_exactly_as_it_is_in_one_plan(self):
        buy = planner.PlannedStep(1, planner.EXECUTABLE, "ok",
                                  command={"kind": "note", "text": "x"},
                                  capability="purchase.execute")
        with self.assertRaises(agenda.AgendaRefused):
            self.run_goal([plan(buy)])

    def test_a_forbidden_kind_is_refused_and_never_executed(self):
        record = self.run_goal([plan(step(1, "approve", id="a1", because="me")),
                                plan(intent="answer", summary="done")])
        kinds = [c["kind"] for c in self.ran]
        self.assertNotIn("approve", kinds)
        refusals = [e for r in record["rounds"] for e in r["refused"]]
        self.assertTrue(any(e.get("kind") == "approve" for e in refusals))

    def test_halt_stops_it_before_the_first_round(self):
        policy.halt("testing", via="operator")
        with self.assertRaises(policy.Halted):
            self.run_goal([plan(step(1, "note", text="x"))])

    def test_halt_mid_pursuit_stops_it(self):
        def halting(command, fleet, **kw):
            policy.halt("stop now", via="operator")
            return "did one"
        with self.assertRaises(policy.Halted):
            self.run_goal([plan(step(1, "note", text="a"), step(2, "note", text="b"))],
                          executor=halting)

    def test_no_mission_no_pursuit(self):
        with mock.patch.object(mission, "covers", return_value=None):
            with self.assertRaises(pursue.PursuitError):
                self.run_goal([plan(step(1, "note", text="x"))])

    def test_a_budget_that_runs_out_mid_pursuit_ends_it(self):
        answers = [{"kind": "anything"}, None]
        with mock.patch.object(mission, "covers", side_effect=lambda *a, **k:
                               answers.pop(0) if answers else None):
            record = self.run_goal([plan(step(1, "note", text="a")),
                                    plan(step(1, "note", text="b"))])
        self.assertEqual(record["state"], pursue.EXHAUSTED)
        self.assertIn("budget", record["note"])


class ItSaysWhatHappenedCase(Fixture):
    def test_the_goal_and_every_round_are_journaled(self):
        self.run_goal([plan(step(1, "note", text="a")),
                       plan(intent="answer", summary="done")])
        text = journal.JOURNAL_PATH.read_text(encoding="utf-8")
        self.assertIn("pursue", text)
        self.assertIn("get it done", text)

    def test_history_given_to_the_model_is_bounded(self):
        rounds = [{"round": i, "summary": "s", "refused": [],
                   "ran": [{"step": 1, "kind": "note", "outcome": "done",
                            "detail": "x" * 200}]} for i in range(40)]
        block = pursue._history_block(rounds)
        self.assertLessEqual(len(block), pursue.MAX_HISTORY_CHARS)
        self.assertIn("note: done", block)

    def test_an_empty_goal_is_refused(self):
        with self.assertRaises(ValueError):
            pursue.pursue("   ", require_mission=False)


if __name__ == "__main__":
    unittest.main()
