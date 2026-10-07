"""A fact he says about himself is kept in his words and read back.

Found 2026-10-07 in the sandbox with every model off: "my favorite color
is blue", "Jess's birthday is March 3" went to the planner, and the
questions back went to a model while her journal could have held the
answer. Also: "help", "stop the timer" and "what's the date tomorrow".
"""
import unittest
from unittest import mock

from aletheia import quick, voice


class SaidAsAFact(unittest.TestCase):
    def test_a_fact_becomes_a_note_in_his_words(self):
        for said in ("my favorite color is blue", "Jess's birthday is March 3",
                     "my shoe size is 11", "my gate code is 4512"):
            with self.subTest(said=said):
                self.assertEqual(voice._interpret(said)["command"], {"kind": "note", "text": said})

    def test_a_complaint_is_not_a_fact(self):
        for said in ("my head is killing me", "my computer is slow", "my phone is dead"):
            with self.subTest(said=said):
                self.assertNotEqual((voice._interpret(said)["command"] or {}).get("kind"), "note")

    def test_a_password_is_refused_out_loud_not_kept_blank(self):
        out = voice._interpret("my wifi password is Hunter22")
        self.assertIsNone(out["command"])
        self.assertIn("password manager", out["say"])
        self.assertIn("password manager", quick.answer("what's my wifi password"))


class AskedBack(unittest.TestCase):
    NOTES = [{"text": "my favorite food is tacos"}, {"text": "my favorite color is blue"},
             {"text": "Jess's birthday is March 3"}]

    def test_by_all_its_words(self):
        with mock.patch.object(quick, "_notes", return_value=self.NOTES):
            self.assertEqual(quick.answer("what's my favorite color"), "You told me: your favorite color is blue.")
            self.assertEqual(quick.answer("what's my favorite food"), "You told me: your favorite food is tacos.")
            self.assertEqual(quick.answer("when is jess's birthday"), "You told me: Jess's birthday is March 3.")

    def test_nothing_on_file_is_said_as_nothing(self):
        with mock.patch.object(quick, "_notes", return_value=self.NOTES):
            self.assertIn("haven't told me your blood type", quick.answer("what is my blood type"))
            self.assertIn("haven't told me your favorite movie", quick.answer("what's my favorite movie"))


class SmallOnes(unittest.TestCase):
    def test_help(self):
        self.assertIn("Just talk to me", quick.answer("help"))
        self.assertIn("Just talk to me", quick.answer("what can i say"))

    def test_stop_the_timer_is_not_the_kill_switch(self):
        self.assertEqual(voice._interpret("stop the timer")["command"],
                         {"kind": "reminder_off", "which": "timer is up"})
        self.assertEqual(voice._interpret("stop")["command"]["kind"], "halt")

    def test_the_date_tomorrow(self):
        self.assertTrue(quick.answer("what's the date tomorrow").startswith("Tomorrow is"))




class SeveralThingsToDoAreSeveralTasks(unittest.TestCase):
    def test_a_list_of_things_to_do_splits(self):
        from aletheia import intercom
        self.assertEqual(intercom.task_parts("call mom, pay rent and buy stamps"),
                         ["call mom", "pay rent", "buy stamps"])

    def test_one_thing_with_an_and_in_it_stays_one(self):
        from aletheia import intercom
        for one in ("call mom and dad", "pay rent and utilities", "call the bank"):
            self.assertEqual(intercom.task_parts(one), [one])

    def test_the_receipt_counts_them(self):
        from aletheia import speech
        said = speech.spoken_receipt("task_new", "3 tasks queued — call mom, pay rent and buy stamps")
        self.assertEqual(said, "Added 3 tasks: call mom, pay rent and buy stamps.")




