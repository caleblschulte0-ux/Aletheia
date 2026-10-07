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


class WhatEmailsIsTheInbox(unittest.TestCase):
    def test_the_inbox(self):
        from aletheia import voice
        for said in ("what emails do i have", "what's new in my email"):
            self.assertEqual(voice._interpret(said)["command"]["kind"], "email_check", said)

    def test_a_persons_email_is_still_a_contact(self):
        from aletheia import voice
        self.assertEqual(voice._interpret("what's sam's email")["command"]["kind"], "contacts")


class CatchMeUpWithNoFleetReadingStillTellsHisDay(unittest.TestCase):
    def test_his_day(self):
        import pathlib
        import tempfile
        from unittest import mock
        from aletheia import intercom, pulse, quick
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(pulse, "PULSE_DIR", pathlib.Path(tmp)), \
                mock.patch.object(quick, "_waiting", return_value="Nothing needs you right now."), \
                mock.patch.object(quick, "_plan_today", return_value="1 task open. Next: call the bank."):
            said = intercom.execute_command({"kind": "brief"}, {"repos": {}}, quote="test")
        self.assertTrue(said.startswith("Nothing needs you right now. 1 task open. Next: call the bank."), said)


class SumsOnSumsAndDistances(unittest.TestCase):
    def test_round_that(self):
        from unittest import mock
        from aletheia import converse, quick
        turns = [{"he_asked": "what's 100 divided by 7", "she_answered": "14.2857."}]
        with mock.patch.object(converse, "recent", return_value=turns):
            self.assertEqual(quick.answer("round that"), "14.")
            self.assertEqual(quick.answer("round it to 2 decimal places"), "14.29.")
            self.assertEqual(quick.answer("round it up"), "15.")

    def test_degrees_with_no_scale_said(self):
        from aletheia import quick
        self.assertEqual(quick.answer("what's 72 degrees in celsius"), "22.2 degrees Celsius.")

    def test_a_race_is_a_distance_not_a_journey(self):
        from aletheia import quick, voice
        self.assertEqual(quick.answer("how far is a 5k in miles"), "A 5K is 5 kilometers, about 3.11 miles.")
        self.assertNotEqual((voice._interpret("how far is a 5k in miles").get("command") or {}).get("kind"), "travel_time")


class PushItBackAnHour(unittest.TestCase):
    def test_from_where_it_is(self):
        import datetime as dt
        from unittest import mock
        from aletheia import converse, intercom, voice
        at = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=3)
        spec = {"id": "r1", "kind": "once", "at": at.isoformat(), "enabled": True,
                "command": {"kind": "notify_operator", "text": "call mom"}}
        turns = [{"he_asked": "remind me to call mom in 3 hours", "she_answered": "I'll remind you..."}]
        with mock.patch.object(converse, "recent", return_value=turns), \
                mock.patch.object(intercom, "_one_reminder", return_value=(spec, "")):
            cmd = voice._interpret("push it back an hour")["command"]
        self.assertEqual(cmd["text"], "call mom")
        self.assertEqual(dt.datetime.fromisoformat(cmd["at"]), at + dt.timedelta(hours=1))

    def test_cancel_all_is_counted(self):
        from aletheia import speech
        said = speech.spoken_receipt("reminder_off", "reminder 1 off — 1 reminder: call mom — today at 9 am")
        self.assertEqual(said, "Cancelled 1 reminder: call mom — today at 9 am.")


class ContactsTheLongWayRound(unittest.TestCase):
    def test_add_to_my_contacts_with_a_number(self):
        from aletheia import voice
        cmd = voice._interpret("add sam to my contacts, his number is 555 222 3333")["command"]
        self.assertEqual((cmd["kind"], cmd["name"], cmd["phone"]), ("contact_add", "sam", "555 222 3333"))

    def test_an_email_is_not_a_number(self):
        from aletheia import voice
        cmd = voice._interpret("add jo to my contacts with email jo@example.com")["command"]
        self.assertEqual((cmd["kind"], cmd["email"]), ("contact_add", "jo@example.com"))

    def test_who_are_my_contacts(self):
        from aletheia import quick
        self.assertEqual(quick.match("who are my contacts")[0], "contacts_count")


