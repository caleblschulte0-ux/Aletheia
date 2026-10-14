""""I need to pick up the kids at 6", then "what time do I need to get the
kids" said "I have nothing about get the kids", and "remind me 15 minutes
before I need to get the kids" looked only at the calendar (2026-10-14)."""
import datetime as dt
import unittest
from unittest import mock

from aletheia import calendar, quick, voice


class GetIsPickUp(unittest.TestCase):
    def setUp(self):
        self.at = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=3)
        self.rows = [(self.at, "pick up the kids", "reminder")]

    def test_when_asked_another_way(self):
        with mock.patch.object(quick, "_coming", return_value=self.rows), mock.patch.object(quick, "_notes", return_value=[]):
            for asked in ("what time do i need to get the kids", "when do i get the kids", "when do i pick up the kids"):
                self.assertTrue(quick.answer(asked).startswith("You have a reminder"), asked)

    def test_a_reminder_before_her_own_reminder(self):
        with mock.patch.object(quick, "_coming", return_value=self.rows), \
                mock.patch.object(calendar, "all_events", return_value=[]), \
                mock.patch.object(voice, "_event_from_notes", return_value=None):
            out = voice._interpret("remind me 15 minutes before i need to get the kids")
        self.assertEqual(out["command"]["kind"], "remind_at")
        self.assertEqual(dt.datetime.fromisoformat(out["command"]["at"]), self.at - dt.timedelta(minutes=15))

    def test_another_errand_is_not_it(self):
        self.assertFalse(quick._errand_matches(quick._errand_words("get the groceries"), "pick up the kids"))


if __name__ == "__main__":
    unittest.main()
