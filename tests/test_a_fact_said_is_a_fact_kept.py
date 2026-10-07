"""A fact he says about himself is kept in his words and read back.

Found 2026-10-07 in the sandbox with every model off: "my favorite color
is blue", "Jess's birthday is March 3" went to the planner, and the
questions back went to a model while her journal could have held the
answer. Also: "help", "stop the timer" and "what's the date tomorrow".
"""
import datetime as dt
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
            # The day he told her, with how far off it is now.
            self.assertRegex(quick.answer("when is jess's birthday"), r"^Jess's birthday is \w+ 3 March(?:, \d+ days away\.| - tomorrow\.| - that's today!)$")

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


class HerOwnHoldsCanBeMovedAndCancelled(unittest.TestCase):
    def run_it(self, said):
        from aletheia import intercom, speech, voice
        cmd = voice._interpret(said)
        if not cmd.get("command"):
            return cmd.get("say")
        return speech.spoken_receipt(cmd["command"]["kind"],
                                     intercom.execute_command(cmd["command"], {"repos": {}}, quote="test"))

    def test_move_then_cancel(self):
        self.assertIn("Pencilled in", self.run_it("put a meeting with quinn on my calendar on saturday at 2"))
        self.assertIn("3 pm", self.run_it("move my meeting with quinn to 3"))
        self.assertIn("off your calendar", self.run_it("cancel my meeting with quinn"))
        self.assertIn("can't cancel", self.run_it("cancel my meeting with quinn"))

    def test_his_live_calendar_is_never_touched(self):
        from unittest import mock
        from aletheia import calendar, voice
        live = {"id": "e1", "title": "dentist", "start": "2099-01-01T15:00:00+00:00", "status": "CONFIRMED", "source": "google"}
        with mock.patch.object(calendar, "all_events", return_value=[live]):
            self.assertEqual(voice._one_of_her_holds("dentist"), (None, ""))


class SmallGames(unittest.TestCase):
    def test_a_card(self):
        from aletheia import quick
        self.assertRegex(quick.answer("pick a card"), r"^The (?:Ace|\d+|Jack|Queen|King) of (?:hearts|diamonds|clubs|spades)\.$")

    def test_a_bare_throw_only_after_she_asked(self):
        from unittest import mock
        from aletheia import converse, quick
        with mock.patch.object(converse, "recent", return_value=[]):
            self.assertIsNone(quick.answer("paper"))
        asked = [{"he_asked": "rock paper scissors", "she_answered": "Say rock, paper or scissors, and I'll throw mine at the same time."}]
        with mock.patch.object(converse, "recent", return_value=asked):
            self.assertRegex(quick.answer("paper"), r"^(?:Rock|Paper|Scissors) - (?:a draw|you win|I win)\.$")


class MoreSums(unittest.TestCase):
    def test_each(self):
        from aletheia import quick
        for said, want in (("what's 50 minus 15 percent", "42.5."), ("what's 1000 divided by 3 rounded", "333."),
                           ("what's 1000 divided by 3 rounded to 2 decimal places", "333.33."),
                           ("how much is 12 dozen", "144."), ("what is 7 factorial", "5,040."),
                           ("what's 80 plus 10%", "88.")):
            self.assertEqual(quick.answer(said), want, said)


class WhatNotesMention(unittest.TestCase):
    def test_a_search_of_his_notes(self):
        from aletheia import quick
        self.assertEqual(quick.match("what notes mention wifi")[0], "note_search")


class MakeItTheAfternoon(unittest.TestCase):
    def test_a_part_of_the_day_is_a_time(self):
        import datetime as dt
        from unittest import mock
        from aletheia import converse, localtime, voice
        turns = [{"he_asked": "remind me to call the bank tomorrow", "she_answered": "I'll remind you tomorrow at 9 am: call the bank."}]
        with mock.patch.object(converse, "recent", return_value=turns):
            cmd = voice._interpret("make it the afternoon")["command"]
        at = dt.datetime.fromisoformat(cmd["at"]).astimezone(localtime.operator_tz())
        self.assertEqual((cmd["text"], at.hour), ("call the bank", 14))


