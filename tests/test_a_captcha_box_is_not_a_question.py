"""A CAPTCHA's token box is not a question, and nothing is ever typed into it.

Live 2026-09-14, Palantir's Lever form (apply-6d06e852, "Legal Operations
Specialist"). The record put six "questions" in front of him:

    Language Skill(s) (Check all that apply)   a real question
    EN                                         hCaptcha's own language picker
    Name                                       eeo[disabilitySignature]
    Date                                       eeo[disabilitySignatureDate]
    h-captcha-response                         @frame1|textarea[name="h-captcha-response"]
    h-captcha-response                         @frame2|#h-captcha-response-0pnpz9pkswmi

and its answers held a model-written essay about Palantir keyed to
`@frame3|textarea[name="h-captcha-response"]`, ready to be typed into the
CAPTCHA on the next stage.

Root cause: the furniture test read the START of the selector for "#h-captcha-
response", and a field read inside a frame starts "@frame1|". Nothing read the
frame's address, so everything inside hCaptcha's frames - its token boxes and
its language list - was read as the employer's form. And a box nobody can see
(a honeypot, a display:none textarea) was a question like any other.

The CAPTCHA itself stays his: the form is still marked as carrying one, and
nothing here solves or touches it.
"""
from __future__ import annotations

import unittest
from unittest import mock

from aletheia import apply_run, campaign, formfill, stateio
from tests.test_apply_run import ApplyCase

LEVER = "https://jobs.lever.co/palantir/18383723-04a2-44ae-ae58-1166a76f0859/apply"
HCAPTCHA_CHECKBOX = ("https://newassets.hcaptcha.com/captcha/v1/7d3c1f0/static/"
                     "hcaptcha.html#frame=checkbox&id=0pnpz9pkswmi&host=jobs.lever.co")
HCAPTCHA_CHALLENGE = ("https://newassets.hcaptcha.com/captcha/v1/7d3c1f0/static/"
                      "hcaptcha.html#frame=challenge&id=0pnpz9pkswmi&host=jobs.lever.co")
LANGS = 'input[name="cards\\[a69a985a-eae9-4c14-90fb-b5a4b891523e\\]\\[field0\\]"]'
ESSAY = ("Palantir builds platforms that help organizations make better decisions "
         "through data analysis and process optimization.")


def _row(selector, label, **kw):
    base = {"selector": selector, "tag": "input", "type": "text", "name": "", "id": "",
            "role": "", "label": label, "required": False, "value": "", "hidden": False}
    base.update(kw)
    return base


def _language_option(text):
    return _row(f'{LANGS}[value="{text}"]', text, type="checkbox", checked=False,
                name="cards[a69a985a-eae9-4c14-90fb-b5a4b891523e][field0]",
                option=text, question="Language Skill(s) (Check all that apply)\n✱",
                group="cards[a69a985a-eae9-4c14-90fb-b5a4b891523e][field0]", required=True)


# What READ_FORM_JS returns in Lever's own document.
LEVER_ROWS = [
    _row('input[name="name"]', "Full name\n✱", name="name", required=True),
    _row('input[name="email"]', "Email\n✱", name="email", type="email", required=True),
    _row('input[name="phone"]', "Phone", name="phone", type="tel"),
    *[_language_option(t) for t in ("English (ENG)", "Spanish (SPA)", "Other")],
    _row('input[name="eeo\\[disabilitySignature\\]"]', "Name", name="eeo[disabilitySignature]"),
    _row('input[name="eeo\\[disabilitySignatureDate\\]"]', "Date",
         name="eeo[disabilitySignatureDate]"),
    # Lever's own copy of the token box, display:none under div.h-captcha.
    _row('textarea[name="h-captcha-response"]', "h-captcha-response", tag="textarea",
         type="textarea", name="h-captcha-response", hidden=True),
]
# Inside hCaptcha's frames. The checkbox frame and the challenge frame each hold
# a token textarea; the challenge frame holds the language picker, which
# READ_ARIA_JS reads as a listbox named "EN".
CHECKBOX_FRAME_ROWS = [
    _row('textarea[name="h-captcha-response"]', "h-captcha-response", tag="textarea",
         type="textarea", name="h-captcha-response", hidden=True)]
CHALLENGE_FRAME_ROWS = [
    _row("#h-captcha-response-0pnpz9pkswmi", "h-captcha-response", tag="textarea",
         type="textarea", id="h-captcha-response-0pnpz9pkswmi")]
CHALLENGE_ARIA_ROWS = [
    {"selector": f"#language-list > div:nth-of-type(1) > div:nth-of-type({i})", "tag": "aria",
     "type": "radio", "name": "", "id": "", "group": "aria:0", "question": "EN",
     "option": lang, "label": lang, "required": False, "value": "", "wraps": "",
     "checked": False}
    for i, lang in enumerate(("Afrikaans", "Albanian", "English"), start=1)]


