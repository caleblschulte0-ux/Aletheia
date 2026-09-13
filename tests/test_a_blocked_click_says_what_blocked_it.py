"""A Submit click that cannot land says what was in front of it.

2026-09-13. Both Lever applications timed out waiting for `#btn-submit` to
take a click, and the reason Playwright gave was cut off in the journal.
A read-only probe of a fresh Lever form found the button visible, enabled
and uncovered, with an invisible hCaptcha loaded behind it - likely, not
proven. So the next blocked click keeps the evidence: a visible CAPTCHA
challenge, whatever covers the button, and a screenshot. A CAPTCHA is named
as the reason, because she does not solve those and he should know why.
"""
from __future__ import annotations

import unittest

from aletheia import apply_run, stateio


class _Page:
    def __init__(self, seen):
        self.seen = seen
        self.shots = []

    def click(self, selector):
        raise TimeoutError('Page.click: Timeout 20000ms exceeded.\nCall log:\n'
                           '  - <iframe src="https://newassets.hcaptcha.com/..."> '
                           'intercepts pointer events')

    def evaluate(self, script, arg=None):
        return self.seen

    def screenshot(self, path, full_page=False):
        self.shots.append(path)


class ABlockedClick(unittest.TestCase):
    def setUp(self):
        self.record = {"id": "apply-blockedclick1", "state": "SUBMITTING"}
        stateio.write_json_atomic(apply_run._record_path(self.record["id"]), self.record)
        self.addCleanup(lambda: apply_run._record_path(self.record["id"]).unlink(missing_ok=True))

    def test_a_captcha_in_front_of_the_button_is_named_and_kept(self):
        page = _Page({"captcha": True, "button_found": True,
                      "covered_by": '<iframe src="https://newassets.hcaptcha.com/captcha">'})
        with self.assertRaises(apply_run.ApplyError) as caught:
            apply_run._press(page, self.record, "#btn-submit")
        self.assertIn("CAPTCHA", str(caught.exception))
        self.assertIn("nothing was sent", str(caught.exception))
        saved = apply_run.load_run(self.record["id"])
        self.assertNotIn("pressed_at", saved, "a click that never landed is not a press")
        self.assertTrue(saved["click_evidence"]["captcha"])
        self.assertEqual(len(page.shots), 1)

    def test_something_else_in_the_way_is_described_not_called_a_captcha(self):
        page = _Page({"captcha": False, "button_found": True,
                      "covered_by": '<div class="cookie-banner">'})
        with self.assertRaises(apply_run.ApplyError) as caught:
            apply_run._press(page, self.record, "#btn-submit")
        self.assertNotIn("CAPTCHA", str(caught.exception))
        self.assertIn("cookie-banner", apply_run.load_run(self.record["id"])["click_evidence"]["covered_by"])

    def test_a_page_that_cannot_be_asked_still_fails_honestly(self):
        page = _Page({})
        page.evaluate = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("page gone"))
        with self.assertRaises(apply_run.ApplyError) as caught:
            apply_run._press(page, self.record, "#btn-submit")
        self.assertIn("nothing was sent", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
