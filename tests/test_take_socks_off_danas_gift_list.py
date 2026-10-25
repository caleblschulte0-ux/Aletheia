"""Two sentences that fell to the planner with every model off (2026-10-25):
"take socks off Dana's gift list" never came off, and "my flight to Denver
is at 6am Friday" / "I have a flight tomorrow at 7" were never kept."""
import datetime as dt
import unittest
from unittest import mock

from aletheia import localtime, voice


class OffAGiftListByWhoseItIs(unittest.TestCase):
    def test_the_line_saved_for_that_person_comes_off(self):
        for said, item in (("take socks off Dana's gift list", "socks for Dana"),
                           ("remove the socks from Dana's gift list", "the socks for Dana"),
                           ("cross socks off my gift list for my sister", "socks for my sister"),
                           ("delete socks from the gift list for Dana", "socks for Dana")):
            self.assertEqual(voice._interpret(said)["command"],
                             {"kind": "list_off", "list": "gift", "item": item}, said)

    def test_it_is_not_an_item(self):
        got = (voice._interpret("take it off Dana's gift list") or {}).get("command") or {}
        self.assertNotEqual(got.get("kind"), "list_off")

    def test_it_comes_off_the_store_and_the_other_idea_stays(self):
        from aletheia import lists
        store = {}
        with mock.patch.object(lists, "_load", lambda name, deleted=False: store.get(name)), \
                mock.patch.object(lists, "write_json_atomic", lambda path, held: store.__setitem__("gift", held)):
            store["gift"] = {"name": "gift", "items": [{"text": "socks for Dana"}, {"text": "a scarf for Dana"}]}
            taken, why = lists.take_off("gift", "socks for Dana")
        self.assertEqual(taken, ["socks for Dana"], why)
        self.assertEqual([i["text"] for i in store["gift"]["items"] if not i.get("done")], ["a scarf for Dana"])


class AFlightToSomewhere(unittest.TestCase):
    def test_a_destination_and_a_weekday_are_kept(self):
        self.assertEqual(voice._interpret("my flight to Denver is at 6am Friday")["command"],
                         {"kind": "note", "text": "my flight to Denver is at 6am Friday"})
        self.assertEqual(voice._interpret("I have a flight to Denver friday at 6am")["command"],
                         {"kind": "note", "text": "my flight to Denver is friday at 6am"})
        self.assertEqual(voice._interpret("I have a flight at 6am on Friday")["command"],
                         {"kind": "note", "text": "my flight is at 6am on Friday"})

    def test_tomorrow_is_written_down_as_its_date(self):
        with mock.patch.object(localtime, "today", return_value=dt.date(2026, 10, 25)):
            self.assertEqual(voice._interpret("I have a flight tomorrow at 7")["command"],
                             {"kind": "note", "text": "my flight is October 26 at 7"})
            self.assertEqual(voice._interpret("I have a flight to Denver tomorrow morning at 6am")["command"],
                             {"kind": "note", "text": "my flight to Denver is October 26 at 6am"})
            self.assertEqual(voice._interpret("i have a flight tomorrow morning")["command"],
                             {"kind": "note", "text": "my flight is October 26 in the morning"})

    def test_news_about_a_flight_is_still_not_its_time(self):
        got = (voice._interpret("my flight to Denver is delayed") or {}).get("command") or {}
        self.assertNotEqual(got.get("kind"), "note")


if __name__ == "__main__":
    unittest.main()