class APlaceSaidIsAPlaceKept(unittest.TestCase):
    """"The gym is at 20 Oak Ave", then "where is the gym" searched his
    Documents for a file called gym, and "how long to the gym" asked him
    to name a place he had just named."""

    def setUp(self):
        import tempfile
        from pathlib import Path
        from aletheia import places
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        for name, value in (("PLACES_DIR", root / "d"), ("TRAVEL_DIR", root / "t")):
            patcher = mock.patch.object(places, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.addCleanup(self.tmp.cleanup)

    run_it = HerOwnHoldsCanBeMovedAndCancelled.run_it

    def test_said_then_asked(self):
        self.assertEqual(self.run_it("the gym is at 20 Oak Ave"), "Got it - the gym is at 20 Oak Ave.")
        self.assertEqual(self.run_it("where is the gym"), "The gym is at 20 Oak Ave.")
        self.assertEqual(quick.answer("where's the gym"), "The gym is at 20 Oak Ave.")
        trip = self.run_it("how long to get to the gym")
        self.assertTrue(trip.startswith("The gym is at 20 Oak Ave."), trip)
        self.assertIn("won't guess", trip)

    def test_work_and_a_friends_house(self):
        self.run_it("my work address is 400 Main Street")
        self.assertEqual(quick.answer("what's my work address"), "Work is at 400 Main Street.")
        self.assertIn("Say \"Sam's house is at\"", self.run_it("where is sam's house"))
        self.run_it("sam's house is at 9 pine road")
        self.assertEqual(self.run_it("where is sam's house"), "Sam's house is at 9 pine road.")

    def test_a_file_is_still_a_file(self):
        self.assertEqual(voice._interpret("where is my resume")["command"]["kind"], "file_find")
        self.assertNotEqual((voice._interpret("the meeting is at 3 pm")["command"] or {}).get("kind"), "place_add")


class TheNextOneIsOne(unittest.TestCase):
    def test_the_soonest_not_the_list(self):
        from aletheia import intercom
        rows = [{"id": "a", "command": {"text": "wake up"}}, {"id": "b", "command": {"text": "stretch"}},
                {"id": "c", "command": {"text": "wake up"}}]
        words = {"a": "wake up — today at 6:30 am", "b": "stretch — today at 6:20 am", "c": "wake up — today at 7 am"}
        with mock.patch.object(intercom, "_reminder_schedules", return_value=rows), \
             mock.patch.object(intercom, "_soonest_first", side_effect=lambda r: sorted(r, key=lambda x: "bac".index(x["id"]))), \
             mock.patch.object(intercom, "_reminder_words", side_effect=lambda r, **_: words[r["id"]]):
            self.assertEqual(voice._interpret("when is my next alarm")["say"],
                             "Your next alarm is today at 6:30 am. You have 1 more after it.")
            self.assertTrue(voice._interpret("what's my next reminder")["say"].startswith("Your next reminder: "))
            self.assertEqual(voice._interpret("next timer")["say"], "You have no timers set.")


class TheListHeMeant(unittest.TestCase):
    def test_buy_is_not_part_of_the_thing(self):
        self.assertEqual(voice._interpret("add buy milk to my list")["command"],
                         {"kind": "shopping_add", "item": "milk"})

    def test_an_empty_task_list_points_at_the_shopping_one(self):
        from aletheia import intercom
        with mock.patch.object(intercom, "_open_tasks", return_value=[]), \
             mock.patch.object(intercom, "_shopping_items", return_value=[{"id": "s1", "need": "milk"}]):
            self.assertEqual(intercom._tasks_answer(), "Nothing on your task list. 1 thing on your shopping list: milk.")

    def test_how_am_i_doing(self):
        with mock.patch.object(quick, "_tasks_done", return_value="Nothing ticked off your list today."), \
             mock.patch.object(quick, "_tasks", return_value="1 task open. Next: call the bank."):
            self.assertEqual(quick.answer("how am i doing on my tasks"),
                             "Nothing ticked off yet today. 1 task open. Next: call the bank.")

    def test_a_call_says_the_number_she_has(self):
        from aletheia import contacts
        with mock.patch.object(contacts, "resolve", return_value={"display_name": "mom", "phones": ["5551234567"]}):
            said = voice._interpret("call mom")["say"]
        self.assertIn("Mom's number is", said)
        with mock.patch.object(contacts, "resolve", side_effect=KeyError("no")):
            self.assertIn("text or email your dentist", voice._interpret("call my dentist")["say"])


class OneMilkNotTwo(unittest.TestCase):
    """"Add milk" twice made two milks, and "I bought milk" then asked
    "Which one - milk or milk?"; "mark milk done" looked only at tasks."""

    def setUp(self):
        import tempfile
        from pathlib import Path
        from aletheia import shopping
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        names = [n for n in dir(shopping) if n.isupper() and isinstance(getattr(shopping, n), Path)]
        for name in names:
            patcher = mock.patch.object(shopping, name, Path(self.tmp.name) / name.lower())
            patcher.start()
            self.addCleanup(patcher.stop)

    def say(self, said):
        from aletheia import intercom, speech
        cmd = voice._interpret(said)
        if not cmd.get("command"):
            return cmd.get("say")
        return speech.spoken_receipt(cmd["command"]["kind"],
                                     intercom.execute_command(cmd["command"], {"repos": {}}, quote=said))

    def test_twice_is_once(self):
        self.assertEqual(self.say("add milk"), "Added to the shopping list: milk.")
        self.assertEqual(self.say("add milk"), "Already on your shopping list: milk.")
        self.assertEqual(self.say("add eggs and milk"),
                         "Added to the shopping list: eggs. Already on it: milk.")
        self.assertIn("milk", self.say("i bought milk"))
        self.assertIn("eggs", self.say("mark eggs done"))
        from aletheia import intercom
        self.assertEqual(intercom._shopping_items(), [])


class DaysThatMeanOneDay(unittest.TestCase):
    def test_in_n_days_and_the_end_of_the_month(self):
        import datetime as dt
        from aletheia import localtime
        today = localtime.today()
        self.assertEqual(voice._spoken_day("in 3 days"), (today + dt.timedelta(days=3)).isoformat())
        self.assertEqual(voice._spoken_day("in two weeks"), (today + dt.timedelta(days=14)).isoformat())
        self.assertTrue(voice._spoken_day("the end of the month").startswith(today.isoformat()[:8]))
        self.assertEqual(voice._interpret("add a task to renew my passport in 2 weeks")["command"]["deadline"],
                         (today + dt.timedelta(days=14)).isoformat())
        # "Next Friday" is still asked about, never guessed.
        self.assertIsNone(voice._spoken_day("next friday"))


class WhenItIsDue(unittest.TestCase):
    def test_the_task_he_names(self):
        from aletheia import tasks
        rows = [{"id": "t1", "description": "renew my passport", "status": "PENDING", "deadline": "2099-10-21"},
                {"id": "t2", "description": "clean the garage", "status": "PENDING"}]
        with mock.patch.object(tasks, "all_tasks", return_value=rows), \
             mock.patch.object(tasks, "is_his", return_value=True):
            said = quick.answer("when is my passport task due")
            self.assertTrue(said.startswith("Renew my passport is due"), said)
            self.assertNotIn("11:59", said)
            self.assertIn("no due date", quick.answer("when do i need to clean the garage by"))


class MakeItAnotherDay(unittest.TestCase):
    def setUp(self):
        from aletheia import converse
        turns = [{"he_asked": "remind me to call the vet on saturday at 10",
                  "she_answered": "I'll remind you Saturday at 10 am: call the vet."}]
        patcher = mock.patch.object(converse, "recent", return_value=turns)
        patcher.start()
        self.addCleanup(patcher.stop)

    def at(self, said, stored=None):
        import datetime as dt
        from aletheia import intercom, localtime
        found = ({"kind": "once", "at": stored}, "") if stored else (None, "none")
        with mock.patch.object(intercom, "_one_reminder", return_value=found):
            cmd = voice._interpret(said)["command"]
        return dt.datetime.fromisoformat(cmd["at"]).astimezone(localtime.operator_tz())

    def test_a_day_keeps_the_time(self):
        import datetime as dt
        from aletheia import localtime
        # Three days on, whatever today is: a fixed weekday is a date bomb.
        day = (localtime.today() + dt.timedelta(days=3)).strftime("%A")
        at = self.at(f"actually make it {day.lower()}")
        self.assertEqual((at.strftime("%A"), at.hour), (day, 10))

    def test_a_bare_hour_after_a_morning_one_is_the_afternoon(self):
        at = self.at("make it 4")
        self.assertEqual(at.hour, 16)

    def test_the_stored_day_wins_over_the_first_sentence(self):
        import datetime as dt
        from aletheia import localtime
        moved = (dt.datetime.now(localtime.operator_tz()) + dt.timedelta(days=20)).replace(hour=10, minute=0)
        at = self.at("make it 4", stored=moved.isoformat())
        self.assertEqual((at.date(), at.hour), (moved.date(), 16))




class WhatsForDinner(unittest.TestCase):
    def test_what_he_likes_first(self):
        with mock.patch.object(quick, "_notes", return_value=[{"text": "my favorite food is tacos"}]):
            self.assertEqual(quick.answer("what should i have for dinner"),
                             "How about tacos? You told me that's your favorite.")

    def test_otherwise_an_idea_said_as_one(self):
        with mock.patch.object(quick, "_notes", return_value=[]):
            said = quick.answer("what's for dinner")
        self.assertTrue(said.startswith("How about "), said)
        self.assertIn("Just an idea", said)


class BusyIsNotFree(unittest.TestCase):
    def test_the_answer_reads_right_either_way(self):
        from aletheia import calendar as cal, intercom
        with mock.patch.object(cal, "conflicts", return_value=[]), \
                mock.patch.object(cal, "all_events", return_value=[{"start": "2026-10-01T09:00:00-05:00"}]):
            said = intercom.free_time_answer({"day": "2026-10-09", "at": "15:00", "tz": "America/Chicago"})
        # "Am I busy at 3" and "am I free at 3" are one command.
        self.assertFalse(said.startswith(("Yes", "No")), said)
        self.assertEqual(voice._interpret("am i busy at 3")["command"]["kind"], "free_time")

    def test_book_a_meeting_with_a_person_is_his_diary(self):
        self.assertEqual(voice._interpret("book a meeting with dana tomorrow at 11")["command"]["kind"],
                         "calendar_hold")
        self.assertNotEqual((voice._interpret("book a table for two tomorrow at 7")["command"] or {}).get("kind"),
                            "calendar_hold")


class BirthdaysHeToldHer(unittest.TestCase):
    def notes(self):
        import datetime as dt
        from aletheia import localtime
        today = localtime.today()
        soon, later = today + dt.timedelta(days=10), today + dt.timedelta(days=40)
        return [{"text": f"my mom's birthday is {later.strftime('%B').lower()} {later.day}"},
                {"text": f"Jess's birthday is {soon.strftime('%B')} {soon.day}"}], soon, later

    def test_when_and_who(self):
        rows, soon, later = self.notes()
        with mock.patch.object(quick, "_notes", return_value=rows):
            self.assertTrue(quick.answer("when is jess's birthday").endswith("10 days away."))
            self.assertTrue(quick.answer("when is mom's birthday").startswith("Your mom's birthday is"))
            said = quick.answer("whose birthday is coming up")
        self.assertTrue(said.startswith("Birthdays coming up: Jess on"), said)
        self.assertIn("your mom on", said)

    def test_none_told_is_said(self):
        with mock.patch.object(quick, "_notes", return_value=[]):
            self.assertIn("haven't told me anybody's birthday", quick.answer("any birthdays coming up"))
            self.assertIn("haven't told me your mom's birthday", quick.answer("when is mom's birthday"))


class ARemindBeforeABirthday(unittest.TestCase):
    def test_the_day_before_at_nine(self):
        import datetime as dt
        from aletheia import localtime
        later = localtime.today() + dt.timedelta(days=40)
        rows = [{"text": f"my mom's birthday is {later.strftime('%B').lower()} {later.day}"}]
        with mock.patch.object(quick, "_notes", return_value=rows):
            cmd = voice._interpret("remind me a day before mom's birthday")["command"]
        at = dt.datetime.fromisoformat(cmd["at"]).astimezone(localtime.operator_tz())
        self.assertEqual((at.date(), at.hour), (later - dt.timedelta(days=1), 9))
        self.assertEqual(cmd["text"], "your mom's birthday is tomorrow")

    def test_unknown_says_how(self):
        with mock.patch.object(quick, "_notes", return_value=[]):
            said = voice._interpret("remind me on sam's birthday")["say"]
        self.assertIn('Say "Sam\'s birthday is"', said)

    def test_an_apostrophe_is_read_out_not_the_receipt(self):
        from aletheia import speech
        said = speech.spoken_receipt("remind_at", 'reminder set for 2099-01-01T17:00:00+00:00 — "call Jess\'s mom"')
        self.assertTrue(said.startswith("I'll remind you"), said)
        self.assertIn("call Jess's mom", said)


class HowLongUntilIt(unittest.TestCase):
    def test_in_hours_and_minutes(self):
        import datetime as dt
        from aletheia import intercom, scheduler
        now = dt.datetime.now(dt.timezone.utc)
        rows = [{"id": "a", "command": {"text": "wake up"}}]
        with mock.patch.object(intercom, "_reminder_schedules", return_value=rows), \
             mock.patch.object(scheduler, "next_occurrence", return_value=now + dt.timedelta(hours=24, minutes=30, seconds=20)):
            self.assertEqual(voice._interpret("how long until my alarm")["say"],
                             "Your next alarm goes off in 24 hours and 30 minutes.")


class ListsSpokenToAsIt(unittest.TestCase):
    def setUp(self):
        import tempfile
        from pathlib import Path
        from aletheia import converse, lists, shopping
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        for mod, name in ((shopping, "SHOP_DIR"),):
            p = mock.patch.object(mod, name, root / "shop")
            p.start()
            self.addCleanup(p.stop)
        p = mock.patch.object(lists, "private_dir", side_effect=lambda sub: root / sub)
        p.start()
        self.addCleanup(p.stop)
        self.turns = []
        p = mock.patch.object(converse, "recent", side_effect=lambda limit=3: self.turns[-limit:])
        p.start()
        self.addCleanup(p.stop)

    def say(self, said):
        from aletheia import intercom, speech
        cmd = voice._interpret(said)
        out = cmd.get("say") if not cmd.get("command") else speech.spoken_receipt(
            cmd["command"]["kind"], intercom.execute_command(cmd["command"], {"repos": {}}, quote=said))
        self.turns.append({"he_asked": said, "she_answered": out})
        return out

    def test_it_is_the_list_just_made(self):
        self.say("make a grocery list")
        self.assertEqual(self.say("add apples to it"), "Added to the shopping list: apples.")
        self.assertIn("weekend list", self.say("make a to do list for the weekend"))
        self.assertEqual(self.say("add mow the lawn to it"), "Added to your weekend list: mow the lawn.")
        self.assertIn("And your shopping list has 1 thing", self.say("what lists do i have"))

    def test_delete_means_the_list(self):
        self.say("make a list called weekend")
        self.say("add mow the lawn to my weekend list")
        self.assertIn("Deleted your weekend list", self.say("delete my weekend list"))
        self.assertNotIn("weekend", self.say("what lists do i have"))
        self.assertIn("empty", self.say("clear my packing list") + self.say("make a list called weekend")
                      + self.say("what's on my weekend list"))


class KitchenSums(unittest.TestCase):
    def test_each(self):
        for said, expected in (("what's half of 3 and a quarter", "1 and 5/8."),
                               ("double 2 and a half cups", "5 cups."),
                               ("what's 3/4 plus 1/2", "1 and a quarter."),
                               ("what's a third of 2 cups", "Two thirds of a cup."),
                               ("triple 1 1/2 teaspoons", "4 and a half teaspoons."),
                               ("1/2 times 1/3", "1/6.")):
            with self.subTest(said=said):
                self.assertEqual(quick.answer(said), expected)
        self.assertEqual(quick.answer("what's 2 plus 2"), "4.")


class TimersByName(unittest.TestCase):
    def specs(self):
        import datetime as dt
        now = dt.datetime.now(dt.timezone.utc)
        return [{"id": "a", "kind": "once", "enabled": True, "at": (now + dt.timedelta(minutes=3)).isoformat(),
                 "command": {"text": "your 3 minute eggs timer is up"}},
                {"id": "b", "kind": "once", "enabled": True, "at": (now + dt.timedelta(minutes=10)).isoformat(),
                 "command": {"text": "your 10 minute pasta timer is up"}}]

    def test_the_length_said_first(self):
        cmd = voice._interpret("set a 10 minute timer for the pasta")["command"]
        self.assertEqual(cmd["text"], "your 10 minute pasta timer is up")
        self.assertEqual(voice._interpret("set a 5 minute timer")["command"]["text"], "your 5 minute timer is up")

    def test_the_one_he_names(self):
        from aletheia import intercom, scheduler
        rows = self.specs()
        with mock.patch.object(intercom, "_reminder_schedules", return_value=rows), \
             mock.patch.object(scheduler, "all_schedules", return_value=rows), \
             mock.patch.object(scheduler, "next_occurrence",
                               side_effect=lambda spec, now: __import__("datetime").datetime.fromisoformat(spec["at"])):
            self.assertEqual(voice._interpret("how long on the pasta")["say"],
                             "10 minutes left on the pasta timer.")
            self.assertTrue(voice._interpret("how long left on the rice")["say"].startswith("You don't have a rice timer."))
            cmd = voice._interpret("add 2 minutes to the pasta timer")["command"]
            self.assertEqual(cmd["replaces"], "your 10 minute pasta timer is up")
            self.assertIn("eggs timer", voice._interpret("what timers do i have")["say"])


class PutThatBack(unittest.TestCase):
    """Every comment beside reminder_off promised "put that back" was one
    command; it went to the planner (2026-10-07)."""

    def setUp(self):
        import tempfile
        from pathlib import Path
        from aletheia import converse, scheduler
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        names = [n for n in dir(scheduler) if n.isupper() and isinstance(getattr(scheduler, n), Path)]
        for name in names:
            p = mock.patch.object(scheduler, name, Path(self.tmp.name) / name.lower())
            p.start()
            self.addCleanup(p.stop)
        self.turns = []
        p = mock.patch.object(converse, "recent", side_effect=lambda limit=3: self.turns[-limit:])
        p.start()
        self.addCleanup(p.stop)

    def say(self, said):
        from aletheia import intercom, speech
        cmd = voice._interpret(said)
        out = cmd.get("say") if not cmd.get("command") else speech.spoken_receipt(
            cmd["command"]["kind"], intercom.execute_command(cmd["command"], {"repos": {}}, quote=said))
        self.turns.append({"he_asked": said, "she_answered": out})
        return out

    def test_stopped_then_put_back(self):
        self.say("remind me every morning to drink water")
        self.assertIn("Stopped reminding you", self.say("stop the water reminder"))
        self.assertTrue(self.say("actually put that back").startswith("Back on: drink water"))
        self.assertIn("drink water", self.say("what reminders do i have"))

    def test_paused_then_all_back(self):
        self.say("remind me every morning to drink water")
        self.say("pause my reminders")
        self.assertEqual(self.say("what reminders do i have"), "You have no reminders set.")
        self.assertTrue(self.say("turn my reminders back on").startswith("Back on:"))


class MoneyBetweenPeople(unittest.TestCase):
    def test_said_is_noted(self):
        for said in ("i owe sam 20 dollars", "jess owes me 15 for lunch", "sam paid me back", "i lent jess 40 dollars"):
            with self.subTest(said=said):
                self.assertEqual(voice._interpret(said)["command"]["kind"], "note")

    def test_added_up_and_settled(self):
        notes = [{"text": "i paid sam back"}, {"text": "jess owes me 15 for lunch"}, {"text": "i owe sam 20 dollars"}]
        with mock.patch.object(quick, "_notes", return_value=notes[1:]):
            self.assertEqual(quick.answer("who do i owe money"), "You owe Sam $20. Jess owes you $15.")
            self.assertEqual(quick.answer("how much do i owe sam"), "You owe Sam $20.")
        with mock.patch.object(quick, "_notes", return_value=notes):
            self.assertEqual(quick.answer("who do i owe"), "You don't owe anybody that you've told me about. Jess owes you $15.")
            self.assertEqual(quick.answer("does jess owe me money"), "Jess owes you $15.")


class TheCalendarBackwards(unittest.TestCase):
    def test_was_reads_back(self):
        import datetime as dt
        from aletheia import localtime
        today = localtime.today()
        said = quick.answer("what day was july 4 this year")
        self.assertTrue(said.startswith(f"July 4, {today.year} "), said)
        last = quick.answer("what day was christmas last year")
        self.assertTrue(last.startswith(f"December 25, {today.year - 1} was a "), last)
        self.assertIn(dt.date(1990, 7, 4).strftime("%A"), quick.answer("what day was july 4 1990"))

    def test_time_ago_and_weekday(self):
        self.assertRegex(quick.answer("what time was it 3 hours ago"), r"^\d{1,2}(?::\d\d)? [ap]m(?: yesterday)?\.$")
        self.assertRegex(quick.answer("is today a weekday"), r"^(?:Yes|No)")


class ThingsHeDid(unittest.TestCase):
    def test_said_is_noted(self):
        for said in ("i changed the oil today", "i gave the dog his medicine", "my license expires june 2027",
                     "i watered the plants"):
            with self.subTest(said=said):
                self.assertEqual(voice._interpret(said)["command"]["kind"], "note")
        self.assertEqual(voice._interpret("did i get any emails")["command"]["kind"], "email_check")

    def test_asked_back(self):
        import datetime as dt
        now = dt.datetime.now(dt.timezone.utc).isoformat()
        with mock.patch.object(quick, "_notes", return_value=[{"text": "i changed the oil today", "ts": now}]):
            said = quick.answer("when did i last change the oil")
            self.assertTrue(said.startswith("You told me you changed the oil - that was today"), said)
            self.assertTrue(quick.answer("did i change the oil today").startswith("Yes"))
        with mock.patch.object(quick, "_notes", return_value=[]):
            self.assertIn('Say "I watered the plants"', quick.answer("have i watered the plants"))


class SendItIsApproveIt(unittest.TestCase):
    def test_same_gate_his_words(self):
        from aletheia import policy
        with mock.patch.object(policy, "all_approvals", return_value=[]):
            self.assertEqual(voice._interpret("send it")["say"], "There's nothing waiting to send.")
            self.assertEqual(voice._interpret("approve it")["say"], "Nothing is waiting for approval.")
        pending = [{"id": "ap-1", "state": "PENDING", "capability": "email.send"}]
        with mock.patch.object(policy, "all_approvals", return_value=pending), \
             mock.patch.object(voice, "_asked_recently", return_value=True), \
             mock.patch.object(voice, "_approve_by_voice", side_effect=lambda a: {"command": {"kind": "approve", "id": a["id"]}}):
            self.assertEqual(voice._interpret("yes send it")["command"], {"kind": "approve", "id": "ap-1"})


class AnAlarmNamedByItsTime(unittest.TestCase):
    """"Cancel my 6:30 alarm" with two alarms set asked "Which one - wake up
    or wake up?", and the sentence had named it."""

    def setUp(self):
        from zoneinfo import ZoneInfo
        from aletheia import intercom, speech
        zone = ZoneInfo("America/Chicago")
        day = dt.datetime.now(zone).date() + dt.timedelta(days=1)
        def at(h, m):
            return dt.datetime(day.year, day.month, day.day, h, m, tzinfo=zone).astimezone(dt.timezone.utc).isoformat()
        self.rows = [
            {"id": "r-a", "kind": "once", "at": at(6, 30), "command": {"kind": "notify_operator", "text": "wake up"}},
            {"id": "r-b", "kind": "once", "at": at(7, 15), "command": {"kind": "notify_operator", "text": "wake up"}},
            {"id": "r-c", "kind": "daily", "time": "17:00", "command": {"kind": "notify_operator", "text": "call mom"}},
        ]
        for target, name, value in ((intercom, "_reminder_schedules", lambda: list(self.rows)),
                                    (speech, "_operator_zone", lambda: zone)):
            patcher = mock.patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.one = intercom._one_reminder

    def test_the_time_picks_the_alarm(self):
        self.assertEqual(self.one("wake up 6:30")[0]["id"], "r-a")
        self.assertEqual(self.one("wake up 7:15 am")[0]["id"], "r-b")
        self.assertEqual(self.one("5 pm")[0]["id"], "r-c")
        self.assertEqual(self.one("call mom at 5:00")[0]["id"], "r-c")

    def test_two_alike_are_told_apart_by_when(self):
        found, why = self.one("wake up")
        self.assertIsNone(found)
        self.assertNotIn("wake up or wake up", why)
        self.assertRegex(why, r"6:30")

    def test_a_time_with_nothing_set_says_so(self):
        found, why = self.one("wake up 9:45")
        self.assertIsNone(found)
        self.assertIn("nothing set for", why)

    def test_the_sentence_carries_the_time(self):
        for said, which in (("cancel my 6:30 alarm", "wake up 6:30"),
                            ("turn off my alarm for 7 am", "wake up 7 am"),
                            ("delete my alarm", "wake up")):
            with self.subTest(said=said):
                got = (voice.interpret(said) or {}).get("command") or {}
                self.assertEqual(got, {"kind": "reminder_off", "which": which})


class HisTextsReadBack(unittest.TestCase):
    """"Read my last text" went to a model that had never seen a text, while
    the answer to "who called me" offered to read them."""

    ROWS = [{"from": "Sam", "text": "running 10 min late", "when": "10:42 AM", "code": ""},
            {"from": "Mom", "text": "Call me when you can?", "when": "Yesterday", "code": ""}]

    def run_it(self, state="ok", rows=None, **args):
        from aletheia import gvoice, intercom
        with mock.patch.object(gvoice, "check", return_value=(state, "why")), \
                mock.patch.object(gvoice, "recent", return_value=list(self.ROWS if rows is None else rows)):
            return intercom.execute_command({"kind": "texts_read", **args}, {}, quote="test")

    def test_newest_first_and_by_sender(self):
        said = self.run_it()
        self.assertIn("Sam, 10:42 AM: running 10 min late.", said)
        self.assertLess(said.index("Sam"), said.index("Mom"))
        self.assertNotIn("?.", said)
        self.assertEqual(self.run_it(who="mom"), "Your last text is from Mom, Yesterday: Call me when you can?")
        self.assertIn("from Dana", self.run_it(who="Dana"))

    def test_signed_out_says_so_and_never_says_no_texts(self):
        from aletheia import act, gvoice
        with self.assertRaisesRegex(act.Refused, "not signed in to Google Voice"):
            self.run_it(state=gvoice.NOT_SIGNED_IN)
        self.assertNotIn("No texts", self.run_it(rows=[]))

    def test_the_sentences(self):
        for said, cmd in (("read my last text", {"kind": "texts_read"}),
                          ("any new texts", {"kind": "texts_read"}),
                          ("did Sam text me", {"kind": "texts_read", "who": "Sam"}),
                          ("what did my mom text me about", {"kind": "texts_read", "who": "mom"})):
            with self.subTest(said=said):
                self.assertEqual((voice.interpret(said) or {}).get("command"), cmd)


class TheAnswerToWhichOne(unittest.TestCase):
    """"Cancel my alarm" -> "Which one - 6:30 or 7:15?" -> "the 7:15 one"
    went to the planner, which had not heard the question."""

    def said(self, he, she, now):
        from aletheia import converse
        turns = [{"he_asked": he, "she_answered": she}]
        with mock.patch.object(converse, "recent", return_value=turns):
            return (voice.interpret(now) or {}).get("command")

    def test_a_time_or_a_count_names_the_one(self):
        asked = "Which one — tomorrow at 6:30 am or tomorrow at 7:15 am?"
        self.assertEqual(self.said("cancel my alarm", asked, "the 7:15 one"),
                         {"kind": "reminder_off", "which": "wake up 7:15"})
        self.assertEqual(self.said("cancel my alarm", asked, "the second one"),
                         {"kind": "reminder_off", "which": "wake up tomorrow at 7:15 am"})
        self.assertEqual(self.said("cancel the call reminder", "Which one — call mom or call dad?", "dad"),
                         {"kind": "reminder_off", "which": "dad"})

    def test_without_her_question_nothing_changes(self):
        self.assertNotEqual((self.said("cancel my alarm", "Alarm off: tomorrow at 6:30 am.", "the 7:15 one")
                             or {}).get("kind"), "reminder_off")


class ASpokenListHasNoCommas(unittest.TestCase):
    """Speech-to-text writes "add milk eggs and bread", and that went to the
    planner because "milk eggs" read as one thing with a long name."""

    def test_a_run_of_plain_things_is_a_list(self):
        from aletheia import intercom
        self.assertEqual(intercom.shopping_items_of("milk eggs and bread"), ["milk", "eggs", "bread"])
        self.assertEqual(intercom.shopping_items_of("eggs milk butter and cheese"),
                         ["eggs", "milk", "butter", "cheese"])
        for one in ("salt and vinegar chips", "oat milk and eggs", "peanut butter eggs and bread"):
            self.assertEqual(len(intercom.shopping_items_of(one)), 1, one)
        self.assertEqual(voice.interpret("add milk eggs and bread to my list")["command"]["kind"], "shopping_add")


class HealthReadingsLiveOnHisPhone(unittest.TestCase):
    def test_steps_are_answered_honestly(self):
        for said in ("how many steps did i take", "what's my heart rate", "did i hit my steps goal"):
            got = voice.interpret(said)
            self.assertIsNone(got["command"], said)
            self.assertIn("phone or watch", got["say"])


class AnAlarmMovedAndSnoozed(unittest.TestCase):
    def test_change_my_alarm_replaces_the_one_he_named(self):
        from aletheia import localtime
        tz = localtime.operator_tz()
        day = dt.datetime.now(tz).date() + dt.timedelta(days=2)
        two = [(dt.datetime(day.year, day.month, day.day, 6, 30, tzinfo=tz), "wake up"),
               (dt.datetime(day.year, day.month, day.day, 8, 0, tzinfo=tz), "wake up")]
        with mock.patch.object(voice, "_running_once", return_value=two):
            got = voice.interpret("change my 6:30 alarm to 7")["command"]
            self.assertEqual((got["kind"], got["text"], got["replaces"]), ("remind_at", "wake up", "wake up 06:30"))
            self.assertTrue(got["at"].startswith(f"{day.isoformat()}T07:00"), got["at"])
            self.assertIn("say which", voice.interpret("move my alarm to 6:45")["say"])
            self.assertIn("don't have an alarm at 9", voice.interpret("change my 9 alarm to 10")["say"])

    def test_snooze_names_what_went_off(self):
        for said, minutes in (("snooze my alarm for 10 minutes", 10), ("snooze that reminder", 15),
                              ("snooze for 5", 5), ("snooze the alarm", 15)):
            with self.subTest(said=said):
                self.assertEqual(voice.interpret(said)["command"], {"kind": "notify_snooze", "minutes": minutes})


class AReminderSaidAnotherWay(unittest.TestCase):
    def test_set_a_reminder_for_a_time_to(self):
        got = voice.interpret("set a reminder for 3 to call Bob")["command"]
        self.assertEqual((got["kind"], got["text"]), ("remind_at", "call Bob"))

    def test_a_bare_number_after_in_is_minutes(self):
        got = voice.interpret("remind me to check the oven in 20")["command"]
        at = dt.datetime.fromisoformat(got["at"])
        self.assertAlmostEqual((at - dt.datetime.now(dt.timezone.utc)).total_seconds(), 1200, delta=10)

    def test_a_when_with_no_what_asks_for_the_what(self):
        for said in ("remind me at noon tomorrow", "remind me tomorrow at 5"):
            got = voice.interpret(said)
            self.assertIsNone(got["command"], said)
            self.assertIn("Remind you of what", got["say"])


class AForecastByDayIsNotAPlace(unittest.TestCase):
    """"What's the forecast for Saturday" looked up a town called Saturday."""

    def test_a_day_is_a_when(self):
        for said in ("what's the forecast for saturday", "what's the weather for tomorrow"):
            self.assertNotEqual(quick.match(said)[0], "weather_in", said)
        self.assertEqual(quick.match("what's the weather in denver")[0], "weather_in")
        self.assertEqual(quick.match("will it be nice this weekend"), ("weather", "this weekend"))
        self.assertEqual(quick.match("weather this weekend"), ("weather", "this weekend"))


class DaysLeftInTheMonth(unittest.TestCase):
    def test_the_month_and_the_year(self):
        from aletheia import localtime
        today = dt.datetime.now(localtime.operator_tz()).date()
        nxt = dt.date(today.year + (today.month == 12), today.month % 12 + 1, 1)
        left = (nxt - dt.timedelta(days=1) - today).days
        said = quick.answer("how many days left in the month")
        self.assertTrue(said.startswith("Today is the last day") if left == 0 else said.startswith(f"{left} day"), said)
        self.assertEqual(quick.answer("how many days until the end of the month"), said)
        self.assertIn(str(today.year), quick.answer("how many days until the end of the year"))
        self.assertNotIn(" 1 days", quick.answer("how many weeks left in the year"))


class TheNameBeforeTheMessage(unittest.TestCase):
    def test_send_mom_a_message_saying(self):
        self.assertEqual(voice.interpret("send mom a message saying happy birthday")["command"],
                         {"kind": "message_send", "to": "mom", "body": "happy birthday"})
        self.assertEqual(voice.interpret("shoot jess a text saying running late")["command"]["to"], "jess")


class WhatHeDrives(unittest.TestCase):
    def test_a_make_or_a_year_is_a_fact_and_a_feeling_is_not(self):
        self.assertEqual(voice.interpret("my car is a 2015 Honda Civic")["command"]["kind"], "note")
        self.assertEqual(voice.interpret("my phone is an iphone 15")["command"]["kind"], "note")
        for said in ("my car is a mess", "my phone is dying"):
            self.assertNotEqual((voice.interpret(said)["command"] or {}).get("kind"), "note", said)


class ADayKeepsItsCapital(unittest.TestCase):
    def test_days_and_plain_months_but_not_may(self):
        from aletheia import speech
        self.assertEqual(speech.as_she_says_it("my mom may visit tuesday in june"),
                         "your mom may visit Tuesday in June")


class SmallTalkAnswered(unittest.TestCase):
    def test_the_little_ones(self):
        self.assertEqual(quick.match("what time do you have")[0], "clock")
        self.assertIn("around the clock", quick.answer("do you sleep"))
        self.assertIsNone(voice.interpret("nevermind that")["command"])


class HisListReadAsAList(unittest.TestCase):
    def test_a_short_list_is_read_whole(self):
        from aletheia import tasks
        rows = [{"id": "t1", "description": "renew my passport", "status": "QUEUED"},
                {"id": "t2", "description": "call the plumber", "status": "QUEUED"}]
        with mock.patch.object(tasks, "all_tasks", return_value=rows), \
                mock.patch.object(tasks, "is_his", return_value=True), \
                mock.patch.object(tasks, "is_ready", return_value=True):
            self.assertEqual(quick.answer("what tasks do i have"),
                             "2 tasks open: renew my passport and call the plumber.")

    def test_the_next_one_and_a_due_comma(self):
        from aletheia import speech
        for said in ("what's next on my list", "what's the most important thing on my list"):
            self.assertEqual(quick.match(said)[0], "task_top", said)
        self.assertEqual(speech.spoken_receipt("task_new", "task pay-rent queued — pay rent due Friday"),
                         "Added a task: pay rent, due Friday.")


class MusicByMood(unittest.TestCase):
    def test_a_mood_and_put_on_some_music(self):
        self.assertEqual(voice.interpret("play something relaxing")["command"],
                         {"kind": "open_page", "which": "youtube search relaxing music"})
        self.assertEqual(voice.interpret("put on some music")["command"], {"kind": "music", "action": "play"})


class ARecipeIsASearch(unittest.TestCase):
    def test_find_me_a_recipe(self):
        self.assertEqual(voice.interpret("find me a recipe for chicken")["command"],
                         {"kind": "research", "question": "chicken recipe"})


class ANamedTimerByItsName(unittest.TestCase):
    def test_more_on_the_pizza_only_when_there_is_one(self):
        at = dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=20)
        with mock.patch.object(voice, "_running_once", return_value=[(at, "your 25 minute pizza timer is up")]):
            got = voice._interpret("add 5 minutes to the pizza")["command"]
            self.assertEqual(got["kind"], "remind_at")
            self.assertEqual(got["text"], "your 25 minute pizza timer is up")
        with mock.patch.object(voice, "_running_once", return_value=[]):
            self.assertNotEqual((voice._interpret("add 10 minutes to my meeting")["command"] or {}).get("kind"),
                                "remind_at")



