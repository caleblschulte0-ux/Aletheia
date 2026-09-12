"""Twelve of thirteen applications blocked on two questions he had answered.

2026-09-12, his first real run. Thirteen applications staged - Stripe,
Databricks, Brex, Samsara, GitLab, Scale AI, Figma, Reddit, Asana, Vercel,
Anthropic, Datadog - and all but one stopped on the same wall::

    Veteran Status      6 jobs
    Disability Status   6 jobs
    Pronouns            3 jobs
    sexual orientation / transgender   2 jobs

He had already answered every one of them, out loud, in his own words:

    "Veteran status. I am not a protected veteran. Disability status. I
    have no disabilities. Pronouns. He, him, his. ... Sexual orientation.
    I don't think they can ask that. If they do, but I'm not answering."

There was nowhere to keep any of it. ``profile.FIELDS`` had no
``veteran_status`` and no ``disability_status``, and ``_DECLARED_NEVER``
excluded exactly these four categories from ``declared_choice``, so every
new form asked him again from scratch.

The rule those exclusions protect is **never GUESSED** - not *never
stored*. An answer invented on his behalf is a lie in a file an employer
keeps; an answer he gave in his own words, reused where the option plainly
says the same thing, is him answering once instead of forty times. Silence
is still silence: with nothing stored, every one of these still goes back
to him.

The option wordings below are verbatim from those thirteen forms.
"""
from __future__ import annotations

import unittest

from aletheia import formfill

VETERAN_ASANA = [
    "I am not a veteran (I did not serve in the military)I am not a veteran "
    "(I did not serve in the military)",
    "I am a veteran and I belong to a classification of protected veterans",
    "I am a veteran and I do NOT belong to a classification of protected veterans",
    "I don't wish to answer",
]
VETERAN_STRIPE = [
    "I am not a protected veteran",
    "I identify as one or more of the classifications of a protected veteran",
    "I don't wish to answer",
]
DISABILITY_SAMSARA = [
    "Yes, I have a disability (or previously had a disability)",
    "No, I don't have a disability",
    "I prefer to self describe",
    "I don't wish to answer",
]
DISABILITY_STRIPE = [
    "Yes, I have a disability, or have had one in the past",
    "No, I do not have a disability and have not had one in the past",
    "I do not want to answer",
]
ORIENTATION_REDDIT = ["Asexual", "Bisexual", "Gay", "Heterosexual", "Lesbian",
                      "I don't wish to answer"]
TRANSGENDER_REDDIT = ["Yes", "No", "I don't wish to answer"]
PRONOUNS_FIGMA = ["she/her/hers", "he/him/his", "they/them/theirs", "self-describe"]

HIS_WORDS = {
    "veteran_status": {"value": "I am not a protected veteran", "source": "operator"},
    "disability_status": {"value": "No", "source": "operator"},
    "pronouns": {"value": "he/him/his", "source": "operator"},
    "self_id_decline": {"value": "Decline", "source": "operator"},
}


class HeAlreadyAnsweredThatCase(unittest.TestCase):
    def test_veteran_status_as_five_employers_word_it(self):
        for options in (VETERAN_ASANA, VETERAN_STRIPE):
            with self.subTest(options=options[0][:30]):
                chosen = formfill.declared_choice("Veteran Status", options,
                                                  stored=HIS_WORDS)
                self.assertIsNotNone(chosen)
                self.assertIn("not", chosen.casefold())
                self.assertNotIn("wish", chosen.casefold())

    def test_disability_status(self):
        for options in (DISABILITY_SAMSARA, DISABILITY_STRIPE):
            with self.subTest(options=options[0][:30]):
                chosen = formfill.declared_choice(
                    "Do you have a physical or mental disability, impairment, or "
                    "condition that substantially limits major life activity? *",
                    options, stored=HIS_WORDS)
                self.assertIsNotNone(chosen)
                self.assertTrue(chosen.casefold().startswith("no"), chosen)

    def test_orientation_and_transgender_are_declined_because_he_declined(self):
        for label, options in (
                ("What sexual orientation do you most closely identify with? *",
                 ORIENTATION_REDDIT),
                ("Are you a person of transgender experience? *", TRANSGENDER_REDDIT)):
            with self.subTest(label=label[:30]):
                chosen = formfill.declared_choice(label, options, stored=HIS_WORDS)
                self.assertEqual(chosen, "I don't wish to answer")

    def test_pronouns(self):
        self.assertEqual(
            formfill.declared_choice("Pronouns", PRONOUNS_FIGMA, stored=HIS_WORDS),
            "he/him/his")

    def test_silence_is_still_silence(self):
        """Nothing stored means it goes back to him - never a guess."""
        for label, options in (("Veteran Status", VETERAN_STRIPE),
                               ("Disability Status", DISABILITY_STRIPE),
                               ("Pronouns", PRONOUNS_FIGMA),
                               ("What sexual orientation do you identify with?",
                                ORIENTATION_REDDIT)):
            with self.subTest(label=label):
                self.assertIsNone(formfill.declared_choice(label, options, stored={}))

    def test_only_his_own_words_count(self):
        """A value learned from a resume or a model is not him saying it."""
        guessed = {"veteran_status": {"value": "I am not a protected veteran",
                                      "source": "resume"}}
        self.assertIsNone(
            formfill.declared_choice("Veteran Status", VETERAN_STRIPE, stored=guessed))

    def test_these_questions_are_still_never_autofilled_from_facts(self):
        """The guard that stopped a guess stays exactly where it was."""
        for label in ("Veteran Status", "Disability Status",
                      "What sexual orientation do you identify with?"):
            with self.subTest(label=label):
                self.assertTrue(formfill.is_never_autofill({"label": label}))


if __name__ == "__main__":
    unittest.main()
