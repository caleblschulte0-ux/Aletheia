"""Regression tests for the Windows ChatGPT subscription browser mode."""
from __future__ import annotations

import os
import unittest
from unittest import mock

from aletheia import browser_reasoner


class WindowsSubscriptionModeCase(unittest.TestCase):
    def test_windows_uses_visible_chrome_for_subscription_reasoning(self):
        sentinel = object()
        with mock.patch.object(browser_reasoner.os, "name", "nt"), \
             mock.patch.object(browser_reasoner.browse, "_Session", return_value=sentinel) as session:
            result = browser_reasoner._subscription_session()
        self.assertIs(result, sentinel)
        session.assert_called_once_with(headed=True)

    def test_non_windows_keeps_hidden_subscription_browser(self):
        sentinel = object()
        with mock.patch.object(browser_reasoner.os, "name", "posix"), \
             mock.patch.object(browser_reasoner.browse, "_Session", return_value=sentinel) as session:
            result = browser_reasoner._subscription_session()
        self.assertIs(result, sentinel)
        session.assert_called_once_with(headed=False)


if __name__ == "__main__":
    unittest.main()


class UnattendedNeverInheritsTheLease(unittest.TestCase):
    """#74 said browser ChatGPT reasoning is off for unattended runtime. The
    lease is an env var, and env vars are inherited — so declining to SET it
    is not enough. The always-on side must actively drop it."""

    def test_drop_lease_clears_the_variable(self):
        from aletheia import browser_reasoner
        with mock.patch.dict(os.environ,
                             {browser_reasoner.ALLOW_ENV: "1"}):
            self.assertTrue(browser_reasoner.operator_lease_enabled())
            browser_reasoner.drop_lease()
            self.assertFalse(browser_reasoner.operator_lease_enabled())

    def test_drop_lease_scrubs_a_child_env_dict(self):
        from aletheia import browser_reasoner
        child = browser_reasoner.drop_lease(
            {browser_reasoner.ALLOW_ENV: "1", "KEEP": "yes"})
        self.assertNotIn(browser_reasoner.ALLOW_ENV, child)
        self.assertEqual(child["KEEP"], "yes")

    def test_supervisor_never_hands_the_lease_to_the_core(self):
        from aletheia import browser_reasoner, supervisor
        with mock.patch.dict(os.environ, {browser_reasoner.ALLOW_ENV: "1"}):
            env = supervisor._child_env()
        self.assertNotIn(browser_reasoner.ALLOW_ENV, env,
                         "the always-on Core must not inherit a foreground "
                         "lease to open the operator's ChatGPT browser")
        self.assertEqual(env.get("ALETHEIA_SUPERVISED"), "1")
