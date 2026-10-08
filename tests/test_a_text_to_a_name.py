"""Sweep 25 (2026-10-07): sentences that went to the planner and need no model."""
import unittest
from unittest import mock

from aletheia import voice


class ATextToAName(unittest.TestCase):
    def test_a_name_then_a_sentence_is_a_text(self):
        self.assertEqual(voice._interpret("text dana i'm running late")["command"],
                         {"kind": "message_send", "to": "dana", "body": "i'm running late"})
        self.assertEqual(voice._interpret("message sam can you grab milk")["command"]["body"], "can you grab milk")

    def test_a_stranger_and_two_words_is_still_not_guessed(self):
        self.assertNotEqual((voice._interpret("text bob happy birthday").get("command") or {}).get("kind"),
                            "message_send")


class InMyCalendar(unittest.TestCase):
    def test_in_is_on(self):
        from aletheia import quick
        self.assertEqual(quick.match("what's in my calendar next week"), ("agenda", "next week"))


class DoneSaidEveryWay(unittest.TestCase):
    def test_done_with_it_ticks_the_one_task_it_names(self):
        with mock.patch.object(voice, "_names_one_open_task", return_value=True):
            for said, which in (("done with laundry", "laundry"), ("finish the dentist task", "dentist"),
                                ("the laundry task is done", "laundry"), ("i called the dentist", "called the dentist")):
                self.assertEqual(voice._interpret(said)["command"], {"kind": "task_done", "which": which}, said)

    def test_news_about_a_task_he_does_not_have_is_not_a_tick(self):
        with mock.patch.object(voice, "_names_one_open_task", return_value=False):
            got = voice._interpret("i called the plumber").get("command") or {}
            self.assertNotEqual(got.get("kind"), "task_done")

    def test_a_machine_finishing_is_not_his_task_done(self):
        with mock.patch.object(voice, "_names_one_open_task", return_value=True):
            got = voice._interpret("the dishwasher is done").get("command") or {}
            self.assertNotEqual(got.get("kind"), "task_done")


class AReminderMoved(unittest.TestCase):
    def _one(self, hour, words):
        import datetime as dt
        from aletheia import localtime
        tz = localtime.operator_tz()
        day = dt.datetime.now(tz).date() + dt.timedelta(days=1)
        return (dt.datetime.combine(day, dt.time(hour), tzinfo=tz), words)

    def test_by_its_time_on_its_own_day(self):
        was = self._one(15, "call the dentist")
        with mock.patch.object(voice, "_running_once", return_value=[was]):
            got = voice._interpret("change my 3pm reminder to 4pm")["command"]
        self.assertEqual((got["text"], got["replaces"]), ("call the dentist", "call the dentist"))
        self.assertEqual(got["at"], was[0].replace(hour=16).isoformat())

    def test_by_its_words_and_a_bare_hour_keeps_the_afternoon(self):
        was = self._one(15, "take my pills")
        with mock.patch.object(voice, "_running_once", return_value=[was]):
            got = voice._interpret("move my pill reminder to 5")["command"]
        self.assertEqual(got["at"], was[0].replace(hour=17).isoformat())

    def test_two_that_match_are_asked_about(self):
        with mock.patch.object(voice, "_running_once", return_value=[self._one(15, "call mom"), self._one(15, "call dad")]):
            got = voice._interpret("change my 3pm reminder to 4pm")
        self.assertIsNone(got["command"])
        self.assertIn("call mom or call dad", got["say"])

    def test_a_place_is_not_a_time(self):
        got = voice._interpret("remind me when i get home to feed the cat")
        self.assertIsNone(got["command"])
        self.assertIn('remind me at 6 to feed the cat', got["say"])


class ListsAndBills(unittest.TestCase):
    def test_a_bill_split_between_people(self):
        from aletheia import quick
        self.assertEqual(quick.answer("split 120 between 4"), "$30 each.")
        self.assertEqual(quick.answer("split the 90 dollar bill among three people"), "$30 each.")

    def test_deleting_a_list_empties_it(self):
        self.assertEqual(voice._interpret("delete the shopping list")["command"],
                         {"kind": "shopping_off", "item": "everything"})
        with mock.patch("aletheia.lists.is_named_list", return_value=True):
            # Clearing empties a named list; deleting takes the list itself
            # away (kept in the file, marked deleted) - 2026-10-07.
            self.assertEqual(voice._interpret("clear the packing list")["command"],
                             {"kind": "list_off", "list": "packing", "item": "everything"})
            self.assertEqual(voice._interpret("delete the packing list")["command"],
                             {"kind": "list_off", "list": "packing", "item": "the list"})


class HerName(unittest.TestCase):
    def test_her_name_alone_is_answered(self):
        for said in ("hey thea", "ok thea", "thea"):
            self.assertEqual(voice._interpret(said), {"command": None, "say": "I'm listening."}, said)

    def test_her_name_after_filler_does_not_hide_a_quick_question(self):
        from aletheia import quick
        self.assertEqual(quick.match("hey thea what time is it"), quick.match("what time is it"))

    def test_a_word_that_starts_with_her_name_is_not_her_name(self):
        self.assertEqual(voice.strip_wake_word("theater tickets"), "theater tickets")
        self.assertEqual(voice.strip_wake_word("tiara"), "tiara")


class TheNextHoliday(unittest.TestCase):
    def test_every_holiday_has_a_date(self):
        import datetime as dt
        from aletheia import quick
        for name in quick._HOLIDAY_NAMES:
            self.assertIsNotNone(quick._named_date(name, dt.date(2026, 10, 7)), name)

    def test_the_next_one_is_named_and_dated(self):
        from aletheia import quick
        said = quick.answer("what holiday is next")
        self.assertTrue(any(said.startswith(n) for n in quick._HOLIDAY_NAMES), said)
        self.assertRegex(quick.answer("is today a holiday"), r"^(Yes - today is|No\. The next one is) ")


class WhatToWear(unittest.TestCase):
    def test_clothes_are_the_forecast_asked_sideways(self):
        from aletheia import quick
        for said in ("should i wear a jacket", "do i need a coat", "should i wear shorts today"):
            self.assertEqual(quick.match(said)[0], "weather", said)
        self.assertNotEqual(quick.match("do i need milk")[0], "weather")


class ThingsWithNumbers(unittest.TestCase):
    def test_a_locker_is_not_a_contact(self):
        from aletheia import quick
        self.assertNotEqual((voice._interpret("what's my locker number").get("command") or {}).get("kind"), "contacts")
        self.assertEqual(voice._interpret("what's my mom's number")["command"], {"kind": "contacts", "which": "my mom", "asked": "number"})
        with mock.patch.object(quick, "_notes", return_value=[{"text": "my locker is 42"}]):
            self.assertEqual(quick.answer("what's my locker number"), "You told me: your locker is 42.")

    def test_where_the_car_is_reads_where_he_parked(self):
        from aletheia import quick
        with mock.patch.object(quick, "_parked", return_value="Level 3."):
            self.assertEqual(voice._interpret("where's my car")["say"], "Level 3.")

    def test_everything_about_him_is_not_one_sentence(self):
        got = voice._interpret("delete everything you know about me")
        self.assertIsNone(got["command"])
        self.assertIn("one at a time", got["say"])


class SitesAndLookups(unittest.TestCase):
    def test_sites_people_open_by_name(self):
        from aletheia import open_it
        self.assertEqual(voice._interpret("open spotify")["command"], {"kind": "open_page", "which": "spotify"})
        self.assertEqual(open_it.page_for("netflix")[1], "Netflix")

    def test_a_lookup_she_can_answer_is_answered(self):
        from aletheia import quick
        with mock.patch.object(quick, "answer", return_value="3:53 pm in Tokyo."):
            self.assertEqual(voice._interpret("google what time is it in tokyo"), {"command": None, "say": "3:53 pm in Tokyo."})
        with mock.patch.object(quick, "answer", return_value=None):
            self.assertEqual(voice._interpret("look up the weather in paris")["command"]["kind"], "research")
        self.assertEqual(voice._interpret("look up pizza places")["command"], {"kind": "research", "question": "pizza places"})


class HisMoneyAskedOtherWays(unittest.TestCase):
    def test_bills_and_what_he_pays(self):
        for said in ("how much am i paying for netflix", "what bills are due", "how much do i spend on subscriptions a month"):
            self.assertEqual(voice._interpret(said)["command"], {"kind": "subscriptions"}, said)

    def test_a_price_in_the_world_is_not_his_tracker(self):
        self.assertNotEqual((voice._interpret("how much is netflix").get("command") or {}).get("kind"), "subscriptions")

    def test_a_card_balance_is_his_money(self):
        self.assertEqual(voice._interpret("what's my credit card balance")["command"], {"kind": "money"})


class MailAndParcels(unittest.TestCase):
    def test_a_shops_order_is_read_from_his_inbox(self):
        self.assertEqual(voice._interpret("where is my amazon order")["command"], {"kind": "email_read", "which": "amazon"})

    def test_a_parcel_she_cannot_track_says_where_to_look(self):
        got = voice._interpret("track my package")
        self.assertIsNone(got["command"])
        self.assertIn("any emails from Amazon", got["say"])

    def test_mail_she_cannot_change_is_said_plainly(self):
        self.assertIn("can't delete", voice._interpret("delete that email")["say"])

    def test_a_bare_send_an_email_asks_who_and_what(self):
        self.assertIn("Who to", voice._interpret("send an email")["say"])
        self.assertEqual(voice._interpret("what's my most recent email about")["command"], {"kind": "email_check"})


