"""A page refresh was driving his personal ChatGPT account.

2026-09-12, his words: *"this keeps randomly opening chat GPT windows for
no reason and then closing them right away. that's so fucking annoying."*

The chain, found by reading his browser profile's own history (a
chatgpt.com visit at 06:58, sixteen minutes after he revoked the lease):

    interface/command.html   polls /api/setup every 120s while open
      -> core  GET /api/setup
      -> setup.audit()
      -> setup._chatgpt_browser()
      -> chatgpt_session.status()
      -> a REAL headed Chrome on his signed-in profile, loading
         chatgpt.com, then closing

Two separate failures, and the second is the serious one:

- a readiness CHECK was doing the expensive, visible thing it was
  checking for. "Is the sign-in good?" does not require opening the
  sign-in, any more than asking whether a car starts requires driving it
  to work;
- it asked NO lease, so his standing "stop" - said twice, out loud, and
  written to the lease both times - could not reach it. An order he
  gives has to hold everywhere, not only on the paths that remembered to
  ask.
"""
from __future__ import annotations

import unittest
from unittest import mock

from aletheia import chatgpt_session


class AHealthCheckDoesNotOpenHisChatGptCase(unittest.TestCase):
    def setUp(self):
        p = mock.patch.object(chatgpt_session.browse, "available",
                              return_value=(True, "installed"))
        p.start()
        self.addCleanup(p.stop)
        p = mock.patch.object(type(chatgpt_session.browse.PROFILE_DIR), "exists",
                              return_value=True)
        p.start()
        self.addCleanup(p.stop)
        # Any attempt to open a window during a probe is the bug itself.
        self.opened = mock.patch.object(
            chatgpt_session.browser_reasoner, "_subscription_session",
            side_effect=AssertionError("a health check opened his ChatGPT"))
        self.opened.start()
        self.addCleanup(self.opened.stop)

    def _allowed(self, yes: bool, why="ChatGPT browser reasoning is disabled"):
        p = mock.patch.object(chatgpt_session.browser_reasoner, "available",
                              return_value=(yes, why if not yes else "ready"))
        p.start()
        self.addCleanup(p.stop)

    def test_the_default_check_opens_nothing(self):
        """What /api/setup calls, every two minutes, while the tab is open."""
        self._allowed(True)
        out = chatgpt_session.status()
        self.assertTrue(out["ready"])
        self.assertIn("not opened", out["reason"])

    def test_after_he_says_stop_the_check_says_so_instead_of_opening(self):
        self._allowed(False)
        out = chatgpt_session.status()
        self.assertFalse(out["ready"])
        self.assertIn("disabled", out["reason"])

    def test_even_asked_to_open_it_obeys_the_lease(self):
        """His own command line is still his - but "stop" outranks it."""
        self._allowed(False)
        out = chatgpt_session.status(open_a_window=True)
        self.assertFalse(out["ready"])
        self.assertIn("disabled", out["reason"])

    def test_the_audit_no_longer_reaches_for_a_window(self):
        """setup.audit() is served on a page poll; it must stay cheap."""
        from aletheia import setup
        self._allowed(True)
        state, detail = setup._chatgpt_browser()
        self.assertEqual(state, setup.OK)


if __name__ == "__main__":
    unittest.main()
