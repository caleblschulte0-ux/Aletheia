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


class SheKnowsWhatHeToldHerToRemember(ConverseCase):
    """Recall by exact key is fine for code and useless in conversation: he
    says "what's my sister's name", not "recall people.sister". Until this
    existed, a fact he had deliberately asked her to remember could not
    reach an answer — the most obvious way for an assistant to feel like a
    stranger."""

    def test_remembered_facts_travel_with_the_question(self):
        from aletheia import memory
        with mock.patch.object(memory, "_load", side_effect=lambda d: (
                {"sister": {"value": "Ana", "kind": "explicit",
                            "source": "he said so", "ts": "now"}}
                if d == "people" else {})):
            converse.answer("what's my sister's name?", think=self.says())
        self.assertIn("Ana", self.seen["prompt"])

    def test_a_guess_is_labelled_as_a_guess(self):
        from aletheia import memory
        with mock.patch.object(memory, "_load", side_effect=lambda d: (
                {"coffee": {"value": "black", "kind": "inferred",
                            "source": "watched", "ts": "now"}}
                if d == "preferences" else {})):
            converse.answer("how do I take my coffee?", think=self.says())
        self.assertIn("inferred", self.seen["prompt"])

    def test_a_corrupt_memory_file_thins_her_rather_than_muting_her(self):
        from aletheia import memory
        with mock.patch.object(memory, "_load", side_effect=ValueError("bad json")):
            self.assertTrue(converse.answer("hi", think=self.says())["answer"])

    def test_memory_is_bounded(self):
        from aletheia import memory
        fat = {f"k{i}": {"value": "v" * 500, "kind": "explicit",
                         "source": "s", "ts": "t"} for i in range(50)}
        with mock.patch.object(memory, "_load", return_value=fat):
            self.assertLess(len(json.dumps(memory.everything())), 20_000)


class SheAnswersInHisTimeNotUTC(ConverseCase):
    def test_his_local_clock_travels_with_the_question(self):
        """"What's on today?" answered against a UTC clock is wrong for six
        hours out of every twenty-four, in the way that looks right."""
        converse.answer("what's on today?", think=self.says())
        self.assertIn("local time", self.seen["prompt"])

    def test_todays_calendar_is_part_of_the_situation(self):
        from aletheia import calendar, localtime
        import datetime as dt
        here = localtime.operator_tz()
        start = dt.datetime.now(here).replace(hour=15, minute=0, second=0,
                                              microsecond=0)
        event = {"version": 1, "id": "ev1", "title": "Dentist",
                 "start": start.isoformat(),
                 "end": (start + dt.timedelta(hours=1)).isoformat(),
                 "created_at": "x", "updated_at": "x", "status": "CONFIRMED"}
        with mock.patch.object(calendar, "all_events", return_value=[event]):
            converse.answer("am I free tonight?", think=self.says())
        self.assertIn("Dentist", self.seen["prompt"])

    def test_a_cancelled_event_is_not_on_his_day(self):
        from aletheia import calendar, localtime
        import datetime as dt
        start = dt.datetime.now(localtime.operator_tz())
        event = {"version": 1, "id": "ev1", "title": "Called off",
                 "start": start.isoformat(),
                 "end": (start + dt.timedelta(hours=1)).isoformat(),
                 "created_at": "x", "updated_at": "x", "status": "CANCELLED"}
        with mock.patch.object(calendar, "all_events", return_value=[event]):
            converse.answer("what's on?", think=self.says())
        self.assertNotIn("Called off", self.seen["prompt"])

    def test_a_broken_calendar_does_not_end_the_conversation(self):
        from aletheia import calendar
        with mock.patch.object(calendar, "all_events", side_effect=OSError("gone")):
            self.assertTrue(converse.answer("hi", think=self.says())["answer"])


