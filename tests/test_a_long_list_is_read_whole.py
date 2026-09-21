"""A dropdown is read whole, and the question it becomes carries its options.

2026-09-13, Palantir's Lever form (apply-6d06e852). "Which university are you
currently attending or did you last attend?" is a <select> of 3,302 options
ending "Did not attend university" and "Other - School Not Listed". The page
reader took the first 60. His school, University of South Dakota, is on the
real list - and the record said "'University of South Dakota' is not one of
its options", because in the 60 it was not, and neither was the option the
form tells him to pick without it.

The same record's two questions carried no options at all, so the model
answering from his facts wrote "Palantir's careers page" for a list that says
"Palantir Website", and that answer, saved on the record, was refused on
every re-stage.
"""
from __future__ import annotations

import unittest
from unittest import mock

from aletheia import apply_run, campaign, formfill, profile

USD = "University of South Dakota"
OTHER = "Other - School Not Listed"
UNIVERSITY_LABEL = ('Which university are you currently attending or did you last attend? '
                    'Please select "Other (School Not Listed)" if your school is not listed.\n✱')
HEARD_LABEL = "Please tell us how you heard about this opportunity.\n✱"
#: Palantir's list, exactly as the page offers it (21, placeholder included).
PALANTIR_HEARD = ["Select...", "Agency or Non-Palantir Recruiter", "America's Job Exchange",
                  "BuiltIn", "Campus Ambassador", "Friend or Family", "Glassdoor", "Hackajob",
                  "Hallo", "Handshake", "Job Board (Indeed, Monster, etc.)", "LinkedIn",
                  "Palantir Event", "Palantir Medium Blog", "Palantir Recruiter",
                  "Palantir Website", "Rewriting the Code", "Tapia", "University Job Board",
                  "University or University Organization", "Other"]


def universities(*, with_his=True) -> list[str]:
    """3,302 options shaped like the real list: his school far past the 60th,
    a few names that contain words from a race list, and the two escape
    options at the very end."""
    names = [f"School {i:04d}" for i in range(3297)]
    names[10:13] = ["Asian Institute of Technology", "Black Hills State University",
                    "American Indian College"]
    names.insert(2900, USD if with_his else "University of Southern Denmark")
    names += ["South Dakota State University", "Zhongbo Information Technology Research Institute",
              "Did not attend university", OTHER]
    return names


def select(selector, label, texts):
    options = [{"value": t, "text": t} for t in texts]
    return {"selector": selector, "label": label, "tag": "select", "type": "select",
            "required": True, "name": "", "id": "", "value": "", "options": options}


class TheWholeListIsReadCase(unittest.TestCase):
    def test_the_page_reader_no_longer_cuts_a_select_at_sixty(self):
        self.assertNotIn(".slice(0, 60);", formfill.READ_FORM_JS)
        self.assertIn("el.options", formfill.READ_FORM_JS)

    def test_the_fixture_is_the_size_of_the_real_one(self):
        self.assertEqual(len(universities()), 3302)
        self.assertGreater(universities().index(USD), 60)

    def test_his_school_is_found_far_past_the_sixtieth_option(self):
        out = formfill.plan([select("#uni", UNIVERSITY_LABEL, universities())],
                            answers={"school": USD})
        self.assertEqual([(f["selector"], f["value"]) for f in out["fill"]], [("#uni", USD)])
        self.assertEqual(out["ask"], [])

    def test_other_school_not_listed_only_when_his_is_truly_absent(self):
        absent = formfill.plan([select("#uni", UNIVERSITY_LABEL, universities(with_his=False))],
                               answers={"school": USD})
        self.assertEqual([f["value"] for f in absent["fill"]], [OTHER])

    def test_names_in_a_long_list_do_not_make_it_a_protected_question(self):
        texts = universities()
        self.assertEqual(formfill.category_of(UNIVERSITY_LABEL, texts), "")
        self.assertFalse(formfill.is_never_autofill({"label": UNIVERSITY_LABEL, "choices": texts}))
        races = ["American Indian or Alaska Native", "Asian", "Black or African American",
                 "Hispanic or Latino", "White", "I prefer not to disclose"]
        self.assertEqual(formfill.category_of("Please self identify", races), "race",
                         "a real self-identification list is still one")