class MyAppointmentIsCase(unittest.TestCase):
    def test_my_appointment_is_friday_is_a_hold(self):
        from aletheia import voice
        got = voice._interpret("my dentist appointment is friday at 2")
        self.assertEqual(got["command"]["kind"], "calendar_hold")
        self.assertEqual(got["command"]["title"], "dentist appointment")

    def test_a_question_is_not_a_hold(self):
        from aletheia import voice
        got = voice._interpret("when is my dentist appointment") or {}
        self.assertNotEqual((got.get("command") or {}).get("kind"), "calendar_hold")


class AnAppointmentOnADateCase(unittest.TestCase):
    def test_the_15th_is_a_day(self):
        from aletheia import voice
        for said in ("i have a doctor's appointment on the 15th at 10", "my doctor's appointment is on the 15th at 10"):
            got = voice._interpret(said)
            self.assertEqual(got["command"]["kind"], "calendar_hold", said)
            self.assertIn("-15T10:00", got["command"]["start"], said)

    def test_where_he_put_his_keys_is_still_a_note(self):
        from aletheia import voice
        self.assertEqual(voice._interpret("my keys are on the table")["command"]["kind"], "note")


class NextTuesdayOnTheCalendarCase(unittest.TestCase):
    def test_a_meeting_next_tuesday_is_held_like_lunch_next_tuesday(self):
        from aletheia import voice
        told = voice._interpret("i have a meeting next tuesday at 3")["command"]
        asked = voice._interpret("schedule a meeting next tuesday at 3")["command"]
        self.assertEqual(told["kind"], "calendar_hold")
        self.assertEqual(told["start"], asked["start"])


