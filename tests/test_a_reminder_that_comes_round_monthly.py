"""Rent is monthly, and so is everything else that costs money on a date.

2026-10-07: "remind me on the first of every month to pay rent" was
refused at the money door as SPENDING (a reminder about paying is not a
payment), "every other day" and "every two weeks" went to the planner, and
the scheduler had no way to say "the 15th" at all. The scheduler learns a
monthly kind; "every N days/weeks" uses the interval kind it already had.
"""
import datetime as dt
import unittest
from unittest import mock
from zoneinfo import ZoneInfo

from aletheia import intercom, intents, scheduler, speech, voice

CHI = ZoneInfo("America/Chicago")


def spec(monthday, time="09:00"):
    return {"version": 1, "id": "remind-monthly-x", "kind": "monthly",
            "command": {"kind": "notify_operator", "text": "pay rent"},
            "enabled": True, "created_at": "2026-10-01T00:00:00Z",
            "updated_at": "2026-10-01T00:00:00Z", "timezone": "America/Chicago",
            "time": time, "monthday": monthday}


class TheSchedulerKnowsAMonth(unittest.TestCase):
    def test_the_next_one_is_this_month_or_the_next(self):
        after = dt.datetime(2026, 10, 7, 12, tzinfo=CHI)
        self.assertEqual(scheduler.next_occurrence(spec(15), after).astimezone(CHI),
                         dt.datetime(2026, 10, 15, 9, tzinfo=CHI))
        self.assertEqual(scheduler.next_occurrence(spec(1), after).astimezone(CHI),
                         dt.datetime(2026, 11, 1, 9, tzinfo=CHI))

    def test_the_31st_is_the_last_day_of_a_short_month_never_skipped(self):
        after = dt.datetime(2027, 2, 1, tzinfo=CHI)
        self.assertEqual(scheduler.next_occurrence(spec(31), after).astimezone(CHI).date(),
                         dt.date(2027, 2, 28))
        after = dt.datetime(2026, 4, 2, tzinfo=CHI)
        self.assertEqual(scheduler.next_occurrence(spec(31), after).astimezone(CHI).date(),
                         dt.date(2026, 4, 30))

    def test_december_rolls_into_january(self):
        after = dt.datetime(2026, 12, 20, tzinfo=CHI)
        self.assertEqual(scheduler.next_occurrence(spec(5), after).astimezone(CHI).date(),
                         dt.date(2027, 1, 5))

    def test_the_due_one_is_the_latest_passed(self):
        now = dt.datetime(2026, 10, 7, 12, tzinfo=CHI)
        self.assertEqual(scheduler.occurrence_at_or_before(spec(1), now).astimezone(CHI),
                         dt.datetime(2026, 10, 1, 9, tzinfo=CHI))
        self.assertEqual(scheduler.occurrence_at_or_before(spec(15), now).astimezone(CHI),
                         dt.datetime(2026, 9, 15, 9, tzinfo=CHI))

    def test_a_day_that_is_not_a_day_is_refused(self):
        for bad in (0, 32, "1", None):
            with self.assertRaises(ValueError):
                scheduler.validate(spec(bad))


class HeCanSayIt(unittest.TestCase):
    def cmd(self, said):
        return voice.interpret(said)["command"]

    def test_the_first_of_every_month(self):
        for said in ("remind me on the first of every month to pay rent",
                     "remind me to pay rent on the 1st of every month",
                     "remind me every month on the 1st to pay rent"):
            got = self.cmd(said)
            self.assertEqual((got["kind"], got["day"], got["text"]), ("remind_monthly", 1, "pay rent"), said)

    def test_a_time_and_the_last_day(self):
        got = self.cmd("remind me every month on the 15th at 8 to pay the card")
        self.assertEqual((got["day"], got["time"]), (15, "08:00"))
        self.assertEqual(self.cmd("remind me on the last day of every month to do invoices")["day"], 31)

    def test_every_other_day_and_every_n_days(self):
        self.assertEqual(self.cmd("remind me every other day to run")["every"], 2)
        got = self.cmd("remind me to water the plants every 3 days")
        self.assertEqual((got["kind"], got["every"], got["text"]), ("remind_daily", 3, "water the plants"))

    def test_every_other_weekday_and_fortnightly(self):
        got = self.cmd("remind me every other friday at 5 to submit my timesheet")
        self.assertEqual((got["kind"], got["days"], got["time"], got["every"]),
                         ("remind_weekly", ["friday"], "17:00", 2))
        self.assertEqual(self.cmd("remind me fortnightly to call grandma")["every"], 2)

    def test_the_old_ones_are_untouched(self):
        self.assertNotIn("every", self.cmd("remind me every monday to run"))
        self.assertNotIn("every", self.cmd("remind me every day at 9 to run"))

    def test_a_reminder_about_rent_is_not_paying_rent(self):
        self.assertFalse(intents._asks_to_spend("remind me on the first of every month to pay rent"))


