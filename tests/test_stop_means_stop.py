"""He said stop twice, and windows kept opening.

2026-09-12, in his own words to the wall::

    thea Stop opening up ChatGPT windows in ...
    thea I said stop opening ChatGPT windows

Both were heard. Both wrote ``{"on": false}`` to the lease. And ChatGPT
windows kept appearing over his work every minute, because
``operator_lease_enabled()`` asked its questions in this order::

    1. is the environment lease set?
    2. is he WAITING on this request?     <- true for everything he says
    3. did he grant a standing lease?     <- the only one that saw the "off"

Every sentence he speaks arrives through ``/api/ask``, which
``core.run_command`` marks ATTENDED. So the order he gave could not
outlive the sentence he gave it in: the revoke was written, and the next
thing he said re-opened the door. With Claude out of session, the ladder
fell to the ChatGPT rung on every single request - hence "every fucking
minute".

The rule now: an EXPLICIT off outranks "he is waiting". Never-asked stays
permissive, because that is a different ruling of his (2026-09-08: he
should not have to switch ChatGPT on for a question he asked out loud),
and it is the one ``attended()`` exists to serve.
"""
from __future__ import annotations

import unittest
from unittest import mock

from aletheia import browser_reasoner


class StopMeansStopCase(unittest.TestCase):
    def setUp(self):
        p = mock.patch.dict("os.environ", {browser_reasoner.ALLOW_ENV: ""})
        p.start()
        self.addCleanup(p.stop)

    def _lease(self, record):
        p = mock.patch("aletheia.second_opinion.state", return_value=record)
        p.start()
        self.addCleanup(p.stop)
        granted = bool(record.get("on"))
        p = mock.patch("aletheia.second_opinion.granted", return_value=granted)
        p.start()
        self.addCleanup(p.stop)

    def test_an_order_to_stop_outlives_the_sentence_he_gave_it_in(self):
        """The exact live defect: revoked, then he speaks, and it opens."""
        self._lease({"on": False, "via": "operator: thea stop opening ChatGPT windows"})
        with browser_reasoner.attending():
            self.assertFalse(browser_reasoner.operator_lease_enabled())

    def test_stop_also_holds_when_nobody_is_waiting(self):
        self._lease({"on": False, "via": "operator"})
        self.assertFalse(browser_reasoner.operator_lease_enabled())

    def test_never_having_asked_is_not_an_order(self):
        """His 2026-09-08 ruling, untouched: a question he is waiting on
        may fall through to ChatGPT without him switching anything on."""
        self._lease({})
        with browser_reasoner.attending():
            self.assertTrue(browser_reasoner.operator_lease_enabled())

    def test_turning_it_back_on_works(self):
        self._lease({"on": True, "boot": "b", "via": "operator"})
        self.assertTrue(browser_reasoner.operator_lease_enabled())

    def test_his_own_foreground_shell_is_still_his_to_use(self):
        """He typed the lease into a shell himself; that is not a loop
        quietly driving his account, and stop was about the loop."""
        self._lease({"on": False, "via": "operator"})
        with mock.patch.dict("os.environ", {browser_reasoner.ALLOW_ENV: "1"}):
            self.assertTrue(browser_reasoner.operator_lease_enabled())

    def test_a_stopped_lease_reports_unavailable_rather_than_opening(self):
        """`available()` is what the ladder asks before opening anything."""
        self._lease({"on": False, "via": "operator"})
        with browser_reasoner.attending():
            ok, why = browser_reasoner.available()
        self.assertFalse(ok)
        self.assertIn("disabled", why)


class TheWindowStaysOffHisScreenCase(unittest.TestCase):
    """His words: "without taking my main screen and blocking it"."""

    def test_the_fallback_opens_off_screen_and_unfocused(self):
        seen = {}

        class FakeSession:
            def __init__(self, headed=False, profile=None, args=None):
                seen.update(headed=headed, args=list(args or []))

        with mock.patch("aletheia.browse._Session", FakeSession):
            browser_reasoner._subscription_session()
        joined = " ".join(seen["args"])
        self.assertIn("--window-position=-32000,-32000", joined,
                      "the window opens off the edge of every monitor")
        self.assertIn("--no-startup-window-focus", joined,
                      "it never takes his keyboard")

    def test_a_session_without_args_is_unchanged(self):
        from aletheia import browse
        session = browse._Session()
        self.assertEqual(session.args, [])


if __name__ == "__main__":
    unittest.main()