class RememberThatIsAnInstructionCase(unittest.TestCase):
    def test_quick_does_not_answer_an_instruction(self):
        from aletheia import quick, voice
        for said in ("remember that my car is a 2019 civic", "remember my car is a 2019 civic"):
            self.assertIsNone(quick.match(said), said)
            self.assertEqual(voice._interpret(said)["command"]["kind"], "note", said)

    def test_the_question_still_reaches_her_notes(self):
        from aletheia import quick
        self.assertEqual(quick.match("do you remember my car")[0], "recall")


class ATaskSaidWithItsDayCase(unittest.TestCase):
    def test_the_weekend_and_a_date_are_deadlines(self):
        from aletheia import voice
        for said in ("i should call mom this weekend", "i have to pay rent on the 1st"):
            cmd = voice._interpret(said)["command"]
            self.assertEqual(cmd["kind"], "task_new", said)
            self.assertTrue(cmd.get("deadline"), said)
            self.assertNotIn("weekend", cmd["description"])
            self.assertNotIn("1st", cmd["description"])

    def test_need_is_not_a_past_tense(self):
        from aletheia import voice
        got = voice._interpret("i need to sort the photos by date")["command"]
        self.assertNotEqual(got["kind"], "task_done")


class ThatReminderIsTheNewestCase(unittest.TestCase):
    def test_that_is_the_one_he_set_last(self):
        from aletheia import intercom
        rows = [{"id": "a", "kind": "once", "created_at": "2026-10-07T10:00:00Z", "command": {"text": "call mom"}},
                {"id": "b", "kind": "once", "created_at": "2026-10-07T11:00:00Z", "command": {"text": "pay rent"}}]
        with mock.patch.object(intercom, "_reminder_schedules", return_value=rows):
            self.assertEqual(intercom._one_reminder("that")[0]["id"], "b")
            self.assertEqual(intercom._one_reminder("that reminder")[0]["id"], "b")


