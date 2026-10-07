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
            self.assertEqual(voice._interpret("delete the packing list")["command"],
                             {"kind": "list_off", "list": "packing", "item": "everything"})


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
        self.assertEqual(voice._interpret("what's my mom's number")["command"], {"kind": "contacts", "which": "my mom"})
        with mock.patch.object(quick, "_notes", return_value=[{"text": "my locker is 42"}]):
            self.assertEqual(quick.answer("what's my locker number"), "You told me: my locker is 42.")

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


if __name__ == "__main__":
    unittest.main()