class Frame:
    def __init__(self, url, form=(), aria=()):
        self.url, self.form, self.aria = url, list(form), list(aria)

    def evaluate(self, script, arg=None):
        if script is formfill.READ_FORM_JS:
            return [dict(r) for r in self.form]
        if script is formfill.READ_ARIA_JS:
            return [dict(r) for r in self.aria]
        return None


class PalantirPage:
    """Lever's document plus hCaptcha's two frames, as Playwright lists them."""

    def __init__(self, checkbox_url=HCAPTCHA_CHECKBOX, challenge_url=HCAPTCHA_CHALLENGE):
        self.frames = [Frame(LEVER, LEVER_ROWS),
                       Frame(checkbox_url, CHECKBOX_FRAME_ROWS),
                       Frame(challenge_url, CHALLENGE_FRAME_ROWS, CHALLENGE_ARIA_ROWS)]


def _labels(rows):
    return [" ".join(str(r["label"]).split()) for r in rows]


class ThePalantirFormAsksOneQuestion(unittest.TestCase):
    def test_before_the_fix_a_framed_token_box_passed_the_furniture_test(self):
        """The exact selector from the record. `startswith("#h-captcha-response")`
        never matched "@frame2|#h-captcha-response-...", and nothing else looked."""
        framed = {"selector": "@frame2|#h-captcha-response-0pnpz9pkswmi",
                  "label": "h-captcha-response", "tag": "textarea", "type": "textarea"}
        self.assertTrue(formfill.is_widget_furniture(framed))
        self.assertTrue(formfill.is_anti_bot(framed))
        self.assertTrue(formfill.is_anti_bot(
            {"selector": '@frame3|textarea[name="h-captcha-response"]'}))

    def test_every_row_read_inside_the_captcha_frames_is_marked(self):
        rows = formfill.read_all(PalantirPage())
        inside = [r for r in rows if r["selector"].startswith(("@frame1|", "@frame2|"))]
        self.assertEqual(len(inside), 5)
        self.assertTrue(all(r.get("anti_bot") for r in inside))
        self.assertFalse(any(r.get("anti_bot") for r in rows
                             if not r["selector"].startswith("@frame")))

    def test_he_is_asked_the_language_question_and_nothing_else(self):
        rows = formfill.read_all(PalantirPage())
        out = formfill.plan(rows, answers={"legal_name": "Caleb Schulte",
                                           "email": "c@example.com", "phone": "(605) 555-0100"})
        self.assertEqual(_labels(out["ask"]), ["Language Skill(s) (Check all that apply) ✱"])
        skipped = _labels(out["skipped"])
        for junk in ("EN", "Name", "Date", "h-captcha-response"):
            self.assertIn(junk, skipped)
        for row in out["skipped"]:
            if row["label"] in ("EN", "h-captcha-response"):
                self.assertIn("not a question", row["why"])
        self.assertFalse([f for f in out["fill"] if "captcha" in f["selector"]
                          or "language-list" in f["selector"]])

    def test_a_captcha_frame_whose_address_was_not_read_is_still_caught_by_name(self):
        rows = formfill.read_all(PalantirPage(checkbox_url="", challenge_url="about:blank"))
        out = formfill.plan(rows, answers={})
        self.assertNotIn("h-captcha-response", _labels(out["ask"]))

    def test_the_form_is_still_marked_as_carrying_the_check(self):
        """The handoff to him is unchanged: the record still says hCaptcha."""
        self.assertEqual(apply_run._captcha_in_fields(formfill.read_all(PalantirPage())),
                         "hcaptcha")

    def test_every_provider_token_box_is_refused(self):
        for selector in ('@frame1|textarea[name="g-recaptcha-response"]',
                         "#g-recaptcha-response-100000",
                         'input[name="cf-turnstile-response"]',
                         '@frame4|input[name="cf-turnstile-response"]',
                         'input[name="frc-captcha-solution"]',
                         'input[name="_gotcha"]'):
            self.assertTrue(formfill.is_anti_bot({"selector": selector}), selector)
        for selector in ('textarea[name="cards\\[ce72d538\\]\\[field1\\]"]',
                         "#additional-information", 'input[name="captain_name"]'):
            self.assertFalse(formfill.is_anti_bot({"selector": selector}), selector)