class MealsAndMeetings(unittest.TestCase):
    def test_a_meal_with_no_time_is_at_its_hour(self):
        self.assertIn("T12:00", voice._interpret("schedule lunch with sam on friday")["command"]["start"])
        self.assertIn("T18:30", voice._interpret("schedule dinner with mom saturday")["command"]["start"])
        self.assertIn("T13:00", voice._interpret("schedule lunch friday at 1")["command"]["start"])

    def test_the_day_after_a_name_is_the_window_not_the_name(self):
        got = voice._interpret("schedule a call with dana friday")["command"]
        self.assertEqual(got["person"], "dana")
        self.assertEqual(got["from_day"], got["to_day"])


class ATimerReceiptSaysWhatItIs(unittest.TestCase):
    def say(self, words):
        from aletheia import speech
        return speech.spoken_receipt("remind_at", f"reminder r1 set for 2030-01-01T12:00:00+00:00 — '{words}'")

    def test_a_named_timer(self):
        self.assertTrue(self.say("your 10 minute eggs timer is up").startswith("Timer set for 10 minutes for the eggs - "))

    def test_his_own_number_word(self):
        self.assertTrue(self.say("your ten-minute timer is up").startswith("Timer set for ten minutes - "))
        self.assertTrue(self.say("your one-minute timer is up").startswith("Timer set for one minute - "))


class WhereHeLivesAndHisClock(unittest.TestCase):
    def test_his_town_is_remembered_as_he_said_it(self):
        self.assertEqual(voice._interpret("i live in austin")["command"],
                         {"kind": "remember", "domain": "identity", "key": "home_city", "value": "Austin"})
        self.assertEqual(voice._interpret("i moved to denver, co")["command"]["value"], "Denver, CO")
        self.assertEqual(voice._interpret("i live in 80202")["command"]["key"], "postal_code")
        self.assertNotEqual((voice._interpret("i live in an apartment").get("command") or {}).get("key"), "home_city")

    def test_the_weather_reads_his_town_when_there_is_no_postcode(self):
        from aletheia import memory, weather
        with mock.patch.object(memory, "everything", return_value={"identity": {"home_city": "Austin"}}), \
                mock.patch("aletheia.profile.answer", return_value=""), \
                mock.patch.object(weather, "place_point", return_value=(30.2, -97.7, "Austin, Texas")) as looked:
            code, name = weather.where_he_is()
            self.assertEqual(weather._home_point(code, name), (30.2, -97.7, "Austin, Texas"))
        looked.assert_called_once_with("Austin")

    def test_his_time_zone(self):
        for said, zone in (("set my timezone to pacific", "America/Los_Angeles"), ("i'm on eastern time", "America/New_York")):
            self.assertEqual(voice._interpret(said)["command"],
                             {"kind": "remember", "domain": "identity", "key": "timezone", "value": zone}, said)

    def test_percent_and_rounding_said_plainly(self):
        from aletheia import quick
        self.assertEqual(quick.answer("15 percent of 200"), "30.")
        self.assertEqual(quick.answer("round 3.14159 to 2 decimals"), "3.14.")


class TheConversationReadBack(unittest.TestCase):
    def test_what_we_talked_about_is_his_own_words(self):
        from aletheia import converse, quick
        turns = [{"you": "thea, add milk to my list"}, {"you": "what's the weather"},
                 {"you": "what's the weather"}, {"you": "what did we talk about"}]
        with mock.patch.object(converse, "_thread", return_value=turns):
            self.assertEqual(quick.answer("what did we talk about"),
                             "You asked me \u201cadd milk to my list\u201d and \u201cwhat's the weather\u201d.")
        with mock.patch.object(converse, "_thread", return_value=turns[:3]):
            self.assertEqual(quick.answer("what was the last thing i asked"), "You asked: \u201cwhat's the weather.\u201d")

    def test_a_pep_talk(self):
        from aletheia import quick
        self.assertEqual(quick.answer("give me a pep talk"), quick.answer("motivate me"))


class LooseTimesOfDay(unittest.TestCase):
    def test_after_lunch_is_one(self):
        for said in ("remind me after lunch to stretch", "remind me to stretch after lunch"):
            got = voice._interpret(said)["command"]
            self.assertEqual((got["kind"], got["text"]), ("remind_at", "stretch"), said)
            self.assertIn("T13:00", got["at"])

    def test_in_a_bit_with_nothing_to_remind_asks(self):
        got = voice._interpret("remind me in a bit")
        self.assertIsNone(got["command"])
        self.assertIn("Remind you of what", got["say"])


class HisCalendarByDateAndBlocks(unittest.TestCase):
    def test_a_day_by_its_date(self):
        import datetime as dt
        from aletheia import calendar, localtime, quick
        tz = localtime.operator_tz()
        today = dt.datetime.now(tz).date()
        later = today + dt.timedelta(days=3)
        event = {"title": "Dentist", "start": dt.datetime.combine(later, dt.time(15), tzinfo=tz).isoformat()}
        with mock.patch.object(calendar, "all_events", return_value=[event]):
            said = quick.answer(f"what do i have on {later.strftime('%B').lower()} {later.day}")
        self.assertEqual(said, f"{later.strftime('%A')} {later.day} {later.strftime('%B')}: Dentist at 3 pm.")
        self.assertEqual(quick.match("what's on my calendar on the 15th")[0], "agenda_on")

    def test_a_block_of_time_for_something(self):
        got = voice._interpret("block 2 hours tomorrow morning for focus")["command"]
        self.assertEqual((got["kind"], got["title"], got["minutes"]), ("calendar_hold", "Focus", 120))
        self.assertIn("T09:00", got["start"])

    def test_the_first_meeting_is_todays_when_no_day_is_said(self):
        from aletheia import quick
        self.assertEqual(quick.match("what's my first meeting")[0], "first_meeting")


class FreeTimeAskedEveryWay(unittest.TestCase):
    def test_time_on_his_calendar_is_not_a_file(self):
        got = voice._interpret("find me 30 minutes tomorrow")["command"]
        self.assertEqual((got["kind"], got["minutes"]), ("free_time", 30))
        for said in ("what time am i free tomorrow", "when's my next free hour", "do i have time for lunch",
                     "when can i fit in a workout tomorrow"):
            self.assertEqual(voice._interpret(said)["command"]["kind"], "free_time", said)

    def test_a_file_called_something_is_searched_by_its_name(self):
        self.assertEqual(voice._interpret("find a file called notes")["command"], {"kind": "file_find", "query": "notes"})

    def test_an_appointment_she_cannot_cancel(self):
        self.assertIn("can't cancel", voice._interpret("cancel my dentist appointment")["say"])


class DoubleBooked(unittest.TestCase):
    def events(self):
        import datetime as dt
        from aletheia import localtime
        tz = localtime.operator_tz()
        day = dt.datetime.now(tz).date() + dt.timedelta(days=2)
        at = lambda h, m=0: dt.datetime.combine(day, dt.time(h, m), tzinfo=tz).isoformat()
        return [{"title": "Dentist", "start": at(15), "end": at(16)},
                {"title": "Standup", "start": at(15, 30), "end": at(15, 45)},
                {"title": "Gym", "start": at(18), "end": at(19)}]

    def test_two_that_overlap_are_named(self):
        from aletheia import calendar, quick
        with mock.patch.object(calendar, "all_events", return_value=self.events()):
            said = quick.answer("am i double booked")
        self.assertTrue(said.startswith("Yes: Dentist and Standup overlap "), said)

    def test_none_that_overlap(self):
        from aletheia import calendar, quick
        with mock.patch.object(calendar, "all_events", return_value=self.events()[2:]):
            self.assertEqual(quick.answer("do i have any conflicts this week"),
                             "No - nothing on your calendar overlaps in the next week.")


class PlayingAndTheNews(unittest.TestCase):
    def test_play_the_news_reads_the_headlines(self):
        from aletheia import quick
        with mock.patch.object(quick, "_news", return_value="Here are the headlines."):
            self.assertEqual(voice._interpret("play the news"), {"command": None, "say": "Here are the headlines."})

    def test_a_volume_number_is_said_plainly(self):
        # "Volume 50" is a level, and since 2026-10-07 she sets it.
        self.assertEqual(voice._interpret("volume 50")["command"]["level"], 50)


class FilesByName(unittest.TestCase):
    def test_delete_and_rename_a_file_in_her_workspace(self):
        self.assertEqual(voice._interpret("delete the file test.txt")["command"], {"kind": "file_delete", "path": "test.txt"})
        self.assertEqual(voice._interpret("rename notes.txt to ideas.txt")["command"],
                         {"kind": "file_move", "path": "notes.txt", "to": "ideas.txt"})

    def test_a_folder_that_might_be_his_is_not_guessed(self):
        self.assertNotEqual((voice._interpret("move report.docx to documents").get("command") or {}).get("kind"), "file_move")

    def test_a_document_called_something_asks_what_goes_in_it(self):
        self.assertIn("groceries", voice._interpret("make a word document called groceries")["say"])


