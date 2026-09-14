"""Forms on Workable and Ashby read the way a person reads them.

The first real Workable and Ashby applications staged in a sandbox,
2026-09-13, read correctly on Greenhouse terms and wrongly on their own:

- Workable's yes/no questions are <fieldset role=radiogroup
  aria-labelledby=...> with no legend, and all four of Hugging Face's reached
  him as "YES" - each option's own text standing in for its question.
- A Workable picker keeps what was picked in an unlabelled twin input, which
  reached him as "CA_10627".
- Workable's resume box is <input id="input_files_input_..."> under a heading
  that says Resume, so no upload box "said resume" and none got his resume.
- Ashby's text-message consent is two radios with no id sharing one name, so
  both options had the same selector and "No" would have clicked "Yes".
- An essay question that mentions GitHub got his GitHub URL.

The markup below is the shape those systems served, cut to the parts that
matter. One Chromium launch for the whole file; it skips without one.
"""
import tempfile
import unittest
from pathlib import Path

from aletheia import apply_run, formfill

WORKABLE = """
<form>
  <div><span id="q1_label">Are you eligible to work in the country you are applying?</span>
    <fieldset role="radiogroup" aria-labelledby="q1_label">
      <div role="radio" aria-labelledby="q1_label r1"><label>
        <input id="r1" type="radio" name="CA_10628" value="true" required>
        <div><span id="r1l">YES</span></div></label></div>
      <div role="radio" aria-labelledby="q1_label r2"><label>
        <input id="r2" type="radio" name="CA_10628" value="false" required>
        <div><span id="r2l">NO</span></div></label></div>
    </fieldset></div>
  <label for="input_CA_10627_input">Notice period / availability</label>
  <input id="input_CA_10627_input" type="text">
  <input name="CA_10627" type="text">
  <div class="field"><label>Resume</label>
    <div class="dropzone"><span>Upload a file or drag and drop here</span>
      <input id="input_files_input_a7u3Ne2TEWlPUcCi" type="file"></div></div>
  <div class="block"><div><strong>Cover letter</strong></div>
    <div><input id="input_files_input_b8v4" type="file"></div></div>
</form>"""

ASHBY = """
<form>
  <div><label>Would you like to receive text messages?</label>
    <label><input type="radio" name="communicationConsent" value="Yes">Yes - I consent</label>
    <label><input type="radio" name="communicationConsent" value="No">No - I do not consent</label>
  </div>
  <div class="ashby-application-form-field-entry" data-field-path="3080cfba">
    <label class="_heading _required_f7cvd_91" for="3080cfba">Do you have a minimum of 7 years of experience building software?</label>
    <div class="ashby-application-form-input-yesno">
      <button type="button" aria-pressed="false" data-option="yes">Yes</button>
      <button type="button" aria-pressed="false" data-option="no">No</button>
      <input type="checkbox" tabindex="-1" name="3080cfba">
    </div>
  </div>
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


class WorkableReadsRight(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.page = Browser.page(WORKABLE)
        cls.rows = cls.page.evaluate(formfill.READ_FORM_JS)

    def test_a_radiogroup_is_asked_by_its_accessible_name(self):
        radios = [r for r in self.rows if r["type"] == "radio"]
        self.assertEqual({r["question"] for r in radios},
                         {"Are you eligible to work in the country you are applying?"})

    def test_an_option_wrapping_a_native_radio_is_one_control_and_keeps_required(self):
        rows = [r for r in formfill.read_all(self.page) if r["type"] == "radio"]
        self.assertEqual([(r["tag"], r["option"]) for r in rows], [("aria", "YES"), ("aria", "NO")],
                         "read once, as the thing a person clicks")
        self.assertTrue(all(r["required"] for r in rows), "the native input said required")

    def test_an_unanswered_group_blocks_once_by_its_question(self):
        page = Browser.page(WORKABLE)
        radios = [b for b in formfill.blocking(page) if b.get("why") == "pick one"]
        self.assertEqual([b["label"] for b in radios],
                         ["Are you eligible to work in the country you are applying?"])

    def test_the_value_field_behind_a_picker_is_not_a_second_question(self):
        self.assertNotIn("CA_10627", [r["name"] for r in self.rows])
        self.assertIn("Notice period / availability", [r["label"] for r in self.rows])

    def test_the_resume_box_is_found_by_the_words_around_it_and_the_cover_letter_is_not(self):
        with tempfile.TemporaryDirectory() as d:
            resume = Path(d) / "Caleb_Schulte_Resume.pdf"
            resume.write_bytes(b"%PDF-1.4 resume")
            self.assertTrue(apply_run._attach_resume(self.page, str(resume)))
        held = self.page.evaluate("""() => [...document.querySelectorAll('input[type=file]')]
            .map(i => [i.id, i.files.length])""")
        self.assertEqual(dict(held), {"input_files_input_a7u3Ne2TEWlPUcCi": 1, "input_files_input_b8v4": 0})


def workable_load(first: str, second: str) -> str:
    """One Workable yes/no question as a page load renders it, with the ids that load minted."""
    return f"""
