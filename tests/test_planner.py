"""The planner's real contract: a model may propose anything, and only the
registries and the gates decide what that means.

Every test here injects a stub provider. Nothing calls a real model — the
point under test is what Aletheia does with an answer, not the answer.
"""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import brain, journal, planner, policy

FLEET = {"repos": {"Aletheia": {}, "schwab-trader": {}}}

REGISTRY = {
    "providers": {"aletheia.local": {}},
    "capabilities": [
        {"id": "task.persist", "status": "AVAILABLE", "provider": "aletheia.local"},
        {"id": "automation.define", "status": "AVAILABLE", "provider": "aletheia.local"},
        {"id": "purchase.execute", "status": "NOT_BUILT", "provider": "aletheia.local"},
        {"id": "calendar.read", "status": "NEEDS_CONFIGURATION",
         "provider": "aletheia.local"},
    ],
}


def provider(output: dict, provider_id="stub") -> brain.Provider:
    return brain.Provider(provider_id, lambda text, ctx: output)


def exploding(exc) -> brain.Provider:
    def boom(text, ctx):
        raise exc
    return brain.Provider("stub.broken", boom)


class ClassifyCase(unittest.TestCase):
    def compile(self, output):
        return planner.compile("do the thing", fleet=FLEET,
                               provider=provider(output), registry=REGISTRY)

    def test_a_valid_command_is_executable(self):
        plan = self.compile({"intent": "plan", "summary": "s", "steps": [
            {"kind": "note", "text": "hello"}]})
        self.assertEqual([s.status for s in plan.steps], [planner.EXECUTABLE])
        self.assertEqual(plan.executable[0].command["kind"], "note")

    def test_an_invented_kind_is_refused_not_executed(self):
        plan = self.compile({"intent": "plan", "summary": "s", "steps": [
            {"kind": "launch_missiles", "target": "moon"}]})
        self.assertEqual([s.status for s in plan.steps], [planner.REFUSED])
        self.assertEqual(plan.executable, [])
        self.assertIn("not in", plan.steps[0].detail)

    def test_wrong_args_for_a_real_kind_are_refused(self):
        plan = self.compile({"intent": "plan", "summary": "s", "steps": [
            {"kind": "note"}]})  # missing `text`
        self.assertEqual(plan.steps[0].status, planner.REFUSED)
        self.assertIn("missing args", plan.steps[0].detail)

    def test_extra_args_are_refused(self):
        # a model that adds a plausible-looking argument must not have it
        # silently dropped on the way to execution
        plan = self.compile({"intent": "plan", "summary": "s", "steps": [
            {"kind": "note", "text": "hi", "urgency": "high"}]})
        self.assertEqual(plan.steps[0].status, planner.REFUSED)
        self.assertIn("unexpected args", plan.steps[0].detail)

    def test_a_gap_on_a_missing_capability_is_a_gap(self):
        plan = self.compile({"intent": "plan", "summary": "s", "steps": [
            {"gap": "purchase.execute", "why": "cannot buy things"}]})
        self.assertEqual(plan.steps[0].status, planner.GAP)
        self.assertEqual(plan.steps[0].capability, "purchase.execute")
        self.assertIn("NOT_BUILT", plan.steps[0].detail)

    def test_a_gap_claimed_on_an_available_capability_is_refused(self):
        # hallucinated INCAPACITY is the same defect as hallucinated
        # capability: the registry decides, never the model
        plan = self.compile({"intent": "plan", "summary": "s", "steps": [
            {"gap": "automation.define", "why": "I don't think I can"}]})
        self.assertEqual(plan.steps[0].status, planner.REFUSED)
        self.assertIn("AVAILABLE", plan.steps[0].detail)

    def test_a_gap_on_an_unknown_id_says_so(self):
        plan = self.compile({"intent": "plan", "summary": "s", "steps": [
            {"gap": "telepathy.read", "why": "nope"}]})
        self.assertEqual(plan.steps[0].status, planner.GAP)
        self.assertIn("not a capability in the registry", plan.steps[0].detail)

    def test_manual_steps_stay_manual(self):
        plan = self.compile({"intent": "plan", "summary": "s", "steps": [
            {"manual": "sign the form yourself"}]})
        self.assertEqual(plan.steps[0].status, planner.MANUAL)
        self.assertEqual(plan.executable, [])

    def test_a_single_command_output_is_a_one_step_plan(self):
        plan = self.compile({"intent": "command", "summary": "s",
                             "command": {"kind": "note", "text": "hi"}})
        self.assertEqual(len(plan.executable), 1)

    def test_required_capabilities_are_checked_against_the_registry(self):
        plan = self.compile({"intent": "plan", "summary": "s",
                             "steps": [{"kind": "note", "text": "hi"}],
                             "required_capabilities": ["calendar.read", "task.persist"]})
        gap_steps = [s for s in plan.steps if s.status == planner.GAP]
        self.assertEqual([s.capability for s in gap_steps], ["calendar.read"])

    def test_a_capability_named_twice_appears_once(self):
        plan = self.compile({"intent": "plan", "summary": "s", "steps": [
            {"gap": "purchase.execute", "why": "no"}],
            "required_capabilities": ["purchase.execute"]})
        self.assertEqual(len([s for s in plan.steps
                              if s.capability == "purchase.execute"]), 1)

    def test_unknown_required_capability_is_named_not_swallowed(self):
        plan = self.compile({"intent": "plan", "summary": "s", "steps": [],
                             "required_capabilities": ["mind.control"]})
        self.assertEqual(plan.steps[0].status, planner.GAP)
        self.assertIn("not in the registry at all", plan.steps[0].detail)


