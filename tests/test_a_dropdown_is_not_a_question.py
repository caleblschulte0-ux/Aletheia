"""Four real applications, and every one asked him to name a country.

Live 2026-09-11. She found Account Executive roles at Stripe, Databricks,
Brex and Samsara, filled what his facts settle, and handed back nine
"questions". Two of them were on all four::

    List of countries   #iti-0__item-af    radio, 200+ choices, not required
    Search              #iti-0__search-input   search box, not required

Neither is a question. They are the inside of the phone-number country
picker (``intl-tel-input``), which opens *because she fills in his phone
number*. The reCAPTCHA's answer box arrived the same way. So the summary
he got said nine answers were needed when the real number at Stripe was
one, and the first thing he was asked to do was pick his country out of a
list of every country on earth, with dial codes.

His ruling that evening: *"simple typos and mistakes like that cannot
affect ... make sure I can ask this to apply for jobs."*

Matched on the SELECTOR and never the label, because "Search" and "List of
countries" are plausible wordings for a real question - and an employer
who actually asks which countries he can work in must still reach him.
"""
from __future__ import annotations

import unittest

from aletheia import formfill


def _field(selector, label, **kw):
    base = {"selector": selector, "label": label, "name": "", "id": "",
            "tag": "input", "type": "text", "required": False, "value": ""}
    base.update(kw)
    return base


class ADropdownIsNotAQuestionCase(unittest.TestCase):
    def test_the_phone_pickers_country_list_never_reaches_him(self):
        """Exactly what Stripe, Databricks, Brex and Samsara each sent back."""
        form = [_field("#iti-0__item-af", "List of countries", type="radio",
                       tag="input", name="country"),
                _field("#iti-0__search-input", "Search", type="search"),
                _field("#g-recaptcha-response-100000", "g-recaptcha-response",
                       tag="textarea", type="textarea")]
        out = formfill.plan(form, answers={})
        self.assertEqual(out["ask"], [], "he is asked nothing about a picker")
        self.assertEqual([s["selector"] for s in out["skipped"]],
                         ["#iti-0__item-af", "#iti-0__search-input",
                          "#g-recaptcha-response-100000"])
        for row in out["skipped"]:
            self.assertEqual(row["why"], "part of a picker on the page, not a question")

    def test_a_real_question_about_countries_still_reaches_him(self):
        """The label is not the test. An employer really does ask this."""
        form = [_field("#question_62720865",
                       "Which countries are you authorized to work in?",
                       required=True)]
        out = formfill.plan(form, answers={})
        self.assertEqual([q["label"] for q in out["ask"]],
                         ["Which countries are you authorized to work in?"])

    def test_a_real_field_named_search_is_not_swallowed(self):
        form = [_field("#question_99", "Search committee experience", required=True)]
        out = formfill.plan(form, answers={})
        self.assertEqual(len(out["ask"]), 1)

    def test_the_predicate_is_about_the_selector_not_the_words(self):
        self.assertTrue(formfill.is_widget_furniture({"selector": "#iti-0__item-gb"}))
        self.assertTrue(formfill.is_widget_furniture(
            {"selector": "#x", "name": "g-recaptcha-response"}))
        self.assertFalse(formfill.is_widget_furniture(
            {"selector": "#question_1", "label": "List of countries"}))


if __name__ == "__main__":
    unittest.main()