<form>
  <input id="firstname" name="firstname" type="text"><label for="firstname">First name</label>
  <span id="{first}_label">Are you eligible to work in the country you are applying?</span>
  <fieldset role="radiogroup" aria-labelledby="{first}_label">
    <div id="wrapper_{first}" role="radio" aria-labelledby="{first}_label"
         onclick="this.querySelector('input').checked = true"><label>
      <input id="{first}" type="radio" name="QA_12194413" value="true" required><span>YES</span></label></div>
    <div id="wrapper_{second}" role="radio" aria-labelledby="{first}_label"
         onclick="this.querySelector('input').checked = true"><label>
      <input id="{second}" type="radio" name="QA_12194413" value="false" required><span>NO</span></label></div>
  </fieldset>
</form>"""


class ASelectorSurvivesTheNextPageLoad(unittest.TestCase):
    """Workable mints new ids on every render; the fill runs in a later load
    than the read, and the send in a later one still."""

    def test_what_was_read_on_one_load_is_found_on_the_next(self):
        page = Browser.page(workable_load("HO2q69PjIohQ40rW", "SttOzxZfPjv97Rpv"))
        rows = {r["label"]: r["selector"] for r in formfill.read_all(page)}
        self.assertEqual(rows["First name"], "#firstname", "an id nobody minted is still the id")
        self.assertNotIn("HO2q69PjIohQ40rW", rows["NO"] + rows["YES"])
        later = Browser.page(workable_load("cedfyMSPdOianhkc", "n7vJPWbSV6WD15sB"))
        for option, selector in (("YES", rows["YES"]), ("NO", rows["NO"])):
            self.assertEqual(later.evaluate("(s) => document.querySelector(s).innerText.trim()", selector),
                             option, selector)
        later.click(rows["NO"])
        self.assertEqual(later.evaluate(
            "() => document.querySelector('input[name=QA_12194413]:checked').value"), "false")

    def test_a_render_uuid_in_front_of_a_steady_id_is_left_out(self):
        """Ashby: "<per-load uuid>_<field uuid>-labeled-radio-0", name included."""
        def ashby_load(prefix):
            field = "b0a5aba8-dbb7-41a9-b548-f72cc3e48956"
            return "<form><p>What pronouns would you like our team to use?</p>" + "".join(
                f'<label><input type="radio" id="{prefix}_{field}-labeled-radio-{i}" '
                f'name="{prefix}_{field}" value="{i}">{text}</label>'
                for i, text in enumerate(("He/Him", "She/Her"))) + "</form>"
        first = Browser.page(ashby_load("46a20b52-5cec-41e1-8a09-4ab3310ae0e8"))
        rows = {r["label"]: r["selector"] for r in first.evaluate(formfill.READ_FORM_JS)}
        self.assertNotIn("46a20b52", rows["He/Him"])
        later = Browser.page(ashby_load("2ac35076-9bac-4d02-af6e-1732c02650d2"))
        self.assertEqual(later.evaluate("(s) => document.querySelector(s).parentElement.innerText.trim()",
                                        rows["He/Him"]), "He/Him")

    def test_the_minted_id_test_keeps_real_names(self):
        page = Browser.page("""<form>
            <input id="question_8812" name="q" type="text"><label for="question_8812">GitHub</label>
            <input id="communicationConsent" name="communicationConsent" type="text">
            <input id="4b71793a-c95c-4cc9-9d06-02e6ef7c5777" type="tel">
          </form>""")
        selectors = [r["selector"] for r in page.evaluate(formfill.READ_FORM_JS)]
        self.assertIn("#question_8812", selectors)
        self.assertIn("#communicationConsent", selectors)
        self.assertEqual(len(selectors), 3, "an input with only a uuid id is still read by it")


class AshbyReadsRight(unittest.TestCase):
    def test_two_options_without_ids_have_two_selectors(self):
        page = Browser.page(ASHBY)
        rows = page.evaluate(formfill.READ_FORM_JS)
        selectors = [r["selector"] for r in rows if r["type"] == "radio"]
        self.assertEqual(len(selectors), 2)
        self.assertEqual(len(set(selectors)), 2, "one selector for both options clicks the first")
        no = next(r["selector"] for r in rows if r["type"] == "radio" and r["label"].startswith("No"))
        page.click(no)
        self.assertEqual(page.evaluate(
            "() => document.querySelector('input[name=communicationConsent]:checked').value"), "No")

    def test_a_yes_no_pair_of_buttons_is_one_question_not_a_box(self):
        page = Browser.page(ASHBY)
        self.assertNotIn("3080cfba", [r["name"] for r in page.evaluate(formfill.READ_FORM_JS)],
                         "the checkbox behind the buttons is not a question of its own")
        rows = [r for r in page.evaluate(formfill.READ_ARIA_JS)
                if r["question"].startswith("Do you have a minimum")]
        self.assertEqual([r["option"] for r in rows], ["Yes", "No"])
        self.assertTrue(all(r["required"] for r in rows), "the label is marked required")
        self.assertEqual([page.evaluate("(s) => document.querySelector(s).innerText", r["selector"])
                          for r in rows], ["Yes", "No"])


class AnUploadThatNamesTheFileHasLanded(unittest.TestCase):
    """Workable shows the uploaded resume through a delete button's label, not
    the page's text, and every staging said the upload did not finish."""

    def test_a_control_naming_the_file_means_it_was_taken(self):
        page = Browser.page("""<div class="resume"><span style="display:none">x</span>
            <button aria-label="delete Caleb_Schulte_Resume.pdf" type="button"></button></div>""")
        self.assertTrue(apply_run._resume_landed(page, "C:/x/Caleb_Schulte_Resume.pdf", wait_ms=0))

    def test_a_page_that_names_no_file_has_not(self):
        page = Browser.page("""<div class="resume"><div role="progressbar" aria-valuenow="0">0%</div>
            <button aria-label="delete" type="button"></button></div>""")
        self.assertFalse(apply_run._resume_landed(page, "C:/x/Caleb_Schulte_Resume.pdf", wait_ms=0))