class TheHoldWhereItIsNowCase(unittest.TestCase):
    def test_a_moved_hold_is_read_at_its_new_time(self):
        from aletheia import calendar, voice
        held = {"title": "dentist appointment", "start": "2026-10-09T14:00:00-05:00"}
        live = {"title": "dentist appointment", "start": "2026-10-09T15:00:00-05:00", "status": "TENTATIVE"}
        with mock.patch.object(calendar, "load", return_value={"status": "CANCELLED"}), \
                mock.patch.object(calendar, "all_events", return_value=[live]):
            self.assertEqual(voice._hold_as_it_is_now(held)["start"], live["start"])
        with mock.patch.object(calendar, "load", return_value={"status": "TENTATIVE"}):
            self.assertEqual(voice._hold_as_it_is_now(held)["start"], held["start"])


class AnExtendedTimerCase(unittest.TestCase):
    def test_a_length_it_outgrew_is_not_said(self):
        from aletheia import intercom, voice
        at = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=15)).isoformat()
        spec = {"kind": "once", "at": at, "command": {"text": "your 10-minute timer is up"}}
        with mock.patch.object(intercom, "_reminder_schedules", return_value=[spec]):
            said = voice._timer_left()
        self.assertNotIn("10-minute", said)
        self.assertIn("15 minutes left", said)


