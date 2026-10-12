"""Reminders named, counted and cleared from what she just read (2026-10-12).

"Push call mom back an hour" said she can't move things on his calendar.
"Push them both back an hour" said the same. "When's my last reminder
today" and "cancel all of them" after her list both waited for a model.
"""
import datetime as dt
import unittest
from unittest import mock

from aletheia import intercom, voice

SOON = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=3)
LATER = SOON + dt.timedelta(hours=2)
RUNNING = [(SOON, "call mom"), (LATER, "buy milk")]


def said(sentence, answered=""):
    with mock.patch("aletheia.voice._running_once", return_value=RUNNING), \
            mock.patch("aletheia.voice._one_of_her_holds", return_value=(None, "")), \
            mock.patch("aletheia.voice._previous_turn", return_value=("what reminders do I have", answered)), \
            mock.patch("aletheia.converse.recent", return_value=[]):
        return voice.interpret(f"thea {sentence}")


class PushANamedReminder(unittest.TestCase):
    def test_by_its_words(self):
        got = said("push call mom back an hour")["command"]
        self.assertEqual(got, {"kind": "remind_at", "at": (SOON + dt.timedelta(hours=1)).isoformat(),
                               "text": "call mom", "replaces": "call mom"})

    def test_by_its_words_and_the_word_reminder(self):
        got = said("push the milk reminder back 30 minutes")["command"]
        self.assertEqual((got["text"], got["at"]), ("buy milk", (LATER + dt.timedelta(minutes=30)).isoformat()))

    def test_by_its_place_in_the_list_she_read(self):
        rows = [{"id": "a", "kind": "once", "command": {"text": "call mom"}},
                {"id": "b", "kind": "once", "command": {"text": "buy milk"}}]
        with mock.patch("aletheia.intercom._reminder_schedules", return_value=rows), \
                mock.patch("aletheia.intercom._soonest_first", side_effect=lambda r: r):
            got = said("push the second one back an hour", answered="2 reminders: call mom ... and buy milk ...")
        self.assertEqual(got["command"]["text"], "buy milk")

    def test_them_both_is_not_the_calendar(self):
        got = said("push them both back an hour")
        self.assertIsNone(got["command"])
        self.assertNotIn("calendar", got["say"])

    def test_a_hold_of_hers_still_wins(self):
        hold = {"title": "lunch with sarah", "start": SOON.isoformat(), "end": (SOON + dt.timedelta(hours=1)).isoformat()}
        with mock.patch("aletheia.voice._one_of_her_holds", return_value=(hold, "")), \
                mock.patch("aletheia.converse.recent", return_value=[]):
            got = voice.interpret("thea push lunch back 30 minutes")["command"]
        self.assertEqual(got["kind"], "calendar_hold")


class CancelAllOfThem(unittest.TestCase):
    def test_after_the_whole_list_it_is_every_reminder(self):
        with mock.patch("aletheia.intercom._reminder_schedules", return_value=[{}, {}]):
            got = said("cancel all of them", answered="2 reminders: call mom — today at 4 pm and buy milk — today at 6 pm.")
        self.assertEqual(got["command"], {"kind": "reminder_off", "which": "all reminders"})

    def test_not_when_the_list_was_only_part_of_them(self):
        with mock.patch("aletheia.intercom._reminder_schedules", return_value=[{}, {}, {}]):
            got = said("cancel all of them", answered="2 reminders: call mom — today at 4 pm and buy milk — today at 6 pm.") or {}
        self.assertNotEqual((got.get("command") or {}).get("which"), "all reminders")


class TheLastOneToday(unittest.TestCase):
    def test_it_is_asked_for(self):
        self.assertEqual(voice.interpret("thea when's my last reminder today")["command"],
                         {"kind": "reminders", "which": "last today"})

    def test_it_names_the_latest_and_counts_the_rest(self):
        from aletheia import localtime
        tz = localtime.operator_tz()
        end_of_day = dt.datetime.now(tz).replace(hour=23, minute=0, second=0, microsecond=0)
        first, last = end_of_day - dt.timedelta(minutes=50), end_of_day - dt.timedelta(minutes=20)
        if first <= dt.datetime.now(tz):
            self.skipTest("too close to midnight to have two left today")
        rows = [{"id": "a", "kind": "once", "at": first.isoformat(), "enabled": True, "command": {"text": "call mom"}},
                {"id": "b", "kind": "once", "at": last.isoformat(), "enabled": True, "command": {"text": "buy milk"}}]
        with mock.patch("aletheia.intercom._reminder_schedules", return_value=rows), \
                mock.patch("aletheia.scheduler.next_occurrence",
                           side_effect=lambda spec, after: (dt.datetime.fromisoformat(spec["at"])
                                                            if dt.datetime.fromisoformat(spec["at"]) > after else None)):
            answer = intercom._reminders_answer("last today")
        self.assertTrue(answer.startswith("Your last reminder today is at 10:40 pm: buy milk."), answer)
        self.assertIn("There is 1 other before it.", answer)


if __name__ == "__main__":
    unittest.main()