class HisApplicationsAskedOtherWays(unittest.TestCase):
    def test_show_me_my_applications(self):
        self.assertEqual(voice._interpret("show me my applications")["command"], {"kind": "applications"})

    def test_which_companies_did_you_apply_to(self):
        from aletheia import quick
        self.assertEqual(quick.match("which companies did you apply to")[0], "applied_to")


class CalendarArithmetic(unittest.TestCase):
    """Both sides move with the calendar: the expectation is computed from today too."""

    def setUp(self):
        import datetime as dt
        from aletheia import localtime
        self.today = dt.datetime.now(localtime.operator_tz()).date()

    def test_weeks_and_days_from_today(self):
        import datetime as dt
        from aletheia import quick
        when = self.today + dt.timedelta(days=21)
        self.assertEqual(quick._date_after("what's 3 weeks from today"),
                         f"{when.strftime('%A')} {when.day} {when.strftime('%B')} {when.year}.")
        when = self.today + dt.timedelta(days=7)
        self.assertIn(when.strftime("%A"), quick._date_after("what is a week from today"))

    def test_the_date_in_months_is_not_a_date_lookup(self):
        from aletheia import quick
        self.assertEqual(quick.match("what's the date in two months")[0], "date_after")

    def test_days_since_counts_back_to_the_one_that_passed(self):
        from aletheia import quick
        said = quick._days_since("january 1")
        self.assertIn(f"since {__import__('datetime').date(self.today.year, 1, 1).strftime('%A')} 1 January", said)
        self.assertIn(f"{(self.today - __import__('datetime').date(self.today.year, 1, 1)).days:,} day", said)

    def test_is_it_the_weekend(self):
        from aletheia import quick
        said = quick._weekend_q()
        self.assertTrue(said.startswith("Yes" if self.today.weekday() >= 5 else "No"))
        self.assertEqual(quick.match("is it the weekend")[0], "weekend_q")

    def test_a_bare_ordinal_is_this_month_or_next(self):
        from aletheia import quick
        d = quick._a_date("the 15th", self.today)
        self.assertEqual(d.day, 15)
        self.assertGreaterEqual(d, self.today)

    def test_born_in_a_year(self):
        from aletheia import quick
        age = self.today.year - 1990
        self.assertIn(f"{age - 1} or {age}", quick._born_in("1990"))
        self.assertIsNone(quick._born_in("1066"))



class AReminderAboutAPronoun(unittest.TestCase):
    def test_this_is_asked_about(self):
        said = voice.interpret("remind me about this tomorrow")
        self.assertIsNone(said["command"])
        self.assertIn("What should I remind you about", said["say"])

    def test_a_real_thing_is_kept(self):
        self.assertEqual(voice.interpret("remind me tomorrow to call the bank")["command"]["kind"], "remind_at")



class TheWhenSaidFirst(unittest.TestCase):
    def test_every_weekday_first(self):
        self.assertEqual(voice._interpret("every weekday at 8 remind me to stretch")["command"],
                         voice._interpret("remind me every weekday at 8 to stretch")["command"])

    def test_tomorrow_first(self):
        self.assertEqual(voice._interpret("tomorrow at 3 remind me to call the bank")["command"]["text"], "call the bank")


class OtherWaysToAskTheSameThing(unittest.TestCase):
    def test_updates_urgent_summary_and_recurring(self):
        self.assertEqual(voice._interpret("any updates")["command"], {"kind": "notify_check"})
        self.assertEqual(voice._interpret("give me a summary")["command"], {"kind": "brief"})
        self.assertEqual(voice._interpret("what are my recurring reminders")["command"], {"kind": "reminders"})
        self.assertIsNone(voice._interpret("what's urgent")["command"])

    def test_net_worth_and_bank_balance_read_the_money_store(self):
        for said in ("what's my net worth", "check my bank balance", "show me my accounts"):
            self.assertEqual(voice._interpret(said)["command"], {"kind": "money"}, said)



class WhenIsMyDentist(unittest.TestCase):
    def test_a_question_is_never_a_note_about_somebody_called_when(self):
        self.assertNotEqual((voice._interpret("when is my dentist").get("command") or {}).get("kind"), "note")
        self.assertEqual(voice._interpret("dana is my sister")["command"]["kind"], "note")

    def test_it_reads_the_calendar_by_who_it_is_with(self):
        import datetime as dt
        from aletheia import quick
        self.assertEqual(quick.match("when is my next dentist")[0], "when_mine")
        at = dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=2)
        with mock.patch.object(quick, "_coming", return_value=[(at, "Dentist with Dr Lee", "calendar")]):
            self.assertTrue(quick._when_mine("dentist").startswith("Dentist with Dr Lee is"))


class SixAmIsMorning(unittest.TestCase):
    def test_a_glued_am_is_still_am(self):
        self.assertFalse(voice._is_bare_hour("6am"))
        self.assertTrue(voice._is_bare_hour("6"))
        self.assertIn("T06:00", voice._interpret("put gym on my calendar tomorrow at 6am")["command"]["start"])


class MessagesAndFacetime(unittest.TestCase):
    def test_phone_only_things_say_so(self):
        for said in ("read my messages", "do i have voicemail"):
            self.assertIn("stay on your phone", voice._interpret(said)["say"], said)
        # A text to his Google Voice number is one she can read.
        self.assertEqual(voice._interpret("what did dana text me")["command"],
                         {"kind": "texts_read", "who": "dana"})
        self.assertIn("can't place phone calls", voice._interpret("facetime sam")["say"])



class TheTimeBetweenTheThingAndTheRepeat(unittest.TestCase):
    def test_pills_at_9pm_every_day(self):
        self.assertEqual(voice._interpret("remind me to take my pills at 9pm every day")["command"],
                         {"kind": "remind_daily", "time": "21:00", "text": "take my pills"})

    def test_stretch_at_8_every_weekday(self):
        cmd = voice._interpret("remind me to stretch at 8 every weekday")["command"]
        self.assertEqual((cmd["time"], cmd["text"]), ("08:00", "stretch"))


class RememberIsNotTheFact(unittest.TestCase):
    def test_the_verb_stays_out_of_the_note(self):
        self.assertEqual(voice.interpret("Remember Dana's birthday is March 3")["command"],
                         {"kind": "note", "text": "Dana's birthday is March 3"})



class APlaceNearHimIsNotAFile(unittest.TestCase):
    def test_nearby_places_are_a_web_search(self):
        self.assertEqual(voice._interpret("find a gas station")["command"],
                         {"kind": "research", "question": "gas station near me"})
        self.assertEqual(voice._interpret("where's the nearest starbucks")["command"]["question"], "starbucks near me")

    def test_his_own_things_are_still_files(self):
        self.assertEqual(voice._interpret("find the report")["command"]["kind"], "file_find")

    def test_how_far_is_a_place_and_not_the_moon(self):
        self.assertEqual(voice._interpret("how far is chicago")["command"], {"kind": "travel_time", "place": "chicago"})
        self.assertNotEqual((voice._interpret("how far is the moon").get("command") or {}).get("kind"), "travel_time")


class MoreWeatherWords(unittest.TestCase):
    def test_sunrise_and_rain_reach_the_weather(self):
        from aletheia import quick
        self.assertEqual(quick.match("sunrise tomorrow")[0], "sun")
        for said in ("how much rain today", "what's the chance of rain tomorrow", "will it be sunny tomorrow"):
            self.assertIn(quick.match(said)[0], ("weather", "weather_more"), said)



class TickingTheShoppingList(unittest.TestCase):
    def setUp(self):
        from aletheia import intercom
        self.rows = mock.patch.object(intercom, "_shopping_items", return_value=[{"need": "milk"}])
        self.rows.start()
        self.addCleanup(self.rows.stop)
        self.tasks = mock.patch.object(voice, "_names_one_open_task", return_value=False)
        self.tasks.start()
        self.addCleanup(self.tasks.stop)

    def test_check_off_milk_is_the_list_not_a_task(self):
        self.assertEqual(voice._interpret("check off milk")["command"], {"kind": "shopping_off", "item": "milk"})
        self.assertEqual(voice._interpret("grabbed the milk")["command"], {"kind": "shopping_off", "item": "milk"})

    def test_did_i_add_milk(self):
        self.assertEqual(voice._interpret("did i add milk")["say"], "Yes - milk is on your shopping list.")

    def test_clear_the_list_with_no_other_list(self):
        with mock.patch.object(voice, "_other_lists", return_value=False):
            self.assertEqual(voice._interpret("clear the list")["command"], {"kind": "shopping_off", "item": "everything"})
        with mock.patch.object(voice, "_other_lists", return_value=True):
            self.assertNotEqual((voice._interpret("clear the list").get("command") or {}).get("kind"), "shopping_off")



