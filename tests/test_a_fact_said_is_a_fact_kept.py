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
        self.assertTrue(intercom._reminder_words(spec).startswith("your 10-minute timer — going off"))
        # A comma would collide with the list joining it to the others.
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
            # He asked who HE owes: that half alone (2026-10-07).
            self.assertEqual(quick.answer("who do i owe money"), "You owe Sam $20.")
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


class WhatDidIAskYouCase(unittest.TestCase):
    def test_a_person_is_not_a_repository_and_her_reminders_are_a_read(self):
        from aletheia import quick, voice
        self.assertEqual(quick.match("what did I ask you to do today")[0], "asked_on")
        self.assertEqual(voice.interpret("thea did you set any reminders")["command"], {"kind": "reminders"})


class WhatSheDidIsInThePastCase(unittest.TestCase):
    def test_a_reminder_receipt_is_read_back_as_done(self):
        from aletheia import quick
        self.assertEqual(quick._as_done("I'll remind you today at 5 pm: call Dana"),
                         "Set a reminder for today at 5 pm: call Dana")
        self.assertEqual(quick._as_done("Every Monday at 9 am I'll remind you: take out the trash"),
                         "Set a reminder for every Monday at 9 am: take out the trash")
        self.assertEqual(quick._as_done("Added to the shopping list: milk"), "Added to the shopping list: milk")


class HowLongUntilCase(unittest.TestCase):
    def test_until_names_a_timer_only_when_one_has_that_name(self):
        from aletheia import voice
        running = [(dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=10), "your 10 minute pasta timer is up")]
        with mock.patch.object(voice, "_running_once", return_value=running), \
                mock.patch.object(voice, "_timer_left", side_effect=lambda named="", **_: f"timer:{named}"):
            self.assertEqual(voice._interpret("how long until the pasta")["say"], "timer:pasta")
            self.assertEqual(voice._interpret("how long on the eggs")["say"], "timer:eggs")
            for said in ("how long until christmas", "how long until the weekend", "how long until my haircut"):
                got = voice._interpret(said) or {}
                self.assertFalse(str(got.get("say") or "").startswith("timer:"), said)

    def test_until_his_own_appointment_reads_her_calendar(self):
        from aletheia import localtime, quick
        tz = localtime.operator_tz()
        at = dt.datetime.now(tz) + dt.timedelta(days=2, hours=3, minutes=1)
        with mock.patch.object(quick, "_coming", return_value=[(at, "dentist appointment", "calendar")]):
            said = quick._until_mine("my dentist appointment")
        self.assertTrue(said.startswith("2 days and 3 hours - "), said)
        with mock.patch.object(quick, "_coming", return_value=[]):
            self.assertIsNone(quick._until_mine("my haircut"))


class RemindMeOnADayHeNamesCase(unittest.TestCase):
    def test_tonight_the_day_after_tomorrow_and_a_holiday(self):
        from aletheia import localtime, voice
        today = localtime.today()
        def at(said):
            return voice._interpret(said)["command"]["at"]
        self.assertTrue(at("remind me the day after tomorrow to call mom").startswith(
            (today + dt.timedelta(days=2)).isoformat()))
        self.assertIn("-10-31T09:00", at("remind me on halloween to buy candy"))
        self.assertIn("-12-24T09:00", at("remind me on christmas eve to wrap presents"))
        tonight = dt.datetime.fromisoformat(at("remind me tonight at 8 to take my pills"))
        self.assertTrue(tonight.hour == 20 or tonight > dt.datetime.now(tonight.tzinfo), tonight)


class TheDayAfterTomorrowIsOneDayCase(unittest.TestCase):
    def test_tasks_and_holds_keep_the_whole_day(self):
        from aletheia import localtime, voice
        later = (localtime.today() + dt.timedelta(days=2)).isoformat()
        task = voice._interpret("add a task to call mom the day after tomorrow")["command"]
        self.assertEqual((task["description"], task["deadline"]), ("call mom", later))
        hold = voice._interpret("put dinner with mom on my calendar the day after tomorrow at 6")["command"]
        self.assertEqual(hold["title"], "dinner with mom")
        self.assertTrue(hold["start"].startswith(later + "T18:00"), hold["start"])
        party = voice._interpret("i have a party tonight at 8")["command"]
        self.assertIn("T20:00", party["start"])


class TheAnswerToForHowLongCase(unittest.TestCase):
    def test_fifteen_minutes_after_for_how_long_is_a_plain_timer(self):
        from aletheia import voice
        asked = ("set a timer", 'For how long? Say "set a timer for ten minutes".')
        with mock.patch.object(voice, "_previous_turn", return_value=asked):
            self.assertEqual(voice._interpret("15 minutes")["command"]["text"], "your 15-minute timer is up")
            self.assertEqual(voice._interpret("set a timer for 5 minutes")["command"]["text"],
                             "your 5-minute timer is up")


class WakeMeUpCase(unittest.TestCase):
    def test_wake_me_up_with_no_time_asks_for_one(self):
        from aletheia import voice
        for said in ("wake me up", "set an alarm for tomorrow", "can you wake me up"):
            self.assertIn("For what time?", voice.interpret(f"thea {said}")["say"], said)


class WhatShouldItSayCase(unittest.TestCase):
    def test_the_answer_is_the_message_and_a_question_is_not(self):
        from aletheia import voice
        asked = ("text mom", 'What should it say? Say "text Mom that you\'re running late" and I\'ll draft it.')
        with mock.patch.object(voice, "_previous_turn", return_value=asked):
            sent = voice._interpret("that i'll be late")["command"]
            self.assertEqual((sent["kind"], sent["body"]), ("message_send", "i'll be late"))
            self.assertEqual(voice._interpret("running ten minutes behind")["command"]["body"],
                             "running ten minutes behind")
            got = voice._interpret("what time is it") or {}
            self.assertNotEqual((got.get("command") or {}).get("kind"), "message_send")
        asked = ("email dana", 'What should it say? Say "email Dana saying you\'ll be late" and I\'ll draft it.')
        with mock.patch.object(voice, "_previous_turn", return_value=asked):
            self.assertEqual(voice._interpret("saying the meeting moved to 3")["command"]["kind"], "email_draft")



class HerNameAndHerBirthdayCase(unittest.TestCase):
    """2026-10-07: "my sister's name is Dana", "my sister's birthday is
    march 3", then "when is Dana's birthday" - she said he never told her."""

    def test_a_name_finds_the_relation_he_named(self):
        from aletheia import quick
        notes = [{"text": "my sister's birthday is march 3"}, {"text": "my sister's name is Dana"}]
        with mock.patch.object(quick, "_notes", return_value=notes):
            self.assertEqual(quick._relation_for_name("Dana"), "sister")
            self.assertIn("3 March", quick._birthday_when("Dana") or "")
            self.assertIsNone(quick._relation_for_name("Sam"))



class AnOutgrownTimerCase(unittest.TestCase):
    """2026-10-07: after "add 5 minutes", "how much time is left" said
    "15 minutes left on your 10-minute timer"."""

    def test_a_length_it_outgrew_is_not_its_name(self):
        from aletheia import quick, scheduler
        now = dt.datetime(2026, 10, 7, 12, 0, tzinfo=dt.timezone.utc)
        spec = {"kind": "once", "enabled": True, "command": {"text": "your 10-minute timer is up"}}
        with mock.patch.object(scheduler, "all_schedules", return_value=[spec]), \
                mock.patch.object(scheduler, "next_occurrence", return_value=now + dt.timedelta(minutes=15)):
            self.assertEqual(quick._timer_left(now), "15 minutes left on your timer.")
        with mock.patch.object(scheduler, "all_schedules", return_value=[spec]), \
                mock.patch.object(scheduler, "next_occurrence", return_value=now + dt.timedelta(minutes=4)):
            self.assertEqual(quick._timer_left(now), "4 minutes left on your 10-minute timer.")



class BlockTwoToFourCase(unittest.TestCase):
    """2026-10-07: "block off 2 to 4 tomorrow for deep work" went to the planner."""

    def test_a_hold_between_two_times(self):
        from aletheia import voice
        for said, hour, minutes, title in (("block off 2 to 4 tomorrow for deep work", 14, 120, "Deep work"),
                                           ("block tomorrow from 11 to 1", 11, 120, "Busy"),
                                           ("block off 9am to 11:30am friday", 9, 150, "Busy")):
            with self.subTest(said=said):
                cmd = voice.interpret(said)["command"]
                self.assertEqual(cmd["kind"], "calendar_hold")
                self.assertEqual(dt.datetime.fromisoformat(cmd["start"]).hour, hour)
                self.assertEqual(cmd["minutes"], minutes)
                self.assertEqual(cmd["title"], title)


class NoContactYetCase(unittest.TestCase):
    """2026-10-07: "what's Dana's number" said "I have no contact for 'dana'."."""

    def test_says_how_to_give_it(self):
        from aletheia import intercom, contacts
        with mock.patch.object(contacts, "all_contacts", return_value=[]):
            said = intercom._contacts_answer("dana")
        self.assertNotIn("'dana'", said)
        self.assertIn("Dana", said)
        self.assertIn("Dana's number is", said)



class LunchWithSamTomorrowCase(unittest.TestCase):
    """2026-10-07: "lunch with Sam tomorrow at noon" went to the planner, and
    "call tomorrow" offered to text somebody called Tomorrow."""

    def test_a_diary_line_without_a_verb(self):
        from aletheia import voice
        cmd = voice.interpret("lunch with Sam tomorrow at noon")["command"]
        self.assertEqual(cmd["kind"], "calendar_hold")
        self.assertEqual(cmd["title"], "lunch with Sam")
        self.assertEqual(dt.datetime.fromisoformat(cmd["start"]).hour, 12)

    def test_a_day_is_not_a_person(self):
        from aletheia import voice
        self.assertNotIn("Tomorrow", str(voice.interpret("call tomorrow").get("say") or ""))



class WhoOwesMeCase(unittest.TestCase):
    """2026-10-07: "who owes me money" opened with "You don't owe anybody",
    and "does anyone owe me money" went to a model."""

    def test_the_half_he_asked_about(self):
        from aletheia import quick
        with mock.patch.object(quick, "_ledger", return_value={"sam": 20, "jo": -5}):
            self.assertEqual(quick._owed("who owes me money"), "Sam owes you $20.")
            self.assertEqual(quick._owed("who do i owe"), "You owe Jo $5.")
            self.assertIn("Sam owes you $20", quick._owed("does anyone owe me money"))
        with mock.patch.object(quick, "_ledger", return_value={"jo": -5}):
            self.assertTrue(quick._owed("who owes me money").startswith("Nobody owes you"))
        self.assertEqual(quick.match("does anyone owe me money")[0], "owed")



class HowMuchDidIRunCase(unittest.TestCase):
    """2026-10-07: "I went for a 20 minute run" and "how much did I run this
    week" both went to the planner."""

    def test_said_and_added_up(self):
        from aletheia import quick, voice
        self.assertEqual(voice._interpret("i went for a 20 minute run")["command"],
                         {"kind": "note", "text": "I ran for 20 minutes"})
        self.assertEqual(voice._interpret("i went for a 3 mile walk")["command"]["text"], "I walked 3 miles")
        now = dt.datetime.now(dt.timezone.utc).isoformat()
        notes = [{"text": "I ran for 20 minutes", "ts": now}, {"text": "I ran 3 miles", "ts": now},
                 {"text": "I worked out for an hour", "ts": now}]
        with mock.patch.object(quick, "_notes", return_value=notes):
            self.assertEqual(quick.answer("how much did i run this week"), "20 minutes and 3 miles this week.")
            self.assertEqual(quick.answer("how long did i work out today"), "1 hour today.")
            self.assertIn("any walking", quick.answer("how much did i walk this week"))



class AndAddATaskCase(unittest.TestCase):
    """2026-10-07: "and add a task to pay rent", said after another ask, was
    refused at the money door as spending."""

    def test_the_and_is_not_the_ask(self):
        from aletheia import voice
        self.assertEqual(voice.interpret("and add a task to pay rent")["command"]["kind"], "task_new")
        self.assertEqual(voice.interpret("also remind me at 5 to call mom")["command"]["kind"], "remind_at")

    def test_writing_it_down_is_not_spending_and_buying_still_is(self):
        from aletheia import intents
        self.assertFalse(intents._asks_to_spend("and add a task to pay rent"))
        self.assertTrue(intents._asks_to_spend("and buy me a pizza"))



class WhatsMyLockerComboCase(unittest.TestCase):
    """2026-10-07: "what's my locker combo" paid a model to find the note
    "my locker combo is 12 34 56"."""

    def test_a_note_in_so_many_words(self):
        from aletheia import quick
        notes = [{"text": "my locker combo is 12 34 56"}]
        with mock.patch.object(quick, "_notes", return_value=notes):
            self.assertEqual(quick.answer("what's my locker combo"), "You told me: your locker combo is 12 34 56.")
            # Nothing said is nothing answered: the model still gets it.
            self.assertIsNone(quick.answer("what are my chances"))



class AListOfMoviesCase(unittest.TestCase):
    """2026-10-07: "start a list of movies to watch" went to the planner, and
    "add Dune to it" put Dune on the packing list he had just deleted."""

    def test_a_list_of_things(self):
        from aletheia import voice
        self.assertEqual(voice._interpret("start a list of movies to watch")["command"],
                         {"kind": "list_new", "list": "movies to watch"})

    def test_it_is_not_a_deleted_list(self):
        from aletheia import voice, lists
        with mock.patch.object(voice, "_the_named_list_just_used", return_value=("packing", True)), \
                mock.patch.object(lists, "exists", return_value=False):
            out = voice._interpret("add dune to it")
        self.assertIsNone(out["command"])
        self.assertIn("deleted", out["say"])



class ATimerCalledTeaCase(unittest.TestCase):
    """2026-10-07: "set a timer for 5 minutes called tea" went to the planner,
    and "how long has it been" after the stopwatch went to a model."""

    def test_called(self):
        from aletheia import voice
        for said in ("set a timer for 5 minutes called tea", "set a 5 minute timer called tea"):
            with self.subTest(said=said):
                self.assertIn("tea timer", voice._interpret(said)["command"]["text"])

    def test_how_long_has_it_been(self):
        from aletheia import voice, converse, quick
        with mock.patch.object(converse, "recent", return_value=[{"he_asked": "start a stopwatch",
                                                                   "she_answered": "Stopwatch started."}]), \
                mock.patch.object(quick, "answer", return_value="Your stopwatch is at 2 minutes."):
            self.assertEqual(voice._interpret("how long has it been")["say"], "Your stopwatch is at 2 minutes.")



