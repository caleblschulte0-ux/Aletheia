"""Three standing rules he gave once, so no form asks him again.

2026-09-12, after three applications went in and six came back each
needing one more thing::

    "it needs to be able to handle these weird outlier questions with my
    simple baseline. Which is where I work in? Any city. Would I be willing
    to relocate? Yes. The Versa one, that sounds like an issue that you need
    to fix. I don't need to give the go ahead to draft a why you want to
    join ... just have AI write it off the bat. It does not need to
    check-in with me. The AI policy boxes ... if yes is an answer, just hit
    yes. Like, why lie? Yes. We helped you, the AI, to do this."

Three separate things, and only one of them was a missing answer:

- **Vercel was a bug.** "Your authorization to work in the country where
  you live" matched ``country`` on longest-phrase-wins, so the form asking
  whether he may legally work would have been told "United States". The
  same shape as the sponsorship defect the same night: the right words,
  the wrong fact.
- **The AI policy boxes are answerable honestly.** An application written
  with AI, disclosed as written with AI, is true. The only AI box still
  refused is one asserting he did NOT use it - there, yes is the lie.
- **"Why do you want to join X" is never his to write.** It came back to
  him only because Claude was out of session and the draft failed into a
  bare ``except: continue``.
"""
from __future__ import annotations

import unittest

from aletheia import campaign, formfill


def _field(label, **kw):
    base = {"selector": "#q", "label": label, "name": "", "id": "",
            "tag": "input", "type": "text", "required": True, "value": ""}
    base.update(kw)
    return base


class TheVercelQuestionCase(unittest.TestCase):
    #: Live wording from Vercel's form, 2026-09-12.
    VERCEL = ("Your authorization to work in the country where you live. "
              "Please choose the option that describes your situation.")

    def test_it_asks_about_authorization_not_geography(self):
        self.assertEqual(formfill.match_field(_field(self.VERCEL)),
                         "work_authorization")

    def test_every_wording_that_names_a_place_but_asks_permission(self):
        for label in (
                "Are you legally authorized to work in the country in which you are applying?",
                "Do you have the right to work in the United States?",
                "Are you eligible to work in the country where this job is located?",
        ):
            with self.subTest(label=label[:44]):
                self.assertEqual(formfill.match_field(_field(label)),
                                 "work_authorization")

    def test_a_real_country_question_is_still_a_country_question(self):
        for label, expected in (("Country", "country"),
                                ("Please select the country where you currently reside.",
                                 "country"),
                                ("Location (City)", "city")):
            with self.subTest(label=label[:40]):
                self.assertEqual(formfill.match_field(_field(label)), expected)


class TheAiPolicyBoxCase(unittest.TestCase):
    def test_an_acknowledgement_is_answered_yes(self):
        """Samsara and Anthropic both ask it, Yes/No, and yes is true."""
        for label in ("AI Policy for Application*", "AI Policy for Interviewers*",
                      "Do you agree to our AI policy?"):
            with self.subTest(label=label):
                self.assertEqual(formfill.routine_consent(label, ["Yes", "No"]), "Yes")

    def test_a_claim_that_he_did_not_use_ai_is_still_refused(self):
        """His own reasoning, kept: yes only where yes is true."""
        for label in ("I certify that I did not use AI tools to complete this application.",
                      "I confirm this application was completed without artificial "
                      "intelligence assistance.",
                      "I have not used ChatGPT or any large language model here.",
                      "AI was not used in preparing this application."):
            with self.subTest(label=label[:46]):
                self.assertIsNone(formfill.routine_consent(label, ["Yes", "No"]))

    def test_perjury_and_background_checks_are_untouched(self):
        for label in ("I declare under penalty of perjury that this is true.",
                      "I authorize a background check."):
            with self.subTest(label=label[:40]):
                self.assertIsNone(formfill.routine_consent(label, ["I agree"]))


class TheEssayIsNeverHisToWriteCase(unittest.TestCase):
    def test_the_writer_accepts_the_timeout_draft_essays_passes(self):
        """The whole defect in one line: `think(prompt, text, timeout_s=...)`
        against a helper taking two positional arguments raises TypeError
        into `except: continue`, and the question lands on him."""
        import inspect
        signature = inspect.signature(campaign._any_model_writes)
        self.assertIn("timeout_s", signature.parameters)

    def test_a_drafted_answer_is_used_rather_than_asked(self):
        record = {"url": "https://x", "job_title": "AE — Figma",
                  "questions": [{"selector": "#why", "type": "textarea",
                                 "required": True,
                                 "label": "Why do you want to join Figma?*"}]}
        drafted = campaign.draft_essays(
            record, "RESUME",
            think=lambda prompt, text, timeout_s=None: "Because the work is real.")
        self.assertEqual(drafted, {"#why": "Because the work is real."})

    def test_cannot_write_still_comes_back_blank(self):
        """A question his resume does not support is not invented."""
        record = {"url": "https://x", "job_title": "AE",
                  "questions": [{"selector": "#q", "type": "textarea",
                                 "required": True,
                                 "label": "Describe your nuclear engineering work."}]}
        drafted = campaign.draft_essays(
            record, "RESUME",
            think=lambda prompt, text, timeout_s=None: "CANNOT WRITE")
        self.assertEqual(drafted, {})


if __name__ == "__main__":
    unittest.main()
