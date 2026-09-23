"""Two live applications the night of 2026-09-23, read with her own functions
against the real pages afterwards:

- Vanta (Ashby): the required Location box is <input role=combobox> with no
  id and no name under <label for="_systemfield_location">. The reader
  skipped it, thirteen fields went in, and Submit refused the form.
- Voltus (Lever): the upload wait searched the whole page for "analyzing"
  and found Lever's AI notice ("...analyzing resumes...") - so "Success!"
  beside the file was never believed and Resume/CV went to him as a question.

One Chromium launch for the file; it skips without one.
"""
import unittest

from aletheia import apply_run, formfill, profile

ASHBY_LOCATION = """
<form>
  <div class="ashby-application-form-field-entry" data-field-path="_systemfield_name">
    <label class="_label_1e3gg_42" for="_systemfield_name">Full Name</label>
    <input id="_systemfield_name" name="_systemfield_name" type="text" required>
  </div>
  <div class="_fieldEntry_1e3gg_28 ashby-application-form-field-entry" data-field-path="_systemfield_location"
       data-field-entry-id="6ed41e4c-ca48-4958-a7e1-b97088067bb2__systemfield_location">
    <label class="_heading_f7cvd_52 _required_f7cvd_91 _label_1e3gg_42 ashby-application-form-question-title"
           for="_systemfield_location">Location</label>
    <div class="_inputContainer_d7ago_28">
      <input class="_input_d7ago_28 ashby-application-form-input-autocomplete" placeholder="Start typing..."
             aria-autocomplete="list" aria-expanded="false" aria-haspopup="listbox" role="combobox" value="">
      <button class="_toggleButton_d7ago_32" type="button"><svg viewBox="0 0 640 640"></svg></button>
    </div>
  </div>
</form>"""

LEVER_AFTER_UPLOAD = """
<div class="section application-form">
  <li class="application-question resume">
    <div class="application-label">Resume/CV <span class="required">*</span></div>
    <div class="application-field">
      <a href="#" class="postings-btn visible-resume-upload has-file">ATTACH RESUME/CV</a>
      <input id="resume-upload-input" type="file" name="resume">
      <div class="resume-upload-label" style="display:none">Analyzing resume...</div>
      <div class="resume-upload-success">Success!</div>
      <div class="resume-upload-failure" style="display:none">File exceeds the maximum upload size of 100MB.</div>
    </div>
  </li>
  <p>We may use artificial intelligence (AI) tools to support parts of the hiring
     process, such as reviewing applications, analyzing resumes, or assessing responses.</p>
</div>"""

LEVER_STILL_WORKING = LEVER_AFTER_UPLOAD.replace(
    '<div class="resume-upload-label" style="display:none">', '<div class="resume-upload-label">').replace(
    '<div class="resume-upload-success">', '<div class="resume-upload-success" style="display:none">')


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


class ABoxWithNoIdAndNoNameIsStillAQuestion(unittest.TestCase):
    def test_ashbys_location_is_read_required_and_findable(self):
        page = Browser.page(ASHBY_LOCATION)
        rows = page.evaluate(formfill.READ_FORM_JS)
        loc = [r for r in rows if r["role"] == "combobox"]
        self.assertEqual(len(loc), 1, [r["label"] for r in rows])
        row = loc[0]
        self.assertEqual(row["label"], "Location")
        self.assertTrue(row["required"], "the label's own class says required")
        self.assertEqual(row["selector"], '[data-field-path="_systemfield_location"] input[role="combobox"]')
        self.assertIsNotNone(page.query_selector(row["selector"]), "the selector finds it on the page")
        # the neighbour with a real id is untouched by the new rule
        name = next(r for r in rows if r["id"] == "_systemfield_name")
        self.assertEqual((name["label"], name["selector"]), ("Full Name", "#_systemfield_name"))

    def test_a_bare_location_is_where_he_lives_and_somebody_elses_places_are_not(self):
        self.assertEqual(formfill.match_field({"label": "Location"}), "city")
        self.assertEqual(formfill.match_field({"label": "Location*"}), "city")
        self.assertEqual(formfill.match_field({"label": "Your location (City, State)"}), "city")
        for label in ("Preferred office location", "Which locations are you open to?",
                      "Location of the role you are applying for"):
            self.assertNotEqual(formfill.match_field({"label": label}), "city", label)


class AParagraphIsNotAProgressMessage(unittest.TestCase):
    def test_levers_success_is_believed_beside_its_ai_notice(self):
        page = Browser.page(LEVER_AFTER_UPLOAD)
        self.assertEqual(apply_run._upload_state(page), "held")

    def test_a_shown_analyzing_line_is_still_working(self):
        page = Browser.page(LEVER_STILL_WORKING)
        self.assertEqual(apply_run._upload_state(page), "working")


ASHBY_BUTTONS = """
<form>
  <div><label>Resume</label><div><button>Upload file</button></div></div>
  <div><label>Consent</label><div><button aria-pressed="false">Yes</button><button aria-pressed="false">No</button></div></div>
  <div class="_actions"><button class="_button_zyh3g_28 _submitButton_5yu8i_411">Submit Application</button></div>
</form>"""


