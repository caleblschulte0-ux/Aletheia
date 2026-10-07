"""Sweep 24 (2026-10-07): where he put things, alarms said every way, a
weekend reminder, a need said as a task, and a reminder before an event."""
import datetime as dt
import unittest
from unittest import mock

from aletheia import intercom, quick, voice


class WhereHePutIt(unittest.TestCase):
    def test_putting_it_somewhere_is_a_note(self):
        self.assertEqual(voice._interpret("i put my keys in the drawer")["command"],
                         {"kind": "note", "text": "i put my keys in the drawer"})
        self.assertEqual(voice._interpret("my passport is in the safe")["command"]["kind"], "note")

    def test_the_note_answers_where(self):
        notes = [{"text": "I put my keys in the drawer", "ts": "2026-10-07T01:00:00Z"}]
        with mock.patch.object(quick, "_notes", return_value=notes):
            self.assertEqual(voice._interpret("where are my keys")["say"],
                             "You told me: you put your keys in the drawer.")

    def test_no_note_is_still_the_honest_no_eyes(self):
        with mock.patch.object(quick, "_notes", return_value=[]):
            self.assertIn("no eyes in the room", voice._interpret("where are my keys")["say"])


class AlarmsEveryWay(unittest.TestCase):
    def test_every_weekday_first(self):
        self.assertEqual(voice._interpret("set an alarm for every weekday at 6")["command"],
                         {"kind": "remind_weekly", "days": ["weekdays"], "time": "06:00", "text": "wake up"})

    def test_a_nap(self):
        got = voice._interpret("wake me up in 20 minutes")["command"]
        at = dt.datetime.fromisoformat(got["at"])
        self.assertEqual((got["text"], round((at - dt.datetime.now(dt.timezone.utc)).total_seconds() / 60)),
                         ("wake up", 20))

    def test_how_long_until_it(self):
        self.assertEqual(quick.match("how long until my alarm")[0], "alarm_left")
        self.assertEqual(quick.match("how long until christmas")[0], "until")
        soon = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=7, minutes=30)
        with mock.patch.object(quick, "_coming", return_value=[(soon, "wake up", "reminder")]):
            self.assertIn("7 hours and 30 minutes from now", quick.answer("how long until my alarm"))


class AWeekendAndANeed(unittest.TestCase):
    def test_this_weekend_is_saturday_morning(self):
        got = voice._interpret("remind me this weekend to clean the garage")["command"]
        self.assertEqual(got["text"], "clean the garage")
        self.assertIn(dt.datetime.fromisoformat(got["at"]).weekday(), (5, 6))

    def test_a_need_is_a_task(self):
        got = voice._interpret("i need to call the bank tomorrow")["command"]
        self.assertEqual((got["kind"], got["description"]), ("task_new", "call the bank"))
        self.assertIn("deadline", got)
        self.assertEqual(voice._interpret("don't let me forget to pay rent")["command"]["description"], "pay rent")

    def test_a_need_with_a_clock_time_is_a_reminder(self):
        self.assertEqual(voice._interpret("i have to pick up the kids at 3")["command"]["kind"], "remind_at")

    def test_not_every_need_is_a_task(self):
        self.assertEqual(voice._interpret("i need to know the time")["command"]["kind"], "intent")


class BeforeTheEvent(unittest.TestCase):
    def test_the_other_order(self):
        from aletheia import calendar as cal
        start = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=3)
        events = [{"title": "Dentist", "start": start.isoformat(), "end": start.isoformat(), "status": "CONFIRMED"}]
        with mock.patch.object(cal, "all_events", return_value=events):
            got = voice._interpret("remind me about the meeting 10 minutes before")["command"]
        self.assertEqual(got["text"], "Dentist in 10 minutes")
        self.assertEqual(dt.datetime.fromisoformat(got["at"]), start - dt.timedelta(minutes=10))


class SmallerReads(unittest.TestCase):
    def test_do_i_need_milk_only_answers_yes(self):
        with mock.patch.object(intercom, "_shopping_items", return_value=[{"need": "milk"}]):
            self.assertEqual(quick.answer("do i need milk"), "Yes - milk is on your shopping list.")
            self.assertIsNone(quick.answer("do i need a visa"))

    def test_his_last_note(self):
        with mock.patch.object(quick, "_notes", return_value=[{"text": "my gate code is 4321"}]):
            self.assertEqual(quick.answer("what's my last note"), "Your last note: your gate code is 4321.")
        self.assertEqual(voice._interpret("read me my latest note")["command"]["kind"], "intent")


class HisAlarmAskedEveryWay(unittest.TestCase):
    def test_the_phrasings_reach_the_alarm_reader(self):
        for said in ("when does my alarm go off", "is my alarm set", "what's my alarm set for"):
            self.assertEqual(quick.match(said)[0], "alarm_q", said)
