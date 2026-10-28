"""A reminder every few months, and a moved reminder is not a stopped one.

2026-10-28, talking to her with the models off:

    > remind me to change the air filter every 3 months      (to the planner)
    > remind me every other month to rotate the tires         (to the planner)
    > move the vitamins reminder to 9, then
    > what reminders do I have     ... You stopped this one this week: take
                                   your vitamins — every day at 8 am.
"""
import datetime as dt
import unittest
from unittest import mock
from zoneinfo import ZoneInfo

from aletheia import intercom, scheduler, speech, voice

CHI = ZoneInfo("America/Chicago")


def spec(**more):
    return {"version": 1, "id": "remind-monthly-x", "kind": "monthly",
            "command": {"kind": "notify_operator", "text": "change the air filter"},
            "enabled": True, "created_at": "2026-01-01T00:00:00Z", "updated_at": "2026-01-01T00:00:00Z",
            "timezone": "America/Chicago", "time": "09:00", "monthday": 28, **more}


class EveryFewMonths(unittest.TestCase):
    def test_only_the_counted_months(self):
        s = spec(every_months=3, start_month="2027-01")
        scheduler.validate(s)
        after = dt.datetime(2026, 10, 28, 12, tzinfo=CHI)
        got = []
        for _ in range(3):
            after = scheduler.next_occurrence(s, after)
            got.append(after.astimezone(CHI).date())
        self.assertEqual(got, [dt.date(2027, 1, 28), dt.date(2027, 4, 28), dt.date(2027, 7, 28)])
        self.assertEqual(scheduler.occurrence_at_or_before(s, dt.datetime(2027, 6, 1, tzinfo=CHI)).astimezone(CHI).date(),
                         dt.date(2027, 4, 28))

    def test_a_bad_count_is_refused(self):
        for bad in (spec(every_months=1, start_month="2027-01"), spec(every_months=3), spec(every_months=13, start_month="2027-01")):
            with self.assertRaises(ValueError):
                scheduler.validate(bad)

    def test_he_can_say_it(self):
        for said, every, day in (("remind me to change the air filter every 3 months", 3, None),
                                 ("remind me every quarter on the 15th to pay estimated taxes", 3, 15),
                                 ("remind me every other month to rotate the tires", 2, None),
                                 ("remind me twice a year to check the smoke detectors", 6, None)):
            got = voice.interpret(said)["command"]
            self.assertEqual((got["kind"], got["every"]), ("remind_monthly", every), said)
            if day:
                self.assertEqual(got["day"], day)
        self.assertNotIn("every", voice.interpret("remind me every month on the 1st to pay rent")["command"])

    def test_the_receipt_names_the_first(self):
        said = speech.spoken_receipt("remind_monthly", "monthly reminder remind-monthly-1 set for day 15 at 09:00 "
                                                       "every 3 months from 2026-11 — 'pay estimated taxes'")
        self.assertEqual(said, "Every 3 months on the 15th at 9 am I'll remind you: pay estimated taxes. "
                               "The first is November 15th.")


class MovedIsNotStopped(unittest.TestCase):
    def test_the_old_time_of_a_moved_one_is_not_named(self):
        now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        old = {**spec(), "id": "a", "kind": "daily", "enabled": False, "updated_at": now,
               "command": {"kind": "notify_operator", "text": "take your vitamins"}}
        new = {**old, "id": "b", "enabled": True}
        with mock.patch.object(scheduler, "all_schedules", return_value=[old, new]):
            self.assertEqual(intercom._stopped_reminders(), [])
        with mock.patch.object(scheduler, "all_schedules", return_value=[old]):
            self.assertEqual([r["id"] for r in intercom._stopped_reminders()], ["a"])


if __name__ == "__main__":
    unittest.main()
