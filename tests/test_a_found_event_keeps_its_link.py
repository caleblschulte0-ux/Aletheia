"""A hold made from a listing kept no address to sign up on, and a hold she took back stayed in what
the task found (his PC, 2026-10-11)."""

import unittest
from unittest import mock

from aletheia import program_run, programs, research


class AFoundEventKeepsItsLink(unittest.TestCase):
    LINKS = [{"text": "Tails on the Trail - WWE South Dakota", "href": "https://example.org/e/tails-on-the-trail"},
             {"text": "Browse events", "href": "https://example.org/events"},
             {"text": "Trail running club", "href": "https://example.org/e/trail-club"}]

    def test_the_link_whose_words_are_the_title_is_the_events(self):
        self.assertEqual(research.event_link("WWE South Dakota: Tails on the Trail", self.LINKS,
                                             "https://example.org/events"),
                         "https://example.org/e/tails-on-the-trail")

    def test_no_link_is_better_than_a_near_one(self):
        self.assertEqual(research.event_link("Sioux Falls Fall Job Fair", self.LINKS), "")
        self.assertEqual(research.event_link("Trail", self.LINKS), "")

    def test_a_dated_line_carries_the_link(self):
        page = {"url": "https://example.org/events", "links": self.LINKS,
                "full": "WWE South Dakota: Tails on the Trail\nSaturday, October 24, 2099 at 9:00 AM\n"}
        lines = research.dated_lines([page])
        self.assertTrue(lines, lines)
        self.assertIn("(link https://example.org/e/tails-on-the-trail)", lines[0])

    def test_a_hold_taken_back_leaves_what_was_found(self):
        said = ("Pencilled in Hold Friday at 10 for the tour Friday, October 6 at 10 am, tentative / "
                "Pencilled in WWE South Dakota: Tails on the Trail Saturday, October 24 at 9 am, tentative")
        kept = programs.without_taken_back(said, {"Hold Friday at 10 for the tour"})
        self.assertNotIn("for the tour", kept)
        self.assertIn("Tails on the Trail", kept)

    def test_the_sign_up_takes_the_link_of_what_was_pencilled_in(self):
        record = {"tasks": [
            {"key": "a1-1", "from_activity": "a1", "state": "DONE", "results": [
                {"outcome": "ok", "at": "2026-10-11T17:00:00Z", "said":
                 "Found two. Dated: Sioux Falls Fall Job Fair, Oct 17 at 6 pm (link https://example.org/e/fair); "
                 "WWE South Dakota: Tails on the Trail, Saturday, October 24 at 9:00 AM "
                 "(link https://example.org/e/tails-on-the-trail)."}]},
            {"key": "t3", "state": "DONE", "needs": [], "results": [
                {"outcome": "ok", "at": "2026-10-11T18:00:00Z",
                 "said": "Pencilled in WWE South Dakota: Tails on the Trail Saturday, October 24 at 9 am, tentative"}]},
            {"key": "t4", "state": "READY", "needs": ["t3"], "results": []}]}
        with mock.patch.object(programs, "taken_back_titles", return_value=set()):
            self.assertEqual(program_run._held_event_link(record, record["tasks"][2]),
                             "https://example.org/e/tails-on-the-trail")
        with mock.patch.object(programs, "taken_back_titles",
                               return_value={"WWE South Dakota: Tails on the Trail"}):
            self.assertEqual(program_run._held_event_link(record, record["tasks"][2]), "")


if __name__ == "__main__":
    unittest.main()
