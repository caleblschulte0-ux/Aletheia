"""The scheduler could do weekly. The grammar could not say it.

"remind me every monday to take out the trash" compiled to a generic
`do_task` under the summary "Set weekly Monday reminder to take out the
trash" — a promise of recurrence that nothing in the step delivered,
while `scheduler.KINDS` had held "weekly" since the day it was written.
That is a capability nothing can ask for, which CLAUDE.md's rule zero
calls no capability at all.
"""
import unittest
from unittest import mock

from aletheia import act, intercom, planner, scheduler, speech, voice


class HeCanAskForIt(unittest.TestCase):
    def test_the_deterministic_path_hears_a_day(self):
        got = voice.interpret("remind me every monday to take out the trash")
        self.assertEqual(got["command"]["kind"], "remind_weekly")
        self.assertEqual(got["command"]["days"], ["monday"])
        self.assertEqual(got["command"]["text"], "take out the trash")

    def test_a_named_time_beats_the_default(self):
        got = voice.interpret("remind me every friday at 6 pm to call mom")
        self.assertEqual(got["command"]["time"], "18:00")

    def test_no_time_means_nine_and_the_receipt_says_so(self):
        # A reminder needs an hour and he did not give one. Guessing is
        # fine BECAUSE the confirmation says it back — he corrects it in
        # one sentence instead of missing bin day.
        got = voice.interpret("remind me every monday to take out the trash")
        self.assertEqual(got["command"]["time"], voice.DEFAULT_REMINDER_TIME)

    def test_a_list_of_days_he_says_in_one_breath(self):
        # Through the planner this came back "Weekly reminder Tue/Thu 6pm
        # to go to the gym" — a calendar entry, not a sentence.
        got = voice.interpret(
            "remind me every tuesday and thursday at 6pm to go to the gym")
        self.assertEqual(got["command"]["days"], ["tuesday", "thursday"])
        self.assertEqual(got["command"]["time"], "18:00")
        got = voice.interpret("remind me every mon, wed and fri at 7 to log hours")
        self.assertEqual(got["command"]["days"], ["mon", "wed", "fri"])

    def test_the_groups_are_heard_too(self):
        got = voice.interpret("remind me every weekend to water the plants")
        self.assertEqual(got["command"]["days"], ["weekend"])

    def test_every_day_is_still_the_daily_kind(self):
        got = voice.interpret("remind me every day at 8 am to stretch")
        self.assertEqual(got["command"]["kind"], "remind_daily")

    def test_the_planner_is_told_the_verb_exists(self):
        brief = planner.grammar_brief()
        self.assertIn("remind_weekly(", brief)
        self.assertIn("every Monday", brief)


class TheDaysAreParsedOrRefused(unittest.TestCase):
    def test_words_abbreviations_and_numbers(self):
        self.assertEqual(intercom._weekday_numbers(["monday", "wed"]), [0, 2])
        self.assertEqual(intercom._weekday_numbers("friday"), [4])
        self.assertEqual(intercom._weekday_numbers([0, 6]), [0, 6])

    def test_the_groups_that_are_not_days(self):
        self.assertEqual(intercom._weekday_numbers("weekdays"), [0, 1, 2, 3, 4])
        self.assertEqual(intercom._weekday_numbers("weekend"), [5, 6])

    def test_duplicates_collapse_because_the_scheduler_refuses_them(self):
        self.assertEqual(intercom._weekday_numbers(["mon", "monday"]), [0])

    def test_a_day_it_cannot_read_is_refused_not_guessed(self):
        # A reminder on the wrong day is worse than no reminder; asking
        # again costs one sentence.
        for bad in (["funday"], [9], [], "", [True]):
            with self.assertRaises(act.Refused):
                intercom._weekday_numbers(bad)


class TheConfirmationIsASentence(unittest.TestCase):
    def test_it_says_the_day_the_hour_and_the_thing(self):
        said = speech.spoken_receipt(
            "remind_weekly",
            "weekly reminder remind-weekly-9f2 set for Monday at 09:00 "
            "— 'take out the trash'")
        self.assertEqual(said, "Every Monday at 9 am I'll remind you: take out the trash.")

    def test_a_group_does_not_get_an_every_in_front_of_it(self):
        said = speech.spoken_receipt(
            "remind_weekly",
            "weekly reminder r set for weekdays at 07:00 — 'log hours'")
        self.assertTrue(said.startswith("Weekdays at 7 am"), said)

    def test_a_24_hour_clock_is_a_display_not_a_sentence(self):
        self.assertEqual(speech.clock_words("09:00"), "9 am")
        self.assertEqual(speech.clock_words("18:30"), "6:30 pm")
        self.assertEqual(speech.clock_words("00:00"), "12 am")
        self.assertEqual(speech.clock_words("12:00"), "12 pm")
        # Never mangles something it does not understand.
        self.assertEqual(speech.clock_words("soon"), "soon")
        self.assertEqual(speech.clock_words("33:99"), "33:99")

    def test_the_daily_one_says_the_hour_the_same_way(self):
        said = speech.spoken_receipt(
            "remind_daily", "daily reminder r set for 08:00 — 'stretch'")
        self.assertIn("8 am", said)


class ItReallySchedules(unittest.TestCase):
    def test_the_command_creates_a_weekly_schedule(self):
        made = {}

        def create(sid, command, **kw):
            made.update({"id": sid, "command": command, **kw})
            return {}

        with mock.patch.object(scheduler, "create", create):
            said = intercom.execute_command(
                {"kind": "remind_weekly", "days": ["monday", "thursday"],
                 "time": "09:00", "text": "take out the trash"}, {})
        self.assertEqual(made["kind"], "weekly")
        self.assertEqual(made["weekdays"], [0, 3])
        self.assertEqual(made["time"], "09:00")
        self.assertEqual(made["command"]["kind"], "notify_operator")
        self.assertIn("Monday and Thursday", said)

    def test_the_scheduler_accepts_what_the_handler_builds(self):
        # The two have to agree about weekdays being unique ints 0..6 —
        # this is the contract `validate` enforces.
        scheduler.validate({"version": 1, "id": "remind-weekly-x", "kind": "weekly",
                            "command": {"kind": "notify_operator", "text": "x"},
                            "enabled": True, "created_at": "2026-09-07T00:00:00Z",
                            "updated_at": "2026-09-07T00:00:00Z",
                            "timezone": "America/Chicago",
                            "time": "09:00",
                            "weekdays": intercom._weekday_numbers(["mon", "thu"])})

    def test_it_is_routine_and_local_like_every_other_reminder(self):
        self.assertIn("remind_weekly", intercom.ROUTINE_KINDS)
        self.assertIn("remind_weekly", intercom.LOCAL_KINDS)
        self.assertEqual(intercom.tier("remind_weekly"),
                         intercom.tier("remind_daily"))


if __name__ == "__main__":
    unittest.main()