class TheFileStaysOpenForTheFollOwUp(ConverseCase):
    """"Look at resume.md" then "make the second bullet stronger" is ONE
    conversation. The second half names no file, so without this she goes
    blind again mid-thread and answers from a 900-character summary of her
    own last reply."""

    def setUp(self):
        super().setUp()
        self.ws = Path(self.tmp.name) / "ws"
        self.ws.mkdir()
        env = mock.patch.dict(os.environ, {"ALETHEIA_WORKSPACE": str(self.ws)})
        env.start(); self.addCleanup(env.stop)
        (self.ws / "resume.md").write_text("- ran a pipeline\n- the weak bullet\n")

    def test_the_follow_up_still_sees_the_file(self):
        converse.answer("look at resume.md, what is weak?", think=self.says())
        converse.answer("make the second bullet stronger", think=self.says())
        self.assertIn("the weak bullet", self.seen["prompt"])
        self.assertIn("STILL OPEN", self.seen["prompt"])

    def test_the_thread_stores_the_PATH_never_the_contents(self):
        """His resume does not get copied into her conversation store."""
        converse.answer("look at resume.md", think=self.says())
        raw = converse.THREAD_PATH.read_text()
        self.assertIn("resume.md", raw)
        self.assertNotIn("the weak bullet", raw)

    def test_an_old_file_is_not_dragged_into_a_new_subject(self):
        converse.answer("look at resume.md", think=self.says())
        turns = json.loads(converse.THREAD_PATH.read_text())["turns"]
        turns[-1]["at"] = "2020-01-01T00:00:00Z"
        converse.THREAD_PATH.write_text(json.dumps({"turns": turns}))
        converse.answer("what is the capital of Peru?", think=self.says())
        self.assertNotIn("the weak bullet", self.seen["prompt"])

    def test_naming_a_new_file_replaces_the_carried_one(self):
        (self.ws / "cover.md").write_text("- the cover letter line")
        converse.answer("look at resume.md", think=self.says())
        converse.answer("now read cover.md", think=self.says())
        self.assertIn("the cover letter line", self.seen["prompt"])
        self.assertNotIn("the weak bullet", self.seen["prompt"])

    def test_a_carried_file_that_vanished_is_not_an_error_message(self):
        """He did not ask for it this time; "could not read resume.md"
        stapled to an unrelated answer reads like a malfunction."""
        converse.answer("look at resume.md", think=self.says())
        (self.ws / "resume.md").unlink()
        out = converse.answer("what is the capital of Peru?", think=self.says())
        self.assertEqual(out["unreadable"], [])


class ThePromptFitsWhatTheReasonerWillACCEPT(ConverseCase):
    """The ceiling is not ours. `reasoner.validate_input` refuses any prompt
    over brain.MAX_TEXT (16,000) before the CLI is even started, with a bare
    ValueError that reads — by the time it reaches the phone — as "I could
    not reach a model". A 20 KB document would not have produced a worse
    answer; it would have produced NO answer and no hint of why."""

    def setUp(self):
        super().setUp()
        self.ws = Path(self.tmp.name) / "ws"
        self.ws.mkdir()
        env = mock.patch.dict(os.environ, {"ALETHEIA_WORKSPACE": str(self.ws)})
        env.start(); self.addCleanup(env.stop)

    def checked(self, text="fine"):
        """A `think` that enforces the REAL contract, not a stand-in for it."""
        from aletheia import reasoner
        seen = {}

        def fake(system, prompt, **kwargs):
            reasoner.validate_input(system, prompt, None)   # raises if too big
            seen["prompt"] = prompt
            return text
        self.seen = seen
        return fake

    def test_a_big_document_still_gets_an_answer(self):
        (self.ws / "spec.md").write_text("PARAGRAPH. " * 6_000)   # ~66 KB
        out = converse.answer("read spec.md and summarise it", think=self.checked())
        self.assertEqual(out["answer"], "fine")
        self.assertIn("truncated here", self.seen["prompt"])

    def test_the_ceiling_holds_with_everything_at_once(self):
        from aletheia import memory
        (self.ws / "a.md").write_text("A" * 40_000)
        (self.ws / "b.md").write_text("B" * 40_000)
        for i in range(30):
            converse.answer(f"turn {i} " + "x" * 500, think=self.says("y" * 800))
        fat = {f"k{i}": {"value": "v" * 400, "kind": "explicit",
                         "source": "s", "ts": "t"} for i in range(30)}
        with mock.patch.object(memory, "_load", return_value=fat):
            converse.answer("read a.md and b.md, " + "q" * 3_000,
                            think=self.checked())
        self.assertLessEqual(len(self.seen["prompt"]), converse.MAX_PROMPT_CHARS)

    def test_the_budget_leaves_room_for_the_context_floor(self):
        self.assertGreater(
            converse.MAX_PROMPT_CHARS,
            converse.MAX_QUESTION_CHARS + converse.MAX_ATTACHED_CHARS
            + converse.MIN_CONTEXT_CHARS + converse.SECTION_OVERHEAD,
            "the worst case must fit without relying on the belt-and-braces cut")


