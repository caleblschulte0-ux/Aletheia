"""Sixty-one of a hundred and four blockers were boxes he'd leave blank.

2026-09-13. Fourteen finished applications were parked on NEEDS_YOU, and
counting what they were actually waiting for gave: 104 blocking
questions, 43 of them required, **61 optional**. The optional ones were
`Twitter`, `Website`, `Portfolio`, `Other Links`, `Personal Website` —
with `why` reading, honestly and uselessly, "she does not know his
Twitter".

He does not have a Twitter. He does not have a personal site. The form
does not require either. So the application was complete, and she stopped
to ask him to come back and type nothing into a box nobody needs filled.

That is worse than it sounds, because it is indistinguishable from a
real question in the queue: fourteen applications "waiting on him" reads
as fourteen things he has to do, and the actual number was closer to
three. A queue padded with non-questions is a queue he stops reading.

The rule: an OPTIONAL field she has no fact for is skipped, with a `why`
that says so. Required stays required — a required box she cannot answer
is still his, because submitting a form with a mandatory field blank
either fails or misrepresents him.

The veteran half of this file is the same shape one layer down. He
answered once, on the 12th: "I am not a protected veteran". Greenhouse
asks "Protected Veteran Status" and offers that sentence back. Robinhood
asks "What is your military status?" and offers "No military service" —
the same answer in a different dialect. `declared_choice` had two
branches, each testing HIS wording and then searching only for options in
its own dialect, and the second one RETURNED rather than falling through,
so Robinhood reached him with his own answer sitting on file.
"""
from __future__ import annotations

import unittest

from aletheia import formfill


def field(label, *, required=False, type="text", selector=None):
    return {"label": label, "selector": selector or "#" + label.lower()[:8],
            "type": type, "required": required}


class TheBlankBoxHeCannotFillCase(unittest.TestCase):
    """An optional box with no fact behind it is not a question."""

    def plan_for(self, *fields, answers=None):
        return formfill.plan(list(fields), answers=answers or {})

    def test_an_optional_link_he_does_not_have_is_skipped(self):
        out = self.plan_for(field("Twitter"), field("Website"), field("Portfolio"))
        self.assertEqual(out["ask"], [], "he has none of these and none are required")
        self.assertEqual(len(out["skipped"]), 3)

    def test_a_free_text_box_is_NOT_a_link_field(self):
        """"Other Links" reads like one and is not: nothing maps it to a
        field of hers, so she genuinely cannot tell what it wants. My first
        version of this test asserted it was skipped, which was me writing
        down what I wanted rather than the rule — the narrow set is keyed on
        fields where HAVING NOTHING IS THE ANSWER, not on labels that look
        link-shaped."""
        out = self.plan_for(field("Other Links"))
        self.assertEqual(len(out["ask"]), 1)
        self.assertIn("could not tell", out["ask"][0]["why"])

    def test_a_REQUIRED_box_she_cannot_answer_is_still_his(self):
        """The line that keeps this from being a way to submit bad forms."""
        out = self.plan_for(field("Website", required=True))
        self.assertEqual(len(out["ask"]), 1)
        self.assertEqual(out["skipped"], [])

    def test_the_skip_says_why_in_words_he_would_use(self):
        out = self.plan_for(field("Portfolio"))
        why = out["skipped"][0]["why"]
        self.assertNotIn("profile", why.lower())
        self.assertNotIn("_", why)

    def test_an_optional_box_she_CAN_answer_is_still_filled(self):
        """Skipping optional fields must not stop her filling the ones she
        knows — that would trade one silence for a worse one."""
        out = self.plan_for(field("LinkedIn Profile"),
                            answers={"linkedin": "https://www.linkedin.com/in/x"})
        self.assertEqual(out["ask"], [])
        self.assertTrue(out["fill"], "she has this one and should type it")


class OneAnswerManyDialectsCase(unittest.TestCase):
    """He said it once. Every employer words it differently."""

    STORED = {"veteran_status": {"value": "I am not a protected veteran",
                                 "source": "operator"}}

    def choice(self, label, options):
        return formfill.declared_choice(label, options, stored=self.STORED)

    def test_the_wording_that_reached_him_with_his_answer_on_file(self):
        """Robinhood, live 2026-09-13."""
        self.assertEqual(
            self.choice("What is your military status?*",
                        ["No military service", "Veteran", "Active duty",
                         "Decline to answer"]),
            "No military service")

    def test_the_wording_that_already_worked_still_works(self):
        self.assertEqual(
            self.choice("Protected Veteran Status*",
                        ["I identify as one or more of the classifications of a "
                         "protected veteran", "I am not a protected veteran",
                         "I don't wish to answer"]),
            "I am not a protected veteran")

    def test_the_option_that_says_not_about_something_else(self):
        """Asana offers two options containing "not", and only one of them
        says he is not a veteran. A bare "not" answered neither."""
        self.assertEqual(
            self.choice("Veteran Status",
                        ["I am not a veteran (I did not serve in the military)",
                         "I am a veteran and I do NOT belong to a classification "
                         "of protected veterans", "I decline to answer"]),
            "I am not a veteran (I did not serve in the military)")

    def test_a_plain_yes_or_no(self):
        self.assertEqual(
            self.choice("Are you a protected veteran?", ["Yes", "No",
                                                         "I prefer not to say"]),
            "No")

    def test_silence_is_still_silence(self):
        """Nothing on file answers nothing. The whole point of reading only
        his own words is that a blank profile cannot be guessed into one."""
        self.assertIsNone(
            formfill.declared_choice("What is your military status?*",
                                     ["No military service", "Veteran"],
                                     stored={}))


if __name__ == "__main__":
    unittest.main()
