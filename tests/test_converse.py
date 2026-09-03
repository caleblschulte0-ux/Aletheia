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

    def test_an_actionable_failure_reaches_him_intact(self):
        """"Claude CLI is not on PATH" tells him what to do. Rewriting it
        into "(ConverseError)" is how an actionable failure becomes a shrug."""
        from aletheia import intents
        source = (Path(__file__).parent.parent / "aletheia" / "intents.py"
                  ).read_text(encoding="utf-8")
        branch = source[source.index("converse.answer(request)"):]
        branch = branch[:branch.index("return record")]
        self.assertIn("except converse.ConverseError", branch)
        self.assertIn("str(exc)", branch)
        self.assertLess(branch.index("except converse.ConverseError"),
                        branch.index("except Exception"),
                        "the specific reason must be caught first")



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


class SheReadsTheFileHeNames(ConverseCase):
    """"Look at my resume and tell me what's weak" was answered BLIND.

    She had no way to notice that `resume.md` was a file rather than a word,
    so the reply was a confident paragraph about a document she had never
    opened — indistinguishable from the real thing until he checked.
    """

    def setUp(self):
        super().setUp()
        ws = Path(self.tmp.name) / "ws"
        ws.mkdir()
        self.ws = ws
        env = mock.patch.dict(os.environ, {"ALETHEIA_WORKSPACE": str(ws)})
        env.start(); self.addCleanup(env.stop)

    def test_the_contents_travel_with_the_question(self):
        (self.ws / "resume.md").write_text("Ran a six-video-a-day pipeline.")
        out = converse.answer("look at resume.md and tell me what is weak",
                              think=self.says())
        self.assertIn("Ran a six-video-a-day pipeline.", self.seen["prompt"])
        self.assertEqual(len(out["files_read"]), 1)

    def test_a_file_she_cannot_read_is_named_not_papered_over(self):
        out = converse.answer("read missing_notes.md and summarise it",
                              think=self.says())
        self.assertEqual(out["files_read"], [])
        self.assertTrue(out["unreadable"])
        self.assertIn("missing_notes.md", out["unreadable"][0])
        self.assertIn("COULD NOT READ", self.seen["prompt"])
        self.assertIn("Do not answer as though you had read it",
                      self.seen["prompt"])

    def test_the_miss_does_not_name_paths_he_never_mentioned(self):
        """The first version reported the LAST attempt's error verbatim —
        "/root/notes.md is not a file" — which is true, useless, and tells
        him where she went rummaging."""
        out = converse.answer("read notes.md please", think=self.says())
        self.assertNotIn(str(Path.home()), out["unreadable"][0])

    def test_a_file_found_but_unusable_says_WHY(self):
        (self.ws / "bad.md").write_bytes(b"\xff\xfe\x00not text")
        out = converse.answer("read bad.md", think=self.says())
        self.assertIn("UTF-8", out["unreadable"][0])

    def test_a_passing_mention_of_a_filename_is_not_a_complaint(self):
        """"The bug is in converse.py" must not produce "I couldn't find
        converse.py" stapled to an otherwise fine answer."""
        out = converse.answer("the bug is somewhere in converse.py I think",
                              think=self.says())
        self.assertEqual(out["unreadable"], [])
        self.assertNotIn("COULD NOT READ", self.seen["prompt"])

    def test_she_does_not_slurp_the_whole_folder(self):
        for i in range(4):
            (self.ws / f"f{i}.md").write_text(f"file {i}")
        out = converse.answer(
            "read f0.md f1.md f2.md f3.md and compare them", think=self.says())
        self.assertEqual(len(out["files_read"]), converse.MAX_ATTACHED)
        self.assertTrue(out["unreadable"], "the ones she skipped are declared")

    def test_a_long_file_is_truncated_and_says_so(self):
        (self.ws / "long.md").write_text("y" * (converse.MAX_ATTACHED_CHARS + 5_000))
        converse.answer("read long.md", think=self.says())
        self.assertIn("truncated here", self.seen["prompt"])

    def test_reading_is_the_only_thing_it_does_to_a_file(self):
        source = (Path(__file__).parent.parent / "aletheia" / "converse.py"
                  ).read_text(encoding="utf-8")
        for reach in ("workspace.write", "workspace.edit", "workspace.restore"):
            self.assertNotIn(reach, source, reach)

    def test_the_journal_counts_files_without_naming_their_contents(self):
        (self.ws / "resume.md").write_text("A private line about my health.")
        converse.answer("look at resume.md", think=self.says())
        log = journal.JOURNAL_PATH.read_text(encoding="utf-8")
        self.assertIn("1 file(s) read", log)
        self.assertNotIn("private line about my health", log)


