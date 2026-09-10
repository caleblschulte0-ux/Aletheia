"""She denied having an off switch she has.

    > how do i turn you off
      [5.6s] I don't have a built-in shutdown command myself - that's not
      something in my registry as a capability. If I'm running as a
      process on this machine, closing the terminal window or app I'm
      running in, or killing the process (Task Manager, or Ctrl+C in the
      terminal), stops me the same way it would stop any program.

`core.close` is AVAILABLE and its description reads "Close me the way you
close a window - I finish what I am holding, exit cleanly, and stay shut
until you open me again". She sent him to Task Manager instead.

The cause is two words and it is the same one twice:

    "how do i turn you off"  ->  finance.hand_off

because "off" is inside "hand_off". A question about her kill switch
answered by a money capability. And "can you shut down" matched NOTHING,
because "shut down" is two words when a person says it and `_words`
splits on anything non-alphanumeric, so a one-word "shutdown" key is
never reached.

With no capability in its context the model answered from memory, and a
confident answer with no context is indistinguishable from a grounded one
until he checks. CLAUDE.md: *"the question she is asked in the negative
reaches nothing"* - same defect, on the single most important question
anybody can ask this system.

Her ears, which he ruled on personally, were the same:

    > are you listening to me right now
      [9.6s] No. I only see what's in a message when you send it to me -
      I don't have an open mic or a standing audio feed. Whatever you say
      gets converted to text and handed to me at the moment you send it.

Plausible, about a chat model, and not about HIS microphone. `are you
listening` had to match the whole sentence, so the way it is really asked
- with "to me right now" on the end - reached the planner.
"""
from __future__ import annotations

import unittest

from aletheia import capabilities, quick, self_knowledge as sk, voice


class SheKnowsHerOwnOffSwitchCase(unittest.TestCase):
    def _best(self, question):
        found = sk.relevant(question)
        return found[0]["capability"] if found else None

    def test_the_ways_he_would_ask_to_turn_her_off(self):
        for said in ("how do i turn you off", "can you shut down",
                     "how do i close you", "how do i quit",
                     "how do i shut you down", "can i close you"):
            with self.subTest(said=said):
                best = self._best(said)
                self.assertIsNotNone(best, f"{said} reached no capability")
                self.assertTrue(best.startswith(("core", "policy")),
                                f"{said} -> {best}")

    def test_her_kill_switch_is_not_a_money_capability(self):
        """"off" is inside "hand_off"."""
        self.assertNotEqual(self._best("how do i turn you off"),
                            "finance.hand_off")

    def test_the_money_capability_is_still_reachable(self):
        """The fix must not simply move the error."""
        self.assertEqual(self._best("can you hand off a payment"),
                         "finance.hand_off")

    def test_she_says_yes_about_closing(self):
        said = (quick.answer("can you shut down") or "").lower()
        self.assertTrue(said.startswith("yes"), said)
        self.assertIn("close", said)

    def test_the_capability_she_names_really_exists(self):
        """An answer from the registry is only as good as the entry."""
        entry = capabilities.get("core.close")
        self.assertEqual(entry["status"], "AVAILABLE")


class SheKnowsWhetherSheIsListeningCase(unittest.TestCase):
    def _kind(self, said):
        return ((voice._interpret(said) or {}).get("command") or {}).get("kind")

    def test_the_ways_he_would_ask(self):
        for said in ("are you listening", "are you listening to me",
                     "are you listening to me right now", "can you hear me",
                     "can you hear me right now", "is the microphone on",
                     "is the mic off", "are you recording me",
                     "microphone status", "the microphone"):
            with self.subTest(said=said):
                self.assertEqual(self._kind(said), "mic", said)

    def test_it_does_not_swallow_its_neighbours(self):
        """A pattern that takes too much answers a DIFFERENT question."""
        for said in ("are you listening to the radio",
                     "can you hear the difference",
                     "can you hear what i am saying about the meeting"):
            with self.subTest(said=said):
                self.assertNotEqual(self._kind(said), "mic", said)

    def test_the_question_costs_no_round_trip(self):
        """He ruled on the microphone himself. It is answerable always."""
        from aletheia import intercom
        self.assertIn("mic", intercom.KIND_ARGS)

    def test_the_capability_is_findable_by_the_word_he_says(self):
        found = sk.relevant("is the microphone on")
        self.assertTrue(found)
        self.assertTrue(found[0]["capability"].startswith(("voice", "audio")))


class TheSynonymsStayReachableCase(unittest.TestCase):
    def test_two_words_when_he_says_them(self):
        """"shut down" is two words; a "shutdown" key is never reached."""
        self.assertIn("shut", sk.SYNONYMS)
        self.assertIn("close", sk._query_terms("can you shut down"))


if __name__ == "__main__":
    unittest.main()
