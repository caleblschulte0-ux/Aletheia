""""Cancel all my reminders" took the monthly rent reminder with it and said
nothing of the way back (2026-10-16, every model off). They are switched off,
not deleted, so the answer names the one sentence that undoes it."""
import unittest

from aletheia import speech


class TheWayBack(unittest.TestCase):
    def test_several_say_how_to_put_them_back(self):
        said = speech.spoken_receipt("reminder_off", "reminder 2 off — 2 reminders: call mom — tomorrow at 9 am and pay rent — "
                                     "on the 15th of every month at 9 am")
        self.assertTrue(said.startswith("Cancelled 2 reminders: call mom"), said)
        self.assertTrue(said.endswith('Say "put them back" if you didn\'t mean that.'), said)

    def test_one_needs_no_way_back(self):
        said = speech.spoken_receipt("reminder_off", "reminder 1 off — 1 reminder: call mom — tomorrow at 9 am")
        self.assertEqual(said, "Cancelled 1 reminder: call mom — tomorrow at 9 am.")

    def test_an_alarm_is_its_time(self):
        said = speech.spoken_receipt("reminder_off", "reminder 2 off — 2 alarms: wake up — today at 6 am and wake up — weekdays at 7 am")
        self.assertTrue(said.startswith("Cancelled 2 alarms: today at 6 am and weekdays at 7 am."), said)


if __name__ == "__main__":
    unittest.main()