class TheThreadIsBoundedBySize(ConverseCase):
    """A turn COUNT is the wrong bound. Twenty-four one-line exchanges are
    nothing; twenty-four long ones are a slow, expensive question every
    time, and the oldest of them stopped being relevant long ago."""

    def test_long_turns_are_dropped_before_the_count_runs_out(self):
        big = "z" * 800
        for i in range(10):
            converse.answer(f"q{i} " + big, think=self.says("a" + big))
        turns = json.loads(converse.THREAD_PATH.read_text())["turns"]
        size = sum(len(t["you"]) + len(t["her"]) for t in turns)
        self.assertLess(len(turns), 10, "size, not just the turn ceiling")
        self.assertLessEqual(size, converse.MAX_THREAD_CHARS)

    def test_the_most_recent_turn_always_survives(self):
        """Even one turn over budget on its own. Dropping what he just said
        is never the right answer to "this is too long"."""
        huge = [{"at": "now", "you": "x" * 99_999, "her": "y" * 99_999}]
        self.assertEqual(len(converse._trim(huge)), 1)

    def test_an_oversized_thread_on_disk_is_trimmed_on_the_way_out(self):
        converse.THREAD_PATH.parent.mkdir(parents=True, exist_ok=True)
        converse.THREAD_PATH.write_text(json.dumps({"turns": [
            {"at": "t", "you": "old " * 400, "her": "older " * 400}
            for _ in range(30)]}))
        converse.answer("and now?", think=self.says())
        self.assertLess(len(self.seen["prompt"]),
                        converse.MAX_THREAD_CHARS + 40_000)

    def test_junk_in_the_thread_does_not_crash_the_answer(self):
        converse.THREAD_PATH.parent.mkdir(parents=True, exist_ok=True)
        converse.THREAD_PATH.write_text(json.dumps({"turns": ["not a turn", 7]}))
        self.assertTrue(converse.answer("still there?", think=self.says())["answer"])


class AnAnswerGetsLongerThanAnInterpretation(ConverseCase):
    def test_the_model_call_carries_the_conversation_timeout(self):
        """90s is sized for classifying a sentence. A real reply to a real
        question is allowed longer before it is called a failure."""
        seen = {}

        def fake(system, prompt, **kwargs):
            seen.update(kwargs)
            return "fine"
        converse.answer("explain the trade-off", think=fake)
        self.assertEqual(seen.get("timeout_s"), converse.TIMEOUT_S)
        self.assertGreater(converse.TIMEOUT_S, 90.0)

    def test_an_unreachable_model_carries_the_REASON_not_a_type_name(self):
        """"Claude CLI is not on PATH" tells him what to do. The old message
        printed only the exception class and dropped the useful sentence."""
        def dead(*a, **k):
            raise RuntimeError("Claude CLI is not on PATH")
        with self.assertRaises(converse.ConverseError) as caught:
            converse.answer("hello", think=dead)
        said = str(caught.exception)
        self.assertIn("Claude CLI is not on PATH", said)
        self.assertIn("Sign the Claude CLI in", said)


if __name__ == "__main__":
    unittest.main()