class AQuarterToFiveCase(unittest.TestCase):
    """2026-10-07: "remind me at quarter to 5 to pick up Jo" went to the planner."""

    def test_the_clock_and_the_errand(self):
        from aletheia import voice
        cmd = voice.interpret("remind me at quarter to 5 to pick up Jo")["command"]
        self.assertEqual(cmd["kind"], "remind_at")
        self.assertEqual(cmd["text"], "pick up Jo")
        self.assertEqual(dt.datetime.fromisoformat(cmd["at"]).strftime("%H:%M"), "16:45")
        self.assertEqual(voice._a_clock_said("at a quarter past six"), "at 6:15")



class WhatAndShhCase(unittest.TestCase):
    """2026-10-07: a bare "what?" went to a model, and "shh" to the planner."""

    def test_what_is_say_that_again(self):
        from aletheia import quick
        for said in ("what?", "huh", "wait what"):
            with self.subTest(said=said):
                self.assertEqual(quick.match(said)[0], "repeat")

    def test_shh_is_quiet(self):
        from aletheia import voice
        self.assertEqual(voice._interpret("shh")["command"]["kind"], "notify_snooze")



class HisBirthdaySaidBackCase(unittest.TestCase):
    """2026-10-07: "I was born on May 5 1995" was confirmed as "I'll remember
    your birthday", and "my birthday is the 3rd of march" went to the planner."""

    def test_said_back(self):
        from aletheia import speech, memory
        for kept, said in (("may 5 1995", "Got it - your birthday is May 5, 1995."),
                           ("march 3rd", "Got it - your birthday is March 3rd."),
                           ("3rd of march", "Got it - your birthday is the 3rd of March.")):
            with self.subTest(kept=kept), mock.patch.object(memory, "recall", return_value=kept):
                self.assertEqual(speech.spoken_receipt("remember", "remembered identity.birthday"), said)

    def test_the_third_of_march(self):
        from aletheia import voice
        self.assertEqual(voice._interpret("my birthday is the 3rd of march")["command"]["key"], "birthday")



class TwoPlacesCase(unittest.TestCase):
    """2026-10-07: "1000 divided by 7" was read out as "142.8571"."""

    def test_two_places(self):
        from aletheia import quick
        self.assertEqual(quick.answer("what is 1000 divided by 7"), "142.86.")
        self.assertEqual(quick.answer("what is 2 divided by 3"), "0.6667.")
        self.assertEqual(quick.answer("what is 7.5 times 2"), "15.")



class AReminderAskedInTwoHalvesCase(unittest.TestCase):
    """2026-10-07: "add a reminder" then "for tomorrow at 9 to email Sam" was
    asked "when?" again; "set a reminder for 5" went to the planner."""

    def test_the_when_and_the_what_after_her_question(self):
        from aletheia import voice
        got = voice._answering_her("for tomorrow at 9 to email sam",
                                   'What should I remind you about, and when? Say "remind me at 3 to call the dentist".')
        self.assertEqual(got["command"]["kind"], "remind_at")
        self.assertEqual(got["command"]["text"], "email sam")

    def test_a_time_first(self):
        from aletheia import voice
        asked = voice._interpret("set a reminder for 5")["say"]
        self.assertIn("at 5?", asked)
        got = voice._answering_her("take the bins out", asked)
        self.assertEqual(got["command"]["text"], "take the bins out")
        self.assertEqual(dt.datetime.fromisoformat(got["command"]["at"]).hour, 17)

    def test_a_question_is_still_a_question(self):
        from aletheia import voice
        self.assertIsNone(voice._answering_her("what time is it", "What should I remind you about at 5? Just say it."))



class TheGateCodeCase(unittest.TestCase):
    """2026-10-07: "the gate code is 4471" went to the planner, and "what's
    our room number" to a model with "the hotel room number is 312" kept."""

    def test_kept(self):
        from aletheia import voice
        self.assertEqual(voice._interpret("the gate code is 4471")["command"]["kind"], "note")
        self.assertNotEqual((voice._interpret("the wifi password is hunter2")["command"] or {}).get("kind"), "note")

    def test_read_back(self):
        from aletheia import quick
        notes = [{"text": "the hotel room number is 312"}, {"text": "the gate code is 4471"}]
        with mock.patch.object(quick, "_notes", return_value=notes):
            self.assertEqual(quick.answer("what's our room number"), "You told me: the hotel room number is 312.")
            self.assertEqual(quick.answer("what's the gate code"), "You told me: the gate code is 4471.")



class RemoveThatCase(unittest.TestCase):
    """2026-10-07: "add bread to the shopping list" then "remove that" went
    to the planner."""

    def test_that_is_what_he_just_did(self):
        from aletheia import voice
        with mock.patch.object(voice, "_last_ask_is_undoable", return_value=True):
            for said in ("remove that", "actually take it off", "delete that", "take that off the list"):
                with self.subTest(said=said):
                    self.assertEqual(voice._interpret(said)["command"], {"kind": "undo"})
        with mock.patch.object(voice, "_last_ask_is_undoable", return_value=False):
            self.assertNotEqual((voice._interpret("remove that")["command"] or {}).get("kind"), "undo")



class WhatsFridayLookLikeCase(unittest.TestCase):
    """2026-10-07: "what's Friday look like" went to a model."""

    def test_a_day_he_names(self):
        from aletheia import quick
        for said, day in (("what's friday look like", "friday"), ("what does next week look like", "next week")):
            with self.subTest(said=said):
                self.assertEqual(quick.match(said), ("agenda", day))



class EverySundayNightCase(unittest.TestCase):
    """2026-10-07: "remind me every Sunday night to plan the week" went to the planner."""

    def test_the_part_of_the_day(self):
        from aletheia import voice
        for said, time in (("remind me every sunday night to plan the week", "21:00"),
                           ("remind me every monday morning to email sam", "09:00"),
                           ("remind me every sunday night at 8 to call mom", "20:00")):
            with self.subTest(said=said):
                cmd = voice.interpret(said)["command"]
                self.assertEqual(cmd["kind"], "remind_weekly")
                self.assertEqual(cmd["time"], time)



class NextMonthCase(unittest.TestCase):
    """2026-10-07: "make sure I renew my license next month" kept "next month"
    in the task with no date, and "what's due this month" went to a model."""

    def test_a_task_due_next_month(self):
        from aletheia import voice
        cmd = voice.interpret("make sure I renew my license next month")["command"]
        self.assertEqual(cmd["description"], "renew my license")
        self.assertEqual(dt.date.fromisoformat(cmd["deadline"]).day, 1)

    def test_due_this_month(self):
        from aletheia import quick
        self.assertEqual(quick.match("what's due this month")[0], "tasks_due")



class HowMuchSleepCase(unittest.TestCase):
    """2026-10-07: "how much sleep will I get" went to a model with an alarm set."""

    def test_the_alarm_sum(self):
        from aletheia import quick
        self.assertEqual(quick.match("how much sleep will i get")[0], "alarm_left")


class AQuietRefusalIsNotOvernightCase(unittest.TestCase):
    """2026-10-07: "Good morning. Overnight: ...; refused — Nothing is waiting
    to be snoozed"."""

    def test_dropped(self):
        from aletheia import quick, recollection
        rows = [{"ts": "2099-01-01T00:00:00Z", "kind": "action", "actor": "operator-local-core",
                 "subject": "core:notify_snooze", "text": "refused — Nothing is waiting to be snoozed"}]
        with mock.patch.object(recollection, "_read_journal", return_value=(rows, True)), \
                mock.patch.object(recollection, "_something_she_did", return_value=True), \
                mock.patch.object(recollection, "_row", return_value={"what": "refused — Nothing is waiting to be snoozed"}), \
                mock.patch.object(quick, "_sent_records", return_value=[]):
            self.assertNotIn("snoozed", quick._overnight())



class WhatCanICallYouCase(unittest.TestCase):
    """2026-10-07: "what can I call you" went to a model."""

    def test_her_name(self):
        from aletheia import quick
        for said in ("what can i call you", "do you have a name"):
            with self.subTest(said=said):
                self.assertEqual(quick.match(said)[0], "her_name")



class ABareNumberIsMinutesCase(unittest.TestCase):
    """2026-10-07: "remind me in 10" and "20" after "For how long?" went to the planner."""

    def test_minutes(self):
        from aletheia import voice
        self.assertIn("10-minute", voice._interpret("remind me in 10")["command"]["text"])
        self.assertEqual(voice._interpret("remind me in 10 to check the laundry")["command"]["text"], "check the laundry")
        self.assertIn("20-minute", voice._interpret("set a timer for 20")["command"]["text"])



class WhatHappenedThisMorningCase(unittest.TestCase):
    """2026-10-07: "what happened this morning" and "what did I note last week"
    went to a model."""

    def test_matched(self):
        from aletheia import quick
        self.assertEqual(quick.match("what happened this morning"), ("today", "this morning"))
        self.assertEqual(quick.match("what did i note last week"), ("notes_day", "last week"))

    def test_last_week_is_a_range(self):
        from aletheia import quick, localtime
        today = dt.datetime.now(localtime.operator_tz()).date()
        last_week = today - dt.timedelta(days=today.weekday() + 5)
        stamp = dt.datetime.combine(last_week, dt.time(12), tzinfo=localtime.operator_tz()).isoformat()
        with mock.patch.object(quick, "_notes", return_value=[{"text": "the plumber is Bob", "ts": stamp}]):
            self.assertIn("the plumber is Bob", quick._notes_day("last week"))
            self.assertEqual(quick._notes_day("today"), "No notes from today.")



class TwoAtFiveCase(unittest.TestCase):
    """2026-10-07: two reminders at 5, "cancel the 5 o'clock reminder" said
    none was about 5 o'clock, and "cancel both" was a subscription called "both"."""

    def test_both(self):
        from aletheia import voice
        asked = "You have 2 reminders at 5 pm: call Jo or call the bank. Which one, or all of them?"
        with mock.patch.object(voice, "_previous_turn", return_value=("cancel the 5 o'clock reminder", asked)):
            for said in ("both", "cancel both", "all of them"):
                with self.subTest(said=said):
                    self.assertEqual(voice._interpret(said)["command"], {"kind": "reminder_off", "which": "all at 17:00"})

    def test_both_is_never_a_service(self):
        from aletheia import voice
        with mock.patch.object(voice, "_previous_turn", return_value=("", "")):
            self.assertNotEqual((voice._interpret("cancel both")["command"] or {}).get("kind"), "subscription_cancel")

    def test_the_clock_names_two(self):
        from aletheia import intercom
        rows = [{"id": "a", "kind": "once", "at": "2026-10-07T22:00:00+00:00", "command": {"text": "call Jo"}},
                {"id": "b", "kind": "once", "at": "2026-10-07T22:00:00+00:00", "command": {"text": "call the bank"}}]
        with mock.patch.object(intercom, "_reminder_schedules", return_value=rows), \
                mock.patch.object(intercom, "_reminder_clock", return_value="17:00"):
            found, why = intercom._one_reminder("5 o'clock")
        self.assertIsNone(found)
        self.assertIn("Which one, or all of them?", why)



class CallMomIsNotTheTextCase(unittest.TestCase):
    """2026-10-07: "text mom" - "What should it say?" - "call mom" drafted a
    text to Mom that said "call mom"."""

    def test_an_ask_is_an_ask(self):
        from aletheia import voice
        asked = 'What should it say? Say "text Mom that you\'re running late" and I\'ll draft it for you to send.'
        self.assertIsNone(voice._answering_her("call mom", asked))
        self.assertEqual(voice._answering_her("running late", asked)["command"]["kind"], "message_send")



class RemindMeAboutTheDentistCase(unittest.TestCase):
    """2026-10-07: "remind me about the dentist" with nothing kept said "I
    don't have anything remembered"; "remind me tomorrow at 9 about the car"
    went to the planner."""

    def test_asks_when(self):
        from aletheia import voice, quick
        with mock.patch.object(quick, "_recall", return_value="I have nothing about the dentist on file."):
            said = voice._interpret("remind me about the dentist")["say"]
        self.assertIn("When should I remind you about the dentist?", said)
        got = voice._answering_her("tomorrow at 2", said)
        self.assertEqual(got["command"]["text"], "the dentist")

    def test_what_she_knows_is_still_read(self):
        from aletheia import voice, quick
        with mock.patch.object(quick, "_recall", return_value="You told me: the dentist is Dr. Lee."):
            self.assertEqual(voice._interpret("remind me about the dentist")["command"]["kind"], "recall")

    def test_a_when_then_about(self):
        from aletheia import voice
        cmd = voice._interpret("remind me tomorrow at 9 about the car")["command"]
        self.assertEqual((cmd["kind"], cmd["text"]), ("remind_at", "the car"))



class HolidaysInNovemberCase(unittest.TestCase):
    """2026-10-07: "is Monday a holiday" and "what holidays are in November"
    went to the planner, and Veterans Day was not a holiday she knew."""

    def test_matched(self):
        from aletheia import quick
        self.assertEqual(quick.match("is monday a holiday"), ("holiday_next", "monday"))
        self.assertEqual(quick.match("what holidays are in november"), ("holiday_next", "november"))
        self.assertIn("Veterans Day", quick._holiday_next("november"))
        self.assertTrue(quick.answer("when is veterans day").endswith("from now."))



class ImAtTheStoreCase(unittest.TestCase):
    """2026-10-07: "I'm at the store" went to a model."""

    def test_the_list(self):
        from aletheia import quick
        for said in ("i'm at the store", "im at costco", "we're at the supermarket"):
            with self.subTest(said=said):
                self.assertEqual(quick.match(said)[0], "shopping")



class AnythingWaitingOnMeCase(unittest.TestCase):
    """2026-10-07: "anything waiting on me" went to a model."""

    def test_waiting(self):
        from aletheia import quick
        for said in ("anything waiting on me", "is anything waiting on me", "what needs my attention"):
            with self.subTest(said=said):
                self.assertEqual(quick.match(said)[0], "waiting")



class MyRemindersAreAllOfThem(unittest.TestCase):
    """2026-10-07: "cancel my reminders" looked for one called "my"."""

    def test_plural_is_every_one(self):
        for said, sort in (("cancel my reminders", "reminders"), ("clear my alarms", "alarms"),
                           ("stop the timers", "timers")):
            with self.subTest(said=said):
                self.assertEqual(voice._interpret(said)["command"], {"kind": "reminder_off", "which": "all " + sort})

    def test_my_reminder_is_the_one_or_a_question(self):
        from aletheia import intercom
        rows = [{"id": "a", "command": {"text": "call mom"}}, {"id": "b", "command": {"text": "feed the cat"}}]
        words = {"a": "call mom — today at 5 pm", "b": "feed the cat — today at 6 pm"}
        with mock.patch.object(intercom, "_reminder_schedules", return_value=rows[:1]):
            self.assertEqual(intercom._one_reminder("my")[0]["id"], "a")
        with mock.patch.object(intercom, "_reminder_schedules", return_value=rows), \
             mock.patch.object(intercom, "_soonest_first", side_effect=lambda r: list(r)), \
             mock.patch.object(intercom, "_reminder_words", side_effect=lambda r, **_: words[r["id"]]):
            found, why = intercom._one_reminder("my")
            self.assertIsNone(found)
            self.assertIn(" or ", why)
            self.assertTrue(why.startswith("You have 2 reminders. Which one: "))