class TheContextIsCutBySENSENotByTheByte(ConverseCase):
    def test_a_halt_survives_a_crowded_context(self):
        """What gets squeezed out by a spreadsheet must never be "she is
        stopped". Slicing the JSON string dropped whatever happened to be
        last, which — once memory and the calendar joined — was exactly
        that."""
        from aletheia import memory
        policy.halt("I stopped her", via="test")
        fat = {f"k{i}": {"value": "v" * 400, "kind": "explicit",
                         "source": "s", "ts": "t"} for i in range(40)}
        with mock.patch.object(memory, "_load", return_value=fat):
            converse.answer("why is nothing happening?", think=self.says())
        self.assertIn("halted", self.seen["prompt"])

    def test_what_was_dropped_is_said_not_silently_missing(self):
        from aletheia import memory
        fat = {f"k{i}": {"value": "v" * 400, "kind": "explicit",
                         "source": "s", "ts": "t"} for i in range(40)}
        with mock.patch.object(memory, "_load", return_value=fat):
            converse.answer("hello", think=self.says())
        self.assertIn("context_trimmed", self.seen["prompt"])

    def test_the_context_is_always_valid_json(self):
        """A truncated object that stops mid-key is worse than a smaller one."""
        big = {"now": "t", "situation": {"a": "x" * 9_000, "b": "y" * 9_000},
               "recent_exchanges": [{"you": "z" * 9_000, "her": "w"}]}
        json.loads(converse._fit(big, 2_000))


class ThePlannerKnowsAnsweringIsAnOption(ConverseCase):
    """The whole conversational half was UNREACHABLE.

    `brain.ALLOWED_INTENTS` has always contained "answer" and
    `intents.propose` has routed it to `converse` since this morning — but
    the planner's own system prompt never told the model that returning
    intent "answer" was allowed. It documented plans, gaps, manual steps
    and clarify, so a question with no matching command came back as one of
    those: most often `clarify`, which returns BEFORE converse is reached.
    A capability nothing can select is not a capability.
    """

    def test_the_prompt_says_answering_is_a_valid_reply(self):
        from aletheia import planner
        self.assertIn('"intent": "answer"', planner.PROMPT_HEADER)

    def test_it_says_a_question_is_not_a_missing_capability(self):
        from aletheia import planner
        flat = " ".join(planner.PROMPT_HEADER.split())
        self.assertIn("not a missing capability", flat)
        self.assertIn("never for a question", flat.lower())

    def test_research_is_still_the_route_for_current_information(self):
        """A question about the state of the world today must not collapse
        into an offline opinion — and the rule is about the ANSWER, not the
        phrasing, so it does not have to say "look into"."""
        from aletheia import planner
        flat = " ".join(planner.PROMPT_HEADER.split())
        self.assertIn("RESEARCH kind", flat)
        self.assertIn("changes with the day", flat)

    def test_the_intent_it_names_is_one_the_validator_accepts(self):
        from aletheia import brain
        brain.validate_output({"intent": "answer", "summary": "why the tides?",
                               "steps": [], "required_capabilities": [],
                               "confidence": 0.9})

    def test_such_a_plan_routes_to_converse_not_to_a_summary(self):
        """End to end through the real planner, with only the model faked."""
        from aletheia import intents, planner
        plan = planner.Plan(
            request="why are there tides?", summary="why are there tides?",
            intent="answer", steps=[], provider="test", degraded=None)
        with mock.patch.object(planner, "compile", return_value=plan), \
             mock.patch.object(converse, "answer",
                               return_value={"answer": "The moon pulls."}):
            record = intents.propose("why are there tides?", quote="he asked")
        self.assertEqual(intents.spoken(record), "The moon pulls.")


