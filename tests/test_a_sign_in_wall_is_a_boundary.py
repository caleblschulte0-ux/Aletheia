"""Live 2026-09-23, a pursuit pass on AlphaSense: the model wrote two
addresses joined by "or" in a look move's url, the browser walked the whole
string, landed on LinkedIn's sign-in form, and "Sign in ... Email or phone
... Password ... Join now" was kept as evidence about the employer. A wall
is a boundary she states herself, never a page's words kept as facts."""
import datetime as dt
import unittest
from unittest import mock

from aletheia import pursuit
from tests.test_pursuit import PursuitCase

NOW = dt.datetime(2026, 9, 23, 7, 0, tzinfo=dt.timezone.utc)

LINKEDIN_WALL = {
    "url": "https://www.linkedin.com/uas/login?session_redirect=https%3A%2F%2Fwww.linkedin.com%2Fcompany%2Falphasense%2F",
    "title": "LinkedIn Login, Sign in | LinkedIn",
    "text": "Sign in\n\nNew to LinkedIn?\n\nJoin now\nSign in with Microsoft\n\nEmail or phone\nPassword\nForgot password?\n\nKeep me signed in\n\nSign in",
}
CAREERS_PAGE = {
    "url": "https://www.alphasense.com/careers",
    "title": "Careers at AlphaSense",
    "text": ("We are hiring across sales and customer success. " * 40)
            + "Already applied? Sign in to check your application status. Your password is never shared.",
}


class AWallIsToldFromAPage(unittest.TestCase):
    def test_linkedins_login_form_is_a_wall(self):
        said = pursuit.sign_in_wall("https://www.linkedin.com/company/alphasense/", LINKEDIN_WALL)
        self.assertIn("www.linkedin.com wants a sign-in", said)
        self.assertNotIn("Email or phone", said)

    def test_a_login_path_alone_is_a_wall(self):
        said = pursuit.sign_in_wall("https://x.com/login", {"url": "https://x.com/login", "title": "X", "text": "hello"})
        self.assertTrue(said)

    def test_a_careers_page_that_mentions_signing_in_is_still_a_page(self):
        self.assertEqual(pursuit.sign_in_wall("https://www.alphasense.com/careers", CAREERS_PAGE), "")

    def test_a_short_form_with_a_password_box_is_a_wall_whatever_its_title(self):
        page = {"url": "https://portal.example.com/", "title": "Portal",
                "text": "Welcome back\nEmail\nPassword\nLog in\nForgot your password?"}
        self.assertTrue(pursuit.sign_in_wall("https://portal.example.com/", page))


class TheLookKeepsABoundaryNotTheForm(unittest.TestCase):
    def test_the_wall_is_evidence_of_a_boundary_and_the_forms_words_are_not_kept(self):
        record = {"evidence": [], "subject": {"name": "AlphaSense"}}
        move = {"kind": "look", "detail": {"url": "https://www.linkedin.com/company/alphasense/", "query": ""}}
        with mock.patch("aletheia.browse.read_page", return_value=LINKEDIN_WALL):
            out = pursuit._do_look(record, move, NOW)
        self.assertEqual(out["state"], "done", "done, so the address joins never_repeat")
        self.assertEqual(len(record["evidence"]), 1)
        row = record["evidence"][0]
        self.assertEqual(row["kind"], "boundary")
        self.assertEqual(row["provenance"], pursuit.TRUSTED)
        self.assertIn("wants a sign-in", row["text"])
        self.assertNotIn("Join now", row["text"])
        self.assertIn("boundary", out["effect"])

    def test_a_real_page_is_kept_as_before(self):
        record = {"evidence": [], "subject": {"name": "AlphaSense"}}
        move = {"kind": "look", "detail": {"url": "https://www.alphasense.com/careers", "query": ""}}
        with mock.patch("aletheia.browse.read_page", return_value=CAREERS_PAGE):
            out = pursuit._do_look(record, move, NOW)
        self.assertEqual(record["evidence"][0]["kind"], "looked")
        self.assertEqual(record["evidence"][0]["provenance"], pursuit.UNTRUSTED)
        self.assertIn("kept what it said", out["effect"])


class OneAddressPerLook(PursuitCase):
    def test_two_addresses_joined_by_or_become_the_first(self):
        record = self.opportunity()
        eid = record["evidence"][0]["id"]
        clean, dropped = pursuit.validate(
            {"moves": [{"kind": "look", "why": "to find the hiring manager", "cites": [eid],
                        "detail": {"url": "https://www.linkedin.com/company/alphasense/ or https://www.alphasense.com/careers",
                                   "question": "who hires"}}]}, record)
        self.assertEqual(len(clean["moves"]), 1, dropped)
        self.assertEqual(clean["moves"][0]["detail"]["url"], "https://www.linkedin.com/company/alphasense/")


if __name__ == "__main__":
    unittest.main()
