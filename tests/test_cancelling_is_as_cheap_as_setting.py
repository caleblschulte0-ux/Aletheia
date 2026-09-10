"""Setting one was free. Cancelling it cost four seconds and permission.

    > remind me to call the dentist at 3     [0.1s] I'll remind you today
                                             at 3 pm: call the dentist.
    > cancel the dentist reminder            [4.1s] 1 step ready - Cancel
                                             the dentist reminder for
                                             today at 3 pm. Say approve
                                             to run it.

`reminder_off` existed the whole time. The deterministic pattern required
the word "reminder" BEFORE the subject — "cancel the reminder about the
dentist" — and he used the other word order, which is the ordinary one.

So the planner compiled it, four seconds later, and then asked permission
to undo something she had done a moment earlier for nothing. Same shape
as the shopping list an hour before: the writer is instant and the reader
or the un-doer is not.

Two more from driving the same loop:

- "CANCEL THE FIRST REMINDER" is how a person names a thing in a list
  they were just read. `_one_task` already resolves an ordinal; this
  did not, and answered "No reminder matching 'first'".
- "No reminder matching 'plumber'." is true, becomes two sentences jammed
  once the caller prefixes "I can't do that:", and leaves him with
  nothing to say next. What he DOES have is the answer to what he asked -
  an empty answer still proves the store.
"""
from __future__ import annotations

import unittest

from aletheia import voice


class BothWordOrdersCase(unittest.TestCase):
    def _cmd(self, said):
        return (voice._interpret(said) or {}).get("command") or {}

    def test_the_word_order_he_used(self):
        for said, which in (("cancel the dentist reminder", "dentist"),
                            ("delete the bins reminder", "bins"),
                            ("remove the 3pm reminder", "3pm"),
                            ("stop the dentist reminder", "dentist"),
                            ("turn off my morning reminder", "morning")):
            with self.subTest(said=said):
                got = self._cmd(said)
                self.assertEqual(got.get("kind"), "reminder_off", said)
                self.assertEqual(got.get("which"), which)

    def test_the_word_order_that_already_worked(self):
        got = self._cmd("cancel the reminder about the dentist")
        self.assertEqual(got.get("kind"), "reminder_off")
        self.assertEqual(got.get("which"), "the dentist")

    def test_stop_reminding_me_still_works(self):
        got = self._cmd("stop reminding me about the bins")
        self.assertEqual(got.get("kind"), "reminder_off")

    def test_it_does_not_swallow_a_subscription(self):
        """"Cancel my gym membership" must still reach the thing that
        really cancels things. Anchored to the whole sentence and ending
        in the word itself, so it cannot."""
        for said, kind in (("cancel my gym membership", "subscription_cancel"),
                           ("cancel my netflix subscription",
                            "subscription_cancel")):
            with self.subTest(said=said):
                self.assertEqual(self._cmd(said).get("kind"), kind, said)

    def test_it_does_not_swallow_a_pending_approval(self):
        """"Cancel that" denies what is waiting; it is not a reminder."""
        self.assertNotEqual(self._cmd("cancel that").get("kind"),
                            "reminder_off")


class NamingItByPositionCase(unittest.TestCase):
    """"The first one", after she has just read them out in that order."""

    def _one(self, which, texts):
        from unittest import mock
        from aletheia import intercom
        rows = [{"id": f"r{i}", "command": {"text": t}}
                for i, t in enumerate(texts)]
        with mock.patch.object(intercom, "_reminder_schedules", lambda: rows), \
             mock.patch.object(intercom, "_reminder_words",
                               lambda r: r["command"]["text"]):
            return intercom._one_reminder(which)

    def test_an_ordinal_picks_by_position(self):
        found, why = self._one("first", ["call the dentist", "take the bins out"])
        self.assertIsNotNone(found, why)
        self.assertEqual(found["id"], "r0")
        found, _ = self._one("second", ["call the dentist", "take the bins out"])
        self.assertEqual(found["id"], "r1")

    def test_an_ordinal_past_the_end_says_how_many(self):
        found, why = self._one("fourth", ["call the dentist"])
        self.assertIsNone(found)
        self.assertIn("only have 1 reminder", why)

    def test_words_still_beat_nothing(self):
        found, _ = self._one("dentist", ["call the dentist", "take the bins out"])
        self.assertEqual(found["id"], "r0")

    def test_a_reminder_containing_the_word_first_is_not_hijacked(self):
        """Checked before the text match, so a sentence that is plainly
        counting cannot be claimed by a reminder that happens to say it."""
        found, _ = self._one("first", ["do the first draft", "call the dentist"])
        self.assertEqual(found["id"], "r0", "position, not the word")


class AMissIsStillAnAnswerCase(unittest.TestCase):
    def _why(self, which, texts):
        from unittest import mock
        from aletheia import intercom
        rows = [{"id": f"r{i}", "command": {"text": t}}
                for i, t in enumerate(texts)]
        with mock.patch.object(intercom, "_reminder_schedules", lambda: rows), \
             mock.patch.object(intercom, "_reminder_words",
                               lambda r: r["command"]["text"]):
            return intercom._one_reminder(which)[1]

    def test_it_says_what_he_does_have(self):
        why = self._why("plumber", ["call the dentist"])
        self.assertIn("plumber", why)
        self.assertIn("call the dentist", why)

    def test_it_is_grammatical_for_either_word_order(self):
        """"no reminder about plumber" / "no the dentist reminder" is
        wrong one way or the other; this frame takes both."""
        for which in ("plumber", "the accountant"):
            with self.subTest(which=which):
                self.assertIn(f"is about {which}.",
                              self._why(which, ["call the dentist"]))

    def test_an_empty_store_says_it_is_empty(self):
        """Which is a different situation, and he needs to know which."""
        self.assertIn("no reminders set", self._why("plumber", []))


class TheRefusalReadsAsOneSentenceCase(unittest.TestCase):
    def test_a_reason_that_is_already_a_sentence_keeps_no_preamble(self):
        said = voice.spoken_reply("reminder_off", "refused",
                                  "None of your reminders is about plumber. "
                                  "The one you have is call the dentist.")
        self.assertFalse(said.startswith("I can't do that"))
        self.assertTrue(said.startswith("None of your reminders"))

    def test_a_fragment_still_gets_one(self):
        """Most refusals are still fragments and need the frame."""
        said = voice.spoken_reply("travel_time", "refused",
                                  "no place matches 'the airport'")
        self.assertTrue(said.startswith("I can't do that"))


if __name__ == "__main__":
    unittest.main()
