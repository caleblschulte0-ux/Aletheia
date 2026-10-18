""""Remind me in 30 minutes to stretch and in an hour to drink water" and
"remind me tomorrow to call mom and on Friday to pay rent" each set ONE
reminder with the second half in its words (2026-10-18, every model off)."""
import unittest

from aletheia import voice


class TwoWaits(unittest.TestCase):
    def test_each_wait_keeps_its_own_thing(self):
        self.assertEqual(voice.two_asks("remind me in 30 minutes to stretch and in an hour to drink water"),
                         ["remind me in 30 minutes to stretch", "remind me in an hour to drink water"])
        self.assertEqual(voice.two_asks("remind me in 10 minutes to check the oven and in half an hour to take it out"),
                         ["remind me in 10 minutes to check the oven", "remind me in half an hour to take it out"])


class TwoDays(unittest.TestCase):
    def test_each_day_keeps_its_own_thing(self):
        self.assertEqual(voice.two_asks("remind me tomorrow to call mom and on friday to pay rent"),
                         ["remind me tomorrow to call mom", "remind me friday to pay rent"])

    def test_one_day_two_things_is_untouched(self):
        self.assertIsNone(voice.two_asks("remind me tomorrow to call mom and dad"))


if __name__ == "__main__":
    unittest.main()