class WhichTuesdayIsAnswered(unittest.TestCase):
    """2026-10-07: "Which Tuesday?" dropped the time he gave, and "the 13th"
    in answer went to the planner. Same for "Which reminder?"."""

    ASKED = ("Which Tuesday — the 13th, or the week after on the 20th? "
             "Say 'remind me on the 13th at noon to call the bank' and it's set.")

    def test_the_time_travels_in_the_offer(self):
        said = voice._interpret("remind me next tuesday at noon to call the bank")["say"] or ""
        if said.startswith("Which Tuesday"):
            self.assertIn("at noon to call the bank", said)

    def test_the_answer_sets_it(self):
        for answer, day in (("the 13th", "13"), ("the first one", "13"), ("the week after", "20"), ("20th", "20")):
            with self.subTest(answer=answer), \
                 mock.patch.object(voice, "_previous_turn", return_value=("remind me next tuesday", self.ASKED)):
                got = voice._interpret(answer)["command"]
                self.assertEqual(got["kind"], "remind_at")
                self.assertIn(f"-{day}T12:00", got["at"])
                self.assertEqual(got["text"], "call the bank")

    def test_which_reminder_is_answered(self):
        asked = "You have 2 reminders. Which one: call mom — today at 5 pm or feed the cat — today at 6 pm?"
        with mock.patch.object(voice, "_previous_turn", return_value=("delete my reminder", asked)):
            self.assertEqual(voice._interpret("the call mom one")["command"], {"kind": "reminder_off", "which": "call mom"})
            self.assertEqual(voice._interpret("both")["command"], {"kind": "reminder_off", "which": "all reminders"})



class EveryWayToSayANote(unittest.TestCase):
    """2026-10-07: "add to my notes that ...", "new note: ..." went to the planner."""

    def test_notes(self):
        for said, kept in (("add to my notes that the wifi password is on the router", "the wifi password is on the router"),
                           ("put in my notes the gym opens at 6", "the gym opens at 6"),
                           ("save a note: call the vet", "call the vet"),
                           ("make a note to buy stamps", "buy stamps"),
                           ("new note: dentist is dr kim", "dentist is dr kim")):
            with self.subTest(said=said):
                self.assertEqual(voice._interpret(said)["command"], {"kind": "note", "text": kept})



class ATaskSaidInPassing(unittest.TestCase):
    """2026-10-07: "emailed Sam" with no "I", and "the plumber task is due
    friday", both went to the planner with the task on his list."""

    def test_done_and_due(self):
        with mock.patch.object(voice, "_names_one_open_task", side_effect=lambda w: "plumber" in w or "sam" in w):
            self.assertEqual(voice._interpret("emailed Sam")["command"], {"kind": "task_done", "which": "emailed sam"})
            got = voice._interpret("the plumber task is due friday")["command"]
            self.assertEqual((got["kind"], got["which"]), ("task_change", "plumber"))
            self.assertIn("deadline", got)
        with mock.patch.object(voice, "_names_one_open_task", return_value=False):
            self.assertNotEqual((voice._interpret("emailed Sam")["command"] or {}).get("kind"), "task_done")



class HerHoldIsNotASubscription(unittest.TestCase):
    """2026-10-07: "cancel my haircut" after she pencilled it in was a
    subscription cancellation; "move my haircut to 11" went to the planner."""

    HOLD = {"title": "haircut", "start": "2026-10-08T10:00:00-05:00", "end": "2026-10-08T11:00:00-05:00"}

    def test_cancel_and_move(self):
        with mock.patch.object(voice, "_one_of_her_holds",
                               side_effect=lambda w: (self.HOLD, "") if "haircut" in w else (None, "")):
            self.assertEqual(voice._interpret("cancel my haircut")["command"],
                             {"kind": "hold_release", "title": "haircut", "start": self.HOLD["start"]})
            got = voice._interpret("move my haircut to 11")["command"]
            self.assertEqual((got["kind"], got["replaces"]), ("calendar_hold", self.HOLD["start"]))
            self.assertIn("T11:00", got["start"])
            self.assertEqual(voice._interpret("cancel netflix")["command"]["kind"], "subscription_cancel")


class ADueDayIsKeptAsADate(unittest.TestCase):
    """2026-10-07: "the rent is due friday" went to the planner, and "when
    are my library books due" to a model."""

    def test_a_weekday_becomes_its_date(self):
        got = voice._interpret("the rent is due friday")["command"]
        self.assertEqual(got["kind"], "note")
        self.assertRegex(got["text"], r"^the rent is due Friday \d{1,2} [A-Z][a-z]+$")
        self.assertEqual(voice._interpret("my library books are due tomorrow")["command"]["kind"], "note")

    def test_the_question_in_the_plural(self):
        from aletheia import quick
        self.assertEqual(quick.match("when are my library books due")[0], "task_due")



class TellSomebodyIsAText(unittest.TestCase):
    """2026-10-07: "tell mom dinner is at 7" and "let mom know I'll be late"
    went to the planner."""

    def test_someone_he_has(self):
        self.assertEqual(voice._interpret("tell mom that dinner is at 7")["command"],
                         {"kind": "message_send", "to": "mom", "body": "dinner is at 7"})
        self.assertEqual(voice._interpret("let mom know I'll be late")["command"],
                         {"kind": "message_send", "to": "mom", "body": "I'll be late"})

    def test_not_a_text(self):
        for said in ("tell me a joke", "tell mom about the trip", "let mom know", "tell the story"):
            with self.subTest(said=said):
                self.assertNotEqual(((voice._interpret(said) or {}).get("command") or {}).get("kind"), "message_send")



class NextFridayIsBothFridays(unittest.TestCase):
    """2026-10-07: "what's the date next friday" picked one silently."""

    def test_both_are_said(self):
        from aletheia import quick
        kind, rest = quick.match("what's the date next friday")
        said = quick._date_of(rest)
        self.assertTrue(said.startswith("Friday the "))
        self.assertIn("if you mean the week after", said)
        self.assertNotIn("week after", quick._date_of("this friday"))



class TwoAsksInOneBreath(unittest.TestCase):
    """2026-10-07: "add milk to the list and remind me at 5 to go shopping"
    went to the planner whole, and "add a task to water the plants and set
    a timer for 10 minutes" became one task."""

    def test_split(self):
        for said, halves in (
                ("add milk and eggs to the list and remind me at 5 to go shopping",
                 ["add milk and eggs to the list", "remind me at 5 to go shopping"]),
                ("add a task to water the plants and set a timer for 10 minutes",
                 ["add a task to water the plants", "set a timer for 10 minutes"])):
            with self.subTest(said=said):
                self.assertEqual(voice.two_asks(said), halves)

    def test_one_ask_with_an_and_in_it(self):
        for said in ("remind me to text mom and call dad", "remind me at 5 to buy milk and eggs",
                     "add milk and eggs to the list", "note that Dana called and wants the report",
                     "order a pizza and set a timer for 20 minutes"):
            with self.subTest(said=said):
                self.assertIsNone(voice.two_asks(said))



class TheForecastForADay(unittest.TestCase):
    """2026-10-07: "how hot will it be this weekend" and "what's the
    forecast for friday" went to a model; a day past the forecast was
    answered with right now."""

    PERIODS = [{"name": "Today", "isDaytime": True, "temperature": 60, "shortForecast": "Sunny"},
               {"name": "Tonight", "isDaytime": False, "temperature": 50, "shortForecast": "Clear"},
               {"name": "Thursday", "isDaytime": True, "temperature": 62, "shortForecast": "Cloudy"},
               {"name": "Friday", "isDaytime": True, "temperature": 64, "shortForecast": "Rain"}]

    def test_the_question_reaches_the_forecast(self):
        from aletheia import quick
        for said, when in (("how hot will it be this weekend", "this weekend"),
                           ("what's the forecast for friday", "friday")):
            with self.subTest(said=said):
                self.assertEqual(quick.match(said), ("weather", when))

    def test_the_day_named_or_honestly_not(self):
        from aletheia import weather
        self.assertEqual(weather._periods_for(self.PERIODS, "on friday")[0]["name"], "Friday")
        self.assertIn("doesn't reach Sunday", weather._periods_for(self.PERIODS, "sunday"))



class WhereHeWorks(unittest.TestCase):
    """2026-10-07: "I work for Acme" and "where do I work" both went to the planner."""

    def test_said_and_asked(self):
        from aletheia import quick
        self.assertEqual(voice._interpret("I work for Acme Corp")["command"]["kind"], "note")
        self.assertNotEqual((voice._interpret("I work at 9 tomorrow")["command"] or {}).get("kind"), "note")
        with mock.patch.object(quick, "_notes", return_value=[{"text": "I work for Acme Corp"}]):
            self.assertEqual(quick.answer("where do I work"), "You told me you work for Acme Corp.")
        with mock.patch.object(quick, "_notes", return_value=[]):
            self.assertIsNone(quick.answer("where do I work"))



class WhatsAfterThat(unittest.TestCase):
    """2026-10-07: "what's after that" after her next meeting went to a model."""

    def test_the_one_after_the_one_she_named(self):
        import datetime as dt
        from aletheia import calendar, converse, quick, speech
        soon = dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=1)
        events = [{"title": "lunch with Sam", "start": soon.isoformat()},
                  {"title": "dentist", "start": (soon + dt.timedelta(days=2)).isoformat()}]
        said = f"Next up: lunch with Sam, {speech.humanize_time(soon.isoformat())}."
        with mock.patch.object(calendar, "all_events", return_value=events), \
             mock.patch.object(converse, "_thread", return_value=[{"you": "what's next", "her": said}]):
            self.assertTrue(quick.answer("what's after that").startswith("After that: dentist, "))
        with mock.patch.object(calendar, "all_events", return_value=events), \
             mock.patch.object(converse, "_thread", return_value=[{"you": "hi", "her": "Hello."}]):
            self.assertIsNone(quick.answer("what's after that"))



class SumsWithNoSpaces(unittest.TestCase):
    """2026-10-07: "what is 2+2" and "5*3" went to a model."""

    def test_sums(self):
        from aletheia import quick
        for said, answer in (("what is 2+2", "4."), ("what's 5*3", "15."), ("what's 10/4", "2.5."), ("what's 3x4", "12.")):
            with self.subTest(said=said):
                self.assertEqual(quick.answer(said), answer)



class AnotherWordFor(unittest.TestCase):
    """2026-10-07: "what's a synonym for happy" and "the opposite of hot" went to a model."""

    DATA = [{"meanings": [{"partOfSpeech": "adjective", "synonyms": ["joyful", "cheerful"], "antonyms": ["sad"],
                           "definitions": [{"definition": "x", "synonyms": ["content"], "antonyms": ["unhappy"]}]}]}]

    def test_the_dictionary_lists_them(self):
        from aletheia import dictionary
        self.assertEqual(dictionary.spoken_related("happy", "synonyms", fetch=lambda w: self.DATA),
                         "Other words for happy: joyful, cheerful or content.")
        self.assertEqual(dictionary.spoken_related("happy", "antonyms", fetch=lambda w: self.DATA),
                         "The opposite of happy: sad or unhappy.")
        self.assertEqual(dictionary.spoken_related("zz", "synonyms", fetch=lambda w: []), "")

    def test_the_question_reaches_it(self):
        from aletheia import quick
        self.assertEqual(quick.match("what's a synonym for happy"), ("synonym", "happy"))
        self.assertEqual(quick.match("what's the opposite of hot"), ("antonym", "hot"))



class RestartTheTimer(unittest.TestCase):
    """2026-10-07: "restart the timer" was told she can't pause a timer."""

    def test_the_length_its_words_name(self):
        for words, minutes in (("your 10-minute timer is up", 10), ("your 2-hour timer is up", 120),
                               ("your 1 hour 30 minute timer is up", 90), ("your 90-minute tea timer is up", 90)):
            with self.subTest(words=words):
                self.assertEqual(voice._timer_minutes(words), minutes)

    def test_again_from_now(self):
        import datetime as dt
        soon = dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=3)
        with mock.patch.object(voice, "_running_once", return_value=[(soon, "your 10-minute timer is up")]):
            got = voice._interpret("restart the timer")["command"]
        self.assertEqual((got["kind"], got["text"], got["replaces"]),
                         ("remind_at", "your 10-minute timer is up", "your 10-minute timer is up"))
        left = dt.datetime.fromisoformat(got["at"]) - dt.datetime.now(dt.timezone.utc)
        self.assertGreater(left.total_seconds(), 9 * 60)



class WeightWaterAndSpending(unittest.TestCase):
    """2026-10-07: "I weigh 180" and "I spent 40 dollars on gas" went to the
    planner, and "log 8 glasses of water" was not counted."""

    def test_kept(self):
        for said in ("I weigh 180", "I spent 40 dollars on gas", "i'm 82 kg"):
            with self.subTest(said=said):
                self.assertEqual(voice._interpret(said)["command"]["kind"], "note")
        self.assertNotEqual((voice._interpret("I'm 30")["command"] or {}).get("kind"), "note")

    def test_read_back(self):
        from aletheia import quick
        with mock.patch.object(quick, "_notes", return_value=[{"text": "I weigh 180"}]):
            self.assertEqual(quick.answer("what's my weight"), "You told me you weigh 180.")
        with mock.patch.object(quick, "_notes", return_value=[]):
            self.assertIsNone(quick.answer("how much do I weigh"))



class TheHatIsAHat(unittest.TestCase):
    """2026-10-07: "remove the hat" from a list holding "a hat" said
    "Nothing matches 'the hat'"; "how many lists do I have" went to a model."""

    def test_the_article_is_not_the_thing(self):
        import tempfile
        from pathlib import Path
        from aletheia import lists
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(lists, "_path", side_effect=lambda n: Path(tmp) / f"{n}.json"):
            try:
                lists.create("packing")
            except Exception:
                pass
            lists.add("packing", ["sunscreen", "a hat"])
            gone, why = lists.take_off("packing", "the hat")
            self.assertEqual((gone, why), (["a hat"], ""))
            self.assertEqual(lists.take_off("packing", "the boots")[1], "There's nothing called the boots on your packing list.")

    def test_how_many_lists(self):
        self.assertEqual(voice._interpret("how many lists do I have")["command"], {"kind": "list_read"})



