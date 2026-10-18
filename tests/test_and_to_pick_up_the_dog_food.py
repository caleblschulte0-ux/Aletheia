""""Remind me tomorrow to call the vet", "and to pick up the dog food" went to
the planner, and "what are my reminders tomorrow" to a model (2026-10-18,
every model off)."""
import unittest
from unittest import mock

from aletheia import quick, voice


class TheSameTimeTheNewWords(unittest.TestCase):
    def test_and_to(self):
        just = {"at": "2026-10-19T14:00:00+00:00", "command": {"kind": "remind_at", "text": "call the vet"}}
        with mock.patch.object(voice, "_the_reminder_just_set", return_value=just):
            for said in ("and to pick up the dog food", "also to pick up the dog food", "oh and to pick up the dog food too"):
                with self.subTest(said=said):
                    self.assertEqual(voice.interpret(said)["command"],
                                     {"kind": "remind_at", "at": just["at"], "text": "pick up the dog food"})


class RemindersTomorrow(unittest.TestCase):
    def test_without_for(self):
        for said in ("what are my reminders tomorrow", "what's my reminder tomorrow", "my reminders monday"):
            with self.subTest(said=said):
                self.assertIn("reminders_on", [name for name, rx in quick.PATTERNS if rx.search(quick._tidy(said))])


if __name__ == "__main__":
    unittest.main()