class DoThatMeansTheThingSheJustSaid(ConverseCase):
    """The most common follow-up there is, and the planner had no path to
    it. He asks a question, she answers, he says "do that" — and the planner
    received the words "do that" with no conversation anywhere in its
    context, so it asked what "that" meant. He had just said."""

    def test_the_thread_is_readable_by_anything_that_needs_a_referent(self):
        converse.answer("what should I do about the trader?",
                        think=self.says("Pause it and look at the log."))
        recent = converse.recent()
        self.assertEqual(len(recent), 1)
        self.assertIn("trader", recent[0]["he_asked"])
        self.assertIn("Pause it", recent[0]["she_answered"])

    def test_it_is_short_because_it_costs_a_planning_prompt(self):
        for i in range(10):
            converse.answer("q" * 900, think=self.says("a" * 900))
        recent = converse.recent()
        self.assertLessEqual(len(recent), 3)
        self.assertLessEqual(max(len(t["she_answered"]) for t in recent), 240)

    def test_the_planner_context_carries_it(self):
        from aletheia import situational
        converse.answer("which backup should I use?",
                        think=self.says("Backblaze, then a local copy."))
        snap = situational.snapshot()
        self.assertTrue(snap["recent_conversation"])
        self.assertIn("Backblaze",
                      snap["recent_conversation"][-1]["she_answered"])

    def test_the_planner_is_told_what_to_do_with_it(self):
        from aletheia import planner
        flat = " ".join(planner.PROMPT_HEADER.split())
        self.assertIn("recent_conversation", flat)
        self.assertIn("he has just said", flat)

    def test_it_is_declared_untrusted_like_everything_else(self):
        """Half of it is her own model output, which may be quoting a page."""
        from aletheia import situational
        snap = situational.snapshot()
        self.assertIn("never instructions", snap["trust_boundary"])

    def test_a_broken_thread_does_not_break_planning(self):
        from aletheia import situational
        with mock.patch.object(converse, "recent", side_effect=OSError("gone")):
            self.assertEqual(situational.snapshot()["recent_conversation"], [])


class TwoQuestionsAtOnceLoseNothing(ConverseCase):
    """The Core is a ThreadingHTTPServer and its beat runs on another
    thread, so the phone and the room really can ask at the same moment.
    Remembering a turn is read-modify-write on one small file."""

    def test_concurrent_answers_all_reach_the_thread(self):
        import threading
        done = []

        def ask(i):
            converse.answer(f"question {i}", think=self.says(f"answer {i}"))
            done.append(i)
        workers = [threading.Thread(target=ask, args=(i,)) for i in range(8)]
        for w in workers:
            w.start()
        for w in workers:
            w.join()
        turns = json.loads(converse.THREAD_PATH.read_text())["turns"]
        self.assertEqual(len(done), 8)
        self.assertEqual(len(turns), 8, "a lost race is a lost exchange")


if __name__ == "__main__":
    unittest.main()
