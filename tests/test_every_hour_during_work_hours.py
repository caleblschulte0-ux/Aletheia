"""An hourly reminder kept to his hours (2026-10-12).

"Remind me to stretch every hour", then "only during work hours", waited for
a model - and the scheduler had no way to keep an interval to part of the
day, so there was nothing for any model to compile it into.
"""
import datetime as dt
import unittest
from unittest import mock
from zoneinfo import ZoneInfo

from aletheia import scheduler, voice

CHICAGO = ZoneInfo("America/Chicago")


def at(day, hour, minute=0):
    return dt.datetime(2026, 10, day, hour, minute, tzinfo=CHICAGO).astimezone(dt.timezone.utc)


def spec(**window):
    base = {"version": 1, "id": "s1", "kind": "interval", "enabled": True, "created_at": "x",
            "command": {"kind": "notify_operator", "text": "stretch"},
            "every_minutes": 60, "anchor": at(12, 9).isoformat()}
    return {**base, **window}


WORK = {"hours": ["09:00", "17:00"], "timezone": "America/Chicago", "weekdays": [0, 1, 2, 3, 4]}


class TheWindow(unittest.TestCase):
    # 2026-10-12 is a Monday; the 16th a Friday.
    def test_inside_the_hours_it_is_hourly(self):
        self.assertEqual(scheduler.next_occurrence(spec(**WORK), at(12, 10, 30)), at(12, 11))

    def test_after_five_the_next_is_nine_tomorrow(self):
        self.assertEqual(scheduler.next_occurrence(spec(**WORK), at(12, 17, 5)), at(13, 9))

    def test_friday_evening_skips_to_monday(self):
        self.assertEqual(scheduler.next_occurrence(spec(**WORK), at(16, 17, 30)), at(19, 9))

    def test_nothing_is_due_outside_the_hours(self):
        self.assertIsNone(scheduler.occurrence_at_or_before(spec(**WORK), at(12, 20, 10)))
        self.assertEqual(scheduler.occurrence_at_or_before(spec(**WORK), at(12, 14, 10)), at(12, 14))

    def test_without_a_window_nothing_changes(self):
        self.assertEqual(scheduler.next_occurrence(spec(), at(12, 22, 30)), at(12, 23))

    def test_a_window_that_ends_before_it_starts_is_refused(self):
        with self.assertRaises(ValueError):
            scheduler.validate(spec(hours=["17:00", "09:00"], timezone="America/Chicago"))


def said(sentence):
    return voice.interpret(f"thea {sentence}")["command"]


class SayingIt(unittest.TestCase):
    def test_during_work_hours_in_one_breath(self):
        self.assertEqual(said("remind me to stretch every hour during work hours"),
                         {"kind": "remind_every", "minutes": 60, "text": "stretch",
                          "between": ["09:00", "17:00"], "days": "weekdays"})

    def test_between_9_and_5_ends_in_the_afternoon(self):
        got = said("remind me to drink water every 2 hours between 8 and 6")
        self.assertEqual((got["minutes"], got["between"]), (120, ["08:00", "18:00"]))
        self.assertNotIn("days", got)

    def test_on_weekdays_before_the_words(self):
        got = said("remind me every 30 minutes on weekdays to check email")
        self.assertEqual((got["minutes"], got["days"], got["text"]), (30, "weekdays", "check email"))

    def test_only_during_work_hours_after_setting_one(self):
        with mock.patch("aletheia.voice._recent_ask_of",
                        return_value={"kind": "remind_every", "minutes": 60, "text": "stretch"}):
            got = said("only during work hours")
        self.assertEqual(got, {"kind": "remind_every", "minutes": 60, "text": "stretch",
                               "between": ["09:00", "17:00"], "days": "weekdays", "replaces": "stretch"})

    def test_only_during_work_hours_with_nothing_set_is_not_a_reminder(self):
        with mock.patch("aletheia.voice._recent_ask_of", return_value={}):
            got = voice.interpret("thea only during work hours") or {}
        self.assertNotEqual((got.get("command") or {}).get("kind"), "remind_every")


class SettingIt(unittest.TestCase):
    def test_the_schedule_keeps_the_hours_and_the_receipt_says_them(self):
        from aletheia import intercom, speech
        made = {}

        def create(sid, command, **kw):
            made.update(kw)
            return {}
        with mock.patch.object(scheduler, "create", create):
            said = intercom.execute_command({"kind": "remind_every", "minutes": 60, "text": "stretch",
                                             "between": ["09:00", "17:00"], "days": "weekdays"}, {})
        self.assertEqual((made["hours"], made["weekdays"]), (["09:00", "17:00"], [0, 1, 2, 3, 4]))
        anchor = dt.datetime.fromisoformat(made["anchor"])
        self.assertEqual(anchor.astimezone(ZoneInfo(made["timezone"])).minute, 0)
        self.assertEqual(speech.spoken_receipt("remind_every", said),
                         "Every hour, 9 am to 5 pm on weekdays, I'll remind you: stretch.")

    def test_hours_that_end_before_they_start_are_refused(self):
        from aletheia import act, intercom
        with self.assertRaises(act.Refused):
            intercom.execute_command({"kind": "remind_every", "minutes": 60, "text": "x",
                                      "between": ["17:00", "09:00"]}, {})


if __name__ == "__main__":
    unittest.main()
