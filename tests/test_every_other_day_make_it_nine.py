""""Remind me to water the plants every other day at 8", "make it 9"
(2026-10-14: to a model, then an approval for a plain move), and "what's on
the list now" after taking something off (to a model, twice).

An every-N-days reminder moves to the new time on the days it already had,
and the list says the clock he hears, not the anchor's stored offset.
"""
import datetime as dt
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import intercom, localtime, quick, scheduler, voice

EVERY_OTHER = {"id": "e1", "kind": "interval", "every_minutes": 2880, "anchor": "2026-10-15T08:00:00-05:00",
               "command": {"kind": "notify_operator", "text": "water the plants"}}


def asks(**by_kind):
    return lambda kind, needs, turns=4: by_kind.get(kind, {})


def said(sentence):
    return voice.interpret(f"thea {sentence}")


class ThePhrasing(unittest.TestCase):
    def test_every_other_day_moves_and_stays_every_other_day(self):
        with mock.patch("aletheia.voice._recent_ask_of",
                        side_effect=asks(remind_daily={"time": "08:00", "text": "water the plants", "every": 2})), \
                mock.patch("aletheia.intercom._one_reminder", return_value=(EVERY_OTHER, "")):
            got = said("make it 9")["command"]
        self.assertEqual(got, {"kind": "remind_daily", "time": "09:00", "text": "water the plants",
                               "replaces": "water the plants", "every": 2})

    def test_a_bare_hour_keeps_the_evening(self):
        with mock.patch("aletheia.voice._recent_ask_of",
                        side_effect=asks(remind_daily={"time": "20:00", "text": "water the plants", "every": 3})), \
                mock.patch("aletheia.intercom._one_reminder", return_value=(EVERY_OTHER, "")):
            got = said("make it 7")["command"]
        self.assertEqual((got["time"], got["every"]), ("19:00", 3))

    def test_every_other_week_is_still_not_this(self):
        weekly = {**EVERY_OTHER, "every_minutes": 20160}
        with mock.patch("aletheia.voice._recent_ask_of",
                        side_effect=asks(remind_weekly={"days": ["sunday"], "time": "10:00",
                                                        "text": "water the plants", "every": 2})), \
                mock.patch("aletheia.intercom._one_reminder", return_value=(weekly, "")):
            got = (said("make it 11") or {}).get("command") or {}
        self.assertNotEqual(got.get("kind"), "remind_weekly")


class TheMove(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        for attr, sub in (("SCHEDULE_DIR", "defs"), ("RECEIPT_DIR", "receipts")):
            patcher = mock.patch.object(scheduler, attr, Path(tmp.name) / sub)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.tz = localtime.operator_tz()

    def run_(self, cmd):
        return intercom.execute_command(cmd, {})

    def enabled(self):
        return [s for s in scheduler.all_schedules() if s.get("enabled", True)]

    def test_it_keeps_its_days_and_takes_the_new_time(self):
        self.run_({"kind": "remind_daily", "time": "08:00", "text": "water the plants", "every": 2})
        first = scheduler.next_occurrence(self.enabled()[0], dt.datetime.now(dt.timezone.utc))
        self.run_({"kind": "remind_daily", "time": "09:00", "text": "water the plants", "every": 2,
                   "replaces": "water the plants"})
        left = self.enabled()
        self.assertEqual(len(left), 1)
        nxt = scheduler.next_occurrence(left[0], dt.datetime.now(dt.timezone.utc)).astimezone(self.tz)
        self.assertEqual((nxt.hour, nxt.minute), (9, 0))
        self.assertEqual(nxt.date(), first.astimezone(self.tz).date())
        self.assertEqual(left[0]["every_minutes"], 2880)

    def test_the_list_says_his_clock_whatever_offset_the_anchor_was_written_in(self):
        at = dt.datetime.now(self.tz).replace(hour=21, minute=0, second=0, microsecond=0) + dt.timedelta(days=1)
        spec = dict(EVERY_OTHER, anchor=at.astimezone(dt.timezone.utc).isoformat())
        self.assertIn("every other day at 9 pm", intercom._reminder_words(spec))


class WhatsOnTheListNow(unittest.TestCase):
    def first(self, text):
        return next((n for n, p in quick.PATTERNS if p.match(quick._tidy(text))), None)

    def test_asked_again_is_the_same_list(self):
        for sentence in ("what's on the list now", "what else is on the list", "what's still on the list"):
            self.assertEqual(self.first(sentence), "the_list", sentence)
        for sentence in ("what's on my list now", "what's still on my shopping list", "what's on the shopping list now"):
            self.assertEqual(self.first(sentence), "shopping", sentence)

    def test_a_named_list_just_used_is_read(self):
        with mock.patch("aletheia.voice._the_named_list_just_used", return_value=("camping", "tent")):
            for sentence in ("what's on the list now", "what else is on the list"):
                self.assertEqual(said(sentence)["command"], {"kind": "list_read", "list": "camping"}, sentence)


class CancelItAfterTheTimer(unittest.TestCase):
    """"Set a timer", "pause the timer" (she can't), "cancel it" said "Nothing is
    waiting for approval" (2026-10-14)."""

    def test_the_timer_she_was_just_talking_about(self):
        with mock.patch("aletheia.policy.all_approvals", return_value=[]), \
                mock.patch("aletheia.voice._her_last_answer",
                           return_value="I can't pause a timer - it goes off at a set time."):
            got = said("cancel it")["command"]
        self.assertEqual(got, said("cancel the timer")["command"])


class AtTheSameTime(unittest.TestCase):
    ONCE = {"id": "r1", "kind": "once", "at": "2026-10-15T15:00:00-05:00",
            "command": {"kind": "notify_operator", "text": "call the bank"}}

    def test_the_time_of_the_one_just_set(self):
        with mock.patch("aletheia.voice._the_reminder_just_set", return_value=self.ONCE):
            for sentence in ("and remind me to email Sarah at the same time", "also remind me to email Sarah then too"):
                self.assertEqual(said(sentence)["command"],
                                 {"kind": "remind_at", "at": "2026-10-15T15:00:00-05:00", "text": "email Sarah"}, sentence)

    def test_with_nothing_just_set_it_is_not_guessed(self):
        with mock.patch("aletheia.voice._the_reminder_just_set", return_value=None):
            got = (said("remind me to email Sarah at the same time") or {}).get("command") or {}
        self.assertNotEqual(got.get("kind"), "remind_at")


if __name__ == "__main__":
    unittest.main()
