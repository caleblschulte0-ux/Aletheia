"""The headlines, "read my email", a when with no what, and calendar moves.

2026-10-07, every model off:

    > what's the news                        -> the planner (no way to know it)
    > read my email                          -> an email from somebody called "my"
    > what's my schedule look like           -> the planner
    > remind me tomorrow                     -> the planner
    > move my dentist appointment to friday  -> the planner (no door to his calendar's events)
"""
import unittest
from unittest import mock

from aletheia import news, quick, voice

RSS = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>NPR</title>
<item><title>Storm reaches the coast</title></item>
<item><title>Markets close higher.</title></item>
<item><title>Council votes on the budget</title></item>
<item><title>A fourth story</title></item>
</channel></rss>"""

ATOM = b"""<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"><title>Wire</title>
<entry><title>Storm reaches the coast</title></entry>
<entry><title>Bridge reopens</title></entry>
</feed>"""

FEEDS = [{"name": "NPR", "url": "https://example.org/npr.xml", "take": 3},
         {"name": "the Wire", "url": "https://example.org/wire.xml", "take": 3}]


class TheHeadlines(unittest.TestCase):
    def fetch(self, url):
        return RSS if "npr" in url else ATOM

    def test_rss_and_atom_titles_in_feed_order(self):
        self.assertEqual(news.parse(RSS)[:2], ["Storm reaches the coast", "Markets close higher"])
        self.assertEqual(news.parse(ATOM), ["Storm reaches the coast", "Bridge reopens"])

    def test_a_document_that_declares_entities_is_refused(self):
        bomb = b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]><rss><channel><item><title>&a;</title></item></channel></rss>'
        self.assertEqual(news.parse(bomb), [])
        self.assertEqual(news.parse(b"not xml at all"), [])

    def test_each_headline_is_said_with_its_source_and_never_twice(self):
        with mock.patch.object(news, "feeds", return_value=FEEDS):
            said = news.spoken(fetch=self.fetch)
        self.assertTrue(said.startswith("Here are the headlines."), said)
        self.assertIn("From NPR: Storm reaches the coast; Markets close higher; Council votes on the budget.", said)
        self.assertIn("From the Wire: Bridge reopens.", said)
        self.assertEqual(said.count("Storm reaches the coast"), 1)
        self.assertNotIn("A fourth story", said)

    def test_one_feed_down_is_not_the_news_down(self):
        def fetch(url):
            if "npr" in url:
                raise OSError("unreachable")
            return ATOM
        with mock.patch.object(news, "feeds", return_value=FEEDS):
            self.assertIn("Bridge reopens", news.spoken(fetch=fetch))

    def test_every_feed_down_says_so_plainly(self):
        def fetch(url):
            raise OSError("unreachable")
        with mock.patch.object(news, "feeds", return_value=FEEDS):
            said = news.spoken(fetch=fetch)
        self.assertIn("couldn't reach any of the news feeds", said)
        self.assertNotIn("OSError", said)

    def test_no_sources_says_so(self):
        with mock.patch.object(news, "feeds", return_value=[]):
            self.assertIn("don't have any news sources", news.spoken(fresh=True))

    def test_the_feed_list_is_data_and_https_only(self):
        rows = news.feeds()
        self.assertTrue(rows)
        self.assertTrue(all(r["url"].startswith("https://") for r in rows))

    def test_the_ways_he_asks(self):
        for said in ("what's the news", "tell me the news", "what's in the news", "read me the headlines",
                     "what are the top headlines", "what's happening in the world today", "any news today"):
            with self.subTest(said=said):
                self.assertEqual((quick.match(said) or ("",))[0], "news")
        # News about one of his own things is not the headlines.
        self.assertNotEqual((quick.match("any news on the stripe job") or ("",))[0], "news")


class HisInbox(unittest.TestCase):
    def test_read_my_email_is_the_inbox(self):
        for said in ("read my email", "read my mail", "read me my email"):
            with self.subTest(said=said):
                self.assertEqual(voice._interpret(said)["command"], {"kind": "email_check"})

    def test_a_named_sender_is_still_that_sender(self):
        self.assertEqual(voice._interpret("read me the stripe email")["command"],
                         {"kind": "email_read", "which": "stripe"})


class HisSchedule(unittest.TestCase):
    def test_what_my_schedule_looks_like(self):
        self.assertEqual(quick.match("what's my schedule look like"), ("agenda", ""))
        self.assertEqual(quick.match("what does my calendar look like tomorrow"), ("agenda", "tomorrow"))


class AWhenWithNoWhat(unittest.TestCase):
    def test_she_asks_for_the_what_with_his_when(self):
        for said, when in (("remind me tomorrow", "tomorrow"), ("remind me at 3", "at 3"),
                           ("remind me on friday", "on friday")):
            with self.subTest(said=said):
                got = voice._interpret(said)
                self.assertIsNone(got["command"])
                self.assertIn(f'"remind me {when} to', got["say"])

    def test_remind_me_later_is_still_a_snooze(self):
        self.assertEqual(voice._interpret("remind me later")["command"]["kind"], "notify_snooze")


class MovingACalendarEvent(unittest.TestCase):
    def test_said_plainly(self):
        with mock.patch.object(voice, "_names_one_open_task", return_value=False):
            for said in ("move my dentist appointment to friday", "move my 3pm to 4",
                         "reschedule my meeting with dana to monday"):
                with self.subTest(said=said):
                    got = voice._interpret(said)
                    self.assertIsNone(got["command"])
                    self.assertIn("can't move things on your calendar", got["say"])

    def test_a_task_of_his_by_that_name_is_still_the_task(self):
        with mock.patch.object(voice, "_names_one_open_task", return_value=True):
            got = voice._interpret("move my dentist appointment to friday")
        self.assertNotIn("can't move things", got.get("say") or "")


if __name__ == "__main__":
    unittest.main()


class TheSmallerOnes(unittest.TestCase):
    """Same pass: each went to the planner with every model off."""

    def test_clear_my_shopping_list(self):
        for said in ("clear my shopping list", "empty the grocery list"):
            with self.subTest(said=said):
                self.assertEqual(voice._interpret(said)["command"], {"kind": "shopping_off", "item": "everything"})

    def test_a_message_with_no_words_asks_for_them(self):
        for said, who in (("send a message to dana", "Dana"), ("text sam", "Sam"), ("send mom a text", "Mom")):
            with self.subTest(said=said):
                got = voice._interpret(said)
                self.assertIsNone(got["command"])
                self.assertIn(f'"text {who} that', got["say"])
        for said in ("send it", "send money", "text bob happy birthday"):
            with self.subTest(said=said):
                self.assertNotIn("What should it say", voice._interpret(said).get("say") or "")

    def test_how_are_you_today_and_the_next_birthday_and_time_left(self):
        self.assertEqual(quick.match("how are you doing today")[0], "greeting")
        self.assertEqual(quick.match("when is my next birthday")[0], "birthday")
        self.assertEqual(quick.match("how much time is left")[0], "timer_left")


class WhatHeAsksAfter(unittest.TestCase):
    """Same pass, the second half."""

    def test_the_ways_he_asks_what_she_did(self):
        for said in ("what did you do while i was gone", "what have you been up to"):
            with self.subTest(said=said):
                self.assertEqual(quick.match(said)[0], "today")

    def test_his_cpu_his_notes_and_his_allergies(self):
        self.assertEqual(quick.match("what's my cpu at")[0], "cpu")
        self.assertEqual(quick.match("what did i write down")[0], "notes_list")
        self.assertEqual(quick.match("what am i allergic to"), ("recall", "allergic"))

    def test_a_note_written(self):
        self.assertEqual(voice._interpret("write a note that the car needs oil")["command"],
                         {"kind": "note", "text": "the car needs oil"})

    def test_every_note_at_once_is_not_one_sentence(self):
        got = voice._interpret("delete all my notes")
        self.assertIsNone(got["command"])
        self.assertIn("one at a time", got["say"])

    def test_a_project_the_pulse_does_not_name_is_its_charter(self):
        from aletheia import current_state
        with mock.patch.object(current_state, "repo_words", return_value=None), \
                mock.patch.object(quick, "_project_next", return_value="Next on Barkly, and it's mine: ship it."):
            self.assertEqual(quick.answer("what's new with barkly"), "Next on Barkly, and it's mine: ship it.")


class TheWrongVerbAndTheWrongHour(unittest.TestCase):
    """Fluent and wrong, the failure he cannot detect (2026-10-07)."""

    def test_flights_and_a_time_for_lunch_are_not_files(self):
        self.assertNotEqual(voice._interpret("search for cheap flights to denver")["command"]["kind"], "file_find")
        self.assertEqual(voice._interpret("find a time for lunch with sam this week")["command"],
                         {"kind": "calendar_find_free", "when": "this week", "purpose": "lunch with sam"})
        self.assertEqual(voice._interpret("find my resume")["command"]["kind"], "file_find")

    def test_a_bare_hour_every_day_is_not_the_small_hours(self):
        for said, hhmm in (("remind me to take my pills every night at 10", "22:00"),
                           ("remind me every night at 10 to take my pills", "22:00"),
                           ("remind me to drink water every day at 3", "15:00"),
                           ("remind me every morning to stretch", "09:00"),
                           ("remind me to stretch every morning at 7", "07:00")):
            with self.subTest(said=said):
                self.assertEqual(voice._interpret(said)["command"]["time"], hhmm)

    def test_the_high_and_when_it_gets_dark(self):
        self.assertEqual(quick.match("what's the high today"), ("weather", "today"))
        self.assertEqual(quick.match("when does it get dark")[0], "sun")


class TheItHeJustHeard(unittest.TestCase):
    """"Cancel it" and "what's on it" mean what she just said (2026-10-07)."""

    def turn(self, said, answered):
        return mock.patch("aletheia.converse.recent",
                          return_value=[{"at": "", "he_asked": said, "she_answered": answered}])

    def test_cancel_it_after_one_reminder_was_read_out(self):
        with self.turn("what reminders do i have", "1 reminder: call the vet — today at 5 pm."), \
                mock.patch("aletheia.policy.all_approvals", return_value=[]), \
                mock.patch.object(voice, "_last_ask_is_undoable", return_value=False):
            self.assertEqual(voice._interpret("cancel it")["command"],
                             {"kind": "reminder_off", "which": "call the vet"})

    def test_whats_on_it_after_the_shopping_list(self):
        with self.turn("take the eggs off", "Took it off your shopping list: eggs."):
            self.assertEqual(voice._interpret("what's on it")["command"], {"kind": "shopping_list"})
        with self.turn("add socks to my packing list", "Added to your packing list: socks."):
            self.assertEqual(voice._interpret("what's on it")["command"], {"kind": "list_read", "list": "packing"})
