""""Remind me Friday after work to change the oil" went to the planner, and
"set a reminder for the 1st to pay rent" asked when to remind him about
"the 1st to pay rent" (2026-10-22).
"""
import unittest

from aletheia import voice


class FridayAfterWork(unittest.TestCase):
    def test_a_day_and_after_work_is_that_day_at_half_past_five(self):
        got = voice.interpret("remind me friday after work to change the oil")["command"]
        self.assertEqual(got["kind"], "remind_at")
        self.assertIn("T17:30:00", got["at"])
        self.assertEqual(got["text"], "change the oil")

    def test_after_lunch_on_a_day_is_one(self):
        got = voice.interpret("remind me saturday after lunch to mow")["command"]
        self.assertIn("T13:00:00", got["at"])
        self.assertEqual(got["text"], "mow")

    def test_a_reminder_for_the_first_is_on_the_first(self):
        got = voice.interpret("set a reminder for the 1st to pay rent")["command"]
        self.assertEqual(got["kind"], "remind_at")
        self.assertRegex(got["at"], r"-\d\d-01T")
        self.assertEqual(got["text"], "pay rent")


if __name__ == "__main__":
    unittest.main()
