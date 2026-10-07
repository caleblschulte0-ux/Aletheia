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
                             "10 minutes left on your 10 minute pasta timer.")
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


if __name__ == "__main__":
    unittest.main()
