"""Three misses found talking to her on a Sunday with every model off
(2026-10-18):

- "remind me at 5 to call mom and at 6 to feed the dog" set ONE reminder at
  5 saying "call mom and at 6 to feed the dog";
- "remove eggs and cheese" asked "Which one — cheese or eggs?";
- "what's due this week" said "Nothing's due this week" with a task due
  Friday, because on a Sunday the week ended that night.
"""
import datetime
import unittest
from unittest import mock

from aletheia import intercom, localtime, quick, voice


class TwoTimesTwoThings(unittest.TestCase):
    def test_each_time_keeps_its_own_thing(self):
        self.assertEqual(voice.two_asks("remind me at 5 to call mom and at 6 to feed the dog"),
                         ["remind me at 5 to call mom", "remind me at 6 to feed the dog"])

    def test_a_day_said_once_is_both(self):
        self.assertEqual(voice.two_asks("remind me tomorrow at 9 to call the bank and at 3 to pick up the kids"),
                         ["remind me at 9 tomorrow to call the bank", "remind me at 3 tomorrow to pick up the kids"])

    def test_one_time_one_thing_is_untouched(self):
        self.assertIsNone(voice.two_asks("remind me at 5 to call mom and dad"))


class RemoveBoth(unittest.TestCase):
    def test_two_things_named_both_come_off(self):
        rows = [{"id": "w1", "need": "milk"}, {"id": "w2", "need": "eggs"}, {"id": "w3", "need": "cheese"}]
        gone = []
        with mock.patch.object(intercom, "_shopping_items", return_value=rows), \
                mock.patch("aletheia.shopping.cancel", side_effect=gone.append):
            said = intercom.execute_command({"kind": "shopping_off", "item": "eggs and cheese"}, {})
        self.assertEqual(sorted(gone), ["w2", "w3"])
        self.assertIn("eggs and cheese", str(said))

    def test_a_thing_with_and_in_its_name_is_one_thing(self):
        rows = [{"id": "w1", "need": "mac and cheese"}, {"id": "w2", "need": "cheese"}]
        gone = []
        with mock.patch.object(intercom, "_shopping_items", return_value=rows), \
                mock.patch("aletheia.shopping.cancel", side_effect=gone.append):
            intercom.execute_command({"kind": "shopping_off", "item": "mac and cheese"}, {})
        self.assertEqual(gone, ["w1"])


class ThisWeekOnASunday(unittest.TestCase):
    def test_friday_is_this_week(self):
        tz = localtime.operator_tz()
        sunday = datetime.datetime(2026, 10, 18, 10, 0, tzinfo=tz)

        class Sunday(datetime.datetime):
            @classmethod
            def now(cls, tz=None):
                return sunday if tz is None else sunday.astimezone(tz)

        task = {"id": "t1", "description": "renew my license", "status": "QUEUED", "deadline": "2026-10-23"}
        with mock.patch.object(intercom, "_open_tasks", return_value=[task]), \
                mock.patch.object(quick, "_noted_dates", return_value=[]), \
                mock.patch.object(datetime, "datetime", Sunday):
            said = quick._tasks_due("this week")
        self.assertIn("renew my license", said)


if __name__ == "__main__":
    unittest.main()
