"""Three defects from one twenty-minute conversation with her.

Every one was correct data in a sentence that failed him, which is the
class of thing a unit test cannot find on its own - the author already
believed the code was right. Found by talking:

    > are you using my chatgpt
      I'm not using your ChatGPT account. Say use ChatGPT and I'll ask...
    > what did you do today
      1 thing today. Most recent: I'm not using your ChatGPT account.
      Say use ChatGPT and I'll ask it for a second opinion w

She answered a question, reported ANSWERING IT as her work for the day,
and cut the sentence in the middle of a word. And asked what she could
not do, she said she had no local models and no ChatGPT fallback while
both were running.
"""
from __future__ import annotations

import unittest
from unittest import mock

from aletheia import core, intercom, journal, quick, speech


class TalkingIsNotDoingCase(unittest.TestCase):
    """A read-only answer is an event. Doing something is an action.

    CLAUDE.md already names this failure once - `converse` journalling its
    own replies until she listed them back at him - and it returned by a
    different route: `run_command` journalled EVERY kind as an action.
    """

    def _kind_journalled(self, kind: str) -> str:
        seen = {}

        def spy(entry_kind, source, detail, **kw):
            seen["kind"] = entry_kind

        with mock.patch.object(journal, "append", spy), \
             mock.patch.object(intercom, "execute_command", return_value="ok"), \
             mock.patch.object(intercom, "validate_kind_args", return_value=[]), \
             mock.patch("aletheia.policy.halted", return_value=False):
            core.run_command({"kind": kind}, {})
        return seen.get("kind")

    def test_answering_a_question_is_not_something_she_did(self):
        for kind in ("chatgpt", "mic", "brief", "tasks"):
            with self.subTest(kind=kind):
                self.assertEqual(self._kind_journalled(kind), "event")

    def test_doing_something_still_records_an_action(self):
        for kind in ("task_new", "shopping_add", "remind_at"):
            with self.subTest(kind=kind):
                self.assertEqual(self._kind_journalled(kind), "action")

    def test_making_something_counts_even_without_authority(self):
        """`tier` was the wrong predicate and this is why.

        Four READ_ONLY kinds need no authority and still produce
        something he wants back - a remembered note, a picture, a
        document. Journalling those as mere events would hide real work
        from her own account of the day.
        """
        for kind in ("note", "screenshot", "browse_shot", "research"):
            with self.subTest(kind=kind):
                self.assertEqual(intercom.tier(kind), intercom.TIER_READ)
                self.assertFalse(intercom.only_answers(kind))
                self.assertEqual(self._kind_journalled(kind), "action")

    def test_an_unknown_kind_counts_as_work(self):
        """The safe default: missing real work is the worse error."""
        self.assertFalse(intercom.only_answers("some_verb_added_tomorrow"))

    def test_everything_that_only_answers_is_read_only(self):
        for kind in intercom.KIND_ARGS:
            if intercom.only_answers(kind):
                with self.subTest(kind=kind):
                    self.assertEqual(intercom.tier(kind), intercom.TIER_READ)


class NotInTheMiddleOfAWordCase(unittest.TestCase):
    def test_a_long_line_is_cut_at_a_word(self):
        line = ("I'm not using your ChatGPT account. Say use ChatGPT and I'll "
                "ask it for a second opinion when it's worth one.")
        out = quick._shortened(line)
        self.assertTrue(out.endswith("..."))
        self.assertFalse(out.rstrip(".").endswith(" w"),
                         "cut in the middle of a word")
        self.assertIn(out.rstrip(".").rsplit(" ", 1)[-1], line.split())

    def test_a_short_line_is_left_exactly_alone(self):
        self.assertEqual(quick._shortened("Added a task: call the dentist"),
                         "Added a task: call the dentist")

    def test_the_cut_says_that_it_was_cut(self):
        self.assertTrue(quick._shortened("x " * 200).endswith("..."))


