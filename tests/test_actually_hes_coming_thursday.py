""""Note that the plumber is coming wednesday", then "never mind, he's coming
thursday" went to the planner, and "actually it's thursday" was kept as a
note of its own (2026-10-25) - so "when is the plumber coming" still said
Wednesday. A new day for the note he just made is that note, changed."""
import unittest
from unittest import mock

from aletheia import voice


class ANewDayForTheNoteHeJustMade(unittest.TestCase):
    def said_after(self, note, sentence):
        last = {"kind": "note", "text": note} if note else {}
        with mock.patch.object(voice, "_recent_ask_of", lambda kind, needs, turns=4: last if kind == "note" else {}):
            return voice._interpret(sentence)

    def test_the_day_in_the_note_is_changed(self):
        for sentence, note in (("never mind, he's coming thursday", "the plumber is coming thursday"),
                               ("actually it's thursday", "the plumber is coming thursday"),
                               ("no, thursday", "the plumber is coming thursday"),
                               ("wait, make it friday", "the plumber is coming friday"),
                               ("sorry, it's tomorrow", "the plumber is coming tomorrow")):
            got = self.said_after("the plumber is coming wednesday", sentence)
            self.assertEqual(got["command"], {"kind": "note", "text": note}, sentence)
            self.assertTrue(got["say"].startswith("Changed it: "), got["say"])

    def test_on_is_kept_where_he_said_it(self):
        got = self.said_after("the plumber is coming on wednesday", "actually it's thursday")
        self.assertEqual(got["command"]["text"], "the plumber is coming on thursday")

    def test_a_note_with_no_day_is_not_changed(self):
        got = self.said_after("my locker is 42", "actually it's thursday")
        self.assertNotEqual((got.get("command") or {}).get("text"), "my locker is 42 thursday")

    def test_with_no_note_just_made_nothing_is_changed(self):
        got = self.said_after(None, "no, thursday")
        self.assertFalse(str((got.get("say") or "")).startswith("Changed it"))

    def test_said_in_full_with_instead_it_is_the_plain_note(self):
        for sentence in ("the plumber is coming thursday now", "the plumber is coming thursday instead"):
            got = self.said_after(None, sentence)
            self.assertEqual(got["command"], {"kind": "note", "text": "the plumber is coming thursday"}, sentence)

    def test_a_reminder_moved_to_another_day_is_still_the_reminders(self):
        with mock.patch.object(voice, "_recent_ask_of", lambda kind, needs, turns=4: {}):
            got = voice._note_with_new_day("no, thursday", "thursday")
        self.assertIsNone(got)


if __name__ == "__main__":
    unittest.main()