class HisSisterByNameCase(unittest.TestCase):
    def test_her_number_through_the_name_he_told(self):
        from aletheia import contacts, intercom, quick
        dana = {"id": "dana", "display_name": "Dana", "phones": ["555-123-4567"]}
        with mock.patch.object(contacts, "all_contacts", return_value=[dana]), \
                mock.patch.object(quick, "_notes", return_value=[{"text": "my sister's name is Dana"}]):
            self.assertIn("Dana", intercom._contacts_answer("my sister"))

    def test_a_text_to_my_sister_keeps_his_capitals(self):
        from aletheia import voice
        cmd = voice._interpret("Text my sister I'm running late")["command"]
        self.assertEqual((cmd["kind"], cmd["to"], cmd["body"]), ("message_send", "my sister", "I'm running late"))
        self.assertEqual(voice._interpret("Text Brant that I'm on my way")["command"]["body"], "I'm on my way")

    def test_march_beside_a_day_is_the_month(self):
        from aletheia import speech
        self.assertIn("March 3", speech.as_she_says_it("dana's birthday is march 3"))
        self.assertIn("we march on", speech.as_she_says_it("we march on"))


class AWeekBeforeTheBirthdayHeJustAskedAboutCase(unittest.TestCase):
    def test_the_birthday_in_the_last_turn_is_it(self):
        from aletheia import voice
        seen = []
        real = voice._interpret

        def spy(said):
            seen.append(said)
            return real(said) if len(seen) == 1 else {"command": {"kind": "remind_at"}, "say": None}
        for before in ("when is dana's birthday", "dana's birthday is march 3"):
            seen.clear()
            with mock.patch.object(voice, "_previous_ask", return_value=before), \
                    mock.patch.object(voice, "_interpret", side_effect=spy):
                voice._interpret("remind me a week before")
            self.assertEqual(seen[-1], "remind me a week before dana's birthday", before)