class ItReallySchedules(unittest.TestCase):
    def run_cmd(self, cmd):
        made = {}

        def create(sid, command, **kw):
            made.update({"id": sid, "command": command, **kw})
            return {}

        with mock.patch.object(scheduler, "create", create):
            said = intercom.execute_command(cmd, {})
        return made, said

    def test_monthly(self):
        made, said = self.run_cmd({"kind": "remind_monthly", "day": 1, "time": "09:00", "text": "pay rent"})
        self.assertEqual((made["kind"], made["monthday"], made["time"]), ("monthly", 1, "09:00"))
        self.assertEqual(speech.spoken_receipt("remind_monthly", said),
                         "On the 1st of every month at 9 am I'll remind you: pay rent.")

    def test_every_other_day_is_an_interval_of_two_days(self):
        made, said = self.run_cmd({"kind": "remind_daily", "time": "09:00", "text": "run", "every": 2})
        self.assertEqual((made["kind"], made["every_minutes"]), ("interval", 2880))
        self.assertTrue(speech.spoken_receipt("remind_daily", said).startswith("Every other day"))

    def test_every_other_friday_starts_on_a_friday_at_that_hour(self):
        made, said = self.run_cmd({"kind": "remind_weekly", "days": ["friday"], "time": "17:00",
                                   "text": "timesheet", "every": 2})
        self.assertEqual(made["every_minutes"], 2 * 7 * 1440)
        anchor = dt.datetime.fromisoformat(made["anchor"])
        self.assertEqual((anchor.weekday(), anchor.hour), (4, 17))

    def test_out_of_range_is_refused_not_guessed(self):
        from aletheia import act
        for cmd in ({"kind": "remind_monthly", "day": 40, "time": "09:00", "text": "x"},
                    {"kind": "remind_daily", "time": "09:00", "text": "x", "every": 500}):
            with self.assertRaises(act.Refused):
                self.run_cmd(cmd)


if __name__ == "__main__":
    unittest.main()


class WithinTheDay(unittest.TestCase):
    def test_every_hour_and_every_half_hour(self):
        self.assertEqual(voice.interpret("remind me every hour to drink water")["command"],
                         {"kind": "remind_every", "minutes": 60, "text": "drink water"})
        self.assertEqual(voice.interpret("remind me to stretch every 30 minutes")["command"]["minutes"], 30)

    def test_every_few_hours_asks_for_a_number(self):
        got = voice.interpret("remind me every few hours to drink water")
        self.assertIsNone(got["command"])
        self.assertIn("every 2 hours", got["say"])

    def test_it_is_an_interval_starting_that_long_from_now(self):
        made = {}

        def create(sid, command, **kw):
            made.update(kw)
            return {}
        with mock.patch.object(scheduler, "create", create):
            said = intercom.execute_command({"kind": "remind_every", "minutes": 60, "text": "drink water"}, {})
        self.assertEqual((made["kind"], made["every_minutes"]), ("interval", 60))
        self.assertEqual(speech.spoken_receipt("remind_every", said),
                         "Every hour from now I'll remind you: drink water.")

    def test_too_often_is_refused(self):
        from aletheia import act
        with self.assertRaises(act.Refused):
            intercom.execute_command({"kind": "remind_every", "minutes": 5, "text": "x"}, {})