class DeleteTheNoteAbout(unittest.TestCase):
    def test_the_one_note_with_those_words(self):
        from aletheia import quick
        rows = [{"text": "the wifi is upstairs"}, {"text": "call the bank"}]
        with mock.patch.object(quick, "_notes", return_value=rows):
            self.assertEqual(voice._interpret("delete the note about wifi")["command"],
                             {"kind": "forget", "about": "the wifi is upstairs"})
            self.assertIn("don't have a note", voice._interpret("delete the note about pizza")["say"])

    def test_two_are_asked_about(self):
        from aletheia import quick
        rows = [{"text": "wifi is upstairs"}, {"text": "new wifi router"}]
        with mock.patch.object(quick, "_notes", return_value=rows):
            self.assertIn("Which one", voice._interpret("delete the note about wifi")["say"])

    def test_show_my_notes_from_yesterday(self):
        from aletheia import quick
        self.assertEqual(quick.match("show my notes from yesterday")[0], "notes_day")



class NumbersAPersonCanSay(unittest.TestCase):
    def test_a_long_decimal_is_rounded(self):
        from aletheia import quick
        self.assertEqual(quick._math("what is 100 divided by 7"), "14.29.")

    def test_the_date_yesterday(self):
        from aletheia import quick
        self.assertEqual(quick.match("what was the date yesterday")[0], "calendar_fact")



class HowHeIs(unittest.TestCase):
    def test_busy_is_an_hour_of_quiet(self):
        for said in ("i'm in a meeting", "i'm driving"):
            self.assertEqual(voice._interpret(said)["command"], {"kind": "notify_snooze", "minutes": 60, "quiet": True}, said)

    def test_a_nap_timer_asks_how_long(self):
        self.assertIn("For how long", voice._interpret("set a nap timer")["say"])

    def test_feelings_and_mornings(self):
        from aletheia import quick
        self.assertEqual(quick.match("i had a bad day")[0], "feeling")
        self.assertEqual(quick.match("i'm sick today")[0], "feeling")
        self.assertEqual(quick.match("i'm awake")[0], "good_morning")
        self.assertEqual(quick.match("how productive was i today")[0], "tasks_done")
        self.assertEqual(quick.match("what did i accomplish this week")[0], "tasks_done")



class WhenAmIDone(unittest.TestCase):
    def test_the_last_thing_today_and_when_it_ends(self):
        import datetime as dt
        from aletheia import calendar, localtime, quick
        tz = localtime.operator_tz()
        day = dt.datetime.now(tz).replace(hour=0, minute=0, second=0, microsecond=0)
        rows = [{"title": "Standup", "start": (day + dt.timedelta(hours=9)).isoformat(),
                 "end": (day + dt.timedelta(hours=9, minutes=15)).isoformat()},
                {"title": "Review", "start": (day + dt.timedelta(hours=16)).isoformat(),
                 "end": (day + dt.timedelta(hours=17)).isoformat()}]
        with mock.patch.object(calendar, "all_events", return_value=rows):
            said = quick._last_meeting("today")
        self.assertTrue(said.startswith("Your last thing today is Review, done at"), said)
        self.assertEqual(quick.match("when am i done today")[0], "last_meeting")

    def test_other_ways_to_ask(self):
        from aletheia import quick
        self.assertEqual(quick.match("am i free this weekend")[0], "agenda")
        self.assertEqual(quick.match("what's my most urgent task")[0], "task_top")
        self.assertEqual(quick.match("any deadlines this week")[0], "due")



class AnythingThisEvening(unittest.TestCase):
    def test_a_part_of_today(self):
        self.assertEqual(voice._interpret("anything this evening")["command"]["part"], "evening")
        self.assertEqual(voice._interpret("do i have anything tonight")["command"]["part"], "tonight")



class NewsAboutAThing(unittest.TestCase):
    def test_a_topic_is_web_research(self):
        self.assertEqual(voice._interpret("sports news")["command"], {"kind": "research", "question": "latest sports news"})
        self.assertEqual(voice._interpret("any news about the election")["command"]["question"],
                         "latest news about election")


class HisPlaylistIsNotASearch(unittest.TestCase):
    def test_my_playlist_is_the_honest_half(self):
        self.assertIsNone(voice._interpret("play my playlist")["command"])
        self.assertEqual(voice._interpret("play jazz")["command"]["kind"], "open_page")



class RemoteIsWhereNotWhat(unittest.TestCase):
    def test_remote_jobs(self):
        self.assertEqual(voice._interpret("find me remote jobs")["command"], {"kind": "jobs", "where": "remote"})
        self.assertEqual(voice._interpret("find me remote sales jobs")["command"]["role"], "sales")



class ItIsTheTaskJustAdded(unittest.TestCase):
    def turns(self, answered):
        from aletheia import converse
        return mock.patch.object(converse, "recent", return_value=[
            {"he_asked": "add a task to call the dentist", "she_answered": answered}])

    def test_make_it_due_friday(self):
        with self.turns("Added a task: call the dentist."):
            cmd = voice._interpret("make it due friday")["command"]
        self.assertEqual((cmd["kind"], cmd["which"]), ("task_change", "call the dentist"))

    def test_change_it_after_a_move(self):
        for said in ("Moved: call the dentist due Friday.", "Call the dentist is due Friday now."):
            with self.turns(said):
                self.assertEqual(voice._interpret("actually change it to thursday")["command"]["which"].casefold(),
                                 "call the dentist")

    def test_remind_me_about_it(self):
        with self.turns("Added a task: call the dentist."):
            self.assertEqual(voice.interpret("remind me about it tomorrow at 9")["command"]["text"], "call the dentist")

    def test_with_no_task_just_added_it_is_not_guessed(self):
        with self.turns("It's 3 pm."):
            self.assertNotEqual((voice._interpret("make it due friday").get("command") or {}).get("kind"), "task_change")



class MakeTheHoldEight(unittest.TestCase):
    def test_make_it_8_moves_the_hold_just_made(self):
        held = {"kind": "calendar_hold", "title": "dinner with sam", "start": "2026-10-09T19:00:00-05:00"}
        with mock.patch.object(voice, "_recent_reminder_ask", return_value={}), \
                mock.patch.object(voice, "_recent_ask_of", return_value=held):
            cmd = voice._interpret("make it 8")["command"]
        self.assertEqual(cmd, {"kind": "calendar_hold", "title": "dinner with sam",
                               "start": "2026-10-09T20:00:00-05:00", "replaces": "2026-10-09T19:00:00-05:00"})

    def test_the_old_hold_is_released_and_the_new_one_held(self):
        import tempfile
        from aletheia import calendar, calendar_reasoning, intercom
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(calendar, "CALENDAR_DIR", __import__("pathlib").Path(tmp), create=True):
            first = intercom.execute_command({"kind": "calendar_hold", "title": "Dinner",
                                              "start": "2030-10-09T19:00:00-05:00"}, {}, quote="put dinner on my calendar")
            said = intercom.execute_command({"kind": "calendar_hold", "title": "Dinner",
                                             "start": "2030-10-09T20:00:00-05:00",
                                             "replaces": "2030-10-09T19:00:00-05:00"}, {}, quote="make it 8")
            old = calendar.load(calendar_reasoning.hold_id("Dinner", "2030-10-09T19:00:00-05:00"))
        self.assertIn("Pencilled in", str(first))
        self.assertIn("Moved Dinner to", str(said))
        self.assertEqual(old["status"], "CANCELLED")



class AddingMinutesSaysWhenNotHowLong(unittest.TestCase):
    def test_a_moved_timer_says_when_it_goes_off(self):
        from aletheia import speech
        said = speech.spoken_receipt(
            "remind_at", "reminder remind-1 set for 2030-10-07T08:29:00+00:00 — 'your 10 minute pasta timer is up' (moved)")
        self.assertTrue(said.startswith("Done - your timer for the pasta now goes off"), said)



class HerIsThePersonJustNamed(unittest.TestCase):
    def turns(self, asked):
        from aletheia import converse
        return mock.patch.object(converse, "recent", return_value=[{"he_asked": asked, "she_answered": "Noted."}])

    def test_her_birthday_and_her_number(self):
        with self.turns("my sister's name is Jess"):
            self.assertEqual(voice._with_the_person_named("her birthday is March 3"), "Jess's birthday is March 3")
            self.assertEqual(voice._with_the_person_named("what's her number"), "what's Jess's number")
            self.assertEqual(voice._with_the_person_named("text her happy birthday"), "text Jess happy birthday")

    def test_nobody_named_leaves_the_sentence_alone(self):
        with self.turns("what time is it"):
            self.assertEqual(voice._with_the_person_named("what's her number"), "what's her number")

    def test_a_relation_is_who_she_is(self):
        with self.turns("what's my mom's number"):
            self.assertEqual(voice._with_the_person_named("text her hi"), "text Mom hi")



class WhatAboutTomorrow(unittest.TestCase):
    def turns(self, *asked):
        from aletheia import converse
        return mock.patch.object(converse, "recent", return_value=[{"he_asked": a, "she_answered": "ok"} for a in asked])

    def test_a_statement_in_between_is_stepped_over(self):
        from aletheia import quick
        with self.turns("what's on my calendar", "my zip is 78701"), \
                mock.patch.object(quick, "_agenda", side_effect=lambda day: f"agenda {day}"):
            self.assertEqual(quick.answer("what about tomorrow"), "agenda tomorrow")

    def test_a_place_is_added_to_the_time(self):
        from aletheia import quick
        with self.turns("what time is it"):
            self.assertIn("Tokyo", quick.answer("and in tokyo"))
            self.assertIn("London", quick.answer("how about london"))

    def test_a_thing_that_is_not_a_place_stays_with_a_model(self):
        from aletheia import quick
        with self.turns("what time is it"):
            self.assertIsNone(quick.answer("what about pizza"))



