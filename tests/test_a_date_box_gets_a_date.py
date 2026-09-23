"""Tenex, live 2026-09-23: "What's the earliest date you can begin at Tenex?"
is a react-datepicker text box with no id and no name under a data-field-path
uuid. The reader skipped it (the uuid looked minted), his answer on file was
prose, and the form went to him as "Please fill out this field." A date box
is read, gets a date counted from today, and takes it on Enter."""
import datetime as dt
import unittest
from unittest import mock

from aletheia import formfill

TENEX = """
<form>
  <div class="ashby-application-form-field-entry" data-field-path="_systemfield_name">
    <label for="_systemfield_name">Name</label><input id="_systemfield_name" name="_systemfield_name" required>
  </div>
  <div class="_fieldEntry_1e3gg_28 ashby-application-form-field-entry" data-field-path="879c5fd0-d019-45b8-b6f4-e209b6be0203"
       data-field-entry-id="54deb48a-c933-4b77-ac87-bee97fb77e80_879c5fd0-d019-45b8-b6f4-e209b6be0203">
    <label class="_heading _required_f7cvd_91 _label_1e3gg_42" for="879c5fd0-d019-45b8-b6f4-e209b6be0203">What's the earliest date you can begin at Tenex?</label>
    <div class="react-datepicker-wrapper"><div class="react-datepicker__input-container">
      <input type="text" placeholder="Pick date..." class="_input_gc9ve_28 ashby-application-form-input-date" required="" value="">
    </div></div>
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


class TheDateBoxIsRead(unittest.TestCase):
    def test_tenexs_start_date_box_is_read_as_a_required_date_widget(self):
        page = Browser.page(TENEX)
        rows = page.evaluate(formfill.READ_FORM_JS)
        box = next((r for r in rows if r["label"].startswith("What's the earliest")), None)
        self.assertIsNotNone(box, [r["label"] for r in rows])
        self.assertTrue(box["date_widget"])
        self.assertTrue(box["required"])
        # CSS.escape writes a leading digit as "\38 7..."; the rule is that the
        # field's own key names it and the selector finds exactly it
        self.assertTrue(box["selector"].startswith('[data-field-path="'), box["selector"])
        self.assertEqual(len(page.query_selector_all(box["selector"])), 1)
        self.assertEqual(page.query_selector(box["selector"]).get_attribute("placeholder"), "Pick date...")
        self.assertEqual(formfill.match_field(box), "notice_period")

    def test_the_plan_gives_it_a_date_counted_from_today_and_presses_enter(self):
        page = Browser.page(TENEX)
        rows = page.evaluate(formfill.READ_FORM_JS)
        with mock.patch("aletheia.profile.known", return_value={"notice_period": "Two weeks from an accepted offer.",
                                                                  "first_name": "Caleb", "last_name": "Schulte",
                                                                  "full_name": "Caleb Schulte"}):
            out = formfill.plan(rows, answers={"notice_period": "Two weeks from an accepted offer.",
                                               "full_name": "Caleb Schulte"})
        row = next(f for f in out["fill"] if f["label"].startswith("What's the earliest"))
        expected = (dt.date.today() + dt.timedelta(days=14)).strftime("%m/%d/%Y")
        self.assertEqual(row["value"], expected)
        steps = formfill.steps(out["fill"])
        i = next(k for k, s in enumerate(steps) if s["selector"] == row["selector"] and s["action"] == "type")
        self.assertEqual(steps[i + 1], {"action": "press", "selector": row["selector"], "value": "Enter"})

    def test_words_that_name_no_date_are_his_to_answer(self):
        page = Browser.page(TENEX)
        rows = page.evaluate(formfill.READ_FORM_JS)
        out = formfill.plan(rows, answers={"notice_period": "After my current project wraps up.",
                                           "full_name": "Caleb Schulte"})
        asked = next(a for a in out["ask"] if a["label"].startswith("What's the earliest"))
        self.assertIn("does not name a date", asked["why"])


class WhatHisWordsComeTo(unittest.TestCase):
    def test_spans_dates_and_soon(self):
        today = dt.date(2026, 9, 23)
        self.assertEqual(formfill.start_date_from("Two weeks from an accepted offer.", today), dt.date(2026, 10, 7))
        self.assertEqual(formfill.start_date_from("30 days notice", today), dt.date(2026, 10, 23))
        self.assertEqual(formfill.start_date_from("one month", today), dt.date(2026, 10, 23))
        self.assertEqual(formfill.start_date_from("Immediately", today), today)
        self.assertEqual(formfill.start_date_from("2026-11-01", today), dt.date(2026, 11, 1))
        self.assertEqual(formfill.start_date_from("11/01/2026", today), dt.date(2026, 11, 1))
        self.assertIsNone(formfill.start_date_from("after my current project", today))
        self.assertIsNone(formfill.start_date_from("", today))


if __name__ == "__main__":
    unittest.main()
