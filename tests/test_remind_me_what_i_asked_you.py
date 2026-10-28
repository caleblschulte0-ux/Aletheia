""""Remind me what I asked you yesterday" is the same question as "what did
I ask you yesterday" (2026-10-28: to the planner, and "what have I asked
you to do" to a model). Asking it is never one of the things he asked."""
import unittest

from aletheia import quick


class SameQuestion(unittest.TestCase):
    def test_it_finds_the_day(self):
        for said, day in (("remind me what I asked you yesterday", "yesterday"),
                          ("can you tell me what i asked you to do today", "today"),
                          ("what have I asked you to do", "do"),
                          ("what did I ask you to do so far today", "so far today")):
            self.assertEqual(quick.match(said), ("asked_on", day), said)

    def test_a_reminder_is_still_a_reminder(self):
        self.assertNotEqual((quick.match("remind me to call mom") or ("",))[0], "asked_on")

    def test_asking_it_is_talk_about_the_talk(self):
        for said in ("remind me what I asked you today", "what have I asked you to do", "what did I ask you yesterday"):
            self.assertTrue(quick._about_the_talk(said), said)
        self.assertFalse(quick._about_the_talk("add a task to call the bank"))


if __name__ == "__main__":
    unittest.main()