class TheOtherOne(unittest.TestCase):
    def test_with_one_left_the_other_one_is_it(self):
        from aletheia import intercom
        with mock.patch.object(intercom, "_open_tasks", return_value=[{"id": "t1", "description": "renew my passport"}]):
            self.assertEqual(intercom._one_task("the other one")[0]["id"], "t1")
        with mock.patch.object(intercom, "_open_tasks", return_value=[{"id": "a", "description": "x"},
                                                                      {"id": "b", "description": "y"}]):
            self.assertIn("Which one", intercom._one_task("other")[1])

    def test_whats_left_after_a_tick_is_the_task_list(self):
        with mock.patch.object(voice, "_previous_turn", return_value=("mark the first one done", "Done: call the plumber.")):
            self.assertEqual(voice._interpret("what's left")["command"], {"kind": "tasks"})



class AShoppingRunAfterABareAdd(unittest.TestCase):
    def turns(self, *pairs):
        from aletheia import converse
        return mock.patch.object(converse, "recent", return_value=[{"he_asked": a, "she_answered": b} for a, b in pairs])

    def test_and_apples_after_add_bananas(self):
        with self.turns(("add bananas", "Added to the shopping list: bananas.")):
            self.assertEqual(voice._interpret("and apples and oranges")["command"],
                             {"kind": "shopping_add", "item": "apples and oranges"})

    def test_a_bare_add_that_became_a_task_is_not_a_run(self):
        with self.turns(("add call mom", "Added a task: call mom.")):
            self.assertNotEqual((voice._interpret("and eggs").get("command") or {}).get("kind"), "shopping_add")

    def test_clear_it_only_right_after_the_list(self):
        with mock.patch.object(voice, "_previous_turn", return_value=("how many are on it", "2 things on your shopping list: a and b.")):
            self.assertEqual(voice._interpret("clear it")["command"], {"kind": "shopping_off", "item": "everything"})
        with mock.patch.object(voice, "_previous_turn", return_value=("what time is it", "3 pm.")), \
                self.turns(("add milk to the shopping list", "Added to the shopping list: milk."), ("what time is it", "3 pm.")):
            self.assertNotEqual((voice._interpret("clear it").get("command") or {}).get("kind"), "shopping_off")
            self.assertEqual(voice._interpret("how many things are on it")["command"], {"kind": "shopping_list"})



class TheAnswerToHerQuestion(unittest.TestCase):
    def after(self, answered):
        return mock.patch.object(voice, "_previous_turn", return_value=("x", answered))

    def test_a_reminder_with_no_time_asks_and_the_answer_sets_it(self):
        self.assertIn("When should I remind you to email sam", voice._interpret("remind me to email sam")["say"])
        with self.after('When should I remind you to email sam? Say a time, like "at 3" or "tomorrow morning".'):
            cmd = voice._interpret("tomorrow at 2")["command"]
        self.assertEqual((cmd["kind"], cmd["text"]), ("remind_at", "email sam"))
        self.assertIn("T14:00", cmd["at"])

    def test_how_long_and_what_time(self):
        with self.after('For how long? Say "set a timer for ten minutes".'):
            self.assertEqual(voice._interpret("10 minutes")["command"]["kind"], "remind_at")
        with self.after('For what time? Say "wake me up at 6".'):
            self.assertEqual(voice._interpret("6:30")["command"]["text"], "wake up")

    def test_a_sentence_that_is_not_an_answer_is_left_alone(self):
        with self.after('For how long? Say "set a timer for ten minutes".'):
            self.assertNotEqual((voice._interpret("what's the weather").get("command") or {}).get("kind"), "remind_at")


class CancelTheBankOne(unittest.TestCase):
    def test_a_reminder_by_its_words_is_not_a_subscription(self):
        from aletheia import intercom
        with mock.patch.object(intercom, "_one_reminder", return_value=({"id": "r1"}, "")):
            self.assertEqual(voice._interpret("cancel the bank one")["command"], {"kind": "reminder_off", "which": "bank"})

    def test_and_remind_me_too(self):
        cmd = voice._interpret("and remind me tomorrow at 9 to email sam too")["command"]
        self.assertEqual(cmd["text"], "email sam")


class MakeItTenKeepsTheDay(unittest.TestCase):
    def test_tomorrows_reminder_stays_tomorrow(self):
        import datetime as dt
        from aletheia import localtime
        tz = localtime.operator_tz()
        tomorrow = (dt.datetime.now(tz) + dt.timedelta(days=1)).replace(hour=9, minute=0, second=0, microsecond=0)
        with mock.patch.object(voice, "_recent_reminder_ask",
                               return_value={"kind": "remind_at", "at": tomorrow.isoformat(), "text": "call the bank"}):
            cmd = voice._interpret("make it 10am")["command"]
        self.assertEqual(dt.datetime.fromisoformat(cmd["at"]).date(), tomorrow.date())



class HisNamedListAsIt(unittest.TestCase):
    def turns(self, *pairs):
        from aletheia import converse
        return mock.patch.object(converse, "recent", return_value=[{"he_asked": a, "she_answered": b} for a, b in pairs])

    def test_add_read_take_off_and_clear(self):
        with self.turns(("make a list called packing", 'Started your packing list. Say "add ... to my packing list".')):
            self.assertEqual(voice._interpret("add sunscreen and a hat")["command"],
                             {"kind": "list_add", "list": "packing", "item": "sunscreen and a hat"})
            self.assertEqual(voice._interpret("what's on it")["command"], {"kind": "list_read", "list": "packing"})
            self.assertEqual(voice._interpret("take the hat off")["command"]["kind"], "list_off")
            self.assertEqual(voice._interpret("delete the list")["command"],
                             {"kind": "list_off", "list": "packing", "item": "everything"})

    def test_the_name_is_the_lists_not_the_sentence(self):
        with self.turns(("add the hat back", "Added to your packing list: hat.")):
            self.assertEqual(voice._the_named_list_just_used(), ("packing", True))

    def test_after_the_shopping_list_it_is_the_shopping_list(self):
        with self.turns(("make a list called packing", "Started your packing list."),
                        ("add milk to the shopping list", "Added to the shopping list: milk.")):
            self.assertEqual(voice._the_named_list_just_used(), ("", False))



class NotesThatAnswerWhen(unittest.TestCase):
    def test_a_note_answers_when_the_plumber_comes(self):
        from aletheia import quick
        with mock.patch.object(quick, "_notes", return_value=[{"text": "the plumber comes tuesday"}]):
            self.assertEqual(quick.answer("when does the plumber come"), "You told me: the plumber comes Tuesday.")
        with mock.patch.object(quick, "_notes", return_value=[]):
            self.assertIsNone(quick.answer("when does the plumber come"))

    def test_a_password_in_a_note_is_said_not_faked(self):
        said = voice.interpret("note that the wifi password is hunter2")
        self.assertIsNone(said["command"])
        self.assertIn("don't keep passwords", said["say"])



class TwoTimers(unittest.TestCase):
    def test_another_one_is_a_new_timer(self):
        cmd = voice._interpret("set another one for 10 minutes for the rice")["command"]
        self.assertEqual(cmd["kind"], "remind_at")
        self.assertIn("rice", cmd["text"])

    def test_how_long_left_is_the_timer(self):
        from aletheia import quick
        for said in ("how long left", "how long on the rice", "how much longer"):
            self.assertEqual(quick.match(said)[0], "timer_left", said)

    def test_the_3_minute_one_is_the_3_minute_timer(self):
        from aletheia import intercom
        seen = []

        def one(words):
            seen.append(words)
            return ({"id": "r"}, "") if words == "3-minute" else (None, "no")
        with mock.patch.object(intercom, "_one_reminder", side_effect=one):
            self.assertEqual(voice._interpret("cancel the 3 minute one")["command"], {"kind": "reminder_off", "which": "3-minute"})

    def test_cancel_the_first_one_is_still_counting(self):
        self.assertNotEqual((voice._interpret("cancel the first one").get("command") or {}).get("kind"), "reminder_off")



class CountingIsNotASubject(unittest.TestCase):
    def test_and_the_second_one_is_not_put_into_the_last_question(self):
        from aletheia import converse, quick
        turns = [{"he_asked": "when is my passport due", "she_answered": "x"}]
        with mock.patch.object(converse, "recent", return_value=turns):
            self.assertIsNone(quick.answer("and the second one"))

    def test_when_is_it_due_names_nothing_to_recall(self):
        # "it" is never looked up as a thing called "it"; it is the task
        # just added (2026-10-08), and with none there is no answer here.
        from aletheia import quick, voice
        self.assertNotIn((quick.match("when is it due") or ("",))[0], ("recall", "task_due"))
        with mock.patch.object(voice, "_the_task_just_added", return_value=""):
            self.assertIsNone(quick.answer("when is it due"))



