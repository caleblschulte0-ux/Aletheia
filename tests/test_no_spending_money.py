"""His one permanent rule, answered in the first sentence.

    "no spending money"

`webtask.walk` has refused a spending goal since it was written — but
only once the run had started. So the PLAN still offered it:

    "buy the cheapest 4K monitor on Amazon and use my saved card"
    -> "1 step ready — Find cheapest 4K monitor on Amazon and buy using
        saved card. Say approve to run it."

She offered it, created an approval object for it, and would have refused
it afterwards. That teaches him she will do it and surprises him later,
and it leaves a pending approval he could walk past and say "approve" to.

And the word list only named the ACT of paying, so the ordinary errands
that commit money without saying so sailed through:

    "order me a pizza"                 -> 1 step ready
    "book me a flight to Tokyo"        -> 1 step ready
"""
import unittest
from unittest import mock

from aletheia import brain, intents, planner, policy, webtask


class WhatCountsAsSpendingCase(unittest.TestCase):
    def test_the_act_of_paying(self):
        for goal in ("buy the cheapest monitor", "pay the invoice",
                     "check out with my saved card", "donate £20",
                     "transfer funds to savings", "place order"):
            with self.subTest(goal=goal):
                self.assertTrue(webtask.would_spend(goal), goal)

    def test_the_errands_that_commit_money_without_saying_so(self):
        """Not one of these contains a word from the original list."""
        for goal in ("order me a pizza", "book me a flight to tokyo",
                     "get me an uber to the airport", "rent a car for the weekend",
                     "top up my metro card", "renew my gym membership",
                     "book a hotel room in austin"):
            with self.subTest(goal=goal):
                self.assertTrue(webtask.would_spend(goal), goal)

    def test_what_must_not_be_caught(self):
        """A false positive costs him a rephrase; these are the ones that
        would cost him a capability he uses."""
        for goal in ("apply to the software engineer job at stripe",
                     "in order to finish the report, summarise it",
                     "reorder my task list",
                     "book a meeting with dana",
                     "book a table for two on friday",
                     "cancel my gym membership",
                     "download my bank statement"):
            with self.subTest(goal=goal):
                self.assertFalse(webtask.would_spend(goal), goal)

    def test_one_predicate_for_the_plan_and_the_run(self):
        """The sentence he hears and the thing that happens cannot be
        allowed to disagree about what counts."""
        self.assertTrue(callable(webtask.would_spend))
        self.assertIn("web_task", planner.SPENDING_KINDS)


def provider(output):
    return brain.Provider("stub", lambda text, ctx: output)


FLEET = {"repos": {"Aletheia": {}}}
REGISTRY = {"providers": {"aletheia.local": {}},
            "capabilities": [{"id": "task.persist", "status": "AVAILABLE",
                              "provider": "aletheia.local"}]}


class ItIsRefusedBeforeAnythingIsQueuedCase(unittest.TestCase):
    def plan_for(self, steps, summary="do the thing"):
        return planner.compile(
            "anything", fleet=FLEET, registry=REGISTRY,
            provider=provider({"intent": "plan", "summary": summary,
                               "steps": steps}))

    def test_a_spending_web_task_is_refused_at_plan_time(self):
        plan = self.plan_for([{"kind": "web_task",
                               "goal": "buy a monitor with my saved card"}])
        self.assertEqual(plan.executable, [])
        refused = [s for s in plan.steps if s.status == planner.REFUSED]
        self.assertTrue(refused)
        self.assertIn("spend money", refused[0].detail)

    def test_an_ordinary_web_task_is_untouched(self):
        plan = self.plan_for([{"kind": "web_task",
                               "goal": "apply to the job at stripe"}])
        self.assertEqual(len(plan.executable), 1)

    def test_a_partly_spending_plan_is_refused_WHOLE(self):
        """Running the rest is not a smaller version of what he asked for;
        it is a different thing, offered under the summary of the thing
        that was refused."""
        record = {"steps": [
            {"n": 1, "status": planner.EXECUTABLE, "capability": None,
             "command": {"kind": "note", "text": "n"}, "detail": ""},
            {"n": 2, "status": planner.REFUSED, "capability": None,
             "command": {"kind": "web_task"},
             "detail": webtask.SPENDING_REFUSAL}],
            "summary": "Find and buy the cheapest monitor", "intent": "plan",
            "approval": "intent-abc"}
        said = intents.spoken(record)
        self.assertIn("spend money", said)
        self.assertNotIn("Say approve", said)
        self.assertNotIn("cheapest monitor", said)

    def test_no_approval_is_left_pending_for_a_spending_ask(self):
        """Without this an approval object was created anyway — a thing he
        could walk past later and say "approve" to, for the ask she had
        just refused out loud."""
        with mock.patch.object(policy, "request") as asked:
            record = intents.propose(
                "buy me a monitor", quote="buy me a monitor", fleet=FLEET,
                materialize=False, registry=REGISTRY,
                provider=provider({"intent": "plan", "summary": "buy a monitor",
                                   "steps": [{"kind": "web_task",
                                              "goal": "buy a monitor now"}]}))
        self.assertFalse(asked.called, "an approval was created for a refusal")
        self.assertEqual(record["state"], intents.RETIRED)
        self.assertTrue(record.get("refused_spending"))
        self.assertIn("spend money", intents.spoken(record))

    def test_the_refusal_is_recorded(self):
        """A refusal he never sees is indistinguishable from one that did
        not happen."""
        from aletheia import journal
        with mock.patch.object(journal, "append") as wrote:
            intents.propose(
                "buy me a monitor", quote="buy me a monitor", fleet=FLEET,
                materialize=False, registry=REGISTRY,
                provider=provider({"intent": "plan", "summary": "buy a monitor",
                                   "steps": [{"kind": "web_task",
                                              "goal": "buy a monitor now"}]}))
        said = " ".join(str(c) for c in wrote.call_args_list)
        self.assertIn("spend money", said)