class TheReminderJustSet(unittest.TestCase):
    """2026-10-07: "what time is that reminder", "and remind me to text dad
    too" and "change call mom to call grandma" all went to the planner."""

    SPEC = {"kind": "once", "at": "2026-10-07T23:00:00+00:00", "command": {"text": "call mom"}}

    def test_asked_about_added_to_and_renamed(self):
        with mock.patch.object(voice, "_the_reminder_just_set", return_value=self.SPEC):
            self.assertTrue(voice._interpret("what time is that reminder")["say"].startswith("That's "))
            self.assertEqual(voice._interpret("and remind me to text dad too")["command"],
                             {"kind": "remind_at", "at": self.SPEC["at"], "text": "text dad"})
            self.assertEqual(voice._interpret("change call mom to call grandma")["command"],
                             {"kind": "remind_at", "at": self.SPEC["at"], "text": "call grandma", "replaces": "call mom"})
            # A time is a move, not new words.
            self.assertNotEqual((voice._interpret("change it to 7")["command"] or {}).get("text"), "7")

    def test_nothing_just_set(self):
        with mock.patch.object(voice, "_the_reminder_just_set", return_value=None):
            self.assertIsNone(voice._interpret("and remind me to text dad too")["command"])



class WeekdayAndQuarter(unittest.TestCase):
    """2026-10-07: "is tomorrow a weekday" and "what quarter are we in" went to a model."""

    def test_answers(self):
        from aletheia import quick
        self.assertEqual(quick.answer("is saturday a work day"), "No - Saturday is the weekend.")
        self.assertRegex(quick.answer("is tomorrow a weekday"), r"^(?:Yes|No) - tomorrow is [A-Z][a-z]+day\.$")
        self.assertRegex(quick.answer("what quarter are we in"), r"^The (?:first|second|third|fourth) quarter of \d{4}\.$")



class WhatDidIMissToday(unittest.TestCase):
    def test_brief(self):
        for said in ("what did I miss today", "what did I miss while I was out", "catch me up on today"):
            with self.subTest(said=said):
                self.assertEqual(voice._interpret(said)["command"], {"kind": "brief"})



class MicCheckAndThePC(unittest.TestCase):
    def test_said_plainly(self):
        self.assertEqual(voice._interpret("testing 1 2 3")["say"], "I hear you.")
        self.assertEqual(voice._interpret("is my computer on")["say"], "Yes - I'm running on it right now.")
        self.assertIn("only the PC's", voice._interpret("what's my phone's battery")["say"])



class ReplyToTheEmailSheRead(unittest.TestCase):
    """2026-10-07: "reply saying sounds great" after she read an email went to the planner."""

    READ = ("read the email from sam", "From Sam Lee <sam@x.com> — Dinner Friday?: Are you free Friday at 7?")

    def test_a_draft_to_its_sender(self):
        with mock.patch.object(voice, "_previous_turn", return_value=self.READ):
            self.assertEqual(voice._interpret("reply saying sounds great")["command"],
                             {"kind": "email_draft", "to": "sam@x.com", "subject": "Re: Dinner Friday?",
                              "body": "sounds great"})
            self.assertIn("can't forward", voice._interpret("forward it to Dana")["say"])
            self.assertIn("can't delete, archive", voice._interpret("archive that")["say"])

    def test_not_after_anything_else(self):
        with mock.patch.object(voice, "_previous_turn", return_value=("hi", "Hello.")):
            self.assertNotEqual((voice._interpret("reply saying sounds great")["command"] or {}).get("kind"), "email_draft")



class AddABirthday(unittest.TestCase):
    def test_add_is_the_same_fact(self):
        self.assertEqual(voice.interpret("save Sam's birthday as May 2")["command"],
                         {"kind": "note", "text": "Sam's birthday is May 2"})
        self.assertEqual(voice.interpret("add mom's birthday june 3")["command"]["kind"], "note")



class WhatHisBirthdaySettles(unittest.TestCase):
    """2026-10-07: his sign, the weekday he was born, how old he'll be and a
    reminder on his birthday all went to a model with the date on file."""

    def test_from_the_date_on_file(self):
        from aletheia import quick
        with mock.patch.object(quick, "_birthday_on_file", return_value=(5, 5, 1995)):
            self.assertEqual(quick.answer("what's my zodiac sign"), "Taurus - your birthday is May 5.")
            self.assertEqual(quick.answer("what day was I born"), "You were born on a Friday.")
            self.assertIn("when you turn", quick.answer("how old will I be on my birthday"))
            got = voice._interpret("remind me on my birthday to celebrate")["command"]
            self.assertEqual((got["kind"], got["text"]), ("remind_at", "celebrate"))
            self.assertIn("-05-05T09:00", got["at"])
        with mock.patch.object(quick, "_birthday_on_file", return_value=(12, 25, None)):
            self.assertTrue(quick.answer("what's my sign").startswith("Capricorn"))
            self.assertIn("not the year", quick.answer("what day was I born"))



class HisCommute(unittest.TestCase):
    def test_commute(self):
        with mock.patch.object(voice, "_known_place", return_value=True):
            self.assertEqual(voice._interpret("how long is my commute")["command"], {"kind": "travel_time", "place": "work"})
        with mock.patch.object(voice, "_known_place", return_value=False):
            self.assertIn("work is at", voice._interpret("when should I leave for work")["say"])



class TheListSheJustRead(unittest.TestCase):
    """2026-10-07: after "6 things on your shopping list: ...", "how many is
    that", "is cheese on it" and "take the first one off" went to the planner,
    and "socks and a hat" was one thing on a list."""

    def _read(self, said):
        import re
        return re.match(r"(?P<n>\d+) things? on your (?P<name>[\w' -]+?) list: (?P<items>.+)\.$", said)

    def test_follow_ons(self):
        read = self._read("3 things on your shopping list: bread, cheese and milk.")
        with mock.patch.object(voice, "_list_just_read", return_value=read):
            self.assertEqual(voice._interpret("how many things is that")["say"], "3.")
            self.assertEqual(voice._interpret("is cheese on it")["say"], "Yes - cheese is on it.")
            self.assertEqual(voice._interpret("is ham on it")["say"], "No, ham isn't on it.")
            self.assertEqual(voice._interpret("take the first one off")["command"], {"kind": "shopping_off", "item": "bread"})
        read = self._read("2 things on your packing list: socks and a hat.")
        with mock.patch.object(voice, "_list_just_read", return_value=read):
            self.assertEqual(voice._interpret("remove the last one")["command"],
                             {"kind": "list_off", "list": "packing", "item": "a hat"})

    def test_an_article_is_not_part_of_the_name(self):
        from aletheia import intercom
        self.assertEqual(intercom.shopping_items_of("socks and a hat"), ["socks", "a hat"])
        self.assertEqual(intercom.shopping_items_of("salt and vinegar chips"), ["salt and vinegar chips"])



class ATaskClosedInHisWords(unittest.TestCase):
    """2026-10-07: "delete the last one" said "Email sam is now cancelled"."""

    def test_his_words(self):
        from aletheia import speech, tasks
        with mock.patch.object(tasks, "load", return_value={"description": "email Sam"}):
            self.assertEqual(speech.spoken_receipt("task_status", "task email-sam -> CANCELLED"),
                             "Took it off your list: email Sam.")

    def test_how_many_after_his_task_list(self):
        import re
        read = re.match(r"(?P<n>\d+) things? on your (?:(?P<name>[\w' -]+?) )?list: (?P<items>.+)\.$",
                        "2 things on your list: call the plumber and email Sam.")
        with mock.patch.object(voice, "_list_just_read", return_value=read):
            self.assertEqual(voice._interpret("how many is that")["say"], "2.")



class AlarmAtSeven(unittest.TestCase):
    """2026-10-07: "alarm at 7" and "7am alarm" went to the planner."""

    def test_the_noun_with_a_time(self):
        for said, clock in (("alarm at 7", "T07:00"), ("7am alarm", "T07:00"), ("6:30 alarm tomorrow", "T06:30")):
            with self.subTest(said=said):
                got = voice._interpret(said)["command"]
                self.assertEqual((got["kind"], got["text"]), ("remind_at", "wake up"))
                self.assertIn(clock, got["at"])
        self.assertEqual(voice._interpret("turn on my alarm")["command"], {"kind": "reminder_on", "which": "all alarms"})



class CountsHeKeeps(unittest.TestCase):
    """2026-10-07: "I did 50 pushups" ticked off a task called "50 pushups",
    and "how many pushups have I done" went to a model."""

    def test_kept_and_added_up(self):
        import datetime as dt
        from aletheia import quick
        self.assertEqual(voice._interpret("I did 50 pushups")["command"], {"kind": "note", "text": "I did 50 pushups"})
        now = dt.datetime.now(dt.timezone.utc).isoformat()
        notes = [{"text": "I did 50 pushups", "ts": now}, {"text": "I did 30 push-ups", "ts": now},
                 {"text": "I walked 5000 steps", "ts": now}]
        with mock.patch.object(quick, "_notes", return_value=notes):
            self.assertEqual(quick.answer("how many pushups have I done today"), "80 pushups today.")
            self.assertEqual(voice._interpret("how many steps did I take today")["say"], "5,000 steps today.")
            self.assertTrue(quick.answer("how many squats have I done").startswith("You haven't told me about any squats"))


class WhatHeAte(unittest.TestCase):
    def test_kept_and_read_back_by_day_and_meal(self):
        import datetime as dt
        from aletheia import quick
        self.assertEqual(voice._interpret("I had a burrito for lunch")["command"],
                         {"kind": "note", "text": "I had a burrito for lunch"})
        self.assertEqual(voice._interpret("for dinner I had pasta")["command"]["kind"], "note")
        for not_food in ("I had a meeting for lunch", "I had lunch with Dana", "I ate it"):
            got = voice._interpret(not_food)
            self.assertFalse(got and (got.get("command") or {}).get("kind") == "note", not_food)
        now = dt.datetime.now(dt.timezone.utc)
        notes = [{"text": "I ate an apple", "ts": now.isoformat()},
                 {"text": "I had a burrito for lunch", "ts": now.isoformat()},
                 {"text": "I had soup for lunch", "ts": (now - dt.timedelta(days=1)).isoformat()}]
        with mock.patch.object(quick, "_notes", return_value=notes):
            self.assertEqual(quick.answer("what did I have for lunch"), "You told me you had a burrito for lunch today.")
            self.assertEqual(quick.answer("what did I have for lunch yesterday"), "You told me you had soup for lunch yesterday.")
            self.assertEqual(quick.answer("what did I eat today"),
                             "You told me you had a burrito for lunch and an apple today.")
            self.assertTrue(quick.answer("what did I have for breakfast").startswith("You didn't tell me"))


class SunriseAskedAsAThing(unittest.TestCase):
    def test_the_sunrise_is_the_sun_not_a_note(self):
        from aletheia import quick, weather
        with mock.patch.object(weather, "spoken_sun", side_effect=lambda which, when: f"{which}|{when}"):
            self.assertEqual(quick.answer("what's the sunrise tomorrow"), "rise|tomorrow")
            self.assertEqual(quick.answer("when's the sunset"), "set|")


class CallsHeMade(unittest.TestCase):
    def test_a_call_is_kept_and_counted_from(self):
        import datetime as dt
        from aletheia import quick
        self.assertEqual(voice._interpret("I called mom")["command"], {"kind": "note", "text": "I called mom"})
        self.assertEqual(quick._base_verb("trimmed"), "trim")
        self.assertEqual(quick._base_verb("changed"), "change")
        three = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=3)).isoformat()
        with mock.patch.object(quick, "_notes", return_value=[{"text": "I called mom", "ts": three}]):
            for asked in ("when did I last call mom", "how long since I called mom"):
                said = quick.answer(asked)
                self.assertTrue(said.startswith("You told me you called mom - that was"), (asked, said))
            self.assertTrue(quick.answer("did I call mom today").startswith("Not today"))
        with mock.patch.object(quick, "_notes", return_value=[]):
            self.assertIn(" days, since ", quick.answer("how long since january 1"))


class WhenHeSlept(unittest.TestCase):
    def test_wake_and_bed_times_are_kept(self):
        from aletheia import quick
        self.assertEqual(voice._interpret("I woke up at 7")["command"], {"kind": "note", "text": "I woke up at 7"})
        notes = [{"text": "I went to bed at 11 last night"}, {"text": "I woke up at 6:30"}]
        with mock.patch.object(quick, "_notes", return_value=notes):
            self.assertEqual(quick.answer("what time did I wake up"), "You told me you woke up at 6:30.")
            self.assertEqual(quick.answer("when did I go to bed last night"), "You told me you went to bed at 11 last night.")
        with mock.patch.object(quick, "_notes", return_value=[]):
            self.assertIn("I went to bed at 11", quick.answer("what time did I go to bed"))
        import datetime as dt
        now = dt.datetime.now(dt.timezone.utc).isoformat()
        with mock.patch.object(quick, "_notes", return_value=[{"text": "I woke up at 7", "ts": now}]):
            self.assertEqual(quick.answer("what time did I wake up"), "You told me you woke up at 7 this morning.")

    def test_a_drink_count_needs_no_verb_but_needs_a_day(self):
        from aletheia import quick
        with mock.patch.object(quick, "_notes", return_value=[]):
            self.assertIn("a cup of coffee", quick.answer("how many cups of coffee today"))
        self.assertNotEqual((quick.match("how many cups of water") or ("",))[0], "logged")


class BudgetsAndGoals(unittest.TestCase):
    def test_an_aim_or_a_number_is_kept_and_a_feeling_is_not(self):
        from aletheia import quick
        for kept in ("my budget is 2000 a month", "my goal is to run a marathon", "my step goal is 10000",
                     "my gym is Planet Fitness"):
            self.assertEqual(voice._interpret(kept)["command"]["kind"], "note", kept)
        for felt in ("my budget is tight", "my goal is hard"):
            got = voice._interpret(felt)
            self.assertFalse(got and (got.get("command") or {}).get("kind") == "note", felt)
        with mock.patch.object(quick, "_notes", return_value=[{"text": "my budget is 2000 a month"}]):
            self.assertEqual(quick.answer("what's my budget"), "You told me: your budget is 2000 a month.")


class WhatHeIsForgetting(unittest.TestCase):
    def test_forgetting_is_his_day_not_a_model(self):
        from aletheia import quick
        for asked in ("what am I forgetting", "am I forgetting anything", "did I forget something today"):
            self.assertEqual((quick.match(asked) or ("",))[0], "tasks_due", asked)


class LengthsOfTime(unittest.TestCase):
    def test_converted_and_said_with_the_remainder(self):
        from aletheia import quick
        self.assertEqual(quick.answer("what's 1000 seconds in minutes"), "16 minutes and 40 seconds.")
        self.assertEqual(quick.answer("convert 90 minutes to hours"), "1 hour and 30 minutes.")
        self.assertEqual(quick.answer("what's 3 hours in minutes"), "180 minutes.")
        self.assertEqual(quick.answer("0.5 hours in minutes"), "30 minutes.")


