"""She answers the question — the thing that was missing.

Every ask went through the planner, which turns English into COMMAND
STEPS. Right for "remind me Tuesday", wrong for "explain this to me": the
planner returned intent "answer" with nothing executable, the record was
retired, and she replied with plan.summary — a one-line restatement of
the question. An executor with no mouth.
"""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import converse, journal, policy, tasks


class ConverseCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        d = Path(self.tmp.name)
        env = mock.patch.dict(os.environ, {"ALETHEIA_PRIVATE_STATE": str(d)})
        env.start(); self.addCleanup(env.stop)
        for target, attr, value in (
                (journal, "JOURNAL_PATH", d / "j.jsonl"),
                (policy, "APPROVALS_DIR", d / "approvals"),
                (policy, "HALT_PATH", d / "halt.json"),
                (tasks, "TASKS_DIR", d / "tasks"),
                (converse, "THREAD_PATH", d / "recent.json")):
            p = mock.patch.object(target, attr, value)
            p.start(); self.addCleanup(p.stop)

    def says(self, text="Because the moon pulls the water."):
        seen = {}

        def fake(system, prompt, **kwargs):
            seen["system"] = system
            seen["prompt"] = prompt
            return text
        self.seen = seen
        return fake


class SheActuallyAnswers(ConverseCase):
    def test_a_question_gets_prose_not_a_plan(self):
        out = converse.answer("why are there tides?", think=self.says())
        self.assertEqual(out["answer"], "Because the moon pulls the water.")

    def test_she_is_told_who_she_is(self):
        converse.answer("hello", think=self.says())
        system = self.seen["system"]
        self.assertIn("Thea", system)
        self.assertIn("Caleb", system)

    def test_she_is_told_to_say_when_she_does_not_know(self):
        """The rule that separates her from something that sounds right."""
        self.assertIn("do not know", converse.SYSTEM)
        self.assertIn("Never", converse.SYSTEM)

    def test_an_empty_or_huge_question_is_refused(self):
        for bad in ("", "   ", "x" * 99_999):
            with self.subTest(bad=bad[:12]):
                with self.assertRaises(ValueError):
                    converse.answer(bad, think=self.says())

    def test_a_model_that_returns_nothing_is_an_error_not_a_blank_reply(self):
        with self.assertRaises(converse.ConverseError):
            converse.answer("hello", think=lambda *a, **k: "   ")

    def test_an_unreachable_model_says_which_half_broke(self):
        def dead(*a, **k):
            raise RuntimeError("no CLI")
        with self.assertRaises(converse.ConverseError) as caught:
            converse.answer("hello", think=dead)
        self.assertIn("could not reach", str(caught.exception))


class SheKnowsWhatSheHasBeenDoing(ConverseCase):
    """The part a chat assistant elsewhere cannot do at all."""

    def test_open_work_travels_with_the_question(self):
        tasks.create("fix-trader", "Look at why the trader is paused")
        converse.answer("what was I meant to do about the trader?",
                        think=self.says())
        self.assertIn("Look at why the trader is paused", self.seen["prompt"])

    def test_what_is_waiting_on_him_travels_too(self):
        policy.request("ap-1", "send the email to Dana", "why", "what happens", True)
        converse.answer("anything for me?", think=self.says())
        self.assertIn("send the email to Dana", self.seen["prompt"])

    def test_a_halt_is_part_of_the_situation(self):
        policy.halt("I stopped her", via="test")
        converse.answer("why is nothing happening?", think=self.says())
        self.assertIn("halted", self.seen["prompt"])

    def test_context_is_marked_as_hers_so_she_does_not_recite_it(self):
        tasks.create("t", "something")
        converse.answer("hi", think=self.says())
        self.assertIn("CONTEXT", self.seen["prompt"])
        # the prompt is wrapped; compare on collapsed whitespace
        flat = " ".join(converse.SYSTEM.split())
        self.assertIn("Do not recite it back at him", flat)

    def test_a_broken_store_thins_the_answer_rather_than_killing_it(self):
        with mock.patch.object(tasks, "all_tasks", side_effect=OSError("gone")):
            out = converse.answer("still there?", think=self.says())
        self.assertTrue(out["answer"])


