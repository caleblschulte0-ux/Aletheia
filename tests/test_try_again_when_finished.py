"""Tenex (Ashby), live 2026-09-23, with the refusal reading fixed: the site
answered the press with "We're updating your application (e.g. uploading
files), please try again when they're finished." The resume widget shows a
bare spinner beside the file's name for seven seconds and more, the name
alone read as landed, and the application was recorded refused. Named is
not finished; and a page that asks for a moment gets one press more."""
import unittest

from aletheia import apply_run


class ThePageAskedForAMoment(unittest.TestCase):
    def test_the_words_that_mean_wait_not_fix(self):
        self.assertTrue(apply_run.asks_to_try_again(
            ["We're updating your application (e.g. uploading files), please try again when they're finished."]))
        self.assertTrue(apply_run.asks_to_try_again([], "Your file is still uploading. Please wait."))
        self.assertFalse(apply_run.asks_to_try_again(["Phone number must be 10 digits"]))
        self.assertFalse(apply_run.asks_to_try_again(["There was a problem with your application."]))


class NamedIsNotFinished(unittest.TestCase):
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

    ASHBY = """
      <div class="_fieldEntry ashby-application-form-field-entry"><label>Resume*</label>
        <input type="file" id="res">
        <div class="_file"><span id="spin" class="_spinner_8ul1h_9 _spinner-size-md"></span>
          <span aria-label="delete Caleb_Schulte_Resume.pdf">Caleb_Schulte_Resume.pdf</span></div></div>
      <script>setTimeout(() => document.getElementById('spin').remove(), 900);</script>"""

    def _held(self, page):
        import tempfile, pathlib
        tmp = pathlib.Path(tempfile.mkdtemp()) / "Caleb_Schulte_Resume.pdf"
        tmp.write_bytes(b"%PDF-1.4 resume")
        page.set_input_files("#res", str(tmp))

    def test_a_spinner_beside_the_name_is_still_working_and_then_lands(self):
        page = self._browser.new_page()
        page.set_content(self.ASHBY)
        self._held(page)
        self.assertEqual(apply_run._upload_state(page), "working")
        self.assertEqual(apply_run._wait_for_uploads(page, budget_ms=6000), "the upload finished")
        self.assertEqual(apply_run._upload_state(page), "held")
        page.close()

    def test_resume_landed_waits_out_the_spinner(self):
        page = self._browser.new_page()
        page.set_content(self.ASHBY)
        self._held(page)
        self.assertEqual(apply_run._upload_state(page), "working", "the name is on the page and it is still working")
        self.assertTrue(apply_run._resume_landed(page, "C:/x/Caleb_Schulte_Resume.pdf"))
        self.assertEqual(apply_run._upload_state(page), "held", "it waited the spinner out rather than trusting the name")
        page.close()

    def test_a_name_with_no_spinner_lands_at_once_as_before(self):
        page = self._browser.new_page()
        page.set_content('<div><button aria-label="delete Caleb_Schulte_Resume.pdf"></button></div>')
        self.assertTrue(apply_run._resume_landed(page, "C:/x/Caleb_Schulte_Resume.pdf", wait_ms=0))
        page.close()


class ARecordRefusedForAMomentIsReadAgain(unittest.TestCase):
    def test_tenexs_record_is_read_again_and_a_real_refusal_is_not(self):
        from aletheia import campaign
        moment = {"id": "apply-t", "state": "REJECTED", "url": "https://x/t",
                  "failure": "the site refused it: The site handed it back rather than accepting it - it says "
                             "\"We're updating your application (e.g. uploading files), please try again when they're finished.\""}
        self.assertTrue(campaign.refused_submit(moment))
        self.assertFalse(campaign.refused_submit({**moment, "failure": "the site refused it: it says 'Phone must be 10 digits'"}))
        self.assertFalse(campaign.refused_submit({**moment, "stagings": 3}))


if __name__ == "__main__":
    unittest.main()
