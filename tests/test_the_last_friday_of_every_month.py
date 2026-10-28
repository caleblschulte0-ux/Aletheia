"""Some things come round on a weekday, not a date.

2026-10-28: "remind me on the last Friday of the month to pay the sitter"
went to the planner - with the models out, nothing at all - and the
scheduler had no way to say "the first Monday". A monthly schedule may now
name which one of a weekday (1 to 4, or -1 for the last) instead of a date.
"""
import datetime as dt
import unittest
from unittest import mock
from zoneinfo import ZoneInfo

from aletheia import intercom, scheduler, speech, voice

CHI = ZoneInfo("America/Chicago")


def spec(nth, weekday, time="09:00"):
    return {"version": 1, "id": "remind-monthly-x", "kind": "monthly",
            "command": {"kind": "notify_operator", "text": "pay the sitter"},
            "enabled": True, "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-01-01T00:00:00Z", "timezone": "America/Chicago",
            "time": time, "nth": nth, "weekday": weekday}


class TheSchedulerKnowsWhichOne(unittest.TestCase):
    def test_the_last_friday(self):
        after = dt.datetime(2026, 10, 28, 12, tzinfo=CHI)
        self.assertEqual(scheduler.next_occurrence(spec(-1, 4), after).astimezone(CHI),
                         dt.datetime(2026, 10, 30, 9, tzinfo=CHI))
        self.assertEqual(scheduler.occurrence_at_or_before(spec(-1, 4), after).astimezone(CHI),
                         dt.datetime(2026, 9, 25, 9, tzinfo=CHI))

    def test_the_first_monday_rolls_into_next_month(self):
        after = dt.datetime(2026, 10, 28, tzinfo=CHI)
        self.assertEqual(scheduler.next_occurrence(spec(1, 0), after).astimezone(CHI).date(),
                         dt.date(2026, 11, 2))

    def test_a_fifth_is_refused_not_guessed(self):
        for nth, weekday in ((5, 4), (0, 4), (1, 7), (True, 4)):
            with self.assertRaises(ValueError):
                scheduler.validate(spec(nth, weekday))


class HeCanSayIt(unittest.TestCase):
    def cmd(self, said):
        return voice.interpret(said)["command"]

    def test_every_month(self):
        for said in ("remind me on the last friday of every month to pay the sitter",
                     "remind me to pay the sitter on the last friday of each month",
                     "remind me every month on the last friday to pay the sitter"):
            got = self.cmd(said)
            self.assertEqual((got["kind"], got["nth"], got["weekday"], got["text"]),
                             ("remind_monthly", -1, "friday", "pay the sitter"), said)
        got = self.cmd("remind me on the first monday of every month at 8 to check the smoke alarms")
        self.assertEqual((got["nth"], got["weekday"], got["time"]), (1, "monday", "08:00"))

    def test_the_month_without_every_is_the_next_one(self):
        got = self.cmd("remind me on the last friday of the month to pay the sitter")
        self.assertEqual(got["kind"], "remind_at")
        at = dt.datetime.fromisoformat(got["at"])
        self.assertEqual((at.weekday(), at.hour), (4, 9))
        self.assertNotEqual((at + dt.timedelta(days=7)).month, at.month)

    def test_the_date_ones_are_untouched(self):
        got = self.cmd("remind me on the first of every month to pay rent")
        self.assertEqual((got["kind"], got["day"]), ("remind_monthly", 1))


class ItReallySchedules(unittest.TestCase):
    def test_nth_weekday(self):
        made = {}

        def create(sid, command, **kw):
            made.update({"id": sid, "command": command, **kw})
            return {}

        with mock.patch.object(scheduler, "create", create):
            said = intercom.execute_command({"kind": "remind_monthly", "nth": -1, "weekday": "friday",
                                             "time": "09:00", "text": "pay the sitter"}, {})
        self.assertEqual((made["kind"], made["nth"], made["weekday"]), ("monthly", -1, 4))
        self.assertEqual(speech.spoken_receipt("remind_monthly", said),
                         "On the last Friday of every month at 9 am I'll remind you: pay the sitter.")

    def test_no_day_at_all_is_refused(self):
        from aletheia import act
        with self.assertRaises(act.Refused):
            intercom.execute_command({"kind": "remind_monthly", "time": "09:00", "text": "x"}, {})

    def test_she_reads_it_back(self):
        self.assertEqual(intercom._reminder_words(spec(-1, 4)),
                         "pay the sitter — on the last Friday of every month at 9 am")


if __name__ == "__main__":
    unittest.main()
