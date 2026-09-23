"""Sleeper, live 2026-09-23: two fully filled applications read as "refused
by the site - it says 'must be'". The picture showed the Submit button
still spinning and the form still on screen; the words came from a field
label, "City, State (must be in US)*". The page is read once the send has
settled, a label is not a complaint, and what the page really complains
of is quoted whole."""
import unittest

from aletheia import apply_run, browse

SLEEPER = ("F2P Customer Success Associate\nThis job has application limits\n"
           "Name*\nCaleb Schulte\nEmail*\nCity, State (must be in US)*\nHartford, SD\n"
           "Are you authorized to work legally in the US?*\nSubmit Application")


class ALabelIsNotARefusal(unittest.TestCase):
    def test_a_refusal_word_inside_a_label_proves_nothing(self):
        out = browse.read_outcome(SLEEPER, did="Submit Application")
        self.assertEqual(out["verdict"], "submitted, unconfirmed", out)

    def test_a_real_complaint_is_quoted_whole(self):
        out = browse.read_outcome("There was a problem with your application.\n"
                                  "Phone number must be 10 digits with no punctuation.")
        self.assertEqual(out["verdict"], "rejected")
        self.assertIn("There was a problem with your application", out["note"])
        self.assertNotIn("it says 'there was a problem'", out["note"], "the sentence, not the bare word")

    def test_the_pages_own_complaints_win(self):
        out = browse.read_outcome(SLEEPER, did="Submit Application",
                                  complaints=["Phone must be a valid US number"])
        self.assertEqual(out["verdict"], "rejected")
        self.assertIn("Phone must be a valid US number", out["note"])


class TheSendIsGivenTimeToSettle(unittest.TestCase):
    """A real page whose Submit spins for a moment and then shows its verdict."""
    _pw = _browser = None

    @classmethod
    def setUpClass(cls):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            raise unittest.SkipTest("playwright is not installed")
        cls._pw = sync_playwright().start()
        try:
            cls._browser = cls._pw.chromium.launch(args=["--no-sandbox"])
        except Exception as exc:
            cls._pw.stop()
            raise unittest.SkipTest(f"no chromium: {type(exc).__name__}")

    @classmethod
    def tearDownClass(cls):
        if cls._browser:
            cls._browser.close()
            cls._pw.stop()

    def test_it_waits_for_the_spinner_and_reads_the_complaint_the_page_shows(self):
        page = self._browser.new_page()
        page.set_content("""
          <form><label>City, State (must be in US)*</label><input id="c" value="Hartford, SD">
          <button id="go" aria-busy="true" class="_button _loading">Submit Application</button></form>
          <div id="msg"></div>
          <script>setTimeout(() => {
            const b = document.getElementById('go'); b.setAttribute('aria-busy', 'false'); b.className = '_button';
            const m = document.getElementById('msg'); m.setAttribute('role', 'alert');
            m.innerText = 'You have already applied to this role within the last 30 days.';
          }, 700);</script>""")
        why = apply_run._settled_after_press(page, "#go", budget_ms=6000)
        self.assertEqual(why, "the button is free")
        complaints = apply_run._page_complaints(page)
        self.assertEqual(complaints, ["You have already applied to this role within the last 30 days."])
        out = browse.read_outcome(page.inner_text("body"), did="Submit Application", complaints=complaints)
        self.assertEqual(out["verdict"], "rejected")
        self.assertIn("already applied", out["note"])
        page.close()

    def test_a_page_with_no_complaint_and_a_label_is_unconfirmed_not_refused(self):
        page = self._browser.new_page()
        page.set_content("""<form><label>City, State (must be in US)*</label><input value="Hartford, SD">
          <button id="go">Submit Application</button></form>""")
        self.assertEqual(apply_run._settled_after_press(page, "#go", budget_ms=2000), "the button is free")
        self.assertEqual(apply_run._page_complaints(page), [])
        out = browse.read_outcome(page.inner_text("body"), did="Submit Application", complaints=[])
        self.assertEqual(out["verdict"], "submitted, unconfirmed")
        page.close()


if __name__ == "__main__":
    unittest.main()
