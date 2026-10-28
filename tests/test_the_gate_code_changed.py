""""The gate code changed to 7777" is the same change as "change the gate code to".

2026-10-28, talking to her with the models off:

    > note that the gate code is 4412
    > the gate code changed to 7777
      I could not plan that: nothing could think just now ...
    > the gate code is now 1234
      Noted.                    (and the old code kept beside it)
"""
import unittest
from unittest import mock

from aletheia import quick, voice

OLD = [{"text": "the gate code is 4412", "ts": "2026-10-28T14:00:00+00:00"}]


class ChangedTo(unittest.TestCase):
    def test_the_old_one_is_let_go(self):
        with mock.patch.object(quick, "_notes", return_value=OLD):
            for said, val in (("the gate code changed to 7777", "7777"), ("the gate code is now 1234", "1234"),
                              ("the gate code has changed to 2468", "2468")):
                cmd = voice.interpret(said)["command"]
                self.assertEqual(cmd, {"kind": "note", "text": f"the gate code is {val}", "replaces": "the gate code is 4412"}, said)

    def test_with_nothing_to_replace_it_is_a_note(self):
        with mock.patch.object(quick, "_notes", return_value=[]):
            self.assertEqual(voice.interpret("the gate code changed to 7777")["command"],
                             {"kind": "note", "text": "the gate code is 7777"})

    def test_a_password_is_still_refused(self):
        self.assertIsNone(voice.interpret("the wifi password changed to abc123")["command"])

    def test_her_own_things_are_not_notes(self):
        for said in ("my alarm changed to 7", "my reminder is now at 5"):
            self.assertNotEqual((voice.interpret(said)["command"] or {}).get("kind"), "note", said)


if __name__ == "__main__":
    unittest.main()
