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


if __name__ == "__main__":
    unittest.main()
