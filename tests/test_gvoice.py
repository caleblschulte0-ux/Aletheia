"""Reading his texts — and the three things that must not slip.

The signup number is a Google Voice line, and half of what she signs up
for sends its code by TEXT. Until now she could read the inbox and not the
messages, so an account got as far as "we sent you a code" and stopped.

  * a stale code is refused, because typing one fails in a way that reads
    like a broken form;
  * a login screen is "not signed in", never "no messages";
  * she reads and never replies.

Every browser call is stubbed. This module's whole job is talking to a
page, and a suite that reaches the network answers differently on a train.
"""
from __future__ import annotations

import datetime as dt
import unittest
from unittest import mock

from aletheia import gvoice


SIGNED_OUT = ("Sign in to continue to Google Voice\nUse your Google Account\n"
              "Forgot email?")

PAGE = """Messages
(605) 555-0134
284913 is your Workday verification code
10:42 AM
Google
G-839201 is your Google verification code. Do not share it.
10:39 AM
Mom
call me when you get a chance
Yesterday
"""


def reader_for(text):
    def read(url, *a, **kw):
        return {"url": url, "title": "Google Voice", "text": text, "links": []}
    return read


class FindingTheCodeInAText(unittest.TestCase):
    REAL = {
        "Your verification code is 284913": "284913",
        "G-839201 is your Google verification code.": "839201",
        "284913 is your Workday verification code": "284913",
        "Use code 44821 to verify your phone": "44821",
        "Your one-time passcode: 913022": "913022",
        "Indeed: your code is 5821": "5821",
        "Enter code 662901 to finish signing up": "662901",
    }

    def test_every_real_shape_is_read(self):
        """The email extractor caught one of these six when measured. An
        email says 'paste this code into the security field: ApHIj2MW'; a
        text says '284913 is your code'. Different grammar."""
        for text, want in self.REAL.items():
            with self.subTest(text=text):
                self.assertEqual(gvoice.code_in_text(text), want)

    def test_a_number_that_is_not_a_code_is_refused(self):
        for text in ("Your order from 2024 shipped",
                     "Your total is $284.91 thanks",
                     "See you at 10:42 tomorrow",
                     "Hey are you around"):
            with self.subTest(text=text):
                self.assertEqual(gvoice.code_in_text(text), "")

    def test_empty_text_is_no_code_not_a_crash(self):
        for text in ("", None, "   "):
            self.assertEqual(gvoice.code_in_text(text), "")

    def test_the_email_extractor_is_asked_first(self):
        """So a message both can read is read the same way by both, and
        they cannot drift apart on the overlap."""
        seen = []

        def fake(text):
            seen.append(text)
            return "FROMEMAIL"
        with mock.patch("aletheia.apply_run.code_in", fake):
            self.assertEqual(gvoice.code_in_text("anything at all"), "FROMEMAIL")
        self.assertEqual(seen, ["anything at all"])

    def test_the_sms_shapes_still_work_if_the_email_one_raises(self):
        def boom(text):
            raise RuntimeError("mail module is unhappy")
        with mock.patch("aletheia.apply_run.code_in", boom):
            self.assertEqual(gvoice.code_in_text("your code is 5821"), "5821")


class ReadingThePage(unittest.TestCase):
    def test_messages_are_parsed_into_rows(self):
        rows = gvoice.messages_in(PAGE)
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0]["from"], "(605) 555-0134")
        self.assertEqual(rows[0]["code"], "284913")
        self.assertEqual(rows[0]["when"], "10:42 AM")

    def test_a_message_with_no_code_carries_no_code(self):
        rows = gvoice.messages_in(PAGE)
        mom = next(r for r in rows if r["from"] == "Mom")
        self.assertEqual(mom["code"], "")

    def test_an_unreadable_page_is_no_rows_not_a_crash(self):
        self.assertEqual(gvoice.messages_in("some entirely different layout"), [])
        self.assertEqual(gvoice.messages_in(""), [])