class ATimerJustSetIsStillItsLength(unittest.TestCase):
    def test_nine_fifty_nine_left_is_ten_minutes(self):
        import datetime as dt
        from unittest import mock
        from aletheia import intercom, voice
        now = dt.datetime(2026, 10, 7, 10, 0, 1, tzinfo=dt.timezone.utc)
        spec = {"kind": "once", "at": "2026-10-07T10:10:00+00:00",
                "command": {"kind": "notify_operator", "text": "your 10-minute timer is up"}}
        with mock.patch.object(intercom, "_reminder_schedules", return_value=[spec]):
            self.assertEqual(voice._timer_left(now), "10 minutes left on your 10-minute timer.")

    def test_a_running_timer_is_not_listed_as_gone_off(self):
        from aletheia import intercom
        spec = {"id": "r1", "kind": "once", "at": "2026-10-07T10:10:00+00:00",
                "command": {"kind": "notify_operator", "text": "your 10-minute timer is up"}}
        self.assertTrue(intercom._reminder_words(spec).startswith("your 10-minute timer, going off"))
        self.assertIn("timer is up", intercom._reminder_words(spec, receipt=True))


class WhatHeHasIncludesHisReminders(unittest.TestCase):
    def test_an_empty_calendar_still_says_the_reminder(self):
        from unittest import mock
        from aletheia import quick
        with mock.patch.object(quick, "_agenda", return_value="Nothing on your calendar tomorrow."), \
                mock.patch.object(quick, "_reminders_on", return_value="1 reminder tomorrow: 12 pm, call Jenna."):
            self.assertEqual(quick._agenda_and_reminders("tomorrow"),
                             "Nothing on your calendar tomorrow, but 1 reminder tomorrow: 12 pm, call Jenna.")

    def test_no_reminders_leaves_the_calendar_answer_alone(self):
        from unittest import mock
        from aletheia import quick
        with mock.patch.object(quick, "_agenda", return_value="Tomorrow: dentist at 3 pm."), \
                mock.patch.object(quick, "_reminders_on", return_value="No reminders tomorrow."):
            self.assertEqual(quick._agenda_and_reminders("tomorrow"), "Tomorrow: dentist at 3 pm.")


class WhenIsAHolidayLeadsWithTheDate(unittest.TestCase):
    def test_which_day_leads_with_the_day(self):
        from aletheia import quick
        name, rest = quick.match("what day is thanksgiving")
        self.assertEqual(name, "until_day")
        said = quick.answer("what day is thanksgiving")
        self.assertRegex(said, r"^[A-Z][a-z]+day \d+ November")

    def test_how_many_days_still_leads_with_the_count(self):
        from aletheia import quick
        self.assertEqual(quick.match("how many days until christmas")[0], "until")


class WhereHeParkedIsSaidToHim(unittest.TestCase):
    def test_his_first_person_becomes_hers(self):
        from unittest import mock
        from aletheia import quick
        with mock.patch.object(quick, "_notes", return_value=[{"text": "i parked on level 3 row b"}]):
            self.assertEqual(quick._parked(), "You parked on level 3 row b.")


class AReminderSetAsALengthMovesAsOne(unittest.TestCase):
    def test_make_it_25_after_in_20_minutes(self):
        import datetime as dt
        from unittest import mock
        from aletheia import converse, voice
        turns = [{"he_asked": "remind me in 20 minutes to check the oven",
                  "she_answered": "I'll remind you today at 5:28 am: check the oven."}]
        with mock.patch.object(converse, "recent", return_value=turns):
            said = voice._interpret("actually make it 25")
        cmd = said["command"]
        self.assertEqual((cmd["kind"], cmd["text"], cmd["replaces"]), ("remind_at", "check the oven", "check the oven"))
        left = dt.datetime.fromisoformat(cmd["at"]) - dt.datetime.now(dt.timezone.utc)
        self.assertAlmostEqual(left.total_seconds(), 25 * 60, delta=30)


class RemindersAreReadSoonestFirst(unittest.TestCase):
    def test_soonest_first(self):
        from aletheia import intercom, scheduler
        scheduler.create("t-later", {"kind": "notify_operator", "text": "later"}, kind="once",
                         at="2099-01-02T00:00:00+00:00")
        scheduler.create("t-sooner", {"kind": "notify_operator", "text": "sooner"}, kind="once",
                         at="2099-01-01T00:00:00+00:00")
        rows = [r for r in scheduler.all_schedules() if r["id"] in ("t-later", "t-sooner")]
        self.assertEqual([r["id"] for r in intercom._soonest_first(rows)], ["t-sooner", "t-later"])


class HowManyRemindersIsTheReminderList(unittest.TestCase):
    def test_counted_from_the_store(self):
        from aletheia import voice
        for said in ("how many reminders do i have", "how many timers are running"):
            self.assertEqual(voice._interpret(said)["command"]["kind"], "reminders", said)


