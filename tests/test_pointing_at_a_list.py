"""She read them out in order and then could not count.

    > what are my tasks
      2 things on your list: call the dentist and call the plumber.
    > mark the first one done
      Nothing open matching 'first'.

"The first one" is how anybody refers to a list somebody has just read
them. The matcher was searching task DESCRIPTIONS for the word "first",
while the machinery to resolve exactly this already existed one module
over for approvals - so the table now lives in `speech` and both sides
read the same one.
"""
from __future__ import annotations

import unittest
from unittest import mock

from aletheia import intercom, speech, voice


class OrdinalsAreOneTableCase(unittest.TestCase):
    def test_voice_and_speech_share_it(self):
        """Two copies of a table like this drift."""
        self.assertIs(voice.ORDINALS, speech.ORDINALS)

    def test_the_words_he_actually_uses(self):
        for phrase, index in (("first", 0), ("the first", 0),
                              ("the first one", 0), ("second", 1),
                              ("third", 2), ("last", -1),
                              ("the last one", -1)):
            with self.subTest(phrase=phrase):
                self.assertEqual(speech.ordinal_index(phrase), index)

    def test_a_description_is_not_a_count(self):
        """"The first bank one" describes a task; it does not count to it."""
        for phrase in ("the first bank one", "passport", "call the dentist",
                       "the one about my passport", ""):
            with self.subTest(phrase=phrase):
                self.assertIsNone(speech.ordinal_index(phrase))


class PointingAtATaskCase(unittest.TestCase):
    TASKS = [
        {"id": "t1", "description": "call the dentist", "status": "OPEN"},
        {"id": "t2", "description": "call the plumber", "status": "OPEN"},
        {"id": "t3", "description": "renew my passport", "status": "OPEN"},
    ]

    def _find(self, which):
        with mock.patch.object(intercom, "_open_tasks", return_value=self.TASKS):
            return intercom._one_task(which)

    def test_the_first_one_is_the_one_she_said_first(self):
        found, why = self._find("the first one")
        self.assertEqual(found["id"], "t1", why)

    def test_the_last_one(self):
        found, why = self._find("the last one")
        self.assertEqual(found["id"], "t3", why)

    def test_counting_past_the_end_says_how_many_there_are(self):
        found, why = self._find("the fourth one")
        self.assertIsNone(found)
        self.assertIn("3", why)
        self.assertNotIn("None", why)

    def test_his_words_still_find_it(self):
        """The ordinal path must not have replaced the word matcher."""
        found, _ = self._find("the passport one")
        self.assertEqual(found["id"], "t3")

    def test_an_unknown_phrase_still_says_so(self):
        found, why = self._find("the helicopter one")
        self.assertIsNone(found)
        self.assertIn("Nothing open", why)

    def test_the_refusal_is_sayable(self):
        """It is read out in a room, so no identifiers and no brackets."""
        _found, why = self._find("the ninth one")
        self.assertNotIn("[", why)
        self.assertNotIn("{", why)
        self.assertTrue(why.endswith("."), why)


class PointingWhenThereIsOneCase(unittest.TestCase):
    def test_singular_reads_as_singular(self):
        one = [{"id": "t1", "description": "call the dentist", "status": "OPEN"}]
        with mock.patch.object(intercom, "_open_tasks", return_value=one):
            _found, why = intercom._one_task("the fourth one")
        self.assertIn("is only 1 thing", why)
        self.assertNotIn("are only", why)


class CancellingHerThingsIsNotCancellingAServiceCase(unittest.TestCase):
    """A reminder was compiling a SUBSCRIPTION cancellation.

        > cancel the first reminder   -> subscription_cancel
        > cancel my 3pm reminder      -> subscription_cancel

    Caught in a rehearsal, where the world-touching tier refused it. Live
    it would have gone looking for a real service to cancel because he
    asked about an alarm.

    The guard existed and already listed "reminder" - it used `re.match`,
    which anchors at the START of the phrase, and "the first reminder"
    begins with "first". Every case here is a safety test.
    """

    def _kind(self, sentence):
        return ((voice.interpret(sentence) or {}).get("command") or {}).get("kind")

    def test_nothing_of_hers_reaches_the_subscription_verb(self):
        for sentence in ("cancel the first reminder", "cancel my 3pm reminder",
                         "cancel the reminder", "cancel my 9am alarm",
                         "cancel the dentist task", "cancel my meeting",
                         "cancel my 2pm appointment", "cancel the timer",
                         "cancel that note"):
            with self.subTest(sentence=sentence):
                self.assertNotEqual(self._kind(sentence), "subscription_cancel",
                                    sentence)

    def test_the_word_can_sit_anywhere_in_the_phrase(self):
        """The bug exactly: anchored at the start, it missed all of these."""
        for sentence in ("cancel the first reminder", "cancel my 3pm reminder",
                         "cancel my very last alarm"):
            with self.subTest(sentence=sentence):
                self.assertNotEqual(self._kind(sentence), "subscription_cancel")

    def test_pointing_by_position_is_not_a_service_name(self):
        for sentence in ("cancel the first one", "cancel the last one"):
            with self.subTest(sentence=sentence):
                self.assertNotEqual(self._kind(sentence), "subscription_cancel")

    def test_a_real_subscription_still_takes_the_fast_path(self):
        """The guard must not have swallowed what it is for."""
        for sentence in ("cancel my netflix subscription",
                         "cancel my gym membership",
                         "cancel my spotify",
                         "cancel my hulu plan",
                         "cancel my new york times"):
            with self.subTest(sentence=sentence):
                self.assertEqual(self._kind(sentence), "subscription_cancel",
                                 sentence)


if __name__ == "__main__":
    unittest.main()