class ASubmitSelectorThatResolves(unittest.TestCase):
    """Ashby's buttons carry no type attribute, so el.type says "submit" while
    button[type="submit"] matches nothing: every Ashby send waited on a
    locator no element answered to (Vanta, Spekit, 2026-09-23)."""

    def test_ashbys_submit_button_is_named_by_a_path_that_finds_it(self):
        from aletheia import apply_run
        page = Browser.page(ASHBY_BUTTONS)
        buttons = page.evaluate(apply_run.BUTTONS_JS)
        chosen = apply_run._submit_selector(buttons)
        self.assertIsNotNone(chosen, buttons)
        self.assertNotEqual(chosen, 'button[type="submit"]', "the attribute is not there to match")
        hit = page.query_selector(chosen)
        self.assertIsNotNone(hit, chosen)
        self.assertEqual(hit.inner_text().strip(), "Submit Application")
        self.assertEqual(len(page.query_selector_all(chosen)), 1, "one element, not the first of eight")

    def test_a_button_with_an_id_or_a_real_type_attribute_is_unchanged(self):
        from aletheia import apply_run
        page = Browser.page('<form><button id="submit_app">Submit Application</button></form>')
        self.assertEqual(apply_run._submit_selector(page.evaluate(apply_run.BUTTONS_JS)), "#submit_app")
        page = Browser.page('<form><input type="text"><button type="submit">Submit</button></form>')
        self.assertEqual(apply_run._submit_selector(page.evaluate(apply_run.BUTTONS_JS)), 'button[type="submit"]')


class AFormWhoseSubmitRefusedIsReadAgainAndNotForEver(unittest.TestCase):
    """Vanta and Spekit were filled, renewed and refused four times each in
    one night. A refused Submit is read again with what she knows now; the
    fourth filling is his eyes; a CAPTCHA shown in front of the button is
    not a reading problem at all."""
    REFUSED = {"id": "apply-v", "state": "FAILED", "url": "https://x/v", "resume": "C:/r.pdf",
               "company": "Vanta", "job_title": "CSM",
               "failure": "ApplyError: the Submit button would not take a click - it never became clickable"}

    def test_which_failed_records_are_read_again(self):
        from aletheia import campaign
        self.assertTrue(campaign.refused_submit(self.REFUSED))
        self.assertTrue(campaign.refused_submit({**self.REFUSED, "captcha": "recaptcha"}),
                        "an invisible check merely loaded on the form is not a challenge")
        self.assertFalse(campaign.refused_submit({**self.REFUSED, "stagings": 3}))
        self.assertFalse(campaign.refused_submit({**self.REFUSED, "click_evidence": {"captcha": True}}))
        self.assertFalse(campaign.refused_submit({**self.REFUSED, "failure": "ApplyError: the page went away"}))
        self.assertFalse(campaign.refused_submit({**self.REFUSED, "state": "SUBMITTED"}))

    def test_the_refused_form_is_staged_again(self):
        from unittest import mock
        from aletheia import apply_run, campaign
        calls = []

        def stager(url, **kw):
            calls.append(url)
            return {"id": "apply-v", "url": url, "state": "AWAITING_YOU", "questions": []}
        with mock.patch.object(apply_run, "all_runs",
                               side_effect=lambda state=None: [self.REFUSED] if state == "FAILED" else []), \
             mock.patch.object(campaign, "read_resume", return_value=("C:/r.pdf", "resume text")), \
             mock.patch.object(campaign.policy, "ensure_not_halted"), \
             mock.patch.object(campaign.journal, "append"):
            out = campaign.retry_waiting(stager=stager, json_think=False, writer=False)
        self.assertEqual(calls, ["https://x/v"])
        self.assertEqual(len(out["ready"]), 1)

    def test_stage_counts_its_fillings_and_refuses_the_fourth_of_a_refused_form(self):
        from unittest import mock
        from aletheia import apply_run
        self.assertIn("stagings", apply_run.REMEMBERED, "the count survives stage's rebuild of the record")
        with mock.patch.object(apply_run.policy, "ensure_not_halted"), \
             mock.patch.object(apply_run, "was_sent", return_value=None), \
             mock.patch.object(apply_run, "load_run", return_value={**self.REFUSED, "stagings": 3}):
            with self.assertRaises(apply_run.ApplyError) as held:
                apply_run.stage("https://x/v", reader=lambda url: [])
        self.assertIn("needs your eyes", str(held.exception))
        self.assertIn("3 times", str(held.exception))


class TheEarliestDateHeCanBeginIsOnFile(unittest.TestCase):
    def test_tenexs_question_reaches_his_notice_period(self):
        for label in ("What's the earliest date you can begin at Tenex?",
                      "When can you start?", "What date can you begin?"):
            self.assertEqual(formfill.match_field({"label": label}), "notice_period", label)
        self.assertIn("earliest date", profile.FIELDS["notice_period"]["asks"])


if __name__ == "__main__":
    unittest.main()