class HowOldWillIBe(unittest.TestCase):
    def test_in_a_year_he_names(self):
        from unittest import mock
        from aletheia import quick
        with mock.patch.object(quick, "_birthday_on_file", return_value=(6, 4, 1995)):
            self.assertEqual(quick.answer("how old will i be in 2030"), "You'll turn 35 on June 4 2030, so 34 before that.")

    def test_without_the_year_he_was_born_she_asks_for_it(self):
        from unittest import mock
        from aletheia import quick
        with mock.patch.object(quick, "_birthday_on_file", return_value=(6, 4, None)):
            self.assertIn("year you were born", quick.answer("how old will i be in 2030"))


class MinutesFromNowIsAClock(unittest.TestCase):
    def test_from_now(self):
        from aletheia import quick
        self.assertRegex(quick.answer("what's 30 minutes from now"), r"^\d{1,2}(?::\d\d)? [ap]m")


class DoINeedMilkIsTheList(unittest.TestCase):
    def test_a_staple_not_on_the_list_is_a_no(self):
        from unittest import mock
        from aletheia import quick
        with mock.patch.object(quick, "_shopping_has", return_value="No - your shopping list is empty."):
            self.assertEqual(quick._shopping_need("milk"), "Milk isn't on your shopping list.")
            self.assertIsNone(quick._shopping_need("a visa"))


class WhoSomeoneIsToHimIsKept(unittest.TestCase):
    def test_a_role_and_a_name_is_a_note(self):
        from aletheia import voice
        for said in ("my doctor is dr patel", "my boss is sarah", "my locker code is 4412"):
            self.assertEqual(voice._interpret(said)["command"]["kind"], "note", said)

    def test_how_he_feels_about_them_is_not(self):
        from aletheia import voice
        for said in ("my boss is a jerk", "my vet is out today"):
            self.assertNotEqual((voice._interpret(said).get("command") or {}).get("kind"), "note", said)


class APluralDayIsEvery(unittest.TestCase):
    def test_on_weekdays(self):
        from aletheia import voice
        cmd = voice._interpret("remind me on weekdays at 8 to stand up")["command"]
        self.assertEqual((cmd["kind"], cmd["days"], cmd["time"], cmd["text"]),
                         ("remind_weekly", ["weekday"], "08:00", "stand up"))

    def test_on_mondays_at_the_end(self):
        from aletheia import voice
        cmd = voice._interpret("remind me to call the twins on mondays")["command"]
        self.assertEqual((cmd["kind"], cmd["days"]), ("remind_weekly", ["monday"]))


class WhatFilesHeMadeToday(unittest.TestCase):
    def test_only_the_window_he_named(self):
        import os
        import time
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from unittest import mock
        from aletheia import files, intercom, voice
        with TemporaryDirectory() as tmp:
            old = Path(tmp) / "old plan.docx"
            new = Path(tmp) / "budget.xlsx"
            old.write_text("x")
            new.write_text("x")
            week_ago = time.time() - 10 * 86400
            os.utime(old, (week_ago, week_ago))
            cmd = voice._interpret("what files did i make today")["command"]
            with mock.patch.object(files, "places", lambda: [("Documents", Path(tmp))]):
                said = intercom.execute_command(cmd, {"repos": {}}, quote="test")
        self.assertIn("1 file changed today", said)
        self.assertIn("budget", said)
        self.assertNotIn("old plan", said)


class GoingSomewhereIsAGoodbye(unittest.TestCase):
    def test_the_gym(self):
        from aletheia import quick
        self.assertEqual(quick.match("i'm going to the gym")[0], "farewell")

    def test_the_store_reads_the_list(self):
        from unittest import mock
        from aletheia import quick
        with mock.patch.object(quick, "_shopping", return_value="2 things on your shopping list: bread and eggs."):
            self.assertEqual(quick.answer("i'm going to the store"),
                             "See you. 2 things on your shopping list: bread and eggs.")

    def test_a_reason_after_it_is_not_swallowed(self):
        from aletheia import quick
        self.assertIsNone(quick.match("i'm going to the store to buy milk"))


if __name__ == "__main__":
    unittest.main()
