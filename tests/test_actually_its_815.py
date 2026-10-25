""""My kids' school starts at 8:10", then "actually 8:15", and "Joe's number
is 605 555 1234", then "actually it's 605 555 4321", went to the planner
(2026-10-25) and the old value kept answering. A new time or number said
straight after is the thing he just told her, changed."""
import unittest
from unittest import mock

from aletheia import voice


def _after(last):
    return mock.patch.object(voice, "_recent_ask_of",
                             lambda kind, needs, turns=4: last if last.get("kind") == kind else {})


class ANewTimeOrNumber(unittest.TestCase):
    def test_the_time_in_the_note_is_changed(self):
        for sentence in ("actually 8:15", "no, it's 8:15", "sorry, make it 8:15", "wait, 8:15 instead"):
            with _after({"kind": "note", "text": "my kids' school starts at 8:10"}):
                got = voice._interpret(sentence)
            self.assertEqual(got["command"], {"kind": "note", "text": "my kids' school starts at 8:15"}, sentence)
            self.assertTrue(got["say"].startswith("Changed it: "), sentence)

    def test_a_note_with_no_time_is_not_changed(self):
        with _after({"kind": "note", "text": "my locker is 42"}):
            got = voice._interpret("actually 8:15")
        self.assertNotIn("Changed it", str(got.get("say") or ""))

    def test_the_number_of_the_contact_he_just_saved_is_changed(self):
        with _after({"kind": "contact_add", "name": "Joe", "phone": "605 555 1234"}):
            got = voice._interpret("actually it's 605 555 4321")
        self.assertEqual(got["command"], {"kind": "contact_add", "name": "Joe", "phone": "605 555 4321"})

    def test_with_nothing_just_saved_a_number_is_not_a_contact(self):
        with _after({}):
            got = voice._interpret("actually it's 605 555 4321")
        self.assertNotEqual((got.get("command") or {}).get("kind"), "contact_add")


if __name__ == "__main__":
    unittest.main()
