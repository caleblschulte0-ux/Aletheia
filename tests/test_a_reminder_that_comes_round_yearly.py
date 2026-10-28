"""An anniversary comes round once a year, and so does a registration.

2026-10-28: "remind me every year on my anniversary" set a ONE-OFF reminder
whose text was "every year", and "remind me every year on March 3rd to buy
flowers" went to the planner - which, with the models out, meant nothing
happened at all. The scheduler learns a yearly kind (one day of one month),
and the sentence compiles to it with no model.
"""
import datetime as dt
import unittest
from unittest import mock
from zoneinfo import ZoneInfo

from aletheia import intercom, quick, scheduler, speech, voice

CHI = ZoneInfo("America/Chicago")


def spec(month, monthday, time="09:00"):
    return {"version": 1, "id": "remind-yearly-x", "kind": "yearly",
            "command": {"kind": "notify_operator", "text": "buy flowers"},
            "enabled": True, "created_at": "2025-01-01T00:00:00Z",
            "updated_at": "2025-01-01T00:00:00Z", "timezone": "America/Chicago",
            "time": time, "month": month, "monthday": monthday}


class TheSchedulerKnowsAYear(unittest.TestCase):
    def test_the_next_one_is_this_year_or_the_next(self):
        after = dt.datetime(2026, 10, 28, 12, tzinfo=CHI)
        self.assertEqual(scheduler.next_occurrence(spec(12, 25), after).astimezone(CHI),
                         dt.datetime(2026, 12, 25, 9, tzinfo=CHI))
        self.assertEqual(scheduler.next_occurrence(spec(3, 3), after).astimezone(CHI),
                         dt.datetime(2027, 3, 3, 9, tzinfo=CHI))

    def test_the_due_one_is_the_latest_passed(self):
        now = dt.datetime(2026, 10, 28, 12, tzinfo=CHI)
        self.assertEqual(scheduler.occurrence_at_or_before(spec(3, 3), now).astimezone(CHI),
                         dt.datetime(2026, 3, 3, 9, tzinfo=CHI))
        self.assertEqual(scheduler.occurrence_at_or_before(spec(12, 25), now).astimezone(CHI),
                         dt.datetime(2025, 12, 25, 9, tzinfo=CHI))

    def test_february_29_is_the_28th_in_other_years(self):
        after = dt.datetime(2026, 10, 28, tzinfo=CHI)
        self.assertEqual(scheduler.next_occurrence(spec(2, 29), after).astimezone(CHI).date(),
                         dt.date(2027, 2, 28))

    def test_a_month_that_is_not_a_month_is_refused(self):
        for bad in (0, 13, "3", None):
            with self.assertRaises(ValueError):
                scheduler.validate(spec(bad, 3))


class HeCanSayIt(unittest.TestCase):
    def cmd(self, said):
        return voice.interpret(said)["command"]

    def test_either_word_order_and_either_way_of_saying_the_date(self):
        for said in ("remind me every year on march 3rd to buy flowers",
                     "remind me on march 3 every year to buy flowers",
                     "remind me to buy flowers every year on the 3rd of march",
                     "remind me annually on mar 3 to buy flowers"):
            got = self.cmd(said)
            self.assertEqual((got["kind"], got["month"], got["day"], got["time"], got["text"]),
                             ("remind_yearly", 3, 3, "09:00", "buy flowers"), said)

    def test_a_time(self):
        got = self.cmd("remind me every year on january 1 at 10 to review my budget")
        self.assertEqual((got["month"], got["day"], got["time"]), (1, 1, "10:00"))

    def test_a_day_of_his_she_has_a_note_of(self):
        with mock.patch.object(quick, "_his_date", return_value=dt.date(2027, 8, 12)):
            got = self.cmd("remind me every year on our anniversary to book dinner")
            self.assertEqual((got["kind"], got["month"], got["day"], got["text"]),
                             ("remind_yearly", 8, 12, "book dinner"))
            got = self.cmd("remind me every year on my anniversary")
            self.assertEqual((got["kind"], got["text"]), ("remind_yearly", "your anniversary"))

    def test_a_day_she_does_not_know_is_asked_for_never_guessed(self):
        with mock.patch.object(quick, "_his_date", return_value=None):
            got = voice.interpret("remind me every year on my anniversary")
        self.assertIsNone(got["command"])
        self.assertIn("I don't know when your anniversary is", got["say"])
        got = voice.interpret("remind me every year to buy flowers")
        self.assertIsNone(got["command"])
        self.assertIn("Which day of the year", got["say"])
        self.assertIsNone(voice.interpret("remind me every year on the 30th of february to x")["command"])


class ItReallySchedules(unittest.TestCase):
    def test_yearly(self):
        made = {}

        def create(sid, command, **kw):
            made.update({"id": sid, "command": command, **kw})
            return {}

        with mock.patch.object(scheduler, "create", create):
            said = intercom.execute_command({"kind": "remind_yearly", "month": 3, "day": 3, "time": "09:00",
                                             "text": "buy flowers"}, {})
        self.assertEqual((made["kind"], made["month"], made["monthday"], made["time"]), ("yearly", 3, 3, "09:00"))
        self.assertEqual(speech.spoken_receipt("remind_yearly", said),
                         "Every year on March 3rd at 9 am I'll remind you: buy flowers.")

    def test_out_of_range_is_refused_not_guessed(self):
        from aletheia import act
        with self.assertRaises(act.Refused):
            intercom.execute_command({"kind": "remind_yearly", "month": 13, "day": 3, "time": "09:00",
                                      "text": "x"}, {})

    def test_she_reads_it_back(self):
        self.assertEqual(intercom._reminder_words(spec(3, 3)), "buy flowers — every year on March 3rd at 9 am")


if __name__ == "__main__":
    unittest.main()
