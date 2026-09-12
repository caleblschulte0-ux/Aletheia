"""Routine paperwork she handles; one box she never touches.

2026-09-12. Thirteen real applications, several held up by boxes that ask
nothing about him: "may we process your personal data", "I have read the
applicant privacy notice", "I confirm the information above is accurate",
"Agreement to Arbitrate". His words::

    "I don't really get what the consent and certifications is. Just figure
    out a way around it. It's not that big a deal."

and, when I said I would not tick an arbitration agreement for him::

    "I mean, what would I ever wanna sue anthropic for? I'm just trying to
    apply my job. ... the only thing that I wouldn't want you to ever auto
    click on is something like, hey. You'll go to jail if you use AI on
    this. Like, that's the only thing that you should never auto click on
    in my mind."

So the line he drew, exactly: routine agreements are ticked, and anything
declaring how the application itself was written - or carrying real legal
jeopardy - is never ticked. Samsara and Anthropic both carry an "AI Policy
for Application" box: a declaration about using AI, offered to the thing
writing the application. A false one is his problem for as long as he
works there, so it stays his.

The accuracy certifications are true because of the approval gate: every
application is shown to him and nothing is sent without him saying yes.
"""
from __future__ import annotations

import unittest

from aletheia import formfill


def _box(label, choices=(), selector="#c", type_="checkbox"):
    return {"selector": selector, "label": label, "name": "", "id": "",
            "tag": "input", "type": type_, "required": True, "value": "",
            "choices": list(choices)}


class RoutinePaperworkCase(unittest.TestCase):
    #: Verbatim from the thirteen forms.
    ROUTINE = [
        ("Do you consent to Brex processing your personal information for the "
         "purpose of assessing your candidacy for this position?", ["Consent"]),
        ("Processing of Personal Data*", ["Acknowledge/Confirm"]),
        ("By checking this box, I consent to Asana collecting, storing, and "
         "processing my responses to the demographic data surveys above.*", []),
        ("By submitting my application, I acknowledge that I have read and "
         "understand Vercel's Job Applicant Privacy Notice", ["Acknowledge/Confirm"]),
        ("Please double-check all the information provided above. Ensuring "
         "accuracy is crucial.*",
         ["I have reviewed and confirmed that all the information provided is "
          "accurate and complete."]),
        ("Agreement to Arbitrate*",
         ["I understand and agree to the terms of the Agreement to Arbitrate set "
          "forth above."]),
        ("Please read the arbitration agreement below*",
         ["I will read the arbitration agreement below."]),
    ]

    def test_the_routine_ones_are_ticked(self):
        for label, choices in self.ROUTINE:
            with self.subTest(label=label[:44]):
                self.assertIsNotNone(
                    formfill.routine_consent(label, choices or [label]),
                    "this is paperwork, and it was blocking real applications")

    def test_the_ai_declaration_is_never_ticked(self):
        """The one he named. Both Samsara and Anthropic ask it."""
        for label in ("AI Policy for Application*",
                      "AI Policy for Interviewers*",
                      "I certify that I did not use AI tools to complete this "
                      "application.",
                      "I confirm this application was completed without "
                      "artificial intelligence assistance.",
                      "I agree not to use ChatGPT or any large language model "
                      "during the interview process."):
            with self.subTest(label=label[:44]):
                self.assertIsNone(formfill.routine_consent(label, ["Yes", "No"]))
                self.assertIsNone(formfill.routine_consent(label, ["I agree"]))

    def test_legal_jeopardy_is_never_ticked(self):
        for label in ("I declare under penalty of perjury that the foregoing is true.",
                      "I understand a false statement may result in criminal "
                      "prosecution.",
                      "I authorize a background check and credit check.",
                      "I consent to a pre-employment drug screen."):
            with self.subTest(label=label[:44]):
                self.assertIsNone(formfill.routine_consent(label, ["I agree"]))

    def test_a_real_question_is_not_paperwork(self):
        """"Acknowledge and agree" is not enough to make something routine.

        "This role requires in-office work three days per week (Mon, Wed,
        Thurs). Do you acknowledge and agree to this requirement?" is a
        commitment about his week, not a form to sign - he answers it.
        """
        for label in ("Why do you want to join Figma?*",
                      "Are you legally authorized to work in the United States?",
                      "This role requires in-office work three days per week. Do "
                      "you acknowledge and agree to this requirement?*"):
            with self.subTest(label=label[:44]):
                got = formfill.routine_consent(label, ["Yes", "No"])
                self.assertIsNone(got, f"{label!r} got {got!r}")

    def test_it_never_picks_the_refusing_option(self):
        chosen = formfill.routine_consent(
            "By agreeing here I certify that the information I provided is "
            "accurate and truthful.", ["Yes", "No"])
        self.assertEqual(chosen, "Yes")

    def test_the_plan_ticks_paperwork_and_still_asks_about_ai(self):
        form = [_box("Processing of Personal Data*", ["Acknowledge/Confirm"],
                     selector="#data"),
                _box("AI Policy for Application*", ["Yes", "No"], selector="#ai")]
        out = formfill.plan(form, answers={})
        filled = {step["selector"] for step in out["fill"]}
        asked = {row["selector"] for row in out["ask"]}
        self.assertIn("#data", filled)
        self.assertIn("#ai", asked, "the AI declaration is always his")


if __name__ == "__main__":
    unittest.main()
