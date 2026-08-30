"""Regression tests for the Windows ChatGPT subscription browser mode."""
from __future__ import annotations

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
