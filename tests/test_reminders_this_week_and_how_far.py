""""How many reminders do I have this week" and "how far until my oil change"
went to a model (2026-10-18, every model off); "what reminders do I have this
week" and "how many miles until my oil change" already had answers."""
import unittest

from aletheia import quick


def _names(said):
    return [name for name, rx in quick.PATTERNS if rx.search(quick._tidy(said))]


class TheSameQuestionsSaidOtherWays(unittest.TestCase):
    def test_reminders_this_week(self):
        for said in ("how many reminders do i have this week", "my reminders this week",
                     "what are my reminders for next week"):
            with self.subTest(said=said):
                self.assertIn("reminders_week", _names(said))

    def test_how_far_until_the_oil_change(self):
        for said in ("how far until my oil change", "how much further till my next oil change"):
            with self.subTest(said=said):
                self.assertIn("miles_until", _names(said))

    def test_how_far_until_a_meeting_is_not_mileage(self):
        self.assertNotIn("miles_until", _names("how far until my meeting"))


if __name__ == "__main__":
    unittest.main()
