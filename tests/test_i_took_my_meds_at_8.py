"""A thing he did, with the time he did it.

2026-10-28, talking to her with the models off:

    > I took my meds at 8          (to the planner)
    > I fed the dog at 6           (to the planner)
    > when did I feed the dog      (after "I fed the dog" said at 7:31)
      You told me you fed the dog at 6 - that was today at 7:31 am.
"""
import datetime as dt
import unittest
from unittest import mock

from aletheia import quick, voice

NOW = dt.datetime.now(dt.timezone.utc).isoformat()


class WithTheTime(unittest.TestCase):
    def test_he_can_say_it(self):
        for said, kept in (("i took my meds at 8", "took my meds at 8"),
                           ("i took my pills at 8 am", "took my pills at 8 am"),
                           ("i took my meds", "took my meds"),
                           ("i fed the dog at 6", "i fed the dog at 6"),
                           ("i took the trash out at 9", "I took out the trash at 9"),
                           ("i watered the plants at 7:30 am", "i watered the plants at 7:30 am")):
            self.assertEqual(voice.interpret(said)["command"], {"kind": "note", "text": kept}, said)

    def test_the_time_he_said_is_the_time(self):
        with mock.patch.object(quick, "_notes", return_value=[{"text": "took my meds at 8", "ts": NOW}]):
            self.assertEqual(quick.answer("did i take my meds today"), "Yes - you told me you took your meds at 8 today.")
        with mock.patch.object(quick, "_notes", return_value=[{"text": "i fed the dog at 6", "ts": NOW}]):
            self.assertEqual(quick.answer("when did i feed the dog"), "You told me you fed the dog at 6 today.")
            self.assertEqual(quick.answer("did i feed the dog today"), "Yes - you told me you fed the dog at 6 today.")


if __name__ == "__main__":
    unittest.main()