class HaveIHeardFromCase(unittest.TestCase):
    def test_his_mail_from_them(self):
        from aletheia import quick, voice
        with mock.patch.object(quick, "answer", return_value=None):
            for said in ("have i heard from dana", "anything from dana", "did i hear back from dana"):
                cmd = voice._interpret(said)["command"]
                self.assertEqual((cmd["kind"], cmd.get("which")), ("email_read", "dana"), said)

    def test_his_job_record_answers_first(self):
        from aletheia import quick, voice
        with mock.patch.object(quick, "answer", return_value="Gong wrote back Tuesday."):
            self.assertEqual(voice._interpret("did i hear back from gong")["command"]["kind"], "intent")


class AVolumeLevelIsPressedCase(unittest.TestCase):
    def test_all_the_way_down_then_up_to_the_level(self):
        from aletheia import music
        pressed = []
        with mock.patch.object(music, "press", side_effect=lambda k: pressed.append(k) or True), \
                mock.patch.object(music.journal, "append"):
            said = music.set_volume(30, sleep=lambda _s: None)
        self.assertEqual(pressed.count("volume_down"), 50)
        self.assertEqual(pressed.count("volume_up"), 15)
        self.assertEqual(said, "Volume at 30.")

    def test_no_keys_is_said(self):
        from aletheia import music
        with mock.patch.object(music, "press", return_value=False):
            with self.assertRaises(music.MusicUnavailable):
                music.set_volume(30, sleep=lambda _s: None)


class AreYouSentientCase(unittest.TestCase):
    def test_an_honest_no(self):
        from aletheia import quick
        self.assertIn("AI", quick.answer("are you sentient"))


class APlacesHoursCase(unittest.TestCase):
    def test_hours_are_a_search(self):
        from aletheia import voice
        for said, q in (("when does target close", "target hours"), ("is costco open on sunday", "costco hours on sunday"),
                        ("is the dmv open saturday", "dmv hours saturday")):
            self.assertEqual(voice._interpret(said)["command"], {"kind": "research", "question": q}, said)

    def test_her_own_things_are_not_shops(self):
        from aletheia import voice
        for said in ("is the window open", "is my calendar open", "is it open"):
            self.assertNotEqual((voice._interpret(said)["command"] or {}).get("kind"), "research", said)


class DidTheTeamWinCase(unittest.TestCase):
    def test_a_team_is_a_search(self):
        from aletheia import voice
        self.assertEqual(voice._interpret("did the cowboys win")["command"]["question"], "cowboys score last game")
        self.assertEqual(voice._interpret("when do the cubs play next")["command"]["question"], "when do the cubs play next")

    def test_his_own_things_are_not_a_team(self):
        from aletheia import voice
        for said in ("did i win", "how did dana do", "did you win"):
            self.assertNotEqual((voice._interpret(said)["command"] or {}).get("kind"), "research", said)


class ANoteToSelfCase(unittest.TestCase):
    def test_to_self_is_not_the_note(self):
        from aletheia import voice
        self.assertEqual(voice._interpret("Note to self, buy stamps for Dana")["command"]["text"], "buy stamps for Dana")
        self.assertEqual(voice._interpret("make a note to self that the car needs oil")["command"]["text"],
                         "the car needs oil")

    def test_a_note_of_it_asks(self):
        from aletheia import voice
        self.assertIsNone(voice._interpret("make a note of it")["command"])


class WhatISaidAboutDanaCase(unittest.TestCase):
    def test_the_lead_is_not_the_subject(self):
        from aletheia import intercom
        self.assertEqual(intercom._what_it_is_about("what i said about dana"), "dana")
        self.assertEqual(intercom._what_it_is_about("what you know about my landlord"), "landlord")
        self.assertEqual(intercom._what_it_is_about("my sister's name", keep_whose=True), "my sister's name")

    def test_find_my_note_is_not_a_file(self):
        from aletheia import voice
        self.assertNotEqual((voice._interpret("find my note about dana")["command"] or {}).get("kind"), "file_find")


class PauseEverythingIsTheSwitchCase(unittest.TestCase):
    def test_pause_everything_halts(self):
        from aletheia import voice
        for said in ("pause everything", "stop working", "pause all of it"):
            self.assertEqual(voice._interpret(said)["command"]["kind"], "halt", said)
        self.assertEqual(voice._interpret("pause")["command"]["kind"], "music")
        self.assertNotEqual((voice._interpret("did the printer stop working")["command"] or {}).get("kind"), "halt")


class WhenIsItFromANoteCase(unittest.TestCase):
    def test_a_note_with_a_day_answers(self):
        from aletheia import quick
        with mock.patch.object(quick, "_coming", return_value=[]), \
                mock.patch.object(quick, "_notes", return_value=[{"text": "dentist is the 15th at 10"}]):
            self.assertIn("15th at 10", quick._when_mine("dentist appointment"))
        with mock.patch.object(quick, "_coming", return_value=[]), \
                mock.patch.object(quick, "_notes", return_value=[{"text": "the dentist is nice"}]):
            self.assertIsNone(quick._when_mine("dentist appointment"))


class AHeadacheIsBeingSickCase(unittest.TestCase):
    def test_answered_with_a_sentence_not_a_dead_yes(self):
        from aletheia import quick
        for said in ("i have a headache", "i don't feel well", "i'm sick", "i'm bored"):
            got = quick.answer(said)
            self.assertTrue(got, said)
            self.assertNotIn("Want ", got, said)


class CallHerThenTextHerCase(unittest.TestCase):
    def test_a_call_offers_sentences_he_can_say(self):
        from aletheia import voice
        said = voice._interpret("call my dentist")["say"]
        self.assertIn('"text my dentist', said)
        self.assertNotIn("which would you like", said)

    def test_text_her_is_the_person_just_named(self):
        from aletheia import voice
        with mock.patch.object(voice, "_the_person_just_named", return_value="dana"):
            self.assertEqual(voice._with_the_person_named("text her"), "text Dana")


class HisCapitalsAreKeptCase(unittest.TestCase):
    def test_what_he_wrote_keeps_his_capitals(self):
        from aletheia import voice
        for said, key, want in (("Email Dana saying I'll be late", "body", "I'll be late"),
                                ("Remind me every day at 9 to call Mom", "text", "call Mom"),
                                ("Remember that Dana likes Earl Grey", "text", "Dana likes Earl Grey"),
                                ("remind me in 10 minutes to call Sam", "text", "call Sam"),
                                ("Add a task to email Sam", "description", "email Sam"),
                                ("Add Call Mom to my list", "description", "Call Mom")):
            self.assertEqual(voice._interpret(said)["command"][key], want, said)

    def test_mark_it_read_is_his(self):
        from aletheia import voice
        self.assertIn("mail app", voice._interpret("mark it as read")["say"])


class TheTaskListSaidPlainlyCase(unittest.TestCase):
    def test_a_move_is_when_it_is_due(self):
        from aletheia import speech
        self.assertEqual(speech.spoken_receipt("task_change", "moved — call the bank due Friday"),
                         "Call the bank is due Friday now.")

    def test_the_first_one_of_nothing(self):
        from aletheia import intercom
        with mock.patch.object(intercom, "_open_tasks", return_value=[]):
            self.assertEqual(intercom._one_task("first")[1], "Your list is empty.")


class DueTomorrowSaysTheDayOnceCase(unittest.TestCase):
    def test_the_day_is_the_head(self):
        import datetime as _dt
        from aletheia import intercom, localtime, quick
        tomorrow = (_dt.datetime.now(localtime.operator_tz()) + _dt.timedelta(days=1)).date().isoformat()
        rows = [{"id": "call-the-bank", "description": "call the bank", "deadline": tomorrow}]
        with mock.patch.object(intercom, "_open_tasks", return_value=rows):
            said = quick.answer("what's due tomorrow")
        self.assertEqual(said, "1 thing due tomorrow: call the bank.")


