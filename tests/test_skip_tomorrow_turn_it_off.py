""""Remind me every weekday at 7 to take my pills", "skip tomorrow", and
"wake me up at 6 tomorrow", "turn it off" (2026-10-14: both to a model, and
both came back as an approval to tap for something he had just said).

"Skip tomorrow" is "skip it tomorrow" said short; "turn it off" about the
alarm, reminder or timer she just named is "cancel it". An alarm taken back
is said as the alarm, not as "the reminder to wake up".
"""
import datetime as dt
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import intercom, policy, scheduler, voice


def said(sentence):
    with mock.patch.object(policy, "all_approvals", return_value=[]):
        return voice.interpret(f"thea {sentence}")


class SkipTomorrow(unittest.TestCase):
    def test_after_a_repeating_reminder(self):
        with mock.patch.object(voice, "_recent_ask_of",
                               side_effect=lambda kind, needs, turns=4: {"text": "take your pills"}
                               if kind == "remind_daily" else {}):
            for sentence, once in (("skip tomorrow", "tomorrow"), ("skip friday", "friday"),
                                   ("don't remind me tomorrow", "tomorrow")):
                self.assertEqual(said(sentence)["command"],
                                 {"kind": "reminder_off", "which": "take your pills", "once": once}, sentence)

    def test_with_nothing_repeating_just_set_it_is_not_this(self):
        with mock.patch.object(voice, "_recent_ask_of", return_value={}):
            got = (said("skip tomorrow") or {}).get("command") or {}
        self.assertNotEqual(got.get("kind"), "reminder_off")


class TurnItOff(unittest.TestCase):
    def test_after_she_named_an_alarm_it_is_cancel_it(self):
        with mock.patch.object(voice, "_her_last_answer", return_value="Alarm set for tomorrow at 6 am."), \
                mock.patch.object(voice, "_last_ask_is_undoable", return_value=True):
            self.assertEqual(said("turn it off")["command"], said("cancel it")["command"])
            self.assertEqual(said("switch that off")["command"], {"kind": "undo"})

    def test_after_anything_else_it_is_not_this(self):
        with mock.patch.object(voice, "_her_last_answer", return_value="It's 72 and sunny."), \
                mock.patch.object(voice, "_last_ask_is_undoable", return_value=True):
            got = (said("turn it off") or {}).get("command") or {}
        self.assertNotEqual(got.get("kind"), "undo")


class AndThePharmacyAtFive(unittest.TestCase):
    """"Remind me to call the vet at 4", "and the pharmacy at 5" (2026-10-14: to a model)."""

    def just(self, hours):
        at = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=hours)).replace(minute=0, second=0, microsecond=0)
        return {"id": "r1", "kind": "once", "at": at.isoformat(),
                "command": {"kind": "notify_operator", "text": "call the vet"}}

    def test_the_same_errand_on_the_same_day(self):
        from aletheia import localtime
        just = self.just(30)
        was = dt.datetime.fromisoformat(just["at"]).astimezone(localtime.operator_tz())
        with mock.patch.object(voice, "_she_just_set_a_reminder", return_value=True), \
                mock.patch.object(voice, "_the_reminder_just_set", return_value=just):
            got = said("and the pharmacy at 11:30 am")["command"]
        self.assertEqual(got["kind"], "remind_at")
        self.assertEqual(got["text"], "call the pharmacy")
        at = dt.datetime.fromisoformat(got["at"])
        self.assertEqual((at.date(), at.hour, at.minute), (was.date(), 11, 30))

    def test_not_after_anything_but_a_reminder_just_set(self):
        with mock.patch.object(voice, "_she_just_set_a_reminder", return_value=False):
            got = (said("and the pharmacy at 5") or {}).get("command") or {}
        self.assertNotEqual(got.get("kind"), "remind_at")


class TheAlarmTakenBack(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        for attr, sub in (("SCHEDULE_DIR", "defs"), ("RECEIPT_DIR", "receipts")):
            patcher = mock.patch.object(scheduler, attr, Path(tmp.name) / sub)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_is_said_as_the_alarm(self):
        from aletheia import converse
        intercom.execute_command({"kind": "remind_at", "text": "wake up",
                                  "at": (dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=1)).replace(
                                      microsecond=0).isoformat()}, {})
        turns = [{"he_asked": "wake me up at 6 tomorrow", "she_answered": "Alarm set for tomorrow at 6 am."}]
        with mock.patch.object(converse, "recent", side_effect=lambda limit=4: turns), \
                mock.patch.object(voice, "interpret", return_value={"command": {
                    "kind": "remind_at", "text": "wake up", "at": "x"}, "say": None}):
            said_ = intercom._undo_his_last_ask()
        self.assertTrue(str(said_).startswith("Your alarm "), said_)
        self.assertFalse([s for s in scheduler.all_schedules() if s.get("enabled", True)])


if __name__ == "__main__":
    unittest.main()