class ALineBreakIsNotAPauseCase(unittest.TestCase):
    """A list down the page is a run-on in a room.

    Four capabilities on four bare lines came out as one breath ending
    "...never act on its own And 17 more are experimental" - nothing in
    the text told the voice where to stop.
    """

    def test_each_line_becomes_its_own_sentence(self):
        said = speech.sentences_not_lines(
            "Four things are waiting on setup:\n"
            "Relaying commands to ChatGPT\n"
            "Controlling lights and scenes")
        self.assertNotIn("\n", said)
        self.assertIn("Relaying commands to ChatGPT.", said)
        self.assertIn("Controlling lights and scenes.", said)

    def test_punctuation_it_already_had_is_kept(self):
        said = speech.sentences_not_lines("First one.\nSecond one!\nThird one?")
        self.assertNotIn("..", said)
        self.assertNotIn("!.", said)
        self.assertNotIn("?.", said)

    def test_a_single_line_is_untouched(self):
        self.assertEqual(speech.sentences_not_lines("Just one sentence."),
                         "Just one sentence.")

    def test_blank_lines_do_not_become_empty_sentences(self):
        self.assertEqual(speech.sentences_not_lines("A\n\n\nB"), "A. B.")

    def test_the_speech_door_applies_it(self):
        """It has to be at the ONE door, or a caller will miss it."""
        said = speech.spoken_prose("One thing\nAnother thing")
        self.assertNotIn("\n", said)

    def test_nothing_is_lost_from_the_middle_of_a_line(self):
        """Guessing sentence boundaries INSIDE a line would rewrite him."""
        line = "never act on its own And 17 more are experimental"
        self.assertIn(line, speech.sentences_not_lines(line))


class HisWordsSaidBackByHerCase(unittest.TestCase):
    """"About my resume", out of her mouth, means HER resume.

        > make me a word document about my resume
          I can make that document about MY resume... save it as
          MY-RESUME.docx.
    """

    def test_his_first_person_becomes_second(self):
        self.assertEqual(speech.as_she_says_it("my resume"), "your resume")
        self.assertEqual(speech.as_she_says_it("expenses I paid"),
                         "expenses you paid")

    def test_whole_words_only(self):
        """"myopic" must not become "youropic"."""
        self.assertEqual(speech.as_she_says_it("myopic mice"), "myopic mice")

    def test_our_is_left_alone(self):
        """"Our repos" means both of them; "your repos" is a small lie."""
        self.assertEqual(speech.as_she_says_it("our repos"), "our repos")

    def test_a_file_is_named_for_what_it_is(self):
        """Not for whose it is: "my resume" is resume.docx."""
        self.assertEqual(speech.file_stem("my resume"), "resume")
        self.assertEqual(speech.file_stem("the quarterly numbers"),
                         "quarterly-numbers")
        self.assertEqual(speech.file_stem("my  Q3   Expenses!"), "q3-expenses")

    def test_the_offer_says_it_his_way_round(self):
        from aletheia import voice
        said = (voice.interpret("make me a word document about my resume")
                or {}).get("say") or ""
        self.assertIn("your resume", said)
        self.assertIn("resume.docx", said)
        self.assertNotIn("my resume", said)
        self.assertNotIn("my-resume", said)


class DroppingTheSubjectCase(unittest.TestCase):
    """"Never mind" is not a question about the approvals queue.

        > never mind
          Nothing is waiting for approval.

    Answering a different question than the one asked is the failure he
    cannot detect. "Cancel that" IS about the pending thing, so there the
    same sentence is a real answer.
    """

    def _said(self, sentence):
        from aletheia import voice
        with mock.patch("aletheia.policy.all_approvals", return_value=[]):
            return (voice.interpret(sentence) or {}).get("say") or ""

    def test_dropping_it_is_acknowledged(self):
        for sentence in ("never mind", "nevermind", "forget it",
                         "forget that", "call it off", "don't do it"):
            with self.subTest(sentence=sentence):
                said = self._said(sentence).lower()
                # Both truths: the dismissal is taken, AND he is told
                # there was nothing there - so he cannot walk away
                # believing he just cancelled something.
                self.assertIn("okay", said, sentence)
                self.assertIn("nothing was waiting", said, sentence)
                self.assertNotIn("waiting for approval", said, sentence)

    def test_asking_to_cancel_still_reports_the_queue(self):
        for sentence in ("cancel that", "deny that", "no to that", "drop it"):
            with self.subTest(sentence=sentence):
                self.assertIn("Nothing is waiting", self._said(sentence))

    def test_both_still_deny_a_real_pending_thing(self):
        from aletheia import voice
        pending = [{"id": "intent-abc", "state": "PENDING",
                    "requested_action": "run 1 step(s): note",
                    "reason": "operator said: x", "consequence": "a note"}]
        for sentence in ("never mind", "cancel that"):
            with self.subTest(sentence=sentence):
                with mock.patch("aletheia.policy.all_approvals",
                                return_value=pending):
                    decided = voice.interpret(sentence) or {}
                command = decided.get("command") or {}
                self.assertEqual(command.get("kind"), "deny", sentence)
                self.assertEqual(command.get("id"), "intent-abc")


if __name__ == "__main__":
    unittest.main()
