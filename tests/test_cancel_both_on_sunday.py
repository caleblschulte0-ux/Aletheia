""""What reminders do I have on Sunday", "cancel both" (2026-10-12: to a model).

The ones she just read, that day: a one-off is stopped, a repeating one is
skipped that day only and stays on. "Both" of three is asked about, not guessed.
"""
import datetime as dt
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import act, converse, intercom, localtime, policy, scheduler, voice


def said(sentence, answered):
    turns = [{"he_asked": "what reminders do i have on sunday", "she_answered": answered}]
    with mock.patch.object(policy, "all_approvals", return_value=[]), \
            mock.patch.object(converse, "recent", side_effect=lambda limit=1: turns[-limit:]):
        return voice.interpret(f"thea {sentence}")


TWO = "2 reminders on Sunday: 2 pm, call mom; 3 pm, call dad."
THREE = "3 reminders on Sunday: 8 am, take your pills; 2 pm, call mom; 3 pm, call dad."


class ThePhrasings(unittest.TestCase):
    def test_both_of_two(self):
        for sentence in ("cancel both", "delete both of them", "cancel all of them"):
            self.assertEqual(said(sentence, TWO)["command"], {"kind": "reminder_off", "which": "all on sunday"}, sentence)
        self.assertEqual(said("cancel both", "2 reminders tomorrow: 2 pm, call mom; 3 pm, call dad.")["command"],
                         {"kind": "reminder_off", "which": "all on tomorrow"})

    def test_both_of_three_is_asked(self):
        got = said("cancel both", THREE)
        self.assertIsNone(got["command"])
        self.assertTrue(got["say"].startswith("There are 3 on Sunday."), got["say"])
        self.assertEqual(said("cancel all of them", got["say"])["command"],
                         {"kind": "reminder_off", "which": "all on sunday"})


class TheDay(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        for attr, sub in (("SCHEDULE_DIR", "defs"), ("RECEIPT_DIR", "receipts")):
            patcher = mock.patch.object(scheduler, attr, Path(tmp.name) / sub)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_a_one_off_stops_and_a_repeat_skips_that_day(self):
        tz = localtime.operator_tz()
        day = dt.datetime.now(tz).date() + dt.timedelta(days=2)
        name = day.strftime("%A").casefold()
        at = dt.datetime.combine(day, dt.time(14), tzinfo=tz).astimezone(dt.timezone.utc).isoformat()
        note = {"kind": "notify_operator", "title": "Reminder"}
        scheduler.create("mom", {**note, "text": "call mom"}, kind="once", at=at)
        scheduler.create("pills", {**note, "text": "take my pills"}, kind="daily", timezone=str(tz), time="08:00")
        got = intercom._all_on_day(name)
        self.assertEqual(f"Cancelled 2 reminders on {name.capitalize()}: take your pills and call mom. "
                         "The repeating one is only skipped that day.", got)
        self.assertFalse(scheduler.load("mom")["enabled"])
        self.assertTrue(scheduler.load("pills")["enabled"])
        self.assertEqual(1, len(scheduler.load("pills")["skips"]))

    def test_nothing_that_day_is_said(self):
        with self.assertRaises(act.Refused):
            intercom._all_on_day("tomorrow")


if __name__ == "__main__":
    unittest.main()
