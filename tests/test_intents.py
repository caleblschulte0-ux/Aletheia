"""Durable arbitrary asks: the plan the operator approved is the plan that
runs, or nothing runs.

The binding under test is the one already ratified for computer control
and email — an approval carries a sha256 of the exact plan — extended to
plans a model wrote. `approve` must never be a blank cheque on a sentence.
"""
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import brain, intents, journal, planner, policy

FLEET = {"repos": {"Aletheia": {}}}
REGISTRY = {
    "providers": {"aletheia.local": {}},
    "capabilities": [
        {"id": "task.persist", "status": "AVAILABLE", "provider": "aletheia.local"},
        {"id": "purchase.execute", "status": "NOT_BUILT", "provider": "aletheia.local"},
    ],
}


def provider(output):
    return brain.Provider("stub", lambda text, ctx: output)


class IntentCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        env = mock.patch.dict(os.environ, {"ALETHEIA_PRIVATE_STATE": str(root / "private")})
        env.start(); self.addCleanup(env.stop)
        for module, attr, value in (
                (policy, "APPROVALS_DIR", root / "approvals"),
                (journal, "JOURNAL_PATH", root / "journal.jsonl")):
            p = mock.patch.object(module, attr, value)
            p.start(); self.addCleanup(p.stop)
        (root / "approvals").mkdir(parents=True, exist_ok=True)
        halt = mock.patch.object(policy, "halted", return_value=None)
        halt.start(); self.addCleanup(halt.stop)

    def propose(self, output, request="do the thing", materialize=False):
        return intents.propose(request, quote=request, fleet=FLEET,
                               materialize=materialize, provider=provider(output),
                               registry=REGISTRY)

    def one_step_plan(self):
        # A WORLD-TOUCHING step on purpose. These tests are about the
        # approve/execute machinery, and a read-only plan is now answered on
        # the spot without an approval — which is correct, and would make
        # every assertion below vacuous.
        return {"intent": "plan", "summary": "queue it",
                "steps": [{"kind": "task_new", "id": "water-plants",
                           "description": "water the plants"}]}

    # ---- proposing -------------------------------------------------

    def test_proposing_persists_the_plan_and_asks_but_runs_nothing(self):
        seen = []
        record = self.propose(self.one_step_plan())
        self.assertEqual(record["state"], intents.PROPOSED)
        self.assertEqual(intents.load(record["id"])["summary"], "queue it")
        self.assertEqual(policy.load(record["approval"])["state"], "PENDING")
        self.assertEqual(seen, [])

    def test_the_approval_names_what_would_actually_run(self):
        record = self.propose(self.one_step_plan())
        approval = policy.load(record["approval"])
        self.assertIn("task_new", approval["requested_action"])
        self.assertIn("do the thing", approval["reason"])

    def test_a_plan_with_nothing_executable_asks_for_no_approval(self):
        record = self.propose({"intent": "plan", "summary": "cannot",
                               "steps": [{"gap": "purchase.execute", "why": "no"}]})
        with self.assertRaises(Exception):
            policy.load(record["approval"])
        self.assertIn("purchase.execute", intents.spoken(record))

    # ---- chatter must not become a queue ----------------------------

    def test_a_read_only_plan_is_answered_not_filed(self):
        # Found in real use: the room mic hears a half-sentence, the planner
        # turns it into "report current operational status", and that filed a
        # durable intent AND an operator_always approval. Eight accumulated
        # in a day.
        seen = []
        record = intents.propose(
            "what is going on", quote="what is going on", fleet=FLEET,
            materialize=False, registry=REGISTRY,
            provider=provider({"intent": "plan", "summary": "report status",
                               "steps": [{"kind": "notify_check"}]}))
        self.assertEqual(record["state"], intents.EXECUTED)
        self.assertTrue(record["read_only"])
        with self.assertRaises(Exception):
            policy.load(record["approval"])
        self.assertEqual(intents.all_intents(), [],
                         "a read-only answer was filed as durable work")

    def test_chatter_with_nothing_to_do_is_not_filed_at_all(self):
        record = self.propose({"intent": "answer", "summary": "Acknowledged."})
        self.assertEqual(record["state"], intents.RETIRED)
        self.assertEqual(intents.all_intents(), [])

    def test_a_world_touching_plan_still_files_and_still_asks(self):
        record = self.propose({
            "intent": "plan", "summary": "email dana",
            "steps": [{"kind": "notify_check"},
                      {"kind": "email_draft", "to": "dana", "body": "hi"}]})
        self.assertEqual(record["state"], intents.PROPOSED)
        self.assertEqual(policy.load(record["approval"])["state"], "PENDING")

    def test_the_same_plan_twice_is_one_intent_not_two(self):
        first = self.propose(self.one_step_plan())
        second = self.propose(self.one_step_plan())
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(len(intents.all_intents()), 1)

    # ---- approving and running -------------------------------------

    def test_approved_plans_run_on_a_later_beat(self):
        seen = []
        record = self.propose(self.one_step_plan())
        self.assertEqual(intents.run_approved(FLEET, executor=lambda *a, **k: "x"), [])
        policy.decide(record["approval"], "APPROVED", via="test")
        results = intents.run_approved(
            FLEET, executor=lambda cmd, fleet, quote="": seen.append(cmd["kind"]) or "done")
        self.assertEqual(seen, ["task_new"])
        self.assertEqual(results[0]["outcome"], intents.EXECUTED)

    def test_an_executed_intent_does_not_run_again(self):
        seen = []
        record = self.propose(self.one_step_plan())
        policy.decide(record["approval"], "APPROVED", via="test")
        run = lambda cmd, fleet, quote="": seen.append(cmd["kind"]) or "done"
        intents.run_approved(FLEET, executor=run)
        intents.run_approved(FLEET, executor=run)
        self.assertEqual(seen, ["task_new"])  # once, not twice

    def test_a_denied_intent_is_retired_and_never_runs(self):
        seen = []
        record = self.propose(self.one_step_plan())
        policy.decide(record["approval"], "DENIED", via="test", because="no")
        results = intents.run_approved(
            FLEET, executor=lambda *a, **k: seen.append(1) or "done")
        self.assertEqual(seen, [])
        self.assertEqual(results[0]["outcome"], "denied")
        self.assertEqual(intents.load(record["id"])["state"], intents.RETIRED)

    def test_a_plan_edited_after_approval_is_refused_not_adapted(self):
        seen = []
        record = self.propose(self.one_step_plan())
        policy.decide(record["approval"], "APPROVED", via="test")
        # something rewrites the stored plan between approval and execution
        tampered = intents.load(record["id"])
        tampered["steps"][0]["command"]["description"] = "something else entirely"
        from aletheia import stateio
        stateio.write_json_atomic(intents._record_path(record["id"]), tampered)
        results = intents.run_approved(
            FLEET, executor=lambda *a, **k: seen.append(1) or "done")
        self.assertEqual(seen, [])
        self.assertEqual(results[0]["outcome"], "refused")
        self.assertEqual(intents.load(record["id"])["state"], intents.FAILED)

    def test_a_step_added_after_approval_is_refused(self):
        seen = []
        record = self.propose(self.one_step_plan())
        policy.decide(record["approval"], "APPROVED", via="test")
        tampered = intents.load(record["id"])
        tampered["steps"].append({"n": 2, "status": planner.EXECUTABLE, "detail": "x",
                                  "command": {"kind": "halt"}, "capability": None})
        from aletheia import stateio
        stateio.write_json_atomic(intents._record_path(record["id"]), tampered)
        intents.run_approved(FLEET, executor=lambda *a, **k: seen.append(1) or "done")
        self.assertEqual(seen, [])

    def test_a_failing_step_marks_the_intent_failed(self):
        record = self.propose(self.one_step_plan())
        policy.decide(record["approval"], "APPROVED", via="test")

        def boom(cmd, fleet, quote=""):
            raise ValueError("nope")

        intents.run_approved(FLEET, executor=boom)
        self.assertEqual(intents.load(record["id"])["state"], intents.FAILED)

    def test_halt_stops_an_approved_plan(self):
        seen = []
        record = self.propose(self.one_step_plan())
        policy.decide(record["approval"], "APPROVED", via="test")
        with mock.patch.object(policy, "halted", return_value={"reason": "stop"}):
            intents.run_approved(FLEET,
                                 executor=lambda *a, **k: seen.append(1) or "done")
        self.assertEqual(seen, [])

    # ---- what she says back ----------------------------------------

    def test_spoken_names_the_approval_and_the_gap(self):
        record = self.propose({"intent": "plan", "summary": "mixed", "steps": [
            {"kind": "note", "text": "hi"},
            {"gap": "purchase.execute", "why": "cannot buy"},
            {"manual": "sign it"}]})
        said = intents.spoken(record)
        self.assertIn("1 step ready", said)
        self.assertIn(record["approval"], said)
        self.assertIn("purchase.execute", said)
        self.assertIn("only you can do", said)

    def test_spoken_passes_a_clarifying_question_straight_through(self):
        record = self.propose({"intent": "clarify",
                               "summary": "Which sister — Ana or Mia?"})
        self.assertEqual(intents.spoken(record), "Which sister — Ana or Mia?")

    def test_spoken_is_honest_when_there_was_no_provider(self):
        from aletheia import reasoner
        record = intents.propose(
            "do the thing", fleet=FLEET, materialize=False, registry=REGISTRY,
            provider=brain.Provider("broken", mock.Mock(
                side_effect=reasoner.ReasonerUnavailable("claude not installed"))))
        self.assertIn("could not plan", intents.spoken(record))
        self.assertIn("claude not installed", intents.spoken(record))

    def test_a_corrupt_record_is_not_an_authorization(self):
        record = self.propose(self.one_step_plan())
        policy.decide(record["approval"], "APPROVED", via="test")
        intents._record_path(record["id"]).write_text("{ broken", encoding="utf-8")
        self.assertEqual(intents.all_intents(), [])
        self.assertEqual(intents.run_approved(FLEET, executor=lambda *a, **k: "x"), [])


if __name__ == "__main__":
    unittest.main()
