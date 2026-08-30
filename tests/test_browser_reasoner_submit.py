"""Regression tests for reliable ChatGPT prompt submission."""
from __future__ import annotations

import unittest

from aletheia import browser_reasoner


class _Missing:
    first = None
    def count(self): return 0


class _SendButton:
    def __init__(self, page):
        self.page = page
        self.first = self
    def count(self): return 1
    def is_visible(self): return True
    def is_enabled(self): return True
    def click(self): self.page.sent = "button"


class _Editor:
    def __init__(self):
        self.filled = None
        self.pressed = []
    def fill(self, text): self.filled = text
    def press(self, key): self.pressed.append(key)


class _Page:
    def __init__(self, with_button=True):
        self.with_button = with_button
        self.sent = None
        self.waits = 0
    def locator(self, selector):
        if self.with_button and selector == browser_reasoner.SEND_SELECTORS[0]:
            return _SendButton(self)
        return _Missing()
    def wait_for_timeout(self, _ms): self.waits += 1


class SubmissionCase(unittest.TestCase):
    def test_prefers_visible_enabled_send_button(self):
        page = _Page(with_button=True)
        editor = _Editor()
        browser_reasoner._submit_prompt(page, editor, "bounded prompt", timeout_s=0)
        self.assertEqual(editor.filled, "bounded prompt")
        self.assertEqual(page.sent, "button")
        self.assertEqual(editor.pressed, [])

    def test_falls_back_to_enter_on_editor_not_global_keyboard(self):
        page = _Page(with_button=False)
        editor = _Editor()
        browser_reasoner._submit_prompt(page, editor, "bounded prompt", timeout_s=0)
        self.assertEqual(editor.filled, "bounded prompt")
        self.assertEqual(editor.pressed, ["Enter"])

    def test_fill_error_does_not_echo_prompt(self):
        secret = "private-context-must-not-leak"
        class BrokenEditor(_Editor):
            def fill(self, text):
                raise RuntimeError(text)
        with self.assertRaises(browser_reasoner.BrowserReasonerUnavailable) as ctx:
            browser_reasoner._submit_prompt(_Page(), BrokenEditor(), secret, timeout_s=0)
        self.assertNotIn(secret, str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