class TheNextMeetingInDetail(unittest.TestCase):
    def _events(self):
        import datetime as dt
        from aletheia import localtime
        now = dt.datetime.now(localtime.operator_tz())
        a = (now + dt.timedelta(minutes=30)).replace(microsecond=0)
        return [{"title": "Design review", "start": a.isoformat(),
                 "end": (a + dt.timedelta(hours=1)).isoformat(),
                 "attendees": ["Dana", "Sam"], "location": "Room 4"}]

    def test_who_and_where_come_from_the_event(self):
        from aletheia import calendar, quick
        with mock.patch.object(calendar, "all_events", return_value=self._events()):
            self.assertIn("with Dana and Sam", quick.answer("who is my next meeting with"))
            self.assertIn("at Room 4", quick.answer("where is my next meeting"))

    def test_an_event_with_nobody_listed_says_so(self):
        from aletheia import calendar, quick
        events = self._events()
        events[0]["attendees"] = []
        with mock.patch.object(calendar, "all_events", return_value=events):
            self.assertIn("doesn't list anybody", quick.answer("who is my next meeting with"))

    def test_the_last_meeting_says_today_once(self):
        from aletheia import calendar, quick
        with mock.patch.object(calendar, "all_events", return_value=self._events()):
            said = quick.answer("when's my last meeting today")
        self.assertEqual(said.count("today"), 1, said)

    def test_how_long_is_my_day_is_answered_from_the_calendar(self):
        from aletheia import calendar, quick
        with mock.patch.object(calendar, "all_events", return_value=[]):
            self.assertIn("free", quick.answer("how long is my day"))



class TheDaysTasksAndWhatHeForgot(unittest.TestCase):
    def test_the_sentences_reach_the_deadline_reader(self):
        from aletheia import quick
        self.assertEqual(quick.match("what tasks do i have today"), ("tasks_due", "today"))
        self.assertEqual(quick.match("what did i forget")[0], "tasks_due")
        self.assertEqual(quick.match("did i forget anything")[0], "tasks_due")
        self.assertEqual(quick.match("how hot will it get")[0], "weather")

    def test_what_did_i_forget_is_the_overdue_list(self):
        import datetime as dt
        from aletheia import intercom, quick
        past = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=1)).isoformat()
        rows = [{"id": "a", "description": "renew passport", "deadline": past},
                {"id": "b", "description": "call the bank"}]
        with mock.patch.object(intercom, "_open_tasks", return_value=rows):
            said = quick.answer("what did i forget")
        self.assertIn("overdue", said)
        self.assertIn("renew passport", said)
        self.assertNotIn("call the bank", said)

    def test_nothing_due_still_says_how_many_are_open(self):
        import datetime as dt
        from aletheia import intercom, quick
        later = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=30)).isoformat()
        rows = [{"id": "a", "description": "renew passport", "deadline": later},
                {"id": "b", "description": "call the bank"}]
        with mock.patch.object(intercom, "_open_tasks", return_value=rows):
            said = quick.answer("what tasks do i have today")
        self.assertIn("Nothing's due today", said)
        self.assertIn("2 tasks open", said)

    def test_unread_email_reads_the_inbox(self):
        from aletheia import voice
        self.assertEqual(voice._interpret("unread emails")["command"]["kind"], "email_check")



class TheTripAskedAnotherWay(unittest.TestCase):
    def _kind(self, said):
        from aletheia import voice
        out = voice._interpret(said)
        return (out.get("command") or {}).get("kind"), (out.get("command") or {}).get("place")

    def test_directions_and_take_me_are_the_trip(self):
        self.assertEqual(self._kind("directions to the airport"), ("travel_time", "airport"))
        self.assertEqual(self._kind("take me home"), ("travel_time", "home"))
        self.assertEqual(self._kind("how do i get to the train station"), ("travel_time", "train station"))
        self.assertEqual(self._kind("what's the traffic to work"), ("travel_time", "work"))

    def test_get_to_that_is_not_a_place_is_left_alone(self):
        for said in ("how do i get to sleep", "how do i get rid of ants", "take me to the settings"):
            self.assertNotEqual(self._kind(said)[0], "travel_time", said)

    def test_whats_open_now_is_a_shop_question(self):
        from aletheia import quick, voice
        self.assertEqual(voice._interpret("what's open now")["command"]["kind"], "research")
        self.assertEqual(quick.match("what's open")[0], "windows")



class AReminderSetByAnsweringHer(unittest.TestCase):
    TURNS = [
        {"he_asked": "remind me to call the bank",
         "she_answered": "When should I remind you to call the bank? Say a time, like \"at 3\" or \"tomorrow morning\"."},
        {"he_asked": "at 2pm", "she_answered": "I'll remind you today at 2 pm: call the bank."},
        {"he_asked": "what's the weather", "she_answered": "Sunny."},
    ]

    def test_move_it_finds_the_reminder_his_answer_set(self):
        from aletheia import converse, voice
        with mock.patch.object(converse, "recent", side_effect=lambda limit=4: self.TURNS[-limit:]):
            found = voice._recent_reminder_ask()
        self.assertEqual(found.get("text"), "call the bank")

    def test_cancel_it_takes_that_reminder_off(self):
        from aletheia import converse, policy, voice
        with mock.patch.object(converse, "recent", side_effect=lambda limit=4: self.TURNS[-limit:]), \
                mock.patch.object(policy, "all_approvals", return_value=[]), \
                mock.patch.object(voice, "_last_ask_is_undoable", return_value=False):
            cmd = voice._interpret("cancel it")["command"]
        self.assertEqual(cmd, {"kind": "reminder_off", "which": "call the bank"})



class WhereANoteSaysItIs(unittest.TestCase):
    def test_a_note_answers_before_a_file_search(self):
        from aletheia import quick, voice
        with mock.patch.object(quick, "_notes", return_value=[{"text": "the wifi code is on the fridge"}]):
            said = voice._interpret("where's the wifi code")
        self.assertIsNone(said["command"])
        self.assertIn("fridge", said["say"])

    def test_with_no_note_it_is_still_a_file_search(self):
        from aletheia import quick, voice
        with mock.patch.object(quick, "_notes", return_value=[]):
            self.assertEqual(voice._interpret("where's my lease")["command"]["kind"], "file_find")



class ACancelledTimerIsNotOneThatWentOff(unittest.TestCase):
    def test_the_receipt_says_cancelled(self):
        from aletheia import speech
        said = speech.spoken_receipt("reminder_off", "reminder r1 off — your 10-minute timer is up — today at 4:12 am")
        self.assertEqual(said, "Cancelled your 10-minute timer.")
        said = speech.spoken_receipt("reminder_off", "reminder r2 off — call the bank — today at 3 pm")
        self.assertTrue(said.startswith("Stopped reminding you: call the bank"), said)



class MySisterIsJenna(unittest.TestCase):
    NOTES = [{"text": "Jenna's birthday is March 4"}, {"text": "my sister's name is Jenna"},
             {"text": "Sam is my boss"}]

    def test_the_relation_reads_the_name_from_his_notes(self):
        from aletheia import quick
        with mock.patch.object(quick, "_notes", return_value=self.NOTES):
            self.assertEqual(quick._name_for_relation("my sister"), "Jenna")
            self.assertEqual(quick._name_for_relation("boss"), "Sam")
            self.assertIsNone(quick._name_for_relation("brother"))

    def test_my_sisters_birthday_is_jennas(self):
        from aletheia import quick
        with mock.patch.object(quick, "_notes", return_value=self.NOTES):
            self.assertIn("March 4", quick.answer("when is my sister's birthday"))
            self.assertIn("your brother's birthday", quick.answer("when is my brother's birthday"))

    def test_text_my_sister_finds_jennas_number(self):
        from aletheia import contacts, messages, quick
        with mock.patch.object(quick, "_notes", return_value=self.NOTES), \
                mock.patch.object(contacts, "resolve", side_effect=lambda q, *a: (
                    {"display_name": "Jenna", "phones": ["3125550101"]} if q == "Jenna" else (_ for _ in ()).throw(KeyError(q)))), \
                mock.patch.object(messages, "primary_number", return_value="3125550101"):
            number, name = messages.resolve_number("my sister")
        self.assertEqual(name, "Jenna")
        self.assertTrue(number and number.endswith("5550101"))

    def test_what_do_you_know_reads_his_notes_too(self):
        from aletheia import intercom, memory, quick
        with mock.patch.object(quick, "_notes", return_value=self.NOTES), \
                mock.patch.object(memory, "recall", return_value=None), \
                mock.patch.object(intercom, "_remembered_matching", return_value=[]):
            said = intercom.execute_command({"kind": "recall", "about": "jenna"}, {"repos": {}}, quote="test")
        said = said if isinstance(said, str) else str(said)
        self.assertIn("March 4", said)



class HowOldIsSomebodyHeToldHerAbout(unittest.TestCase):
    def test_the_age_comes_from_the_birthday_in_his_note(self):
        import datetime as dt
        from aletheia import localtime, quick
        today = dt.datetime.now(localtime.operator_tz()).date()
        born = dt.date(today.year - 40, 1, 1) if (today.month, today.day) != (1, 1) else dt.date(today.year - 40, 6, 1)
        notes = [{"text": f"dad was born on {born.strftime('%B')} {born.day}, {born.year}"}]
        with mock.patch.object(quick, "_notes", return_value=notes):
            said = quick.answer("how old is my dad")
        self.assertTrue(said.startswith("Your dad is 40"), said)

    def test_no_year_says_so_and_a_stranger_goes_on(self):
        from aletheia import quick
        notes = [{"text": "Jenna's birthday is March 4"}, {"text": "my sister's name is Jenna"}]
        with mock.patch.object(quick, "_notes", return_value=notes):
            self.assertIn("not the year", quick.answer("how old is my sister"))
            self.assertIsNone(quick.answer("how old is taylor swift"))



