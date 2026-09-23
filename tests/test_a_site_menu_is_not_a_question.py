"""Navan's careers page is a Greenhouse form inside Navan's own website, and
the reader took the website for the form: "Toggle navigation menu",
"Platform", "Travel", "Solutions", "nav-group-toggle-1" reached him as
required questions on three applications (live, 2026-09-22), each one
stopped on a menu. Anything inside the site's chrome - nav, header,
footer, a landmark that says so - is never a question."""
from __future__ import annotations

import unittest

from aletheia import formfill

PAGE = """
<header>
  <nav aria-label="Main">
    <input type="checkbox" id="nav-toggle" class="menu-toggle">
    <label for="nav-toggle">Toggle navigation menu</label>
    <input type="checkbox" id="nav-group-toggle-0"><label for="nav-group-toggle-0">Platform</label>
    <input type="checkbox" id="nav-group-toggle-1"><label for="nav-group-toggle-1">Solutions</label>
    <div role="radiogroup" aria-label="Region"><div role="radio">US</div><div role="radio">EU</div></div>
  </nav>
</header>
<main>
  <form id="application_form">
    <label for="first_name">First Name *</label>
    <input id="first_name" name="first_name" type="text" required>
    <label for="email">Email *</label>
    <input id="email" name="email" type="email" required>
  </form>
</main>
<footer>
  <label><input type="checkbox" name="newsletter"> Subscribe to our newsletter</label>
</footer>
"""


class Browser:
    _pw = _browser = None

    @classmethod
    def page(cls, html):
        if cls._browser is None:
            try:
                from playwright.sync_api import sync_playwright
            except ImportError:
                raise unittest.SkipTest("playwright is not installed")
            cls._pw = sync_playwright().start()
            try:
                cls._browser = cls._pw.chromium.launch(args=["--no-sandbox"])
            except Exception as exc:
                cls._pw.stop()
                cls._pw = None
                raise unittest.SkipTest(f"no chromium: {type(exc).__name__}")
        page = cls._browser.new_page()
        page.set_content(html)
        return page

    @classmethod
    def close(cls):
        if cls._browser is not None:
            cls._browser.close()
            cls._pw.stop()
            cls._browser = cls._pw = None


class TheSiteIsNotTheFormCase(unittest.TestCase):
    @classmethod
    def tearDownClass(cls):
        Browser.close()

    def test_nothing_in_the_chrome_is_read_as_a_field(self):
        page = Browser.page(PAGE)
        try:
            labels = sorted(str(f.get("label") or f.get("question") or "") for f in formfill.read_all(page))
        finally:
            page.close()
        for word in ("Toggle navigation menu", "Platform", "Solutions", "Subscribe", "US", "EU"):
            with self.subTest(word=word):
                self.assertFalse(any(word in l for l in labels), labels)
        self.assertTrue(any("First Name" in l for l in labels), labels)

    def test_nothing_in_the_chrome_blocks_the_form(self):
        page = Browser.page(PAGE)
        try:
            page.fill("#first_name", "Caleb")
            page.fill("#email", "c@example.com")
            left = formfill.blocking(page)
        finally:
            page.close()
        self.assertEqual(left, [], left)


if __name__ == "__main__":
    unittest.main()