class TheSecondOneIsDoneCase(unittest.TestCase):
    def test_counting_ticks_off(self):
        from aletheia import voice
        self.assertEqual(voice._interpret("the second one is done")["command"], {"kind": "task_done", "which": "second"})
        self.assertNotEqual((voice._interpret("the dishwasher is done")["command"] or {}).get("kind"), "task_done")

    def test_the_task_just_added_with_a_due_date(self):
        from aletheia import converse, voice
        turns = [{"he_asked": "add a task", "she_answered": "Added a task: renew my passport, due 20 October."}]
        with mock.patch.object(converse, "recent", return_value=turns):
            self.assertEqual(voice._the_task_just_added(), "renew my passport")


class IGotEverythingCase(unittest.TestCase):
    def test_back_from_the_store_clears_the_list(self):
        from aletheia import intercom, voice
        with mock.patch.object(intercom, "_shopping_items", return_value=[{"need": "eggs"}]):
            self.assertEqual(voice._interpret("i got everything")["command"], {"kind": "shopping_off", "item": "everything"})
        with mock.patch.object(intercom, "_shopping_items", return_value=[]):
            self.assertNotEqual((voice._interpret("i got everything")["command"] or {}).get("kind"), "shopping_off")


class TalkAboutTheTalkIsNotAnAskCase(unittest.TestCase):
    def test_the_days_asks_skip_repeat_that(self):
        import datetime as _dt
        from aletheia import converse, journal, quick
        now = _dt.datetime.now(_dt.timezone.utc).isoformat()
        rows = [{"kind": "note", "subject": converse.ASKED_SUBJECT, "ts": now, "text": t}
                for t in ("remind me at 6 to cook dinner", "what did i just ask you", "repeat that")]
        with mock.patch.object(journal, "entries", return_value=rows):
            said = quick._asked_on("today")
        self.assertIn("cook dinner", said)
        self.assertNotIn("repeat that", said)


class AndTheWeekendCase(unittest.TestCase):
    def test_the_weekend_is_a_day_to_ask_again_with(self):
        from aletheia import quick
        with mock.patch.object(quick, "_previous_ask", return_value="what's the weather"), \
                mock.patch.object(quick, "answer", side_effect=lambda q: q):
            self.assertEqual(quick._follow_up("and the weekend"), "what's the weather the weekend")


class NextWeekendCase(unittest.TestCase):
    def test_next_weekend_is_the_saturday_and_sunday_of_next_week(self):
        from aletheia import calendar, localtime, quick
        tz = localtime.operator_tz()
        today = dt.datetime.now(tz).date()
        saturday = today + dt.timedelta(days=7 - today.weekday() + 5)
        this_saturday = today + dt.timedelta(days=(5 - today.weekday()) % 7)
        events = [{"title": "Lake trip", "start": f"{saturday}T10:00:00"},
                  {"title": "Not this one", "start": f"{this_saturday}T10:00:00"}]
        if this_saturday == saturday:
            events.pop()
        with mock.patch.object(calendar, "all_events", return_value=events), \
                mock.patch.object(calendar, "parse_time",
                                  side_effect=lambda s: dt.datetime.fromisoformat(s).replace(tzinfo=tz)):
            said = quick.answer("anything on next weekend")
        self.assertIn("Lake trip", said)
        self.assertNotIn("Not this one", said)
        self.assertTrue(said.startswith("Next weekend"), said)


class RemindMeInAMonthCase(unittest.TestCase):
    def _at(self, said, now):
        from aletheia import voice
        out = voice._a_loose_when(said.lower(), said, now=now)
        return out and (out["command"]["at"][:10], out["command"]["text"])

    def test_months_land_on_a_real_date(self):
        tz = dt.timezone(dt.timedelta(hours=-5))
        now = dt.datetime(2027, 1, 31, 12, 0, tzinfo=tz)
        self.assertEqual(self._at("remind me in a month to cancel Netflix", now), ("2027-02-28", "cancel Netflix"))
        self.assertEqual(self._at("remind me next month to renew my license", now), ("2027-02-01", "renew my license"))
        self.assertEqual(self._at("remind me in 3 months to check the filter", now), ("2027-04-30", "check the filter"))
        now = dt.datetime(2026, 11, 15, 12, 0, tzinfo=tz)
        self.assertEqual(self._at("remind me to book flights in two months", now), ("2027-01-15", "book flights"))


class AnythingFromTheStoreCase(unittest.TestCase):
    def test_the_store_is_the_shopping_list_not_an_item(self):
        from aletheia import quick
        for said in ("do I need anything from the store", "what do I need to pick up at the store",
                     "what's on my grocery list"):
            self.assertEqual(quick.match(said)[0], "shopping", said)
        self.assertNotEqual((quick.match("what do I need to pick up") or ("",))[0], "shopping")


class PushItToSixCase(unittest.TestCase):
    def test_push_bump_and_shift_move_the_reminder_just_set(self):
        from aletheia import voice
        moved = {"command": {"kind": "remind_at", "at": "x", "text": "call Dana", "replaces": "call Dana"},
                 "say": None}
        for said in ("push it to 6", "bump that to 6pm", "shift it to 6", "reschedule it to 6"):
            with mock.patch.object(voice, "_moved_reminder", return_value=moved) as got:
                self.assertEqual(voice.interpret(f"thea {said}"), moved, said)
                self.assertTrue(got.called, said)


class APastaTimerCase(unittest.TestCase):
    def test_the_name_said_before_the_length_still_names_the_timer(self):
        from aletheia import voice
        for said in ("set a pasta timer for 8 minutes", "set a timer for pasta for 8 minutes"):
            command = voice.interpret(f"thea {said}")["command"]
            self.assertEqual(command["text"], "your 8 minute pasta timer is up", said)
        command = voice.interpret("thea set a new timer for 5 minutes")["command"]
        self.assertEqual(command["text"], "your 5 minute timer is up")


class ALowerCaseNameIsStillANameCase(unittest.TestCase):
    def test_a_contact_said_in_lower_case_is_saved_with_its_capital(self):
        from aletheia import voice
        for said in ("dana's email is dana@example.com", "dana's number is 555 123 4567"):
            self.assertEqual(voice.interpret(f"thea {said}")["command"]["name"], "Dana", said)
        self.assertEqual(voice.interpret("thea McKenna's number is 555 123 4567")["command"]["name"], "McKenna")


class WhereThePasswordIsCase(unittest.TestCase):
    def test_where_a_password_is_kept_is_not_the_password(self):
        from aletheia import sensitivity, voice
        self.assertFalse(sensitivity.carries_secret("my wifi password is on the fridge"))
        self.assertFalse(sensitivity.carries_secret("the password is in my desk drawer"))
        for secret in ("the wifi password is hunter2", "password is in2deep!", "password: on the fridge",
                       "wifi password is on3Fire"):
            self.assertTrue(sensitivity.carries_secret(secret), secret)
        got = voice.interpret("thea remember that my wifi password is on the fridge")
        self.assertEqual(got["command"]["kind"], "note")
        self.assertIsNone(voice.interpret("thea remember my wifi password is hunter22")["command"])


class APoliteAskIsStillAnAskCase(unittest.TestCase):
    def test_would_you_mind_i_need_you_to_and_a_trailing_please(self):
        from aletheia import voice
        self.assertEqual(voice._a_polite_ask("thea would you mind adding a task to call the bank"),
                         "thea add a task to call the bank")
        self.assertEqual(voice._a_polite_ask("i need you to remind me tomorrow to pay rent"),
                         "remind me tomorrow to pay rent")
        self.assertEqual(voice._a_polite_ask("add eggs to my list please"), "add eggs to my list")
        # The words of the ask are never cut, and a question stays a question.
        self.assertEqual(voice._a_polite_ask("remind me at 5 to say thank you"), "remind me at 5 to say thank you")
        self.assertEqual(voice._a_polite_ask("can you buy things"), "can you buy things")
        self.assertEqual(voice._a_polite_ask("would you mind"), "would you mind")


if __name__ == "__main__":
    unittest.main()
