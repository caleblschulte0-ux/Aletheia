"""Forty-third sandbox batch, 2026-10-05: reminders nudged and asked about,
alarms, a blocked afternoon, and the conversation itself.

    > push the vet one back an hour        [5.2s] a plan, an approval
    > when's the bread reminder            [4.1s] a model
    > do I have an alarm set               "I could not find anything matching alarm set. I looked in Documents"
    > cancel the alarm                     "None of your reminders is about alarm."
    > block out friday afternoon           [5.0s] a plan, an approval
    > clear friday afternoon               [7.5s] a model, asking a question back
    > how long have we been talking        [5.5s] a model
    > how many things have I asked you today [6.0s] a model
    > do you ever sleep                    [7.5s] a model
"""
import datetime as dt
import unittest
from unittest import mock

from aletheia import calendar as cal, converse, intercom, localtime, quick, scheduler, voice


def _reminder(text, at):
    return {"id": f"r-{text[:8]}", "kind": "once", "at": at, "enabled": True,
            "command": {"kind": "notify_operator", "text": text}}


class Reminders(unittest.TestCase):
    def setUp(self):
        tz = localtime.operator_tz()
        self.vet_at = dt.datetime.combine(localtime.today() + dt.timedelta(days=1), dt.time(9, 0), tzinfo=tz)
        rows = [_reminder("take the bread out", (dt.datetime.now(tz) + dt.timedelta(hours=1)).isoformat()),
                _reminder("call the vet", self.vet_at.isoformat()),
                _reminder("wake up", dt.datetime.combine(localtime.today() + dt.timedelta(days=1), dt.time(6, 30), tzinfo=tz).isoformat())]
        p = mock.patch.object(scheduler, "all_schedules", return_value=rows)
        p.start(); self.addCleanup(p.stop)

    def test_push_the_vet_one_back_an_hour(self):
        d = voice.interpret("thea push the vet one back an hour")
        self.assertEqual(d["command"]["kind"], "remind_at")
        self.assertEqual(d["command"]["replaces"], "call the vet")
        self.assertEqual(dt.datetime.fromisoformat(d["command"]["at"]), self.vet_at + dt.timedelta(hours=1))
        d = voice.interpret("thea move the vet reminder up 30 minutes")
        self.assertEqual(dt.datetime.fromisoformat(d["command"]["at"]), self.vet_at - dt.timedelta(minutes=30))

    def test_when_is_the_bread_reminder(self):
        for said in ("when's the bread reminder", "when does the bread reminder go off", "when am I reminded about the bread"):
            d = voice.interpret(f"thea {said}")
            self.assertIsNone(d["command"], said)
            self.assertTrue(d["say"].startswith("Your reminder to take the bread out is "), d["say"])

    def test_alarms_are_the_reminders_that_wake_him(self):
        d = voice.interpret("thea do I have an alarm set")
        self.assertIsNone(d["command"])
        self.assertTrue(d["say"].startswith("Yes - your alarm is set for tomorrow at 6:30 am"), d["say"])
        self.assertEqual(voice.interpret("thea cancel the alarm")["command"], {"kind": "reminder_off", "which": "alarm"})
        found, why = intercom._one_reminder("alarm")
        self.assertEqual(found["command"]["text"], "wake up")
        self.assertTrue(voice._not_a_file("alarm set"))

    def test_no_alarm_is_said_with_the_way_to_set_one(self):
        with mock.patch.object(scheduler, "all_schedules", return_value=[]):
            self.assertIn("wake me up at", voice.interpret("thea is my alarm set")["say"])


class TheCalendar(unittest.TestCase):
    def test_block_out_friday_afternoon(self):
        d = voice.interpret("thea block out friday afternoon")
        self.assertEqual(d["command"]["kind"], "calendar_hold")
        self.assertEqual(d["command"]["minutes"], 300)
        self.assertEqual(dt.datetime.fromisoformat(d["command"]["start"]).hour, 12)
        self.assertEqual(dt.datetime.fromisoformat(d["command"]["start"]).strftime("%A"), "Friday")
        self.assertEqual(voice.interpret("thea keep friday free")["command"]["minutes"], 480)
        self.assertEqual(voice.interpret("thea am I busy friday")["command"]["kind"], "free_time")
        self.assertEqual(voice.interpret("thea do I have anything on friday")["command"]["kind"], "free_time")
        self.assertEqual(voice.interpret("thea block tomorrow morning")["command"]["minutes"], 180)

    def test_clear_friday_afternoon_releases_what_is_held_there(self):
        self.assertEqual(voice.interpret("thea clear friday afternoon"),
                         {"command": None, "say": "Nothing on your calendar Friday afternoon."})
        start, _minutes = voice._day_window("friday", "afternoon")
        at = dt.datetime.fromisoformat(start)
        rows = [{"id": "e1", "title": "Blocked out (afternoon)", "start": at.isoformat(),
                 "end": (at + dt.timedelta(hours=5)).isoformat(), "status": "HELD"},
                {"id": "e2", "title": "dentist", "start": (at + dt.timedelta(hours=2)).isoformat(),
                 "end": (at + dt.timedelta(hours=3)).isoformat(), "status": "HELD"},
                {"id": "e3", "title": "breakfast", "start": (at - dt.timedelta(hours=4)).isoformat(),
                 "end": (at - dt.timedelta(hours=3)).isoformat(), "status": "HELD"}]
        with mock.patch.object(cal, "all_events", return_value=rows):
            d = voice.interpret("thea clear friday afternoon")
        self.assertEqual(d["command"], {"kind": "calendar_release", "title": "Blocked out (afternoon)"})
        self.assertEqual(d["and_then"], [{"ask": "take dentist off my calendar"}])


class ANaiveDayIsHisDay(unittest.TestCase):
    def test_tomorrow_on_his_calendar_is_never_today(self):
        """At 9:46 pm Central on the 4th a container clock reads the 5th, and
        "am I free tomorrow" answered "Free today 9 am to 5 pm"."""
        from aletheia import speech
        tomorrow = (localtime.today() + dt.timedelta(days=1)).isoformat()
        self.assertEqual(speech.humanize_time(f"{tomorrow}T12:00:00"), "tomorrow at 12 pm")
        self.assertEqual(speech.humanize_time(f"{localtime.today().isoformat()}T23:59:00")[:5], "today")
        said = intercom._free_sentence([], localtime.today() + dt.timedelta(days=1), "")
        self.assertEqual(said, "Nothing free tomorrow.")


class TheConversationItself(unittest.TestCase):
    def setUp(self):
        converse.forget()
        self.addCleanup(converse.forget)

    def test_how_long_and_how_many(self):
        self.assertEqual(quick.answer("how long have we been talking"),
                         "We just started - nothing earlier today in the conversation.")
        self.assertEqual(quick.answer("how many things have I asked you today"), "Nothing yet today.")
        converse.remember_exchange("add milk", "Added to the shopping list: milk.")
        converse.remember_exchange("what time is it", "9 pm.")
        self.assertRegex(quick.answer("how long have we been talking"), r"^About 1 minute, since ")
        self.assertEqual(quick.answer("how many things have I asked you today"), "2 things today, counting this one.")

    def test_she_does_not_sleep(self):
        self.assertEqual(quick.match("do you ever sleep")[0], "never_sleeps")
        self.assertTrue(quick.answer("are you tired").startswith("No."))


if __name__ == "__main__":
    unittest.main()
