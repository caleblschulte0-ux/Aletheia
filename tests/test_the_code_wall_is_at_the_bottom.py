"""The gate was there, and it never fired, because the page was truncated.

2026-09-12, the second attempt at his six approved applications. The
verification-code step had been built, tested and landed; every one still
came back refused, and the detector reported no code wall on any of them.

The reason was one slice. `_refill_and_submit` read::

    body = (page.inner_text("body") or "")[:4000]

and then asked `_wants_a_code(body)`. A Greenhouse application runs to six
thousand characters or more — the Stripe form is nearly six thousand pixels
tall — and the sentence

    A verification code was sent to <address>. To submit your application,
    enter the 8-character code to confirm you're a human.

is the LAST thing on the page, after every question, both self-identification
surveys and the disability form. So the check was handed a page with the
evidence cut off and correctly found nothing.

Truncate what is STORED, never what is EXAMINED. The record keeps 600
characters because it is read out and rendered; the decision reads the whole
page.

This test drives the real function against a page shaped like the real ones:
the wall lives past the cut, and the code arrives by mail.
"""
from __future__ import annotations

import unittest
from unittest import mock

from aletheia import apply_run

FILLER = ("Apply for this job. First Name Last Name Email Phone Location "
          "Resume Cover Letter Education School Degree. " * 90)
WALL = (" A verification code was sent to openrangeinteractive@gmail.com. To "
        "submit your application, enter the 8-character code to confirm "
        "you're a human. Security code")
CONFIRMED = "Thank you for applying. Your application has been received."


class FakePage:
    """Enough of a Playwright page for `_refill_and_submit`."""

    def __init__(self, pages):
        self.pages = list(pages)      # what inner_text returns, in order
        self.url = "https://boards.greenhouse.io/embed/job_app?for=x&token=1"
        self.clicks = []
        self.filled = []

    def goto(self, url, **kw):
        self.url = url

    def inner_text(self, _sel):
        return self.pages[0] if len(self.pages) == 1 else self.pages.pop(0)

    def click(self, selector):
        self.clicks.append(selector)

    def fill(self, selector, value):
        self.filled.append((selector, value))

    def evaluate(self, js):
        if "one-time-code" in js or "security" in js:
            return [f"#code{i}" for i in range(8)]
        return [{"selector": "#submit", "text": "Submit application"}]

    def wait_for_load_state(self, *a, **kw):
        pass

    def wait_for_timeout(self, *a, **kw):
        pass

    def screenshot(self, path=None, **kw):
        from pathlib import Path
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_bytes(b"png")

    def title(self):
        return "Job Application"

    def close(self):
        pass


class FakeSession:
    def __init__(self, page):
        self.page = page

    def __call__(self, *a, **kw):
        return self

    def __enter__(self):
        return mock.Mock(new_page=lambda: self.page)

    def __exit__(self, *a):
        return False


class TheCodeWallIsAtTheBottomCase(unittest.TestCase):
    def _run(self, page, code_reader):
        record = {"id": "apply-test", "url": page.url, "steps": [], "resume": "",
                  "button": "submit"}
        with mock.patch.object(apply_run.browse, "available", return_value=(True, "ok")), \
             mock.patch.object(apply_run.browse, "_Session", FakeSession(page)), \
             mock.patch.object(apply_run.formfill, "settle", lambda *a, **kw: None), \
             mock.patch.object(apply_run, "_apply_steps", lambda *a, **kw: None), \
             mock.patch.object(apply_run, "_submit_selector", lambda *a: "#submit"), \
             mock.patch.object(apply_run, "_emailed_code", code_reader):
            return apply_run._refill_and_submit(record)

    def test_the_wall_past_four_thousand_characters_is_still_seen(self):
        """The live shape: everything, then the code sentence, at the end."""
        page = FakePage([FILLER + WALL, CONFIRMED])
        self.assertGreater(len(FILLER), 4000, "the fixture must outrun the old slice")
        out = self._run(page, lambda **kw: "X7K9P2M4")
        self.assertEqual(len(page.clicks), 2, "submit, then submit again after the code")
        self.assertEqual(page.filled,
                         [(f"#code{i}", ch) for i, ch in enumerate("X7K9P2M4")])
        self.assertIn("received", out["evidence"].lower())

    def test_no_code_in_the_inbox_is_a_refusal_not_a_send(self):
        page = FakePage([FILLER + WALL])
        with self.assertRaises(apply_run.ApplyError) as caught:
            self._run(page, lambda **kw: "")
        self.assertIn("verification code", str(caught.exception))
        self.assertEqual(len(page.clicks), 1, "it never pressed submit a second time")

    def test_a_page_with_no_wall_is_untouched(self):
        """No wall: one click, no code typed, and the outcome still read
        from the WHOLE page — the confirmation here sits past the 600
        characters the record stores, which is the point of the split."""
        page = FakePage([FILLER + CONFIRMED])
        out = self._run(page, lambda **kw: "SHOULDNOT")
        self.assertEqual(page.filled, [], "no code was typed")
        self.assertEqual(len(page.clicks), 1)
        self.assertNotEqual(out.get("verdict"), "rejected",
                            "a page that confirmed is not a refusal")

    def test_the_stored_evidence_is_still_short(self):
        """It is rendered and read out; the DECISION reads the whole page."""
        page = FakePage([FILLER + WALL, CONFIRMED])
        out = self._run(page, lambda **kw: "X7K9P2M4")
        self.assertLessEqual(len(out["evidence"]), 600)


if __name__ == "__main__":
    unittest.main()
