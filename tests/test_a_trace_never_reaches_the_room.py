"""A Playwright stack trace, read out loud.

    > read nonexistent-site-xyzabc.com
      That failed: Page.goto: net::ERR_NAME_NOT_RESOLVED at
      https://nonexistent-site-xyzabc.com/ Call log: navigating to
      "https://nonexistent-site-xyzabc.com/", waiting until
      "domcontentloaded"

CLAUDE.md names this defect, and `browse.reachable` carries a comment
describing that exact string - because it was fixed THERE and nowhere
else. `_network_reason` had been in the module the whole time: it cuts
the "Call log:" tail, maps the net:: code to English, and keeps the code
in brackets for the screen. Every other `page.goto` called Playwright
raw.

Two rules, and they are different rules:

  say it in English WHERE IT IS RAISED  -> `browse._load`
  take the code out FOR SPEECH          -> `speech.plainly`

The code is worth writing down - ERR_NAME_NOT_RESOLVED and
ERR_CONNECTION_RESET have different fixes - and worth never saying.
"""
from __future__ import annotations

import unittest
from unittest import mock

from aletheia import browse, speech


class WhereItIsRaisedCase(unittest.TestCase):
    def test_a_failed_load_says_english(self):
        page = mock.Mock()
        page.goto.side_effect = RuntimeError(
            'Page.goto: net::ERR_NAME_NOT_RESOLVED at https://nope.example/ '
            'Call log: navigating to "https://nope.example/"')
        with self.assertRaises(browse.BrowseError) as caught:
            browse._load(page, "https://nope.example/")
        said = str(caught.exception)
        self.assertIn("the address did not resolve", said)
        self.assertNotIn("Call log", said)
        self.assertNotIn("Page.goto", said)

    def test_the_code_is_kept_for_the_log(self):
        """Different codes have different fixes; the log wants them."""
        page = mock.Mock()
        page.goto.side_effect = RuntimeError(
            "Page.goto: net::ERR_CONNECTION_RESET at https://x/ Call log: x")
        with self.assertRaises(browse.BrowseError) as caught:
            browse._load(page, "https://x/")
        self.assertIn("net::ERR_CONNECTION_RESET", str(caught.exception))
        self.assertIn("the connection was reset", str(caught.exception))

    def test_a_closed_browser_is_still_the_benign_error(self):
        """Not every exception is a network failure worth rewording."""
        page = mock.Mock()
        page.goto.side_effect = RuntimeError(
            "Target page, context or browser has been closed")
        with self.assertRaises(RuntimeError) as caught:
            browse._load(page, "https://x/")
        self.assertNotIsInstance(caught.exception, browse.BrowseError)

    def test_the_paths_that_reach_the_room_use_the_one_door(self):
        """A caller that forgets is how this reached the room the first time.

        Not a count of `page.goto`: `reachable()` legitimately keeps its
        own handler, because it RETURNS a reason rather than raising, and
        the CLI demo is never spoken. The rule is about the three
        functions whose failure he actually hears - reading a page,
        photographing one, driving one.
        """
        import inspect

        for fn in (browse.read_page, browse.screenshot, browse.interact):
            with self.subTest(fn=fn.__name__):
                body = inspect.getsource(fn)
                self.assertIn("_load(", body,
                              f"{fn.__name__} calls goto directly")
                self.assertNotIn("page.goto(", body)


class TakenOutForSpeechCase(unittest.TestCase):
    def test_the_code_is_not_said(self):
        said = speech.plainly(
            "could not load https://x - the address did not resolve "
            "(net::ERR_NAME_NOT_RESOLVED)")
        self.assertIn("the address did not resolve", said)
        self.assertNotIn("ERR_", said)

    def test_a_call_log_never_survives(self):
        said = speech.plainly("it broke Call log: navigating to x, waiting until y")
        self.assertNotIn("Call log", said)
        self.assertNotIn("navigating", said)

    def test_a_library_method_prefix_is_dropped(self):
        self.assertNotIn("Page.goto",
                         speech.plainly("Page.goto: something went wrong"))

    def test_an_ordinary_reason_is_untouched(self):
        """The messages underneath are usually good."""
        self.assertEqual(speech.plainly("resume is not a file"),
                         "resume is not a file")

    def test_browse_does_not_keep_its_own_copy(self):
        """One implementation; a second regex here would drift."""
        self.assertEqual(browse.say_reason("nope (net::ERR_ABORTED)"), "nope")
        with open(browse.__file__, encoding="utf-8") as handle:
            code = handle.read()
        self.assertIn("speech.without_machine_codes", code)


if __name__ == "__main__":
    unittest.main()
