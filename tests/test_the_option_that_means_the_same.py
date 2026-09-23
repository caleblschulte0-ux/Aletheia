"""Live 2026-09-23, Aptiv: "Country dropdown (the page would not take the
answer I have)" reached him as a question - the list said "United States of
America" and she had "United States". His words that morning: "obviously
type United States for the fucking country I live in." One Chromium launch
for the file; it skips without one."""
import unittest

from aletheia import browser_loop, formfill

PAGE = """
<form>
  <label for="country">Country</label>
  <select id="country" name="country">
    <option value="">Select...</option>
    <option value="CA">Canada</option>
    <option value="USA">United States of America</option>
    <option value="GB">United Kingdom</option>
  </select>
  <label for="state">State</label>
  <select id="state"><option value="">Select...</option><option value="SD">South Dakota</option>
    <option value="ND">North Dakota</option></select>
</form>"""


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
        cls._pw = cls._browser = None


def tearDownModule():
    Browser.close()


class TheOptionThatMeansTheSame(unittest.TestCase):
    def test_united_states_is_united_states_of_america(self):
        page = Browser.page(PAGE)
        self.assertEqual(formfill.select_like(page, "#country", "United States"), "United States of America")
        self.assertEqual(page.eval_on_selector("#country", "el => el.value"), "USA")
        self.assertEqual(formfill.select_like(page, "#state", "SD"), "South Dakota")
        self.assertEqual(page.eval_on_selector("#state", "el => el.value"), "SD")

    def test_nothing_clearly_the_answer_is_left_alone(self):
        page = Browser.page(PAGE)
        self.assertEqual(formfill.select_like(page, "#country", "Narnia"), "")
        self.assertEqual(page.eval_on_selector("#country", "el => el.value"), "")
        self.assertEqual(formfill.select_like(page, "#nowhere", "United States"), "")


class TheLoopTakesTheListsOwnWords(unittest.TestCase):
    class Hands:
        """Selecting by a label the list does not have throws, as Playwright does."""
        def __init__(self, page):
            self.page = page

        def select_option(self, selector, value=None, *, label=None):
            self.page.select_option(selector, label=label)

    def test_the_route_carries_the_option_chosen(self):
        page = Browser.page(PAGE)
        route, attached = [], []
        done = browser_loop._apply(page, self.Hands(page),
                                   [{"action": "select", "selector": "#country", "value": "United States",
                                     "label": "Country"}], route, attached)
        self.assertEqual(done, ["Country"])
        self.assertEqual(route, [{"action": "select", "selector": "#country", "value": "United States of America"}])
        self.assertEqual(page.eval_on_selector("#country", "el => el.value"), "USA")

    def test_an_answer_the_list_does_not_hold_is_still_not_taken(self):
        page = Browser.page(PAGE)
        route: list = []
        done = browser_loop._apply(page, self.Hands(page),
                                   [{"action": "select", "selector": "#country", "value": "Narnia", "label": "Country"}],
                                   route, [])
        self.assertEqual(done, [])
        self.assertEqual(route, [])


if __name__ == "__main__":
    unittest.main()