class WhatTravelsIsBoundedButNotBlindCase(unittest.TestCase):
    def test_a_bounded_list_keeps_his_answer_and_the_escape_options_in_order(self):
        texts = universities()
        kept = formfill.bounded_choices(texts, known={"school": USD, "state": "SD"})
        self.assertLessEqual(len(kept), formfill.MAX_CHOICES_KEPT)
        for needed in (USD, OTHER, "Did not attend university"):
            self.assertIn(needed, kept)
        self.assertEqual(kept, sorted(kept, key=texts.index), "the list's own order")

    def test_a_short_list_is_untouched(self):
        self.assertEqual(formfill.bounded_choices(PALANTIR_HEARD), PALANTIR_HEARD)

    def test_the_question_it_asks_carries_its_options_bounded_with_the_total(self):
        out = formfill.plan([select("#uni", UNIVERSITY_LABEL, universities())], answers={})
        self.assertEqual(len(out["ask"]), 1)
        ask = out["ask"][0]
        self.assertIn(OTHER, ask["choices"])
        self.assertLessEqual(len(ask["choices"]), formfill.MAX_CHOICES_KEPT)
        self.assertEqual(ask["choices_total"], 3302)

    def test_a_select_that_stopped_the_page_comes_back_with_its_options(self):
        """`_unpicked` read `choices`, which a <select> does not have."""
        uni = select("#uni", UNIVERSITY_LABEL, universities())
        with mock.patch.object(profile, "known", return_value={"school": USD}):
            missed, _ = apply_run._unpicked(
                [{"selector": "#uni", "label": UNIVERSITY_LABEL, "value": "USD"}],
                {"#uni": ""}, [uni], [{"label": UNIVERSITY_LABEL, "required": True}])
        self.assertIn(USD, missed[0]["choices"])
        self.assertIn(OTHER, missed[0]["choices"])
        heard = select("#heard", HEARD_LABEL, PALANTIR_HEARD[1:])
        _, rest = apply_run._unpicked([], {}, [heard],
                                      [{"label": HEARD_LABEL, "required": True}])
        self.assertEqual(rest[0]["choices"], PALANTIR_HEARD[1:])

    def test_the_model_is_shown_his_school_and_other_from_a_long_saved_list(self):
        record = {"id": "apply-6d06e852", "url": "https://jobs.lever.co/palantir/x/apply",
                  "questions": [{"selector": "#uni", "label": UNIVERSITY_LABEL, "required": True,
                                 "type": "select", "choices": universities()}]}
        seen = {}

        def think(system, text, **kw):
            seen["choices"] = kw["context"]["questions"][0]["choices"]
            return {"answers": {}}
        with mock.patch.object(profile, "known", return_value={"school": USD}):
            campaign.answer_from_facts(record, "resume", think=think)
        self.assertLessEqual(len(seen["choices"]), formfill.MAX_CHOICES_KEPT)
        self.assertIn(USD, seen["choices"])
        self.assertIn(OTHER, seen["choices"])


class HowHeHeardAboutPalantirCase(unittest.TestCase):
    FOUND_ON = "the company's own careers page"

    def test_the_employers_own_website_is_where_she_found_it(self):
        self.assertEqual(formfill.heard_about_answer(self.FOUND_ON, PALANTIR_HEARD),
                         "Palantir Website")
        self.assertEqual(formfill.heard_about_answer(self.FOUND_ON, PALANTIR_HEARD,
                                                     company="Palantir"), "Palantir Website")

    def test_between_two_websites_the_employers_is_chosen(self):
        both = ["LinkedIn", "University Website", "Palantir Website", "Other"]
        self.assertNotEqual(formfill.heard_about_answer(self.FOUND_ON, both), "Palantir Website",
                            "without the employer's name she cannot tell which site is its own")
        self.assertEqual(formfill.heard_about_answer(self.FOUND_ON, both, company="Palantir"),
                         "Palantir Website")

    def test_plan_picks_it_off_the_select(self):
        out = formfill.plan([select("#heard", HEARD_LABEL, PALANTIR_HEARD[1:])], answers={},
                            found_on=self.FOUND_ON)
        self.assertEqual([f["value"] for f in out["fill"]], ["Palantir Website"])

    def test_obvious_answers_picks_it_with_no_model(self):
        record = {"id": "apply-6d06e852", "company": "Palantir", "found_on": self.FOUND_ON,
                  "url": "https://jobs.lever.co/palantir/x/apply",
                  "questions": [{"selector": "#heard", "label": HEARD_LABEL, "required": True,
                                 "type": "select", "choices": PALANTIR_HEARD}]}
        self.assertEqual(campaign.obvious_answers(record, "", known={}, sent={}),
                         {"#heard": "Palantir Website"})


class ASavedAnswerThatIsNotAnOptionCase(unittest.TestCase):
    """The record kept a model's words from when it saw no options, and every
    re-stage applied them again and refused them again."""

    def test_palantirs_careers_page_lands_on_palantir_website(self):
        heard = select("#heard", HEARD_LABEL, PALANTIR_HEARD[1:])
        given = {"#heard": "Palantir's careers page"}
        out = formfill.plan([heard], answers=given)
        done = formfill.apply_answers(out, [heard], given)
        self.assertEqual(done["steps"], [{"action": "select", "selector": "#heard",
                                          "value": "Palantir Website"}])
        self.assertEqual(out["ask"], [])

    def test_a_school_not_on_the_list_lands_on_other(self):
        uni = select("#uni", UNIVERSITY_LABEL, universities(with_his=False))
        given = {"#uni": USD}
        out = formfill.plan([uni], answers=given)
        done = formfill.apply_answers(out, [uni], given)
        self.assertEqual([s["value"] for s in done["steps"]], [OTHER])

    def test_his_school_on_the_whole_list_is_his_school(self):
        uni = select("#uni", UNIVERSITY_LABEL, universities())
        given = {"#uni": USD}
        out = formfill.plan([uni], answers=given)
        self.assertEqual([s["value"] for s in formfill.apply_answers(out, [uni], given)["steps"]],
                         [USD])

    def test_a_person_is_not_turned_into_other(self):
        heard = select("#heard", HEARD_LABEL, PALANTIR_HEARD[1:])
        given = {"#heard": "A friend of mine who works there"}
        out = formfill.plan([heard], answers=given)
        done = formfill.apply_answers(out, [heard], given)
        self.assertEqual(done["steps"], [])
        self.assertEqual([a["selector"] for a in out["ask"]], ["#heard"])


if __name__ == "__main__":
    unittest.main()
