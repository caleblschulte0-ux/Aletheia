"""Regression tests for ChatGPT's client-rendered composer readiness."""
from __future__ import annotations

import unittest

from aletheia import browser_reasoner


class _MissingLocator:
    first = None

    def count(self):
        return 0


class _PromptLocator:
    def __init__(self, page):
        self.page = page
        self.first = self

    def count(self):
        return 1

    def is_visible(self):
        return self.page.ready


class _DelayedPage:
    def __init__(self, selector="#prompt-textarea", ready=False):
        self.selector = selector
        self.ready = ready
        self.waits = 0

    def locator(self, selector):
        if selector == self.selector:
            return _PromptLocator(self)
        return _MissingLocator()

    def wait_for_timeout(self, _milliseconds):
        self.waits += 1
        self.ready = True


class EditorReadinessCase(unittest.TestCase):
    def test_waits_for_client_rendered_prompt_after_domcontentloaded(self):
        page = _DelayedPage(ready=False)
        editor = browser_reasoner._editor(page, timeout_s=1)
        self.assertIsInstance(editor, _PromptLocator)
        self.assertGreaterEqual(page.waits, 1)

    def test_accepts_current_contenteditable_textbox_variant(self):
        page = _DelayedPage(selector="[contenteditable='true'][role='textbox']", ready=True)
        editor = browser_reasoner._editor(page, timeout_s=0)
        self.assertIsInstance(editor, _PromptLocator)
        self.assertEqual(page.waits, 0)

    def test_zero_timeout_still_checks_once_then_fails_honestly(self):
        page = _DelayedPage(selector="never-matches", ready=False)
        with self.assertRaises(browser_reasoner.BrowserReasonerUnavailable):
            browser_reasoner._editor(page, timeout_s=0)
        self.assertEqual(page.waits, 0)


if __name__ == "__main__":
    unittest.main()
