""""Skip it on Friday" (2026-10-12).

A weekday reminder, then "skip it on friday" - to a model, and with none
running, nothing. "Skip my vitamins reminder on Friday" the same. Now the
coming Friday is skipped once and the schedule stays on.
"""
import datetime as dt
import unittest
from unittest import mock

from aletheia import act, intercom, localtime, policy, scheduler, voice

DAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")


def said(sentence):
    with mock.patch.object(policy, "all_approvals", return_value=[]):
        return voice.interpret(f"thea {sentence}")["command"]


def at_eight_on(weekdays):
    """next_occurrence for a reminder at 8 am on those weekdays."""
    tz = localtime.operator_tz()

    def nxt(spec, after):
        day = after.astimezone(tz).date()
        for step in range(15):
            when = dt.datetime.combine(day + dt.timedelta(days=step), dt.time(8), tzinfo=tz)
            if when.weekday() in weekdays and when > after:
                return when.astimezone(dt.timezone.utc)
        return None
    return nxt


class ThePhrasings(unittest.TestCase):
    def test_a_named_reminder_on_a_weekday(self):
        self.assertEqual(said("skip my vitamins reminder on friday"),
                         {"kind": "reminder_off", "which": "vitamins", "once": "friday"})
        self.assertEqual(said("skip the vitamins reminder this thursday"),
                         {"kind": "reminder_off", "which": "vitamins", "once": "thursday"})

    def test_it_after_a_repeating_reminder(self):
        with mock.patch.object(voice, "_recent_ask_of", return_value={"text": "take my vitamins"}):
            self.assertEqual(said("skip it on friday"),
                             {"kind": "reminder_off", "which": "take my vitamins", "once": "friday"})


class TheComingDay(unittest.TestCase):
    def test_the_coming_weekday(self):
        today = dt.datetime.now(localtime.operator_tz()).date()
        for offset in range(1, 7):
            name = DAYS[(today.weekday() + offset) % 7]
            self.assertEqual(intercom._once_offset(name, None), offset, name)

    def test_todays_name_is_today_only_while_todays_is_still_coming(self):
        tz = localtime.operator_tz()
        today = dt.datetime.now(tz)
        name = DAYS[today.weekday()]
        self.assertEqual(intercom._once_offset(name, today + dt.timedelta(minutes=1)), 0)
        self.assertEqual(intercom._once_offset(name, today + dt.timedelta(days=7)), 7)

    def test_skips_that_day_and_keeps_the_schedule(self):
        tz = localtime.operator_tz()
        today = dt.datetime.now(tz).date()
        target = today + dt.timedelta(days=3)
        name = DAYS[target.weekday()]
        found = {"id": "r1", "kind": "weekly", "command": {"text": "take my vitamins"}}
        with mock.patch.object(scheduler, "next_occurrence", side_effect=at_eight_on(range(7))), \
                mock.patch.object(scheduler, "skip_once") as skipped, \
                mock.patch.object(scheduler, "load", return_value=found), \
                mock.patch.object(intercom, "_reminder_words", return_value="take my vitamins — every day at 8 am"):
            intercom._skip_once(found, name)
        when = skipped.call_args[0][1].astimezone(tz)
        self.assertEqual(when.date(), target)

    def test_a_day_it_does_not_go_off_is_said(self):
        tz = localtime.operator_tz()
        today = dt.datetime.now(tz).date()
        off = (today + dt.timedelta(days=2)).weekday()
        found = {"id": "r1", "kind": "weekly", "command": {"text": "take my vitamins"}}
        with mock.patch.object(scheduler, "next_occurrence", side_effect=at_eight_on([d for d in range(7) if d != off])), \
                mock.patch.object(scheduler, "skip_once") as skipped, \
                mock.patch.object(intercom, "_reminder_words", return_value="take my vitamins — every day at 8 am"), \
                self.assertRaises(act.Refused) as why:
            intercom._skip_once(found, DAYS[off])
        skipped.assert_not_called()
        self.assertIn(f"on {DAYS[off].capitalize()}", str(why.exception))


if __name__ == "__main__":
    unittest.main()
