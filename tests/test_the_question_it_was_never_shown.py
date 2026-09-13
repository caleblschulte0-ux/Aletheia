"""Twenty-seven answerable questions, withheld for being optional.

2026-09-13, counted against his live blocked applications. The single
largest reason anything was waiting on him read "she could not tell what
this is asking for" — seventy-odd questions — and twenty-seven of those
were things a person answers without thinking:

    Are you 18 years of age or older?
    This role requires in-office work three days per week. Do you agree?
    Do you currently reside in the New York, NY or San Francisco, CA area?
    Have you previously worked at Capital One or a company it acquired?
    Are you able to work a hybrid schedule (2-3x week) in NYC?

Every one of them settled by facts he had already given, and every one
marked OPTIONAL by the form — so `answer_from_facts` filtered them out
before the model ever saw them. The brief was not wrong. It could not
answer a question it was never shown.

Optional is not the same as unimportant. Greenhouse marks plenty of real
questions optional, and a blank one still reads as an incomplete
application to whoever opens it.

Nothing about the gates changed, and the tests that say so are the point
of this file: `is_never_autofill` still removes protected and legal
questions before the model sees them AND again on the way back, the
validator still drops any selector that was not offered, and a question
with choices may still only be answered with one of its own choices.
Widening what is ASKED must never widen what is ACCEPTED.
"""
from __future__ import annotations

import unittest

from aletheia import campaign


RESUME = "Caleb Schulte — Business Development. Barkly Financial, 2023-2026."


def question(selector, label, *, required=False, choices=None, type="text"):
    row = {"selector": selector, "label": label, "required": required,
           "type": type}
    if choices:
        row["choices"] = list(choices)
    return row


def record(questions):
    return {"url": "https://boards.greenhouse.io/x", "job_title": "BDR",
            "found_on": "the company's own careers page", "questions": questions}


class TheQuestionItWasNeverShownCase(unittest.TestCase):
    def offered(self, questions, answers=None):
        """What actually reached the model, and what came back."""
        seen = {}

        def think(system, text, **kw):
            seen.update(kw["context"])
            seen["validator"] = kw["validator"]
            return kw["validator"]({"answers": answers or []})

        got = campaign.answer_from_facts(record(questions), RESUME, think=think)
        labels = [q["label"] for q in seen.get("questions", [])]
        return labels, got

    def test_an_optional_question_reaches_the_model(self):
        """The defect. Every one of these was withheld for being optional."""
        labels, _ = self.offered([
            question("#age", "Are you 18 years of age or older?"),
            question("#office", "This role requires in-office work three days "
                                "per week (Mon, Wed, Thurs). Do you agree?"),
            question("#nysf", "Do you currently reside in the New York, NY or "
                              "San Francisco, CA area?"),
        ])
        self.assertEqual(len(labels), 3, labels)

    def test_a_required_question_still_reaches_it(self):
        labels, _ = self.offered([question("#start", "Earliest start date*",
                                           required=True)])
        self.assertEqual(len(labels), 1)

    def test_a_protected_question_still_never_reaches_it(self):
        """The gate that makes widening safe. These are his, always —
        whether the form calls them required or not."""
        labels, _ = self.offered([
            question("#gender", "Gender"),
            question("#felony", "Have you ever been convicted of a felony?"),
            question("#dob", "Date of birth"),
            question("#vet", "Protected veteran status", required=True),
            question("#ok", "Are you 18 years of age or older?"),
        ])
        self.assertEqual(labels, ["Are you 18 years of age or older?"], labels)

    def test_a_protected_answer_is_refused_even_if_a_model_returns_one(self):
        """Belt and braces: the validator re-checks, so a model that
        answers something it was never offered gets nowhere."""
        _, got = self.offered(
            [question("#ok", "Are you 18 years of age or older?",
                      choices=["Yes", "No"])],
            answers=[{"selector": "#ok", "answer": "Yes"},
                     {"selector": "#felony", "answer": "No"}])
        self.assertEqual(got, {"#ok": "Yes"})

    def test_an_answer_must_be_one_of_the_questions_own_choices(self):
        _, got = self.offered(
            [question("#where", "Where would you work from?",
                      choices=["United States", "Canada"])],
            answers=[{"selector": "#where", "answer": "Mars"}])
        self.assertEqual(got, {})

    def test_essays_and_uploads_are_still_left_alone(self):
        """Written answers go down their own path, and a file is his to
        choose. Folding those in here is a different change."""
        labels, _ = self.offered([
            question("#why", "Why do you want to work here?", type="textarea"),
            question("#cv", "Resume/CV", type="file"),
            question("#city", "Current location", type="search"),
            question("#ok", "Are you 18 years of age or older?"),
        ])
        self.assertEqual(labels, ["Are you 18 years of age or older?"], labels)

    def test_a_long_form_is_bounded_and_drops_the_optional_tail_first(self):
        """A form offering a 39-language list and an 81-entry country picker
        would otherwise spend the context on menus before reaching the four
        questions that matter."""
        questions = [question(f"#opt{i}", f"Optional {i}",
                              choices=[str(n) for n in range(40)])
                     for i in range(campaign.MAX_QUESTIONS_ASKED + 20)]
        questions.append(question("#must", "Earliest start date*", required=True))
        labels, _ = self.offered(questions)
        self.assertEqual(len(labels), campaign.MAX_QUESTIONS_ASKED)
        self.assertIn("Earliest start date*", labels,
                      "the required one is never what gets dropped")


class AConditionalQuestionIsNotAnInvitationCase(unittest.TestCase):
    """"If you are not authorized to work here, what sponsorship would you
    need?" — he IS authorized. Naming a sponsorship there would be a false
    statement on an application, and Brex asked it on four separate forms."""

    def test_the_brief_says_so(self):
        self.assertIn("N/A", campaign.ANSWER_BRIEF)
        brief = campaign.ANSWER_BRIEF.casefold()
        self.assertIn("only applies if", brief)


if __name__ == "__main__":
    unittest.main()