class RainThisAfternoon(unittest.TestCase):
    def test_part_of_a_day_is_the_forecasts_half_of_it(self):
        from aletheia import quick, weather
        with mock.patch.object(weather, "rain", side_effect=lambda when: f"rain|{when}"):
            self.assertEqual(quick.answer("will it rain this afternoon"), "rain|today")
            self.assertEqual(quick.answer("is it going to rain this evening"), "rain|tonight")
            self.assertEqual(quick.answer("do I need an umbrella later"), "rain|")


class AChoiceNamesAnOption(unittest.TestCase):
    def test_good_night_is_not_which_alarm(self):
        from aletheia import converse, quick
        asked = [{"she_answered": "Which one \u2014 tomorrow at 6 am or tomorrow at 7 am?"}]
        with mock.patch.object(converse, "recent", return_value=asked), \
                mock.patch.object(voice, "_previous_ask", return_value="turn off my alarm"):
            self.assertIsNone(voice._answers_which("good night"))
            self.assertEqual(voice._answers_which("the 7 one")["command"],
                             {"kind": "reminder_off", "which": "wake up 7:00"})
        self.assertEqual((quick.match("I'm leaving work") or ("",))[0], "farewell")


class TheMoonIsNotAJourney(unittest.TestCase):
    def test_the_rule_rung_does_not_time_a_drive_to_the_moon(self):
        from aletheia import rule_planner
        self.assertIsNone(rule_planner.match("how far is the moon"))
        self.assertIsNotNone(rule_planner.match("how far is chicago"))


class ConstantsWithoutAModel(unittest.TestCase):
    def test_pi_is_said(self):
        from aletheia import quick
        self.assertTrue(quick.answer("what's pi").startswith("Pi is about 3.14159"))
        self.assertTrue(quick.answer("what's the freezing point of water").startswith("0 degrees Celsius"))


class AReminderSaidAsANoun(unittest.TestCase):
    def test_set_a_daily_reminder_is_remind_me_every_day(self):
        cmd = lambda said: (voice._interpret(said).get("command") or {})
        self.assertEqual(cmd("set a daily reminder to take my pills at 9"),
                         {"kind": "remind_daily", "time": "09:00", "text": "take my pills"})
        self.assertEqual(cmd("add a monthly reminder to pay rent on the 1st")["kind"], "remind_monthly")
        self.assertEqual(cmd("add a weekly reminder to take out the trash on tuesdays")["days"], ["tuesday"])
        self.assertEqual(cmd("create a reminder to call mom at 5")["kind"], "remind_at")
        self.assertEqual(cmd("remind me every day to take my pills at 9"),
                         {"kind": "remind_daily", "time": "09:00", "text": "take my pills"})
        self.assertEqual(cmd("set a reminder for 3pm to call the bank")["text"], "call the bank")
        self.assertTrue(voice._interpret("set a reminder to stretch")["say"].startswith("When should I remind you"))
        # Weekly with no day is not quietly made a one-off.
        self.assertNotEqual(cmd("add a weekly reminder to call grandma").get("kind"), "remind_at")


class WhatSheNotedIsSaidPlainly(unittest.TestCase):
    def test_no_slot_names_in_what_she_did(self):
        from aletheia import speech
        self.assertEqual(speech.spoken_receipt("remember", 'set identity.home_city = "Denver" (explicit)'),
                         "Noted: you live in Denver.")
        self.assertEqual(speech.spoken_receipt("remember", 'set people.car_color = "red" (explicit)'),
                         "Noted: car color is red.")


class AFactChanged(unittest.TestCase):
    def test_change_my_address_is_my_address_is(self):
        self.assertEqual(voice._interpret("change my address to 12 Oak St")["command"],
                         {"kind": "remember", "domain": "identity", "key": "address", "value": "12 Oak St"})
        self.assertEqual(voice._interpret("change my shoe size to 11")["command"],
                         {"kind": "note", "text": "my shoe size is 11"})
        got = voice._interpret("change my mind")
        self.assertNotEqual((got.get("command") or {}).get("kind"), "remember")


class AThingToDoOnMyList(unittest.TestCase):
    def test_write_the_report_is_a_task_and_paint_is_shopping(self):
        kind = lambda said: (voice._interpret(said).get("command") or {}).get("kind")
        self.assertEqual(kind("add write the report to my list"), "task_new")
        self.assertEqual(kind("add do the taxes to my list"), "task_new")
        self.assertEqual(kind("add paint to my list"), "shopping_add")
        self.assertEqual(kind("add paper towels to my list"), "shopping_add")


class DoneWithIt(unittest.TestCase):
    def test_done_with_the_dishes_ticks_it_off(self):
        from aletheia import quick
        self.assertEqual(voice._interpret("I'm done with the dishes")["command"], {"kind": "task_done", "which": "dishes"})
        got = voice._interpret("I'm done with you")
        self.assertNotEqual((got.get("command") or {}).get("kind"), "task_done")
        self.assertEqual((quick.match("how many tasks did I finish this week") or ("",))[0], "tasks_done")


class DeleteTheTaskByName(unittest.TestCase):
    def test_the_task_word_reaches_the_store(self):
        from aletheia import intercom
        self.assertEqual(voice._interpret("delete the task called call the vet")["command"],
                         {"kind": "task_change", "which": "call the vet", "drop": True})
        with mock.patch("aletheia.tasks.all_tasks", return_value=[{"id": "t1", "description": "water plants", "status": "QUEUED"}]):
            found, why = intercom._one_task("call the vet")
        if found is None and why.startswith("Nothing"):
            self.assertNotIn("'", why)


class HowDoIUseHer(unittest.TestCase):
    def test_how_do_i_is_the_sentence_that_does_it(self):
        from aletheia import quick
        self.assertIn("remind me at 3", quick.answer("how do I add a reminder"))
        self.assertIn("cancel my reminder", quick.answer("how do I cancel a reminder"))
        self.assertIn("what's on my list", quick.answer("how do I see my tasks"))
        self.assertIsNone(quick.match("how do I make a cake") and quick.answer("how do I make a cake"))
        # Every sentence it recommends is one she understands without a model.
        for said in ("remind me at 3 to call the dentist", "wake me up at 6", "set a timer for 10 minutes",
                     "add call the vet to my list", "note that the plumber is coming Friday",
                     "add a dentist appointment next Tuesday at 10", "start a stopwatch", "cancel the timer",
                     "turn off my 7 am alarm", "take milk off my shopping list", "make a packing list"):
            self.assertTrue((voice._interpret(said) or {}).get("command"), said)


class DoNotDisturbIsQuiet(unittest.TestCase):
    def test_a_meeting_keeps_her_quiet_not_just_one_notice(self):
        import datetime as dt
        import tempfile
        from pathlib import Path
        from aletheia import announce, intercom, notifications, speech, stateio
        self.assertEqual(voice._interpret("I'm in a meeting")["command"], {"kind": "notify_snooze", "minutes": 60, "quiet": True})
        self.assertTrue(voice._interpret("do not disturb")["command"]["quiet"])
        self.assertNotIn("quiet", voice._interpret("snooze that")["command"])
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(announce, "_hush_path", return_value=Path(tmp) / "hush.json"), \
                mock.patch.object(announce, "CONFIG_FILE", Path(tmp) / "announce.json"), \
                mock.patch.object(announce.journal, "append"), \
                mock.patch.object(notifications, "all_notifications", return_value=[]):
            said = intercom.execute_command({"kind": "notify_snooze", "minutes": 60, "quiet": True}, {}, quote="t")
            self.assertTrue(said.startswith("quiet until"), said)
            self.assertIn("Nothing of mine will interrupt you", speech.spoken_receipt("notify_snooze", said))
            self.assertIsNotNone(announce.hushed_until())
            config = {**announce.DEFAULT_CONFIG, "enabled": True, "quiet_from": "00:00", "quiet_until": "00:00"}
            with mock.patch.object(announce.policy, "halted", return_value=False):
                self.assertEqual(announce.pending(config=config), [])
            stateio.write_json_atomic(Path(tmp) / "hush.json", {"until": "2000-01-01T00:00:00Z"})
            self.assertIsNone(announce.hushed_until())
        both = speech.spoken_receipt("notify_snooze", "snoozed snooze-1 until 2030-01-01T18:00:00+00:00 \u2014 'the boiler'; "
                                     "quiet until 2030-01-01T18:00:00Z")
        self.assertTrue(both.startswith("Put away until") and "I'll keep quiet until" in both, both)


class HisNewsHeardLikeAPerson(unittest.TestCase):
    def test_good_and_sad_news_get_a_human_line(self):
        from aletheia import quick
        self.assertEqual(quick.answer("I feel great"), "Glad to hear it.")
        self.assertTrue(quick.answer("I got the job").startswith("Congratulations"))
        self.assertTrue(quick.answer("my dog died").startswith("I'm so sorry"))
        self.assertEqual(quick.answer("today is my anniversary"), "Happy anniversary!")
        self.assertNotEqual((quick.match("I'm good") or ("",))[0], "life_news")
        self.assertEqual((quick.match("what's the news") or ("",))[0], "news")


class ShortDayQuestions(unittest.TestCase):
    def test_anything_tomorrow_and_next_mondays_date(self):
        from aletheia import quick
        self.assertEqual(quick.match("anything tomorrow"), ("agenda", "tomorrow"))
        self.assertEqual(quick.match("what's next monday's date"), ("date_of", "next monday"))
        self.assertIsNone(quick.match("anything else"))


class ThingsHeToldHerOnce(unittest.TestCase):
    def test_a_locker_a_flight_a_loan_and_a_taste_are_kept_and_read(self):
        import datetime as dt
        from aletheia import quick
        for said in ("my locker is 42", "my flight is at 6am friday", "my train leaves at 7:15",
                     "I lent my drill to Bob", "I lent Bob my drill", "Bob borrowed my ladder", "I like my coffee black"):
            self.assertEqual((voice._interpret(said) or {}).get("command"), {"kind": "note", "text": said}, said)
        for feeling in ("my locker is a mess", "my flight is delayed", "I like my coffee a lot"):
            got = voice._interpret(feeling)
            self.assertFalse(got and (got.get("command") or {}).get("kind") == "note", feeling)
        now = dt.datetime.now(dt.timezone.utc).isoformat()
        notes = [{"text": t, "ts": now} for t in ("my locker is 42", "my flight is at 6am friday",
                                                  "I lent my drill to Bob", "I like my coffee black")]
        with mock.patch.object(quick, "_notes", return_value=notes), \
                mock.patch.object(quick, "_coming", return_value=[]):
            self.assertIn("42", quick.answer("what's my locker number"))
            self.assertIn("6am Friday", quick.answer("when is my flight"))
            for asked in ("who has my drill", "who did I lend my drill to"):
                self.assertIn("Bob", quick.answer(asked), asked)
            self.assertIn("Bob", voice._where_he_put("drill"))
            self.assertEqual(quick.answer("who has my ladder"), "You haven't told me you lent your ladder to anybody.")
            self.assertIn("black", quick.answer("how do I like my coffee"))
            self.assertIn("haven't told me", quick.answer("how do I take my tea"))

    def test_who_do_i_owe_money_to_reads_the_ledger(self):
        from aletheia import quick
        with mock.patch.object(quick, "_ledger", return_value={"jo": -5}):
            self.assertIn("Jo", quick.answer("who do I owe money to"))


class TheGymAndARun(unittest.TestCase):
    def test_kept_dated_and_counted(self):
        import datetime as dt
        from aletheia import quick
        with mock.patch.object(voice, "_names_one_open_task", return_value=False):
            for said in ("I went for a run", "I went to the gym", "I worked out", "I meditated"):
                self.assertEqual((voice._interpret(said) or {}).get("command"), {"kind": "note", "text": said}, said)
        now = dt.datetime.now(dt.timezone.utc)
        notes = [{"text": "I went to the gym", "ts": now.isoformat()},
                 {"text": "I went for a run", "ts": (now - dt.timedelta(hours=1)).isoformat()},
                 {"text": "I went to the gym", "ts": (now - dt.timedelta(days=40)).isoformat()}]
        with mock.patch.object(quick, "_notes", return_value=notes):
            self.assertTrue(quick.answer("when did I last go to the gym").startswith("The last time you told me was"))
            self.assertEqual(quick.answer("how many times did I go to the gym this month"), "1 time this month, from what you've told me.")
            self.assertTrue(quick.answer("did I work out today").startswith("Yes"))
            self.assertTrue(quick.answer("have I been for a run today").startswith("Yes"))
            self.assertEqual(quick.answer("did I meditate today"), "Not that you've told me today.")
            self.assertEqual(quick.answer("when did I last go swimming"),
                             "You haven't told me. Say \"I went swimming\" when you do and I'll keep track.")


class WhatHeSaidHeSpent(unittest.TestCase):
    def test_spending_he_told_her_is_added_up(self):
        import datetime as dt
        from aletheia import quick
        now = dt.datetime.now(dt.timezone.utc).isoformat()
        notes = [{"text": "I spent 40 dollars on groceries", "ts": now}, {"text": "I paid $12.50 for gas", "ts": now}]
        with mock.patch.object(quick, "_notes", return_value=notes):
            self.assertEqual(voice._interpret("how much did I spend today")["say"],
                             "$52.50 today, from what you've told me: $40 on groceries and $12.50 on gas.")
            self.assertEqual(voice._interpret("how much did I spend on groceries this week")["say"],
                             "$40 on groceries this week, from what you've told me.")
        with mock.patch.object(quick, "_notes", return_value=[]):
            self.assertEqual(voice._interpret("how much did I spend this week")["command"],
                             {"kind": "money", "about": "spending"})

    def test_a_bill_paid_is_kept_and_dated(self):
        import datetime as dt
        from aletheia import quick
        self.assertEqual(voice._interpret("I paid the electric bill")["command"],
                         {"kind": "note", "text": "I paid the electric bill"})
        two = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=2)).isoformat()
        with mock.patch.object(quick, "_notes", return_value=[{"text": "I paid the electric bill", "ts": two}]):
            self.assertIn("you paid the electric bill", quick.answer("when did I pay the electric bill"))

    def test_what_he_asked_to_be_reminded_of_is_the_list(self):
        for asked in ("what did I ask you to remind me about", "what are you going to remind me about"):
            self.assertEqual(voice._interpret(asked)["command"], {"kind": "reminders"}, asked)