class SheRemembersTheLastFewTurns(ConverseCase):
    def test_a_follow_up_can_refer_back(self):
        converse.answer("who makes the best coffee?", think=self.says("Blue Bottle."))
        converse.answer("what about the other one?", think=self.says("Verve."))
        self.assertIn("Blue Bottle", self.seen["prompt"])

    def test_the_thread_is_bounded(self):
        for i in range(20):
            converse.answer(f"question {i}", think=self.says(f"answer {i}"))
        turns = json.loads(converse.THREAD_PATH.read_text())["turns"]
        self.assertLessEqual(len(turns), converse.KEEP_TURNS,
                             "an unbounded transcript makes every question slow")

    def test_forgetting_really_drops_it(self):
        converse.answer("remember this", think=self.says())
        converse.forget()
        converse.answer("new subject", think=self.says())
        self.assertNotIn("remember this", self.seen["prompt"])


class ItAnswersAndDoesNotACT(ConverseCase):
    """Answering is not a hole in the gates."""

    def test_the_module_reaches_no_executor(self):
        source = (Path(__file__).parent.parent / "aletheia" / "converse.py"
                  ).read_text(encoding="utf-8")
        for reach in ("execute_command", "intercom.execute", "agenda.run",
                      "workspace.write", "computer.act", "errands"):
            self.assertNotIn(reach, source, reach)

    def test_the_prompt_forbids_acting_in_the_reply(self):
        self.assertIn("do not take actions", converse.SYSTEM.lower())

    def test_the_journal_records_that_it_happened_not_what_was_said(self):
        """His questions are his."""
        converse.answer("something private about my health",
                        think=self.says("a private answer"))
        log = journal.JOURNAL_PATH.read_text(encoding="utf-8")
        self.assertIn("answered a question", log)
        self.assertNotIn("my health", log)
        self.assertNotIn("a private answer", log)


class TheAskPathUsesIt(ConverseCase):
    """The wiring: a question through the ordinary intent path must come
    back as an answer, not as a summary of itself."""

    def test_an_answer_intent_is_spoken_as_the_answer(self):
        from aletheia import intents
        record = {"read_only": True, "spoken": "Because the moon pulls the water.",
                  "steps": [], "intent": "answer", "summary": "tides question"}
        self.assertEqual(intents.spoken(record),
                         "Because the moon pulls the water.")

    def test_the_summary_is_no_longer_the_fallback_for_a_question(self):
        from aletheia import intents
        source = (Path(__file__).parent.parent / "aletheia" / "intents.py"
                  ).read_text(encoding="utf-8")
        self.assertIn("converse.answer(request)", source)


if __name__ == "__main__":
    unittest.main()


class ClarifyingIsNotAnswering(ConverseCase):
    """A bug this pass introduced and caught: routing `clarify` through
    converse turned "Which sister — Ana or Mia?" into a paragraph about
    ambiguity. A clarifying question is already the right thing to say."""

    def test_a_clarify_intent_keeps_its_own_wording(self):
        from aletheia import intents
        record = {"read_only": True, "intent": "clarify", "steps": [],
                  "summary": "Which sister — Ana or Mia?"}
        self.assertEqual(intents.spoken(record), "Which sister — Ana or Mia?")

    def test_only_a_question_reaches_converse(self):
        source = (Path(__file__).parent.parent / "aletheia" / "intents.py"
                  ).read_text(encoding="utf-8")
        branch = source[source.index('if not plan.executable and plan.intent'):]
        branch = branch[:branch.index("stateio.write_json_atomic")]
        self.assertIn('if plan.intent == "clarify"', branch)
        self.assertLess(branch.index('plan.intent == "clarify"'),
                        branch.index("converse.answer"),
                        "clarify must return before the answer path")