class AContactCanBeTakenOut(unittest.TestCase):
    def test_hidden_not_deleted_and_back_when_added_again(self):
        from aletheia import contacts, intercom, voice
        run = lambda said: intercom.execute_command(voice._interpret(said)["command"], {"repos": {}}, quote="test")
        run("zed's number is 555 222 3333")
        self.assertIn("zed", [c["id"] for c in contacts.all_contacts()])
        self.assertEqual(voice._interpret("delete zed from my contacts")["command"]["kind"], "contact_remove")
        self.assertIn("removed", run("delete zed from my contacts"))
        self.assertNotIn("zed", [c["id"] for c in contacts.all_contacts()])
        self.assertIn("zed", [c["id"] for c in contacts.all_contacts(include_removed=True)])
        run("zed's number is 555 222 4444")
        self.assertIn("zed", [c["id"] for c in contacts.all_contacts()])

    def test_nobody_by_that_name(self):
        from aletheia import intercom, speech
        said = intercom.execute_command({"kind": "contact_remove", "name": "nobody-at-all"}, {"repos": {}}, quote="test")
        self.assertEqual(speech.spoken_receipt("contact_remove", said), "You have no contact called nobody-at-all.")


class HolidaysAndWorkdays(unittest.TestCase):
    def test_holidays_coming_up_are_listed(self):
        from aletheia import quick
        self.assertTrue(quick.answer("what holidays are coming up").startswith("Coming up: "))

    def test_weekdays_until_counts_monday_to_friday(self):
        from aletheia import quick
        said = quick.answer("how many weekdays until christmas")
        self.assertRegex(said, r"^\d+ weekdays between now and Friday 25 December")


class APackingListForATrip(unittest.TestCase):
    def test_the_sort_is_the_name(self):
        from aletheia import voice
        self.assertEqual(voice._interpret("make a packing list for my trip")["command"],
                         {"kind": "list_new", "list": "packing"})
        self.assertEqual(voice._interpret("start a list for the camping trip")["command"]["list"], "camping trip")


class HisDayLoggedAndAddedUp(unittest.TestCase):
    def notes(self, *texts):
        import datetime as dt
        now = dt.datetime.now(dt.timezone.utc).isoformat()
        return [{"ts": now, "text": t} for t in texts]

    def test_said_is_noted(self):
        from aletheia import voice
        for said, kept in (("i drank a glass of water", "I drank a glass of water"),
                           ("i ran 3 miles today", "I ran 3 miles"), ("i slept 7 hours", "I slept 7 hours")):
            self.assertEqual(voice._interpret(said)["command"], {"kind": "note", "text": kept}, said)

    def test_water_is_counted(self):
        from unittest import mock
        from aletheia import quick
        with mock.patch.object(quick, "_notes", return_value=self.notes("I drank a glass of water", "I drank two glasses of water")):
            self.assertEqual(quick.answer("how much water have i had today"), "3 glasses of water today.")

    def test_miles_and_km_add_up(self):
        from unittest import mock
        from aletheia import quick
        with mock.patch.object(quick, "_notes", return_value=self.notes("I ran 3 miles", "I ran 5 km")):
            self.assertEqual(quick.answer("how far did i run today"), "6.11 miles today.")

    def test_nothing_logged_says_how_to(self):
        from unittest import mock
        from aletheia import quick
        with mock.patch.object(quick, "_notes", return_value=[]):
            self.assertIn("I drank a glass of water", quick.answer("how much water have i had today"))
            self.assertEqual(quick.answer("did i work out today"), "Not that you've told me today.")


class TheClockElsewhereAskedOtherWays(unittest.TestCase):
    def test_how_far_ahead(self):
        from aletheia import quick
        self.assertIn("in Tokyo", quick.answer("how far ahead is tokyo"))
        self.assertIn("in Paris", quick.answer("what's the time difference with paris"))

    def test_there_is_the_place_just_asked_about(self):
        from unittest import mock
        from aletheia import quick
        with mock.patch.object(quick, "_previous_ask", return_value="what's the time in london"):
            self.assertIn("in London", quick.answer("what time is it there"))

    def test_when_its_noon_here(self):
        from aletheia import quick
        self.assertRegex(quick.answer("when it's noon here what time is it in paris"), r"in Paris\.$")


if __name__ == "__main__":
    unittest.main()