class LaterAndSlower(unittest.TestCase):
    def test_later_is_a_nod_not_a_plan(self):
        for said in ("I'll do it later", "later", "not now", "I'll get to it tomorrow"):
            got = voice._interpret(said)
            self.assertIsNone(got["command"], said)
            self.assertTrue(got["say"].startswith("No rush."), said)

    def test_slower_is_said_again(self):
        from aletheia import quick
        self.assertEqual(quick.match("say that again slower")[0], "repeat")


class HisBillsAndHowOften(unittest.TestCase):
    def test_a_bill_with_a_number_is_kept_and_read(self):
        import datetime as dt
        from aletheia import quick
        for said in ("my rent is 1500", "my car insurance is 120 a month"):
            self.assertEqual(voice._interpret(said)["command"], {"kind": "note", "text": said}, said)
        got = voice._interpret("my rent is too high")
        self.assertFalse(got and (got.get("command") or {}).get("kind") == "note")
        now = dt.datetime.now(dt.timezone.utc).isoformat()
        notes = [{"text": t, "ts": now} for t in ("my rent is 1500", "my car insurance is 120 a month")]
        with mock.patch.object(quick, "_notes", return_value=notes):
            self.assertEqual(quick.answer("how much is my rent"), "You told me: your rent is 1500.")
            self.assertIn("120 a month", quick.answer("how much do I pay for car insurance"))
            bills = quick.answer("what are my bills")
            self.assertIn("rent is 1500", bills)
            self.assertIn("car insurance is 120", bills)
        with mock.patch.object(quick, "_notes", return_value=[]):
            self.assertIsNone(quick.answer("how much is my rent"))

    def test_how_many_times_is_counted_from_his_notes(self):
        import datetime as dt
        from aletheia import quick
        now = dt.datetime.now(dt.timezone.utc).isoformat()
        with mock.patch.object(quick, "_notes", return_value=[{"text": "I walked the dog", "ts": now}] * 2):
            self.assertEqual(quick.answer("how many times did I walk the dog today"), "2 times today, from what you've told me.")
        with mock.patch.object(quick, "_notes", return_value=[]):
            self.assertTrue(quick.answer("how many times did I feed the cat this week").startswith("None this week"))

    def test_rent_due_reads_the_reminder(self):
        from aletheia import quick
        with mock.patch.object(quick, "_when_mine", return_value="You have a reminder on the 1st: pay rent.") as found:
            self.assertEqual(quick.answer("when is rent due"), "You have a reminder on the 1st: pay rent.")
            found.assert_called_with("rent")

    def test_what_to_do_tomorrow_is_the_tasks_due(self):
        from aletheia import quick
        self.assertEqual(quick.match("what do I have to do tomorrow"), ("tasks_due", "tomorrow"))


class HisWorkDay(unittest.TestCase):
    def test_start_end_and_commute_are_kept_and_added_up(self):
        import datetime as dt
        from aletheia import quick
        for said in ("I start work at 9", "I get off work at 5", "my commute is 30 minutes", "my shift starts at 7am"):
            self.assertEqual(voice._interpret(said)["command"], {"kind": "note", "text": said}, said)
        now = dt.datetime.now(dt.timezone.utc).isoformat()
        notes = [{"text": t, "ts": now} for t in ("I start work at 9", "I get off work at 5", "my commute is 30 minutes")]
        with mock.patch.object(quick, "_notes", return_value=notes), \
                mock.patch.object(voice, "_known_place", return_value=None):
            self.assertEqual(quick.answer("what time do I start work"), "You told me: you start work at 9.")
            self.assertEqual(quick.answer("when do I get off work"), "You told me: you get off work at 5.")
            self.assertTrue(voice._interpret("when should I leave for work")["say"].startswith("By 8:30 am - you start at 9"))
        with mock.patch.object(quick, "_notes", return_value=notes[:1]), \
                mock.patch.object(voice, "_known_place", return_value=None):
            self.assertIn("where work is", voice._interpret("when should I leave for work")["say"])


class MonthsInOtherYears(unittest.TestCase):
    def test_a_year_named_is_the_year_counted(self):
        from aletheia import quick
        self.assertEqual(quick.answer("how many days in february 2028"), "February 2028 has 29 days.")
        self.assertEqual(quick.answer("how many days does february 2027 have"), "February 2027 has 28 days.")

    def test_yes_or_no_is_a_coin(self):
        from aletheia import quick
        self.assertIn(quick.answer("yes or no"), ("Yes.", "No."))


class WatchedAndRead(unittest.TestCase):
    def test_finishing_a_thing_on_a_list_takes_it_off_and_it_is_counted(self):
        import datetime as dt
        import tempfile
        from pathlib import Path
        from aletheia import intercom, lists, quick
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(lists, "private_dir", side_effect=lambda name: Path(tmp) / name), \
                mock.patch.object(intercom, "_one_task", return_value=(None, "Nothing open matching that.")), \
                mock.patch.object(intercom, "_one_shopping_item", return_value=(None, "")):
            (Path(tmp) / "lists").mkdir()
            lists.create("watch")
            lists.add("watch", ["Dune", "Arrival"])
            lists.create("reading")
            lists.add("reading", ["The Hobbit"])
            said = intercom.execute_command({"kind": "task_done", "which": "dune"}, None, quote="I finished Dune")
            self.assertEqual(said, "Nice - took it off your watch list: Dune.")
            self.assertEqual(lists.items("watch"), ["Arrival"])
            lists.take_off("reading", "the hobbit")
            self.assertEqual(quick.answer("what have I watched"), "You've watched Dune.")
            self.assertEqual(quick.answer("what was the last book I read"), "The Hobbit, from your list.")
            self.assertEqual(quick.answer("how many books have I read this year"), "1 book this year, off your list.")
            now = dt.datetime.now(dt.timezone.utc).isoformat()
            with mock.patch.object(quick, "_notes", return_value=[{"text": "I started reading Dune Messiah", "ts": now}]):
                self.assertEqual(quick.answer("what am I reading"), "You told me you started Dune Messiah.")
            with mock.patch.object(quick, "_notes", return_value=[{"text": "I started reading The Hobbit", "ts": now}]):
                # finished is not "still reading", and not "never told me"
                self.assertIn("you've finished it", quick.answer("what am I reading"))


class SomebodysAddress(unittest.TestCase):
    def test_an_address_is_never_answered_with_a_phone_number(self):
        import datetime as dt
        from aletheia import quick
        self.assertEqual(voice._interpret("Mom lives at 12 Oak Street")["command"],
                         {"kind": "note", "text": "Mom lives at 12 Oak Street"})
        now = dt.datetime.now(dt.timezone.utc).isoformat()
        with mock.patch.object(quick, "_notes", return_value=[]):
            said = voice._interpret("what's mom's address")["say"]
            self.assertIn("don't have your mom's address", said)
            self.assertNotIn("number", said)
        with mock.patch.object(quick, "_notes", return_value=[{"text": "Mom lives at 12 Oak Street", "ts": now}]):
            self.assertEqual(voice._interpret("what's my mom's address")["say"], "You told me: Mom lives at 12 Oak Street.")
            self.assertEqual(voice._interpret("where does mom live")["say"], "You told me: Mom lives at 12 Oak Street.")


class HerDayAndHisWeek(unittest.TestCase):
    def test_meetings_this_week_are_counted_from_the_calendar(self):
        import datetime as dt
        from aletheia import calendar, localtime, quick
        tz = localtime.operator_tz()
        now = dt.datetime.now(tz)
        sunday_night = (now + dt.timedelta(days=6 - now.weekday())).replace(hour=23, minute=0, second=0, microsecond=0)
        soon = min(now + dt.timedelta(seconds=60), sunday_night)
        events = [{"title": "standup", "start": soon.isoformat()},
                  {"title": "far off", "start": (now + dt.timedelta(days=30)).isoformat()},
                  {"title": "gone", "start": soon.isoformat(), "status": "CANCELLED"}]
        with mock.patch.object(calendar, "all_events", return_value=events):
            said = quick.answer("how many meetings do I have this week")
            self.assertTrue(said.startswith("1 thing on your calendar for the rest of this week: standup"), said)

    def test_first_and_last_asked_with_what_time(self):
        from aletheia import quick
        self.assertEqual(quick.match("what time is my last meeting today")[0], "last_meeting")
        self.assertEqual(quick.match("what time is my first meeting tomorrow")[0], "first_meeting")

    def test_a_summary_of_the_day_and_what_she_did(self):
        from aletheia import quick
        self.assertEqual(quick.match("give me a summary of my day")[0], "plan_today")
        self.assertEqual(quick.match("show me what you did")[0], "today")

    def test_notes_that_are_not_about_him_are_not_nothing(self):
        from aletheia import memory, profile, quick
        with mock.patch.object(quick, "_notes", return_value=[{"text": "the spare key is under the mat"}]), \
                mock.patch.object(profile, "known", return_value={}), \
                mock.patch.object(memory, "everything", return_value={}):
            self.assertIn("keeping 1 note", quick.answer("what do you remember about me"))

    def test_a_refusal_is_not_a_thing_she_did(self):
        from aletheia import recollection
        entry = {"kind": "action", "subject": "core:undo", "actor": "operator-local-core",
                 "text": "done — Nothing to undo: I haven't done anything on my own in the last two days."}
        self.assertFalse(recollection._something_she_did(entry))
        self.assertTrue(recollection._something_she_did(dict(entry, text="done — Took it off your list: milk.")))


class HisBodyAndHisMedicine(unittest.TestCase):
    def notes(self, *said, days_apart=0):
        import datetime as dt
        now = dt.datetime.now(dt.timezone.utc)
        return [{"text": t, "ts": (now - dt.timedelta(days=i * days_apart)).isoformat()} for i, t in enumerate(said)]

    def test_said_is_kept(self):
        for said in ("I'm 6 feet tall", "I want to lose 10 pounds", "I slept badly", "I took ibuprofen at 2",
                     "my emergency contact is my mom", "my prescription is lisinopril 10mg"):
            self.assertEqual(voice._interpret(said)["command"], {"kind": "note", "text": said}, said)
        self.assertEqual(voice._interpret("I need to refill my prescription")["command"]["kind"], "task_new")

    def test_height_bmi_and_weight_lost_are_arithmetic_on_his_notes(self):
        from aletheia import quick
        with mock.patch.object(quick, "_notes", return_value=self.notes("I weigh 180", "I'm 6 feet tall", "I weigh 190",
                                                                        days_apart=7)):
            self.assertEqual(quick.answer("how tall am I"), "You told me: you're 6 feet tall.")
            self.assertEqual(quick.answer("what's my BMI"), "About 24.4, from the height and weight you told me.")
            self.assertTrue(quick.answer("how much weight have I lost").startswith("Down about 10 pounds since"))
        with mock.patch.object(quick, "_notes", return_value=[]):
            self.assertIn("your height and your weight", quick.answer("what's my BMI"))

    def test_a_medicine_by_name_is_dated_by_the_time_he_said(self):
        from aletheia import quick
        with mock.patch.object(quick, "_notes", return_value=self.notes("I took ibuprofen at 2")):
            self.assertEqual(quick.answer("when did I last take ibuprofen"), "You told me you took ibuprofen at 2 today.")
            self.assertEqual(quick.answer("did I take ibuprofen today"), "Yes - you told me you took ibuprofen at 2 today.")
        with mock.patch.object(quick, "_notes", return_value=self.notes("my prescription is lisinopril 10mg")):
            self.assertEqual(quick.answer("what medications do I take"), "You told me: your prescription is lisinopril 10mg.")
            self.assertEqual(quick.answer("what's my prescription"), "You told me: your prescription is lisinopril 10mg.")
        with mock.patch.object(quick, "_notes", return_value=self.notes("my emergency contact is my mom")):
            self.assertEqual(quick.answer("who's my emergency contact"), "Your emergency contact is your mom.")


class HisFamilyAndHisHouse(unittest.TestCase):
    def test_said_is_kept(self):
        for said in ("Leo's teacher is Mrs. Brown", "Leo's school is Lincoln Elementary", "my daughter is allergic to nuts",
                     "Leo was born on May 3 2018", "the trash goes out on Tuesdays", "recycling is every other Wednesday",
                     "the kids have soccer on Saturdays at 9", "the babysitter is coming at 6", "my car's mileage is 45000"):
            self.assertEqual(voice._interpret(said)["command"], {"kind": "note", "text": said}, said)
        for not_a_fact in ("the trash is full", "it is coming at 6"):
            got = voice._interpret(not_a_fact)
            self.assertFalse(got and (got.get("command") or {}).get("kind") == "note", not_a_fact)

    def test_read_back_by_what_he_asks(self):
        import datetime as dt
        from aletheia import quick
        now = dt.datetime.now(dt.timezone.utc).isoformat()
        notes = [{"text": t, "ts": now} for t in (
            "the trash goes out on Tuesdays", "the babysitter is coming at 6", "the kids have soccer on Saturdays at 9",
            "Leo's teacher is Mrs. Brown", "Leo's school is Lincoln Elementary", "my daughter is allergic to nuts",
            "Leo was born on May 3 2018", "my son's name is Leo", "my car's mileage is 45000")]
        with mock.patch.object(quick, "_notes", return_value=notes):
            self.assertEqual(quick.answer("when does the trash go out"), "You told me: the trash goes out on Tuesdays.")
            self.assertEqual(quick.answer("when is the babysitter coming"), "You told me: the babysitter is coming at 6.")
            self.assertEqual(quick.answer("when is soccer"), "You told me: the kids have soccer on Saturdays at 9.")
            self.assertEqual(quick.answer("who is my son's teacher"), "You told me: Leo's teacher is Mrs. Brown.")
            self.assertEqual(quick.answer("what school does Leo go to"), "You told me: Leo's school is Lincoln Elementary.")
            self.assertEqual(quick.answer("what is my daughter allergic to"), "You told me: your daughter is allergic to nuts.")
            self.assertTrue(quick.answer("how old is my son").startswith("Leo is "))
            self.assertEqual(voice._interpret("what's my car's mileage")["say"], "You told me: your car's mileage is 45000.")
        with mock.patch.object(quick, "_notes", return_value=[]):
            self.assertIsNone(quick.answer("when is soccer"))

    def test_a_car_job_is_a_task_and_a_pickup_time_is_a_reminder(self):
        with mock.patch("aletheia.tasks.all_tasks", return_value=[]):
            self.assertEqual(voice._interpret("my car needs an oil change")["command"]["description"], "get the car an oil change")
            self.assertEqual(voice._interpret("my car needs new tires")["command"]["description"], "get the car new tires")
        got = voice._interpret("pick up Leo at 3")["command"]
        self.assertEqual((got["kind"], got["text"]), ("remind_at", "pick up Leo"))
        from aletheia import quick
        self.assertEqual(quick.match("what time do I pick up Leo"), ("when_do_i", "pick up leo"))