def consent_page(*buttons: str) -> str:
    """A form under a cookie dialog and its backdrop, the way Workable serves one."""
    close = ("document.querySelectorAll('[data-ui=backdrop],[role=dialog]').forEach(e => e.remove());"
             "window.said = this.innerText")
    shown = "".join(f'<button onclick="{close}">{b}</button>' for b in buttons)
    return f"""
<form><label for="fn">First name</label><input id="fn" name="fn"></form>
<div data-ui="backdrop" style="position:fixed;inset:0;background:rgba(0,0,0,.3)"></div>
<div role="dialog" aria-modal="true" aria-label="Cookie Consent"
     style="position:fixed;left:0;right:0;bottom:0;background:#fff;padding:20px">
  This website uses cookies to improve your experience. {shown}</div>"""


class ACookieDialogOverTheFormIsCleared(unittest.TestCase):
    def test_optional_cookies_are_declined_and_the_form_takes_typing(self):
        page = Browser.page(consent_page("Cookies settings", "Accept all", "Decline all"))
        self.assertEqual(apply_run.clear_consent(page), "declined")
        self.assertEqual(page.evaluate("() => window.said"), "Decline all")
        page.fill("#fn", "Caleb", timeout=3000)
        self.assertEqual(page.evaluate("() => document.querySelector('#fn').value"), "Caleb")

    def test_a_banner_with_no_way_to_decline_is_accepted_and_says_so(self):
        page = Browser.page(consent_page("Got it"))
        self.assertEqual(apply_run.clear_consent(page), "accepted")

    def test_no_banner_touches_nothing(self):
        page = Browser.page("<form><label for='fn'>First name</label><input id='fn'></form>")
        self.assertEqual(apply_run.clear_consent(page), "")


class AnEssayThatMentionsALinkIsNotTheLink(unittest.TestCase):
    def match(self, label, tag="textarea"):
        return formfill.match_field({"label": label, "tag": tag, "type": tag})

    def test_the_hugging_face_question(self):
        self.assertIsNone(self.match(
            "Tell us about something you've built on top of our tools, in the last few years. "
            "What was it, and what was the tricky part? Share a public link if you have one "
            "(GitHub, a demo, a write-up)."))

    def test_a_plain_ask_for_the_link_still_gets_it(self):
        self.assertEqual(self.match("Share your LinkedIn profile", tag="input"), "linkedin")
        self.assertEqual(self.match("*\nGithub profile"), "github")


if __name__ == "__main__":
    unittest.main()