class ASignedOutPageIsNotAnEmptyInbox(unittest.TestCase):
    """The failure that would have been worst: looking at a login screen
    and reporting 'no code' forever while the code sat on his screen."""

    def test_a_login_screen_says_not_signed_in(self):
        state, why = gvoice.check(reader=reader_for(SIGNED_OUT))
        self.assertEqual(state, gvoice.NOT_SIGNED_IN)
        self.assertIn("sign in", why.lower())

    def test_a_real_page_is_ok(self):
        state, _ = gvoice.check(reader=reader_for(PAGE))
        self.assertEqual(state, gvoice.OK)

    def test_recent_refuses_rather_than_returning_nothing(self):
        with self.assertRaises(RuntimeError):
            gvoice.recent(reader=reader_for(SIGNED_OUT))

    def test_a_browser_that_will_not_open_says_so(self):
        def boom(url, *a, **kw):
            raise RuntimeError("no browser here")
        state, why = gvoice.check(reader=boom)
        self.assertEqual(state, gvoice.NO_BROWSER)
        self.assertIn("Google Voice", why)


class AStaleCodeIsRefused(unittest.TestCase):
    """2026-09-12, on the mail path: she typed an hour-old code into the
    box and the form said no, and it read like a broken form rather than a
    stale code."""

    NOW = dt.datetime(2026, 9, 13, 10, 45)

    def _codes(self, reader):
        with mock.patch.object(gvoice.journal, "append", lambda *a, **k: None):
            return gvoice.latest_code(reader=reader, now=self.NOW)

    def test_a_fresh_code_is_returned(self):
        found = self._codes(reader_for(PAGE))
        self.assertEqual(found["code"], "284913")
        self.assertLess(found["age_s"], gvoice.MAX_CODE_AGE_S)

    def test_the_newest_fresh_code_wins(self):
        """Two codes three minutes apart: the one that just arrived is the
        one the form is waiting for."""
        found = self._codes(reader_for(PAGE))
        self.assertEqual(found["when"], "10:42 AM")

    def test_an_hour_old_code_is_not_used(self):
        old = PAGE.replace("10:42 AM", "9:15 AM").replace("10:39 AM", "9:10 AM")
        self.assertIsNone(self._codes(reader_for(old)))

    def test_yesterdays_code_is_not_used(self):
        old = PAGE.replace("10:42 AM", "Yesterday").replace("10:39 AM", "Yesterday")
        self.assertIsNone(self._codes(reader_for(old)))

    def test_a_code_she_cannot_date_is_refused(self):
        """Unreadable is not fresh. Guessing here types an expired code."""
        self.assertIsNone(gvoice._age_seconds("sometime"))
        self.assertIsNone(gvoice._age_seconds(""))

    def test_a_time_later_than_now_was_yesterday(self):
        """11:50 PM read at 10:45 AM is last night, not eleven hours from
        now — and it must not come out as a negative age that sorts first."""
        age = gvoice._age_seconds("11:50 PM", now=self.NOW)
        self.assertGreater(age, 0)
        self.assertGreater(age, gvoice.MAX_CODE_AGE_S)

    def test_no_code_at_all_is_none(self):
        page = "Messages\nMom\ncall me back\n10:44 AM\n"
        self.assertIsNone(self._codes(reader_for(page)))


class SheReadsAndNeverReplies(unittest.TestCase):
    def test_nothing_here_sends_a_text(self):
        """Reading his messages is already a large thing to be able to do.
        Sending as him is a different capability with a different risk."""
        import ast
        with open("aletheia/gvoice.py", encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                base = getattr(node.func.value, "id", "")
                # read_page and available are the read-only door. Anything
                # else on browse can act on a page.
                if base == "browse" and node.func.attr not in ("read_page",
                                                               "available"):
                    self.fail(f"gvoice calls browse.{node.func.attr}")
                if node.func.attr in ("interact", "send", "reply", "click",
                                      "fill", "press", "type"):
                    self.fail(f"gvoice calls {base}.{node.func.attr}")

    def test_it_only_ever_opens_the_messages_page(self):
        asked = []
        gvoice.check(reader=lambda url, *a, **kw: (
            asked.append(url), {"text": PAGE})[1])
        self.assertEqual(asked, [gvoice.MESSAGES_URL])


if __name__ == "__main__":
    unittest.main()