class PluralsAndPercentOff(unittest.TestCase):
    def test_plurals_by_rule_or_by_list_and_never_guessed(self):
        from aletheia import quick
        for asked, said in (("what's the plural of mouse", "Mice."), ("plural of box", "Boxes."),
                            ("what's the plural of city", "Cities."), ("what's the plural of cat", "Cats."),
                            ("what's the plural of stomach", "Stomachs."),
                            ("what's the plural of moose", "Moose - it's the same in the plural.")):
            self.assertEqual(quick.answer(asked), said, asked)
        self.assertIsNone(quick.answer("what's the plural of hoof"))

    def test_percent_off_asked_as_how_much(self):
        from aletheia import quick
        self.assertEqual(quick.answer("how much is 20 percent off 80"), "$64 - you save $16.")


class ADraftPutAway(unittest.TestCase):
    def test_a_held_draft_is_put_away_unsent_and_gone_from_the_list(self):
        import tempfile
        from pathlib import Path
        from aletheia import intercom, mail, policy, speech
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(mail, "MAIL_DIR", Path(tmp)), \
                mock.patch.object(mail, "resolve_address", return_value=("dana@example.com", "Dana")), \
                mock.patch.object(policy, "all_approvals", return_value=[]):
            mail.draft("Dana", "Friday off", "Can I take Friday off?", held=True)
            mail.draft("Dana", "Lunch", "Lunch on Monday?", held=True)
            self.assertEqual(voice._interpret("cancel the draft")["command"], {"kind": "draft_discard"})
            self.assertEqual(voice._interpret("delete the draft about lunch")["command"],
                             {"kind": "draft_discard", "which": "lunch"})
            said = intercom.execute_command({"kind": "draft_discard", "which": "lunch"}, {}, quote="delete the draft about lunch")
            self.assertEqual(speech.spoken_receipt("draft_discard", said), "Put it away unsent: Lunch to Dana.")
            self.assertEqual([d["subject"] for d in mail.held_drafts()], ["Friday off"])
            self.assertTrue(any(p.name.endswith(".refused.json") for p in Path(tmp).iterdir()))
            self.assertIn("1 draft held", intercom.execute_command({"kind": "drafts"}, {}))
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(mail, "MAIL_DIR", Path(tmp)), \
                mock.patch.object(policy, "all_approvals", return_value=[]):
            self.assertEqual(voice._interpret("delete the draft")["say"], "There's no draft waiting.")

    def test_a_draft_waiting_on_its_approval_is_denied(self):
        from aletheia import policy
        pending = [{"id": "mail-1", "state": "PENDING", "capability": "email.send"}]
        with mock.patch.object(policy, "all_approvals", return_value=pending), \
                mock.patch("aletheia.mail.held_drafts", return_value=[]):
            self.assertEqual(voice._interpret("don't send it")["command"],
                             {"kind": "deny", "id": "mail-1", "because": "draft discarded by voice"})


class FocusAndNamedTimers(unittest.TestCase):
    def test_a_focus_session_is_a_timer(self):
        got = voice._interpret("start a focus session")["command"]
        self.assertEqual((got["kind"], got["text"]), ("remind_at", "your 25 minute focus timer is up"))
        got = voice._interpret("start a focus session for 50 minutes")["command"]
        self.assertEqual(got["text"], "your 50 minute focus timer is up")
        self.assertEqual(voice._interpret("end the focus session")["command"],
                         {"kind": "reminder_off", "which": "focus timer is up"})
        with mock.patch("aletheia.intercom._reminder_schedules", return_value=[]):
            self.assertEqual(voice._interpret("how long have I been focusing")["say"], "No focus session is running.")

    def test_a_named_timer_is_cancelled_by_name(self):
        self.assertEqual(voice._interpret("cancel the pasta timer")["command"],
                         {"kind": "reminder_off", "which": "pasta timer is up"})
        self.assertEqual(voice._interpret("stop the timer")["command"],
                         {"kind": "reminder_off", "which": "timer is up"})


class IdeasGoalsThanksAndAJournal(unittest.TestCase):
    def test_said_is_kept_with_its_word_on_the_front(self):
        cases = {
            "I have an idea for a dog treat subscription": "Idea: a dog treat subscription",
            "save this idea: a podcast about woodworking": "Idea: a podcast about woodworking",
            "I want to learn Spanish": "I want to learn Spanish",
            "I'd like to learn how to play guitar": "I want to learn how to play guitar",
            "my goal this year is to run a marathon": "my goal this year is to run a marathon",
            "I'm grateful for my family": "Grateful for my family",
            "journal entry: today was rough but I got through it": "Journal: today was rough but I got through it",
            "today was a good day": "Journal: today was a good day",
            "I'm proud of finishing the deck": "Journal: I'm proud of finishing the deck",
        }
        for said, kept in cases.items():
            self.assertEqual(voice._interpret(said)["command"], {"kind": "note", "text": kept}, said)
        for to_her in ("I'm grateful for your help", "I'm proud of you", "I want to learn more about you"):
            got = voice._interpret(to_her)
            self.assertFalse(got and (got.get("command") or {}).get("kind") == "note", to_her)

    def test_read_back_by_what_he_asks(self):
        import datetime as dt
        from aletheia import quick
        now = dt.datetime.now(dt.timezone.utc)
        old = (now - dt.timedelta(days=9)).isoformat()
        notes = [{"text": t, "ts": now.isoformat()} for t in (
            "Idea: a podcast about woodworking", "Idea: a dog treat subscription", "I want to learn Spanish",
            "my goal this year is to run a marathon", "Grateful for my family", "Journal: today was a good day")]
        notes.append({"text": "Journal: a long week", "ts": old})
        with mock.patch.object(quick, "_notes", return_value=notes):
            self.assertEqual(quick.answer("what ideas have I had"),
                             "Your ideas, newest first: a podcast about woodworking; a dog treat subscription.")
            self.assertEqual(quick.answer("what do I want to learn"), "You want to learn Spanish.")
            self.assertEqual(quick.answer("what are my goals"), "Your goals: to run a marathon.")
            self.assertEqual(quick.answer("what am I grateful for"), "You're grateful for your family.")
            self.assertEqual(quick.answer("what did I write in my journal today"), "Your journal from today: today was a good day.")
            self.assertIn("a long week", quick.answer("read me my journal"))
        with mock.patch.object(quick, "_notes", return_value=[]):
            self.assertIn("No ideas kept yet", quick.answer("read me my ideas"))
            self.assertEqual(quick.answer("what did I write in my journal yesterday"), "Nothing in your journal from yesterday.")

    def test_procrastinating_gets_a_way_in(self):
        from aletheia import quick
        self.assertIn("focus session", quick.answer("I'm procrastinating"))


class GiftsWatchedWeighedAndTheWeek(unittest.TestCase):
    def test_a_gift_idea_is_a_line_on_his_gift_list(self):
        from aletheia import quick
        self.assertEqual(voice._interpret("add a gift idea for my sister: a scarf")["command"],
                         {"kind": "list_add", "list": "gift", "item": "a scarf for my sister"})
        self.assertEqual(voice._interpret("a cookbook would be a great gift for dad")["command"]["item"], "a cookbook for dad")
        with mock.patch("aletheia.lists.items", return_value=["a scarf for my sister", "a cookbook for dad"]):
            self.assertEqual(quick.answer("what gift ideas do I have for my sister"), "Your gift ideas for your sister: a scarf.")
            self.assertEqual(quick.answer("what should I get dad for his birthday"), "Your gift ideas for dad: a cookbook.")
            # nothing kept for her is a question a model can think about
            self.assertIsNone(quick.answer("what should I get my mom"))
            self.assertIn("haven't saved any gift ideas", quick.answer("what gift ideas do I have for my mom"))

    def test_watched_and_reading_are_read_back(self):
        import datetime as dt
        from aletheia import quick
        self.assertEqual(voice._interpret("I watched Oppenheimer")["command"], {"kind": "note", "text": "I watched Oppenheimer"})
        got = voice._interpret("I watched the kids")
        self.assertFalse(got and (got.get("command") or {}).get("kind") == "note")
        now = dt.datetime.now(dt.timezone.utc).isoformat()
        with mock.patch.object(quick, "_notes", return_value=[{"text": "I watched Oppenheimer last night", "ts": now}]), \
             mock.patch("aletheia.lists.all_lists", return_value=[]):
            self.assertEqual(quick.answer("what movies have I watched"), "You've watched Oppenheimer.")
        with mock.patch.object(quick, "_notes", return_value=[]):
            self.assertIn("haven't told me what you're reading", quick.answer("what am I reading"))

    def test_what_he_weighed_then(self):
        import datetime as dt
        from aletheia import quick
        now = dt.datetime.now(dt.timezone.utc)
        notes = [{"text": "I weigh 180", "ts": now.isoformat()},
                 {"text": "I weigh 185", "ts": (now - dt.timedelta(days=8)).isoformat()}]
        with mock.patch.object(quick, "_notes", return_value=notes):
            self.assertTrue(quick.answer("what did I weigh last week").startswith("185 pounds, "))
            self.assertTrue(quick.answer("how much weight have I lost").startswith("Down about 5 pounds"))
        with mock.patch.object(quick, "_notes", return_value=[]):
            self.assertIn("haven't told me your weight", quick.answer("what did I weigh last week"))

    def test_the_week_and_coming_back(self):
        from aletheia import quick
        self.assertEqual(quick.match("what's going on this week"), ("agenda", "this week"))
        self.assertEqual(quick.match("what does my week look like")[0], "agenda")
        self.assertEqual(quick.match("I'm back from the gym")[0], "arrival")
        self.assertEqual(quick.match("what were my notes from yesterday"), ("notes_day", "yesterday"))


class ServicesMealPlansAndPicks(unittest.TestCase):
    def test_a_service_he_had_or_needs(self):
        import datetime as dt
        from aletheia import quick
        with mock.patch("aletheia.tasks.all_tasks", return_value=[]), \
             mock.patch("aletheia.intercom._open_tasks", return_value=[]):
            self.assertEqual(voice._interpret("I got a haircut")["command"], {"kind": "note", "text": "I got a haircut"})
            got = voice._interpret("I'm due for an oil change")["command"]
            self.assertEqual((got["kind"], got["description"]), ("task_new", "get an oil change"))
        # with the task on his list, having it done ticks it off
        rows = [{"id": "get-a-haircut", "description": "get a haircut", "status": "PENDING"}]
        with mock.patch("aletheia.intercom._open_tasks", return_value=rows):
            self.assertEqual(voice._interpret("I got a haircut")["command"], {"kind": "task_done", "which": "get haircut"})
        now = dt.datetime.now(dt.timezone.utc).isoformat()
        with mock.patch.object(quick, "_notes", return_value=[{"text": "I got a haircut", "ts": now}]):
            self.assertTrue(quick.answer("when did I last get a haircut").startswith("You told me you got a haircut"))
        done = [{"id": "get-a-haircut", "description": "get a haircut", "status": "COMPLETED", "updated_at": now}]
        with mock.patch.object(quick, "_notes", return_value=[]), mock.patch("aletheia.tasks.all_tasks", return_value=done):
            self.assertTrue(quick.answer("when did I last get a haircut").startswith("You got a haircut "))
            self.assertTrue(quick.answer("did I get a haircut today").startswith("Yes - you got a haircut"))
        # a service only: an email is the mail's
        self.assertIsNone(quick.match("when did I get that email"))

    def test_a_meal_plan_by_the_day(self):
        from aletheia import quick
        self.assertEqual(voice._interpret("add chicken to my meal plan for monday")["command"],
                         {"kind": "list_add", "list": "meal plan", "item": "Monday: chicken"})
        self.assertEqual(voice._interpret("tuesday dinner is pasta")["command"]["item"], "Tuesday: pasta")
        with mock.patch("aletheia.lists.items", return_value=["Monday: chicken", "Tuesday: pasta"]):
            self.assertEqual(quick.answer("what am I having for dinner monday"), "Chicken on Monday.")
            self.assertEqual(quick.answer("what's for dinner friday"), "Nothing on your meal plan on Friday.")
            self.assertEqual(quick.answer("what's on the meal plan"), "Your meal plan: Monday: chicken; Tuesday: pasta.")
        with mock.patch("aletheia.lists.items", return_value=None):
            self.assertIsNone(quick.answer("what am I having for dinner tomorrow"))

    def test_picked_off_his_own_lists(self):
        from aletheia import quick
        with mock.patch("aletheia.lists.all_lists", return_value=[{"name": "watch"}]), \
             mock.patch("aletheia.lists.kind_of", return_value="watch"), \
             mock.patch("aletheia.lists.items", return_value=["Arrival"]):
            self.assertEqual(quick.answer("recommend a movie"), "From your watch list: Arrival.")
        with mock.patch("aletheia.lists.all_lists", return_value=[]):
            self.assertIsNone(quick.answer("what should I watch tonight"))
        with mock.patch.object(quick, "_notes", return_value=[{"text": "my favorite restaurant is Olive Garden"}]):
            self.assertEqual(quick.answer("where should we eat tonight"), "How about Olive Garden? You told me it's your favorite.")
        with mock.patch.object(quick, "_notes", return_value=[]):
            self.assertIsNone(quick.answer("where should we eat tonight"))


class HisWorkDayAndTalkingToHer(unittest.TestCase):
    def test_a_work_day_is_logged_and_added_up(self):
        import datetime as dt
        from aletheia import quick
        self.assertEqual(voice._interpret("I'm starting work")["command"], {"kind": "note", "text": "started work"})
        self.assertEqual(voice._interpret("I'm done with work for the day")["command"], {"kind": "note", "text": "finished work"})
        self.assertEqual(voice._interpret("clocking out")["command"], {"kind": "note", "text": "finished work"})
        now = dt.datetime.now(dt.timezone.utc)
        notes = [{"text": "finished work", "ts": (now - dt.timedelta(minutes=5)).isoformat()},
                 {"text": "started work", "ts": (now - dt.timedelta(hours=3, minutes=35)).isoformat()}]
        with mock.patch.object(quick, "_notes", return_value=notes):
            self.assertEqual(quick.answer("how long did I work today"), "3 hours and 30 minutes today.")
        with mock.patch.object(quick, "_notes", return_value=notes[1:]):
            self.assertIn("still at it", quick.answer("how many hours have I worked today"))
        with mock.patch.object(quick, "_notes", return_value=[]):
            self.assertIsNone(quick.answer("how long did I work today"))

    def test_a_task_added_to_the_list_for_a_day(self):
        with mock.patch("aletheia.tasks.all_tasks", return_value=[]):
            got = voice._interpret("add call the bank to my list for tomorrow")["command"]
        self.assertEqual((got["kind"], got["description"]), ("task_new", "call the bank"))
        self.assertRegex(got["deadline"], r"^\d{4}-\d{2}-\d{2}$")

    def test_another_one_is_the_same_ask_again(self):
        with mock.patch.object(voice, "_previous_turn", return_value=("tell me a joke", "first joke")):
            said = voice._interpret("another one")["say"]
        self.assertTrue(said and said != "first joke")
        with mock.patch.object(voice, "_previous_turn", return_value=("flip a coin", "Heads.")):
            self.assertIn(voice._interpret("again")["say"], ("Heads.", "Tails."))
        for said in ("sing me a song", "do you dream", "are you busy", "nothing"):
            self.assertIsNone(voice._interpret(said)["command"], said)

    def test_where_was_i_is_the_thread(self):
        from aletheia import quick
        self.assertEqual(quick.match("where was I")[0], "asked_last")


