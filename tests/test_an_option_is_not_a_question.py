"""Twelve questions on a Spotify form, and not one of them was a question.

2026-09-13, live. The staged record listed these as things he had to
answer: "He/him". "Woman". "Woman". "Woman". "Woman". "EN". "Any other
ethnic group". "American Indian or Alaska Native". "Yes". Every one an
OPTION wearing a question's clothes — and four of them things he had
already told her (pronouns, gender, and two survey questions his profile
settles).

The cause is one line of the form reader. A checkbox or radio is folded
into its question by `row.group = el.name`, because radios in a group
share a name — which is true of Greenhouse, and false of Spotify, whose
survey gives every single option its own name:

    surveysResponses[cbf1b3c9-...][responses][field0]
    surveysResponses[cbf1b3c9-...][responses][field1]
    surveysResponses[cbf1b3c9-...][responses][field2]

So each radio became a group of ONE, and `_group_choices` demotes a group
of one back to a standalone field — labelled, reasonably enough, with its
only option. The question text was sitting in the container heading the
whole time.

This is the same defect the grouping code was written for (a Stripe form
asked one question as 26 country checkboxes and produced 26 unanswerable
questions), reappearing through the one assumption that code made about
how a form names things.

The test drives real Chromium against markup shaped like Spotify's,
because the fix is browser-side JavaScript and a Python-level fixture
would be asserting my own idea of what the page returns — which is
exactly the mistake that produced a "0 of 93 answered" measurement
earlier the same night. It skips cleanly with no browser, and launches
its own throwaway profile so it can never queue behind the real one.
"""
from __future__ import annotations

import unittest

from aletheia import formfill


SPOTIFY_SHAPED = """
<form>
  <div class="field">
    <div class="label">What is your gender?</div>
    <ul>
      <li><input type="radio" name="surveysResponses[abc][responses][field0]"
                 id="g0"><label for="g0">Woman</label></li>
      <li><input type="radio" name="surveysResponses[abc][responses][field1]"
                 id="g1"><label for="g1">Man</label></li>
      <li><input type="radio" name="surveysResponses[abc][responses][field2]"
                 id="g2"><label for="g2">Non-binary</label></li>
    </ul>
  </div>
  <fieldset>
    <legend>Which country do you work from?</legend>
    <input type="radio" name="country" id="c0"><label for="c0">Sweden</label>
    <input type="radio" name="country" id="c1"><label for="c1">United States</label>
  </fieldset>
</form>
"""


def chromium():
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        return None
    try:
        return sync_playwright().start()
    except Exception:
        return None


class AnOptionIsNotAQuestionCase(unittest.TestCase):
    """One launch for the class: fifteen seconds a test is how a suite
    stops being run."""

    @classmethod
    def setUpClass(cls):
        cls.pw = chromium()
        if cls.pw is None:
            raise unittest.SkipTest("no playwright/browser here")
        try:
            cls.browser = cls.pw.chromium.launch()
        except Exception as exc:                    # no browser binary
            cls.pw.stop()
            raise unittest.SkipTest(f"no chromium: {type(exc).__name__}")

    @classmethod
    def tearDownClass(cls):
        try:
            cls.browser.close()
        finally:
            cls.pw.stop()

    def rows(self, html):
        page = self.browser.new_page()
        try:
            page.set_content(html)
            return page.evaluate(formfill.READ_FORM_JS)
        finally:
            page.close()

    def test_options_with_unique_names_still_fold_into_one_question(self):
        """Spotify's shape. Three radios, three different names, one
        question — and the question is the heading, not "Woman"."""
        rest, groups = formfill._group_choices(self.rows(SPOTIFY_SHAPED))
        gender = [g for g in groups if "gender" in (g["label"] or "").casefold()]
        self.assertEqual(len(gender), 1,
                         f"expected one gender question, got {[g['label'] for g in groups]}")
        self.assertEqual(len(gender[0]["options"]), 3)
        self.assertNotIn("Woman", gender[0]["label"],
                         "the label is the question, never its first option")

    def test_a_form_that_names_its_radios_properly_is_untouched(self):
        """Greenhouse shares one name across a group, and that path must
        keep working exactly as it did — the fix may only ever ADD."""
        rest, groups = formfill._group_choices(self.rows(SPOTIFY_SHAPED))
        country = [g for g in groups if "country" in (g["label"] or "").casefold()]
        self.assertEqual(len(country), 1)
        self.assertEqual(sorted(o["label"] for o in country[0]["options"]),
                         ["Sweden", "United States"])

    def test_nothing_is_left_masquerading_as_its_own_question(self):
        rest, groups = formfill._group_choices(self.rows(SPOTIFY_SHAPED))
        stray = [f["label"] for f in rest
                 if (f.get("label") or "") in {"Woman", "Man", "Non-binary",
                                               "Sweden", "United States"}]
        self.assertEqual(stray, [], "an option reached him as a question")


if __name__ == "__main__":
    unittest.main()