class ABoxNobodyCanSeeIsATrap(unittest.TestCase):
    def test_an_off_screen_website_box_is_not_filled_from_his_profile(self):
        form = [_row('input[name="website"]', "Website", name="website", hidden=True),
                _row('input[name="urls\\[Portfolio\\]"]', "Website",
                     name="urls[Portfolio]")]
        out = formfill.plan(form, answers={"website": "https://example.com"})
        self.assertEqual([f["selector"] for f in out["fill"]], ['input[name="urls\\[Portfolio\\]"]'])
        self.assertIn("nobody can see", out["skipped"][0]["why"])

    def test_a_hidden_native_radio_behind_a_styled_label_is_still_his_question(self):
        """Styled forms hide the real radio. Hidden means a trap only for a box one TYPES in."""
        form = [_row("#q1-yes", "Yes", type="radio", name="q1", option="Yes", group="q1",
                     question="Do you have a law degree?", required=True, hidden=True),
                _row("#q1-no", "No", type="radio", name="q1", option="No", group="q1",
                     question="Do you have a law degree?", required=True, hidden=True)]
        out = formfill.plan(form, answers={})
        self.assertEqual(_labels(out["ask"]), ["Do you have a law degree?"])

    def test_a_required_self_id_signature_still_reaches_him_and_says_what_it_signs(self):
        form = [_row('input[name="eeo\\[disabilitySignature\\]"]', "Name",
                     name="eeo[disabilitySignature]", required=True)]
        out = formfill.plan(form, answers={"legal_name": "Caleb Schulte"})
        self.assertEqual(out["fill"], [])
        self.assertEqual(len(out["ask"]), 1)
        self.assertIn("self-identification", out["ask"][0]["label"])


class NothingIsTypedIntoTheCheck(ApplyCase):
    def test_an_essay_keyed_to_the_captcha_is_never_a_step(self):
        """The record's own answers, staged again."""
        filler = self.filler()
        with mock.patch.object(apply_run, "waits_for_his_ok", lambda *_a, **_k: False):
            record = apply_run.stage(
                LEVER, reader=lambda url: formfill.read_all(PalantirPage()), filler=filler,
                extra={f'{LANGS}[value="English (ENG)"]': "English (ENG)",
                       '@frame1|textarea[name="h-captcha-response"]': ESSAY,
                       "@frame2|#h-captcha-response-0pnpz9pkswmi": ESSAY})
        self.assertEqual(record["state"], "AWAITING_YOU")
        self.assertTrue(self.typed)
        for step in self.typed:
            self.assertNotIn("captcha", step["selector"])
            self.assertNotEqual(step.get("value"), ESSAY)
        self.assertEqual(record["captcha"], "hcaptcha")
        self.assertNotIn("h-captcha-response", _labels(record["not_filled"]))

    def test_a_step_already_staged_into_the_captcha_is_not_performed(self):
        class Page:
            def __init__(self):
                self.did = []

            def fill(self, selector, value):
                self.did.append(selector)

            def click(self, selector):
                self.did.append(selector)

        page = Page()
        with mock.patch.object(formfill, "is_combobox", lambda *_a: False):
            apply_run._apply_steps(page, [
                {"action": "type", "selector": '@frame3|textarea[name="h-captcha-response"]',
                 "value": ESSAY},
                {"action": "type", "selector": "#additional-information", "value": "hi"}])
        self.assertEqual(page.did, ["#additional-information"])

    def test_the_hands_refuse_it_whoever_asked(self):
        class Page:
            frames = []

            def fill(self, selector, value):
                raise AssertionError("typed into the check")

        with self.assertRaises(formfill.FormError):
            formfill.Hands(Page()).fill('textarea[name="h-captcha-response"]', ESSAY)

    def test_no_essay_is_written_for_it(self):
        record = {"url": LEVER, "job_title": "Legal Operations Specialist", "questions": [
            {"selector": "@frame1|textarea[name=\"h-captcha-response\"]",
             "label": "h-captcha-response", "type": "textarea"},
            {"selector": "#additional-information", "label": "Additional information",
             "type": "textarea"}]}
        asked = []

        def think(prompt, *_a, **_k):
            asked.append(prompt)
            return ESSAY

        with mock.patch.object(campaign, "_essay_facts", lambda: ""):
            drafted = campaign.draft_essays(record, "resume", think=think)
        self.assertEqual(list(drafted), ["#additional-information"])
        self.assertEqual(len(asked), 1)

    def test_a_record_staged_before_the_fix_does_not_put_it_in_front_of_him(self):
        stateio.write_json_atomic(apply_run.staged_dir() / "apply-6d06e852.json", {
            "id": "apply-6d06e852", "state": "NEEDS_YOU", "url": LEVER, "questions": [
                {"selector": "@frame1|textarea[name=\"h-captcha-response\"]",
                 "label": "h-captcha-response", "type": "textarea", "required": False},
                {"selector": f'{LANGS}[value="English (ENG)"]', "type": "checkbox",
                 "label": "Language Skill(s) (Check all that apply)\n✱", "required": True}]})
        self.assertEqual([q["label"] for q in campaign.open_questions()],
                         ["Language Skill(s) (Check all that apply)\n✱"])


if __name__ == "__main__":
    unittest.main()