class DegradationCase(unittest.TestCase):
    def test_a_broken_provider_degrades_honestly_and_plans_nothing(self):
        from aletheia import reasoner
        plan = planner.compile(
            "do the thing", fleet=FLEET, registry=REGISTRY,
            provider=exploding(reasoner.ReasonerUnavailable("claude not installed")))
        self.assertIsNotNone(plan.degraded)
        self.assertIn("claude not installed", plan.degraded)
        self.assertEqual(plan.steps, [])
        self.assertEqual(plan.intent, "clarify")  # never invents a plan

    def test_a_malformed_answer_gets_exactly_one_repair_attempt(self):
        calls = []

        def flaky(text, ctx):
            calls.append(text)
            if len(calls) == 1:
                return {"intent": "plan", "summary": "s",
                        "steps": [{"remind_at": True}]}  # no kind/gap/manual
            return {"intent": "plan", "summary": "repaired",
                    "steps": [{"kind": "note", "text": "hi"}]}

        plan = planner.compile("do the thing", fleet=FLEET, registry=REGISTRY,
                               provider=brain.Provider("stub.flaky", flaky))
        self.assertEqual(len(calls), 2)
        self.assertIn("REJECTED", calls[1])
        self.assertIsNone(plan.degraded)
        self.assertEqual(plan.summary, "repaired")

    def test_a_provider_that_stays_broken_is_reported_not_retried_forever(self):
        calls = []

        def always_bad(text, ctx):
            calls.append(text)
            return {"intent": "plan", "summary": "s", "steps": [{"nope": 1}]}

        plan = planner.compile("do the thing", fleet=FLEET, registry=REGISTRY,
                               provider=brain.Provider("stub.bad", always_bad))
        self.assertEqual(len(calls), 2)  # one attempt, one repair, then stop
        self.assertIn("after one repair attempt", plan.degraded)


class ExecuteCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        p = mock.patch.object(journal, "JOURNAL_PATH",
                              Path(self.tmp.name) / "journal.jsonl")
        p.start(); self.addCleanup(p.stop)

    def plan_of(self, *kinds):
        plan = planner.Plan(request="r", summary="s", intent="plan")
        for i, kind in enumerate(kinds, start=1):
            plan.steps.append(planner.PlannedStep(
                i, planner.EXECUTABLE, "ok", {"kind": kind, "text": "x"}))
        return plan

    def test_steps_run_in_order_through_the_given_executor(self):
        seen = []
        receipts = planner.execute(
            self.plan_of("note", "note"), fleet=FLEET,
            executor=lambda cmd, fleet, quote="": seen.append(cmd["kind"]) or "done")
        self.assertEqual(seen, ["note", "note"])
        self.assertEqual([r["outcome"] for r in receipts], ["done", "done"])

    def test_blocked_steps_are_never_executed(self):
        plan = self.plan_of("note")
        plan.steps.append(planner.PlannedStep(2, planner.GAP, "missing",
                                              capability="purchase.execute"))
        plan.steps.append(planner.PlannedStep(3, planner.REFUSED, "bad"))
        seen = []
        planner.execute(plan, fleet=FLEET,
                        executor=lambda cmd, fleet, quote="": seen.append(cmd) or "done")
        self.assertEqual(len(seen), 1)

    def test_the_first_failure_stops_the_rest(self):
        seen = []

        def boom(cmd, fleet, quote=""):
            seen.append(cmd["kind"])
            raise ValueError("nope")

        receipts = planner.execute(self.plan_of("note", "note"), fleet=FLEET,
                                   executor=boom)
        self.assertEqual(len(seen), 1)
        self.assertEqual(receipts[-1]["outcome"], "failed")
        self.assertIn("nope", receipts[-1]["detail"])

    def test_halt_is_re_read_before_every_step_not_once(self):
        # the operator pressing HALT mid-plan must stop the plan
        seen = []
        with mock.patch.object(policy, "halted",
                               side_effect=[None, {"reason": "stop"}]):
            receipts = planner.execute(
                self.plan_of("note", "note"), fleet=FLEET,
                executor=lambda cmd, fleet, quote="": seen.append(cmd) or "done")
        self.assertEqual(len(seen), 1)
        self.assertEqual(receipts[-1]["outcome"], "halted")


class PromptCase(unittest.TestCase):
    def test_the_grammar_is_generated_from_the_intercom_not_restated(self):
        from aletheia import intercom
        brief = planner.grammar_brief()
        for kind in set(intercom.KIND_ARGS) - intercom.PLANNER_FORBIDDEN:
            self.assertIn(kind, brief)

    def test_the_kill_switch_is_not_in_the_grammar_at_all(self):
        """A compiler that turns English into command names can be led to
        one by a word that merely LOOKS like it: "summarize my resume"
        compiled to [{"kind": "resume"}, ...] — a step that lifts her kill
        switch, marked EXECUTABLE and validating clean, because the noun
        and the kind are the same six letters. Every kind here is reached
        by saying it directly, in aletheia.voice, before the planner is
        ever called."""
        brief = planner.grammar_brief()
        for kind in ("halt", "resume", "approve", "deny"):
            self.assertNotIn(f"  {kind}(", brief, kind)

    def test_it_is_refused_even_if_the_model_names_it_anyway(self):
        """Not shown is a request; refused is a gate."""
        from aletheia import intercom
        for kind in sorted(intercom.PLANNER_FORBIDDEN):
            step = planner._classify({"kind": kind}, FLEET, REGISTRY, 1)
            self.assertEqual(step.status, planner.REFUSED, kind)
            self.assertIn("not a step a plan may take", step.detail)

    def test_capability_brief_splits_on_registry_truth(self):
        brief = planner.capability_brief(REGISTRY)
        available, missing = brief.split("NOT AVAILABLE")
        self.assertIn("task.persist", available)
        self.assertIn("purchase.execute (NOT_BUILT)", missing)
        self.assertNotIn("purchase.execute", available)


if __name__ == "__main__":
    unittest.main()
