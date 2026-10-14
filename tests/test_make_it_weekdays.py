""""Remind me every day at 8 to stretch", "make it weekdays only"; "every
Monday at 9", "add Friday too"; "tonight", "make it every Tuesday"
(2026-10-14: all three to a model).

The reminder just set goes off on the new days at the time it had. A one-off
made repeating stays unless it falls on one of the new days at that time, so
tonight's trash is not lost and Saturday's call is not said twice. "Make it
Saturday" after a one-off is still a move, not a repeat.
"""
import datetime as dt
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import intercom, localtime, policy, scheduler, voice

DAILY = {"id": "d1", "kind": "daily", "time": "08:00", "command": {"kind": "notify_operator", "text": "stretch"}}
MONDAYS = {"id": "w1", "kind": "weekly", "time": "09:00", "weekdays": [0],
           "command": {"kind": "notify_operator", "text": "submit your timesheet"}}


def asks(**by_kind):
    return lambda kind, needs, turns=4: by_kind.get(kind, {})


def said(sentence, kind, found):
    with mock.patch.object(policy, "all_approvals", return_value=[]), \
            mock.patch.object(voice, "_recent_ask_of", side_effect=asks(**{kind: {"text": found["command"]["text"]}})), \
            mock.patch.object(intercom, "_one_reminder", return_value=(found, "")):
        return (voice.interpret(f"thea {sentence}") or {}).get("command") or {}


class NewDays(unittest.TestCase):
    def test_every_day_to_weekdays(self):
        self.assertEqual(said("make it weekdays only", "remind_daily", DAILY),
                         {"kind": "remind_weekly", "days": ["monday", "tuesday", "wednesday", "thursday", "friday"],
                          "time": "08:00", "text": "stretch", "replaces": "stretch"})

    def test_a_day_added(self):
        self.assertEqual(said("add friday too", "remind_weekly", MONDAYS)["days"], ["monday", "friday"])

    def test_every_day_from_weekly(self):
        self.assertEqual(said("make it every day", "remind_weekly", MONDAYS),
                         {"kind": "remind_daily", "time": "09:00", "text": "submit your timesheet",
                          "replaces": "submit your timesheet"})

    def test_a_one_off_made_repeating(self):
        at = dt.datetime.now(localtime.operator_tz()).replace(hour=21, minute=0, second=0, microsecond=0)
        once = {"id": "o1", "kind": "once", "at": at.isoformat(),
                "command": {"kind": "notify_operator", "text": "take out the trash"}}
        other = "tuesday" if at.weekday() != 1 else "wednesday"
        got = said(f"make it every {other}", "remind_at", once)
        self.assertEqual((got["kind"], got["days"], got["time"]), ("remind_weekly", [other], "21:00"))
        self.assertNotIn("replaces", got)
        moved = said(f"make it {other}", "remind_at", once)
        self.assertNotEqual(moved.get("kind"), "remind_weekly")


class TheOneOffIsTheFirstOfThem(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        for attr, sub in (("SCHEDULE_DIR", "defs"), ("RECEIPT_DIR", "receipts")):
            patcher = mock.patch.object(scheduler, attr, Path(tmp.name) / sub)
            patcher.start()
            self.addCleanup(patcher.stop)

    def enabled(self):
        return [s for s in scheduler.all_schedules() if s.get("enabled", True)]

    def test_on_one_of_the_days_it_goes_off(self):
        at = (dt.datetime.now(localtime.operator_tz()) + dt.timedelta(days=2)).replace(hour=18, minute=0, second=0,
                                                                                         microsecond=0)
        intercom.execute_command({"kind": "remind_at", "at": at.isoformat(), "text": "call mom"}, {})
        day = voice._DAY_NAMES[at.weekday()]
        intercom.execute_command({"kind": "remind_weekly", "days": [day], "time": "18:00", "text": "call mom",
                                  "replaces": "call mom"}, {})
        self.assertEqual([s["kind"] for s in self.enabled()], ["weekly"])

    def test_on_another_day_it_stays(self):
        at = (dt.datetime.now(localtime.operator_tz()) + dt.timedelta(days=2)).replace(hour=18, minute=0, second=0,
                                                                                         microsecond=0)
        intercom.execute_command({"kind": "remind_at", "at": at.isoformat(), "text": "call mom"}, {})
        day = voice._DAY_NAMES[(at.weekday() + 1) % 7]
        intercom.execute_command({"kind": "remind_weekly", "days": [day], "time": "18:00", "text": "call mom",
                                  "replaces": "call mom"}, {})
        self.assertEqual(sorted(s["kind"] for s in self.enabled()), ["once", "weekly"])


if __name__ == "__main__":
    unittest.main()