class TaxSavingYearsAndHeights(unittest.TestCase):
    def test_sums_said_as_sums(self):
        import datetime as dt
        from aletheia import quick
        self.assertEqual(quick.answer("what's 8 percent sales tax on 45"), "$3.60 tax, $48.60 total.")
        self.assertEqual(quick.answer("if I save 200 a month how much will I have in a year"), "$2,400, before any interest.")
        self.assertEqual(quick.answer("what year was it 25 years ago"), f"{dt.date.today().year - 25}.")
        self.assertEqual(quick.answer("what year will it be in 10 years"), f"{dt.date.today().year + 10}.")
        self.assertEqual(quick.answer("how tall is 180 cm in feet"), "About 5 feet 11 inches.")
        self.assertEqual(quick.answer("how heavy is 10 kg in pounds"), "About 22.05 pounds.")


class HisPeopleTalkedToAndSeen(unittest.TestCase):
    def test_a_greeting_starts_the_text_on_the_bottom_rung(self):
        # the voice layer still leaves a stranger's name to a model; with
        # none, the rules split at the greeting rather than ask for "sarah happy"
        from aletheia import rule_planner
        with mock.patch("aletheia.messages.resolve_number", return_value=(None, "sarah")):
            said = rule_planner.match("text sarah happy birthday")[1]["say"]
        self.assertIn("phone number for sarah.", said.casefold())

    def test_talking_to_somebody_is_kept_and_any_way_answers(self):
        import datetime as dt
        from aletheia import quick
        for said in ("I talked to mom", "I saw Sam today", "I texted Dana"):
            self.assertEqual(voice._interpret(said)["command"], {"kind": "note", "text": said}, said)
        now = dt.datetime.now(dt.timezone.utc).isoformat()
        with mock.patch.object(quick, "_notes", return_value=[{"text": "I called mom", "ts": now},
                                                              {"text": "I saw Sam today", "ts": now}]):
            self.assertTrue(quick.answer("when did I last talk to mom").startswith("You told me you called mom"))
            self.assertTrue(quick.answer("when did I last see Sam").startswith("You told me you saw Sam"))
            self.assertTrue(quick.answer("did I talk to mom today").startswith("Yes - "))
            self.assertIsNone(quick.answer("did I see the email from Sam"))

    def test_how_he_knows_somebody_and_what_is_with_them(self):
        from aletheia import quick
        with mock.patch.object(quick, "_notes", return_value=[{"text": "Sam is my coworker"}]):
            self.assertEqual(quick.answer("how do I know Sam"), "You told me: Sam is your coworker.")
        self.assertIsNone(quick.match("how do I know if it rains"))
        self.assertEqual(quick.match("what do I have with Sam"), ("when_meeting", "sam"))
        self.assertEqual(quick.match("what's my dentist appointment"), ("when_mine_what", "dentist appointment"))

    def test_call_me_back_is_a_nudge(self):
        got = voice._interpret("call me back in 10 minutes")["command"]
        self.assertEqual((got["kind"], got["text"]), ("remind_at", "pick up where we left off"))


class DoorsAndLockingUp(unittest.TestCase):
    def test_a_door_is_an_honest_no_and_counted(self):
        from aletheia import capabilities, cannot
        entry = capabilities.get("home.lock")
        self.assertEqual((entry["status"], entry["approval_policy"]), ("NOT_BUILT", "operator_always"))
        with mock.patch.object(cannot, "_count_it"):
            for said in ("lock the front door", "is the garage door closed", "open the garage", "is the back door locked"):
                self.assertIn("can't lock doors", cannot.answer(said) or "", said)
            self.assertIsNone(cannot.answer("lock in my answer"))
            # whether HE locked it is his notes' to answer, not a no
            self.assertIsNone(cannot.answer("did I lock the door"))

    def test_locking_up_is_kept_and_read_back(self):
        import datetime as dt
        from aletheia import quick
        self.assertEqual(voice._interpret("I locked the front door")["command"],
                         {"kind": "note", "text": "I locked the front door"})
        now = dt.datetime.now(dt.timezone.utc).isoformat()
        with mock.patch.object(quick, "_notes", return_value=[{"text": "I locked the front door", "ts": now}]):
            self.assertTrue(quick.answer("did I lock the door").startswith("You told me you locked the front door"))
        with mock.patch.object(quick, "_notes", return_value=[]):
            self.assertTrue(quick.answer("did I turn off the stove").startswith("Not that you've told me"))


class HisPlansAndHowHeFeels(unittest.TestCase):
    def test_an_interview_he_pencilled_in_is_his_interview(self):
        import datetime as dt
        from aletheia import quick
        at = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=1)).isoformat()
        with mock.patch("aletheia.calendar.all_events", return_value=[{"title": "job interview", "start": at}]):
            self.assertTrue(quick._interview_when().startswith("Your job interview is tomorrow"))
        with mock.patch("aletheia.calendar.all_events", return_value=[{"title": "Stripe interview", "start": at}]):
            self.assertTrue(quick._interview_when().startswith("Your interview with Stripe is"))

    def test_a_plan_with_a_when_is_kept_and_read_with_the_day_he_said_it(self):
        import datetime as dt
        from aletheia import quick
        for said in ("I'm moving next month", "I start my new job on Monday", "my vacation is next week"):
            self.assertEqual(voice._interpret(said)["command"], {"kind": "note", "text": said}, said)
        got = voice._interpret("I'm going to call mom tomorrow")
        self.assertFalse(got and (got.get("command") or {}).get("kind") == "note")
        now = dt.datetime.now(dt.timezone.utc)
        notes = [{"text": "I'm moving next month", "ts": (now - dt.timedelta(days=3)).isoformat()},
                 {"text": "I start my new job on Monday", "ts": now.isoformat()}]
        with mock.patch.object(quick, "_notes", return_value=notes):
            self.assertTrue(quick.answer("when am I moving").startswith("You told me on "))
            self.assertEqual(quick.answer("when do I start my new job"), "You told me today: you start your new job on Monday.")
            self.assertIsNone(quick.answer("when is my surgery"))

    def test_how_he_feels_gets_a_line(self):
        from aletheia import quick
        for said in ("I'm thirsty", "I'm cold", "I can't focus", "I'm running late", "I'm stuck in traffic",
                     "I didn't get the job", "I quit my job"):
            self.assertTrue(quick.answer(said), said)
        with mock.patch.object(quick, "_interview_when", return_value="No interview on your calendar."):
            self.assertEqual(quick.answer("I'm nervous about my interview"), "That's normal before your interview - it means you care.")
        self.assertNotIn("before your money", quick.answer("I'm worried about money"))

    def test_lost_and_found(self):
        self.assertIn("no eyes in the room", voice._interpret("I lost my keys")["say"])
        self.assertEqual(voice._interpret("I found my wallet")["say"], "Good. Tell me where you put it next time and I'll remember.")


class PartsOfDaysAndMeetingDetails(unittest.TestCase):
    def setUp(self):
        import datetime as dt
        from aletheia import localtime
        tz = localtime.operator_tz()
        start = (dt.datetime.now(tz) + dt.timedelta(days=1)).replace(hour=15, minute=0, second=0, microsecond=0)
        morning = start.replace(hour=9, minute=30)
        self.events = [{"title": "meeting with Sam", "start": start.isoformat(),
                        "end": (start + dt.timedelta(minutes=45)).isoformat()},
                       {"title": "standup", "start": morning.isoformat(), "end": (morning + dt.timedelta(minutes=15)).isoformat()}]

    def test_a_part_of_a_day(self):
        from aletheia import quick
        with mock.patch("aletheia.calendar.all_events", return_value=self.events):
            self.assertEqual(quick.answer("what's on my calendar tomorrow morning"), "Tomorrow morning: standup at 9:30 am.")
            self.assertEqual(quick.answer("what do I have tomorrow afternoon"), "Tomorrow afternoon: meeting with Sam at 3 pm.")

    def test_a_meeting_how_long_who_and_the_busiest_day(self):
        from aletheia import quick
        with mock.patch("aletheia.calendar.all_events", return_value=self.events):
            self.assertTrue(quick.answer("how long is my meeting with Sam").startswith("45 minutes: meeting with Sam"))
            self.assertTrue(quick.answer("who is my meeting with at 3").startswith("Meeting with Sam, tomorrow"))
            # tomorrow is next week's Monday when today is Sunday: both sides move
            import datetime as dt
            week = "next week" if (dt.date.today() + dt.timedelta(days=1)).weekday() == 0 else "this week"
            self.assertTrue(quick.answer(f"what's my busiest day {week}").endswith("with 2 things on it."))
        self.assertIsNone(quick.match("how long is my commute"))

    def test_free_tonight_is_english(self):
        import datetime as dt
        from aletheia import intercom
        self.assertEqual(intercom._free_sentence([], dt.date.today(), "tonight"), "Nothing free tonight.")


class AgesFromAYearAndTheEmailAskedFor(unittest.TestCase):
    def test_a_birth_year_makes_an_age(self):
        from aletheia import quick
        self.assertEqual(voice._interpret("my mom was born in 1965")["command"],
                         {"kind": "note", "text": "my mom was born in 1965"})
        with mock.patch.object(quick, "_notes", return_value=[{"text": "my mom was born in 1965"},
                                                              {"text": "my mom's birthday is May 5"}]):
            self.assertRegex(quick.answer("how old is my mom"), r"^Your mom is \d+, and turns \d+ on May 5\.$|it's today")
        with mock.patch.object(quick, "_notes", return_value=[{"text": "my mom was born in 1965"}]):
            self.assertIn("depending on whether the birthday has come", quick.answer("how old is my mom"))

    def test_the_email_he_asked_for(self):
        from aletheia import intercom
        self.assertEqual(voice._interpret("what's my sister's email")["command"],
                         {"kind": "contacts", "which": "my sister", "asked": "email"})
        rows = [{"id": "dana", "display_name": "Dana", "phones": ["5553334444"], "emails": []}]
        with mock.patch("aletheia.contacts.all_contacts", return_value=rows):
            said = intercom._contacts_answer("dana", "email")
        self.assertTrue(said.startswith("I don't have an email for Dana - only the number"))


class HisAgeAheadAndHisNickname(unittest.TestCase):
    def test_from_the_birthday_on_file(self):
        from aletheia import quick
        with mock.patch.object(quick, "_birthday_on_file", return_value=(8, 4, 1995)):
            self.assertRegex(quick.answer("how old will I be next year"), r"^\d+")
            self.assertRegex(quick.answer("how many days old am I"), r"^[\d,]+ days\.$")
            self.assertTrue(quick.answer("what's my zodiac sign").startswith("Leo"))
        with mock.patch.object(quick, "_birthday_on_file", return_value=(8, 4, None)):
            self.assertIn("not the year", quick.answer("how many days old am I"))

    def test_nickname_is_what_she_calls_him(self):
        from aletheia import quick
        self.assertEqual(quick.match("what's my nickname")[0], "call_me")


class AQuestionAboutBuyingIsNotSpending(unittest.TestCase):
    """2026-10-07: "did i buy milk" was refused as an instruction to spend."""

    def test_the_local_door_lets_a_question_through(self):
        from aletheia import local_planner
        self.assertIsNone(local_planner._refusal_for_spending("did i buy milk"))
        self.assertIsNone(local_planner._refusal_for_spending("have i paid rent yet"))
        self.assertTrue(local_planner._refusal_for_spending("order me a pizza"))
        self.assertTrue(local_planner._refusal_for_spending("buy milk for me"))

    def test_the_shopping_list_answers_it(self):
        from aletheia import shopping, voice
        rows = [{"need": "milk", "state": "RESEARCHING"},
                {"need": "eggs", "state": "CANCELLED", "updated_at": "2026-10-07T15:00:00Z"}]
        with mock.patch.object(shopping, "all_workflows", return_value=rows):
            self.assertIn("Not yet", voice._interpret("did i buy milk")["say"])
            self.assertIn("Yes - eggs came off", voice._interpret("did i get the eggs")["say"])
            self.assertIsNone(voice._interpret("did i get the job")["say"])


class HisBudgetAndPayAreKept(unittest.TestCase):
    """2026-10-07: "am I over budget" and "how much do I make a year" went to
    the planner, with the budget, the spending and the pay all in his notes."""

    def _notes(self, *texts):
        import datetime as dt
        now = dt.datetime.now(dt.timezone.utc).isoformat()
        from aletheia import quick
        return mock.patch.object(quick, "_notes", return_value=[{"text": t, "ts": now} for t in texts])

    def test_a_budget_is_set_against_what_he_spent(self):
        from aletheia import voice
        with self._notes("my grocery budget is 400 a month", "I spent 150 dollars on groceries",
                         "I spent 300 on rent"):
            said = voice._interpret("how much is left in my grocery budget")["say"]
            self.assertIn("$250 left", said)
            self.assertIn("No - you've spent $150", voice._interpret("am i over my grocery budget")["say"])
            self.assertIn("haven't told me a gas budget", voice._interpret("am i over my gas budget")["say"])
        with self._notes():
            self.assertIsNone(voice._interpret("am i over budget")["say"])

    def test_pay_is_kept_in_his_words(self):
        from aletheia import voice
        for said in ("my paycheck is 2000 every two weeks", "I get paid every other Friday",
                     "I make 25 an hour", "I got paid today", "payday is Friday"):
            self.assertEqual(voice._interpret(said)["command"]["kind"], "note", said)
        self.assertNotEqual((voice._interpret("my pay is terrible")["command"] or {}).get("kind"), "note")

    def test_pay_is_read_back_and_worked_out(self):
        from aletheia import voice
        with self._notes("my paycheck is 2000 every two weeks", "I get paid every other Friday"):
            self.assertIn("$52,000 a year", voice._interpret("how much do i make a year")["say"])
            self.assertIn("every other Friday", voice._interpret("when is payday")["say"])
        with self._notes("I make 25 an hour"):
            self.assertIn("40-hour week", voice._interpret("how much do i make a month")["say"])
        with self._notes():
            self.assertIsNone(voice._interpret("how much do i make a year")["say"])


if __name__ == "__main__":
    unittest.main()