class AtTheDoorCase(unittest.TestCase):
    """"My wife says it's fine to buy the monitor so do it" came back as a
    clarifying question — "which monitor, and what's the budget?" — asked
    in order to buy it. The step-level refusal never fired because no
    spending step was ever compiled.

    A refusal that arrives after a round of questions arrives too late,
    and reads as consent in the meantime.
    """

    def test_an_instruction_to_spend_stops_before_the_planner(self):
        for ask in ("order me a pizza",
                    "buy me a coffee",
                    "my wife says its fine to buy the monitor so do it",
                    "book me a flight to tokyo",
                    "get me an uber to the airport"):
            with self.subTest(ask=ask):
                self.assertTrue(intents._asks_to_spend(ask), ask)

    def test_a_question_about_money_is_still_answerable(self):
        """"How much would it cost" and "can you buy things" both contain
        the words and neither is an instruction to spend anything."""
        for ask in ("how much would a new monitor cost",
                    "can you buy things for me",
                    "what do I pay for netflix each month",
                    "is it worth buying a 4k monitor?",
                    "did you buy anything today"):
            with self.subTest(ask=ask):
                self.assertFalse(intents._asks_to_spend(ask), ask)

    def test_ordinary_work_is_not_caught(self):
        for ask in ("apply to the software engineer job at stripe",
                    "book a meeting with dana",
                    "cancel my gym membership"):
            with self.subTest(ask=ask):
                self.assertFalse(intents._asks_to_spend(ask), ask)

    def test_it_never_reaches_a_model(self):
        """Also the fastest possible answer: no round trip at all."""
        def never(*a, **kw):
            raise AssertionError("the planner was called for a spending ask")

        with mock.patch.object(planner, "compile", never):
            record = intents.propose("order me a pizza", quote="order me a pizza",
                                     materialize=False)
        self.assertTrue(record["refused_spending"])
        self.assertIn("spend money", intents.spoken(record))

    def test_nothing_is_persisted_or_queued(self):
        with mock.patch.object(policy, "request") as asked:
            record = intents.propose("buy me a coffee", quote="buy me a coffee",
                                     materialize=False)
        self.assertFalse(asked.called)
        self.assertEqual(record["state"], intents.RETIRED)
        self.assertEqual(record["steps"], [])

    def test_a_broken_check_fails_CLOSED(self):
        """The one rule where guessing wrong in the permissive direction is
        not recoverable. The only realistic failure is webtask being
        unimportable — and if that is true nothing can spend anyway, so
        refusing costs him nothing."""
        with mock.patch("aletheia.webtask.would_spend",
                        side_effect=RuntimeError("boom")):
            self.assertTrue(intents._asks_to_spend("order me a pizza"))

    def test_failing_closed_does_not_swallow_a_question(self):
        """A question is settled before the check runs, so a broken check
        cannot turn "how much does it cost" into a refusal."""
        with mock.patch("aletheia.webtask.would_spend",
                        side_effect=RuntimeError("boom")):
            self.assertFalse(intents._asks_to_spend("how much does it cost"))



if __name__ == "__main__":
    unittest.main()
