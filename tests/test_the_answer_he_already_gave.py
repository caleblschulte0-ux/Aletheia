"""He answered these on the 12th. They kept arriving as questions.

2026-09-13, measured against 21 live blocked applications: 116 blocking
questions, and the two largest groups were things already sitting in his
profile, asked in a dialect the matcher could not read.

- **Disability, 14 blockers** (Vercel, Tebra, Gusto, Coinbase). He said
  "No". The matcher required the word "disabilit" to appear in the option
  it picked, which works for the long EEOC wording and finds nothing at
  all in "Do you have a disability or chronic condition? Yes / No" — the
  negation IS the option, with no noun to negate.
- **Pronouns.** Two defects stacked. `declared_choice` returns None for an
  empty option list before reaching any category branch, so the free-text
  case (Spotify's "Write here...", Asana's optional box) was answered by a
  branch that could never run. And the value it would have returned came
  from `_his_word`, which lowercases and strips punctuation for matching —
  so the fix as first written would have typed "he him his" into a real
  employer's form.

The rule both halves share: a question he has already answered is not a
question, and his answer is typed the way HE wrote it.

What must NOT happen is guessing. Every case here has a mirror: a long
ambiguous option list is still his, an empty option list for any other
category is still his, and an empty profile is still his. Those are the
assertions worth keeping — the feature is only safe because they hold.
"""
from __future__ import annotations

import unittest

from aletheia import formfill


SAID = {
    "disability_status": {"value": "No", "source": "operator"},
    "pronouns": {"value": "he/him/his", "source": "operator"},
}


class TheDisabilityBoxHeAlreadyAnsweredCase(unittest.TestCase):
    def choice(self, label, options, stored=None):
        return formfill.declared_choice(
            label, options, stored=SAID if stored is None else stored)

    def test_the_bare_yes_or_no_that_blocked_fourteen(self):
        """Vercel and Tebra, live: "Do you have a disability or chronic
        condition (physical, visual, auditory, cognitive)?" — Yes / No."""
        self.assertEqual(
            self.choice("Do you have a disability or chronic condition "
                        "(physical, visual, auditory, cognitive)?",
                        ["Yes", "No", "I don't wish to answer"]),
            "No")

    def test_the_long_official_wording_still_works(self):
        """The EEOC form this matcher was written for. A fix for the new
        shape that broke the old one would be a straight trade."""
        self.assertEqual(
            self.choice("Disability Status",
                        ["Yes, I have a disability, or have had one in the past",
                         "No, I do not have a disability and have not had one "
                         "in the past", "I do not want to answer"]),
            "No, I do not have a disability and have not had one in the past")

    def test_a_long_ambiguous_list_is_still_his(self):
        """"No" as one of five is not an answer to anything. The bare
        negative only counts when the list is short enough that it can only
        mean the answer."""
        self.assertIsNone(
            self.choice("Which of these apply to you?",
                        ["Yes", "No", "Maybe", "Sometimes", "Prefer not to say"]))

    def test_nothing_on_file_is_never_guessed(self):
        self.assertIsNone(
            self.choice("Do you have a disability?", ["Yes", "No"], stored={}))


class ThePronounBoxWithNothingToClickCase(unittest.TestCase):
    def choice(self, label, options, stored=None):
        return formfill.declared_choice(
            label, options, stored=SAID if stored is None else stored)

    def test_a_free_text_pronoun_box_is_typed(self):
        """Asana's, live. No options at all, and his answer on file."""
        self.assertEqual(
            self.choice('[Optional, if "other" is selected above] My pronouns are',
                        []),
            "he/him/his")

    def test_it_types_HIS_words_not_the_matching_form(self):
        """The defect that would have reached an employer: `_his_word`
        normalises for comparison, and "he him his" is not what he wrote."""
        got = self.choice("What are your preferred gender pronouns? "
                          "(She/Her/Hers; He/Him/His; They/Them/Theirs, etc.)", [])
        self.assertEqual(got, "he/him/his")
        self.assertIn("/", got)

    def test_a_picker_still_picks(self):
        self.assertEqual(
            self.choice("My pronouns are", ["He/Him", "She/Her", "They/Them"]),
            "He/Him")

    def test_an_empty_list_for_ANY_OTHER_category_is_still_his(self):
        """Pronouns are the exception because the box is routinely free
        text. Nothing to click anywhere else means nothing to answer."""
        for label in ("Disability Status", "Protected Veteran Status*", "Gender"):
            self.assertIsNone(self.choice(label, []), label)

    def test_an_empty_profile_is_still_his(self):
        self.assertIsNone(self.choice("My pronouns are", [], stored={}))


if __name__ == "__main__":
    unittest.main()