class ArithmeticOnHerLastAnswer(unittest.TestCase):
    def _after(self, answered, said):
        from aletheia import converse, quick
        with mock.patch.object(converse, "recent", return_value=[{"he_asked": "x", "she_answered": answered}]):
            return quick.answer(said)

    def test_the_total_is_split_and_a_number_is_carried_on(self):
        self.assertEqual(self._after("$9.00 tip, $54.00 total.", "split it three ways"), "$18 each.")
        self.assertEqual(self._after("12.", "and times 3"), "36.")
        self.assertEqual(self._after("12.", "half it"), "6.")

    def test_a_sentence_that_is_not_a_sum_is_left_alone(self):
        self.assertIsNone(self._after("Sunny and 70.", "times 2"))



class HowLongHasItBeen(unittest.TestCase):
    def test_a_running_stopwatch_is_it(self):
        from aletheia import quick, stopwatch
        with mock.patch.object(stopwatch, "elapsed", return_value=(75.0, True)):
            self.assertIn("1 minute and 15 seconds", quick.answer("how long has it been"))
        with mock.patch.object(stopwatch, "elapsed", return_value=(None, False)):
            self.assertIsNone(quick.answer("how long has it been"))



class DeleteTheXNote(unittest.TestCase):
    def test_the_words_in_front_name_the_note(self):
        from aletheia import quick, voice
        notes = [{"text": "the plumber comes thursday at 10"}, {"text": "my locker is 42"}]
        with mock.patch.object(quick, "_notes", return_value=notes):
            cmd = voice._interpret("delete the plumber note")["command"]
        self.assertEqual(cmd, {"kind": "forget", "about": "the plumber comes thursday at 10"})



class APoliteAskIsAnAsk(unittest.TestCase):
    def test_can_you_with_a_concrete_ask_does_it(self):
        from aletheia import quick, voice
        cmd = voice.interpret("can you remind me at 5 to call mom")["command"]
        self.assertEqual((cmd["kind"], cmd["text"]), ("remind_at", "call mom"))
        self.assertEqual(voice.interpret("could you add milk to the shopping list please")["command"],
                         {"kind": "shopping_add", "item": "milk"})
        self.assertIsNone(quick.answer("can you remind me at 5 to call mom"))

    def test_a_question_about_ability_is_still_one(self):
        from aletheia import quick, voice
        self.assertIn("can't spend", quick.answer("can you buy me a monitor"))
        self.assertEqual(voice._a_polite_ask("can you fly a helicopter"), "can you fly a helicopter")

    def test_an_embedded_question_is_the_question(self):
        from aletheia import quick
        self.assertEqual(quick.match("do you know what time it is")[0], "clock")
        self.assertEqual(quick.match("tell me the time")[0], "clock")
        self.assertEqual(quick.match("can you tell me how long my day is")[0], "day_span")



class ACorrectionLeadsWithAComma(unittest.TestCase):
    def test_no_comma_is_filler_and_a_bare_no_is_not(self):
        from aletheia import voice
        self.assertEqual(voice.interpret("no, add eggs")["command"], {"kind": "shopping_add", "item": "eggs"})
        self.assertEqual(voice._without_preamble("wait, cancel that"), "cancel that")
        self.assertEqual(voice._without_preamble("no"), "no")

    def test_would_you_remind_me_with_no_time_asks_when(self):
        from aletheia import voice
        self.assertIn("When should I remind you to call mom", voice.interpret("would you remind me to call mom")["say"])



class CorrectingWhatSheJustDid(unittest.TestCase):
    def _with(self, turns, said):
        from aletheia import converse, voice
        with mock.patch.object(converse, "recent", side_effect=lambda limit=4: turns[-limit:]):
            return voice.interpret(said)

    def test_make_that_renames_the_task_just_added(self):
        turns = [{"he_asked": "add a task to email sam", "she_answered": "Added a task: email sam."}]
        self.assertEqual(self._with(turns, "actually make that call sam")["command"],
                         {"kind": "task_change", "which": "email sam", "description": "call sam"})

    def test_make_it_15_after_a_timer_is_its_length(self):
        import datetime as dt
        turns = [{"he_asked": "set a timer for 10 minutes", "she_answered": "Timer set for 10 minutes."}]
        cmd = self._with(turns, "make it 15")["command"]
        self.assertEqual(cmd["text"], "your 15-minute timer is up")
        at = dt.datetime.fromisoformat(cmd["at"])
        self.assertLess(abs((at - dt.datetime.now(dt.timezone.utc)).total_seconds() - 900), 30)

    def test_sorry_i_meant_4pm_moves_the_reminder(self):
        turns = [{"he_asked": "remind me at 3pm to call the vet", "she_answered": "I'll remind you today at 3 pm: call the vet."}]
        cmd = self._with(turns, "sorry, i meant 4pm")["command"]
        self.assertEqual((cmd["kind"], cmd["text"], cmd.get("replaces")), ("remind_at", "call the vet", "call the vet"))
        self.assertIn("T16:00", cmd["at"])



class NoIMeantMilk(unittest.TestCase):
    def test_the_item_just_added_is_swapped(self):
        from aletheia import converse, voice
        turns = [{"he_asked": "add eggs to the shopping list", "she_answered": "Added to the shopping list: eggs."}]
        with mock.patch.object(converse, "recent", side_effect=lambda limit=4: turns[-limit:]):
            cmd = voice.interpret("no, i meant milk")["command"]
        self.assertEqual(cmd, {"kind": "shopping_add", "item": "milk", "replaces": "eggs"})

    def test_the_swap_takes_the_old_one_off(self):
        from aletheia import intercom
        calls = []
        real = intercom.execute_command

        def spy(cmd, fleet, *a, **k):
            if cmd["kind"] == "shopping_off":
                calls.append(cmd["item"])
                return "off"
            return real(cmd, fleet, *a, **k)
        with mock.patch.object(intercom, "execute_command", side_effect=spy), \
                mock.patch("aletheia.shopping.create", return_value={"need": "milk"}):
            said = real({"kind": "shopping_add", "item": "milk", "replaces": "eggs"}, {"repos": {}}, quote="test")
        self.assertEqual(calls, ["eggs"])
        self.assertEqual(said, "Swapped eggs for milk on the shopping list.")



class CancelItStepsOverAQuestion(unittest.TestCase):
    def test_the_hold_before_the_question_is_it(self):
        from aletheia import converse, policy, voice
        turns = [{"he_asked": "add a task to call sam", "she_answered": "Added a task: call sam."},
                 {"he_asked": "what's on my list", "she_answered": "1 thing on your list: call sam."}]
        with mock.patch.object(converse, "recent", side_effect=lambda limit=4: turns[-limit:]), \
                mock.patch.object(policy, "all_approvals", return_value=[]):
            self.assertTrue(voice._last_ask_is_undoable())
            self.assertEqual(voice.interpret("cancel it")["command"], {"kind": "undo"})

    def test_a_question_alone_is_not_undoable(self):
        from aletheia import converse, voice
        turns = [{"he_asked": "what's the weather", "she_answered": "Sunny."}]
        with mock.patch.object(converse, "recent", side_effect=lambda limit=4: turns[-limit:]):
            self.assertFalse(voice._last_ask_is_undoable())



class BlockingTimeForSomething(unittest.TestCase):
    def test_the_hold_is_called_what_it_is_for(self):
        from aletheia import voice
        cmd = voice.interpret("block out tomorrow morning for deep work")["command"]
        self.assertEqual((cmd["kind"], cmd["title"], cmd["minutes"]), ("calendar_hold", "Deep work", 180))
        self.assertIn("T09:00", cmd["start"])
        self.assertEqual(voice.interpret("block off friday")["command"]["minutes"], 480)



class AListCalledCostco(unittest.TestCase):
    def _with(self, turns, said):
        from aletheia import converse, voice
        with mock.patch.object(converse, "recent", side_effect=lambda limit=4: turns[-limit:]):
            return voice.interpret(said)

    def test_a_grocery_list_called_costco_is_a_named_list(self):
        from aletheia import lists, voice
        with mock.patch.object(lists, "is_named_list", return_value=True):
            self.assertEqual(voice.interpret("make a grocery list called costco")["command"],
                             {"kind": "list_new", "list": "costco"})

    def test_add_to_a_list_he_has_without_saying_list(self):
        from aletheia import lists
        with mock.patch.object(lists, "exists", side_effect=lambda n: n == "costco"):
            self.assertEqual(self._with([], "add paper towels to costco")["command"],
                             {"kind": "list_add", "list": "costco", "item": "paper towels"})

    def test_and_water_goes_on_it_and_a_meeting_does_not(self):
        turns = [{"he_asked": "add paper towels to costco", "she_answered": "Added to your costco list: paper towels."}]
        self.assertEqual(self._with(turns, "and water")["command"],
                         {"kind": "list_add", "list": "costco", "item": "water"})
        self.assertNotEqual((self._with(turns, "add a meeting to friday")["command"] or {}).get("kind"), "list_add")



