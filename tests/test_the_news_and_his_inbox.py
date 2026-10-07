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