class TheCalendarBackwards(unittest.TestCase):
    def test_a_date_some_days_ago(self):
        import datetime as dt
        from aletheia import localtime, quick
        then = dt.datetime.now(localtime.operator_tz()).date() - dt.timedelta(days=100)
        self.assertEqual(quick.answer("what was the date 100 days ago"),
                         f"{then.strftime('%A')} {then.day} {then.strftime('%B')} {then.year}.")

    def test_how_long_ago_and_daylight_saving(self):
        from aletheia import quick
        self.assertEqual(quick.match("how long ago was january 1"), ("days_since", "january 1"))
        self.assertEqual(quick.match("when is daylight saving")[0], "time_zone")



class AClockTimeInAnotherZone(unittest.TestCase):
    def test_us_zones_by_their_names(self):
        from aletheia import quick
        self.assertEqual(quick.answer("convert 3pm est to pst"), "3 pm EST is 12 pm PST.")
        self.assertEqual(quick.answer("11pm pacific to eastern"), "11 pm Pacific time is 2 am Eastern time, the next day.")

    def test_a_zone_she_does_not_know_goes_on(self):
        from aletheia import quick
        self.assertIsNone(quick.answer("convert 3pm to narnia"))



class FourMoreSums(unittest.TestCase):
    def test_each_is_worked_out(self):
        from aletheia import quick
        self.assertEqual(quick.answer("what percent is 30 of 120"), "25 percent.")
        self.assertEqual(quick.answer("what's 3/4 as a decimal"), "0.75.")
        self.assertEqual(quick.answer("what's 1994 in roman numerals"), "1,994 is MCMXCIV.")
        self.assertEqual(quick.answer("what's xiv in numbers"), "XIV is 14.")
        self.assertIn("178 centimeters", quick.answer("convert 5 feet 10 inches to cm"))
        self.assertEqual(quick.answer("average of 3 4 and 5"), "4.")



class APickUpIsAnErrand(unittest.TestCase):
    def test_a_prescription_tomorrow_is_a_task_not_groceries(self):
        from aletheia import voice
        cmd = voice.interpret("i need to pick up my prescription tomorrow")["command"]
        self.assertEqual((cmd["kind"], cmd["description"]), ("task_new", "pick up my prescription"))

    def test_batteries_tomorrow_go_on_the_list_without_the_day(self):
        from aletheia import voice
        self.assertEqual(voice.interpret("i need to buy batteries tomorrow")["command"],
                         {"kind": "shopping_add", "item": "batteries"})
        self.assertEqual(voice.interpret("we need eggs")["command"], {"kind": "shopping_add", "item": "eggs"})



class AnAppointmentToldNotAsked(unittest.TestCase):
    def test_i_have_a_dentist_appointment_is_a_hold(self):
        from aletheia import voice
        cmd = voice.interpret("i have a dentist appointment tuesday at 2")["command"]
        self.assertEqual((cmd["kind"], cmd["title"]), ("calendar_hold", "dentist appointment"))
        self.assertIn("T14:00", cmd["start"])
        self.assertNotEqual((voice.interpret("i have a cold")["command"] or {}).get("kind"), "calendar_hold")

    def test_remind_me_the_day_before_is_the_hold_just_made(self):
        import datetime as dt
        from aletheia import converse, localtime, voice
        start = (dt.datetime.now(localtime.operator_tz()) + dt.timedelta(days=3)).replace(hour=14, minute=0, second=0, microsecond=0)
        day = start.strftime("%A").lower()
        turns = [{"he_asked": f"i have a dentist appointment {day} at 2", "she_answered": "Pencilled in dentist appointment."}]
        with mock.patch.object(converse, "recent", side_effect=lambda limit=4: turns[-limit:]):
            cmd = voice.interpret("remind me the day before")["command"]
        at = dt.datetime.fromisoformat(cmd["at"])
        self.assertEqual((at.date(), at.hour), ((start - dt.timedelta(days=1)).date(), 9))
        self.assertTrue(cmd["text"].startswith("dentist appointment"))



class TheTalkAboutTheTalkIsSteppedOver(unittest.TestCase):
    THREAD = [{"you": "what's my next meeting", "her": "Nothing coming up."},
              {"you": "what time is it", "her": "4:47 am."},
              {"you": "thanks", "her": "Any time."},
              {"you": "what did i ask you earlier", "her": "You asked: what time is it."}]

    def test_earlier_first_and_again(self):
        from aletheia import converse, quick
        with mock.patch.object(converse, "_thread", return_value=self.THREAD):
            self.assertIn("what time is it", quick.answer("what did i ask you earlier"))
            self.assertIn("what's my next meeting", quick.answer("what was the first thing i asked you today"))
            self.assertEqual(quick.answer("say that again"), "I said: 4:47 am.")
            self.assertNotIn("thanks", quick.answer("what have we talked about"))



class TheWeekAhead(unittest.TestCase):
    PERIODS = [{"name": n, "isDaytime": d, "temperature": 60 + i, "shortForecast": f,
                "probabilityOfPrecipitation": {"value": 60 if "Rain" in f else 0}}
               for i, (n, d, f) in enumerate([("Today", True, "Sunny"), ("Tonight", False, "Clear"),
                                              ("Thursday", True, "Rain Likely"), ("Thursday Night", False, "Rain"),
                                              ("Friday", True, "Cloudy"), ("Friday Night", False, "Clear"),
                                              ("Saturday", True, "Sunny")])]

    def test_this_week_reads_the_days_ahead(self):
        from aletheia import quick, weather
        with mock.patch.object(weather, "forecast", return_value={"periods": self.PERIODS, "place": "Chicago"}):
            said = quick.answer("what's the weather this week")
            self.assertIn("Thursday: Rain Likely", said)
            self.assertIn("Saturday", said)
            self.assertTrue(quick.answer("will it rain this week").startswith("Looks like it"))



class PricesOnAMarketAreLookedUp(unittest.TestCase):
    def test_market_stock_and_coin(self):
        from aletheia import voice
        ask = lambda said: voice.interpret(said)["command"]
        self.assertEqual(ask("how's the stock market"), {"kind": "research", "question": "stock market today"})
        self.assertEqual(ask("how's apple stock"), {"kind": "research", "question": "apple stock price today"})
        self.assertEqual(ask("what's the price of gold"), {"kind": "research", "question": "gold price today"})
        self.assertNotEqual(ask("what's the price of milk").get("question"), "milk stock price today")



class DidITakeMyMedicine(unittest.TestCase):
    def test_taking_it_is_a_note_and_the_question_reads_today(self):
        import datetime as dt
        from aletheia import quick, voice
        self.assertEqual(voice.interpret("i took my medicine")["command"], {"kind": "note", "text": "took my medicine"})
        now = dt.datetime.now(dt.timezone.utc)
        with mock.patch.object(quick, "_notes", return_value=[{"text": "took my medicine", "ts": now.isoformat()}]):
            self.assertTrue(quick.answer("did i take my meds today").startswith("Yes"))
        old = (now - dt.timedelta(days=2)).isoformat()
        with mock.patch.object(quick, "_notes", return_value=[{"text": "took my medicine", "ts": old}]):
            self.assertTrue(quick.answer("did i take my medicine").startswith("Not that you've told me today"))
        with mock.patch.object(quick, "_notes", return_value=[]):
            self.assertIn("haven't told me", quick.answer("did i take my vitamins"))

    def test_any_alarms_is_the_reminders_not_a_file(self):
        from aletheia import voice
        self.assertEqual(voice.interpret("do i have any alarms")["command"]["kind"], "reminders")



class FeelingAndPriorities(unittest.TestCase):
    def test_im_feeling_and_help_me_prioritize(self):
        from aletheia import quick
        self.assertEqual(quick.match("i'm feeling overwhelmed")[0], "feeling")
        self.assertEqual(quick.match("help me prioritize")[0], "focus")
        self.assertEqual(quick.match("what can i do in 30 minutes")[0], "focus")



class DaysHeToldHerAbout(unittest.TestCase):
    NOTES = [{"text": "my anniversary is june 10"}, {"text": "Ana's birthday is may 2"}, {"text": "my wife's name is Ana"}]

    def test_how_long_until_reads_his_notes(self):
        from aletheia import quick
        with mock.patch.object(quick, "_notes", return_value=self.NOTES):
            self.assertIn("10 June", quick.answer("how long until our anniversary"))
            self.assertIn("2 May", quick.answer("how many days until my wife's birthday"))
            self.assertIsNone(quick.answer("how long until the wedding"))

    def test_remind_me_on_that_day(self):
        from aletheia import quick, voice
        with mock.patch.object(quick, "_notes", return_value=self.NOTES):
            cmd = voice.interpret("remind me to book dinner on our anniversary")["command"]
            self.assertEqual((cmd["kind"], cmd["text"]), ("remind_at", "book dinner"))
            self.assertIn("-06-10T09:00", cmd["at"])
            self.assertIn("your dad's birthday", voice.interpret("remind me to call dad on his birthday")["say"])


if __name__ == "__main__":
    unittest.main()
