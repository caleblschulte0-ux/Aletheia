"""The information he should never type again, and the form that asks for it.

"Half the jobs these days hand you off to an external website and make
you type in all your information again." The packet builder solved the
wrong half: a good cover letter is what any chat assistant can already
give him. Retyping his phone number into a Workday for the ninth time is
the part only something living on his machine can fix.

The safety model is one rule and it has no off switch: a field she does
not know the answer to is a QUESTION, never a guess. A wrong phone number
is an annoyance. A guessed "no" on "have you ever been convicted of a
felony" is a lie submitted under his name to a company that keeps it.
"""
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import formfill, journal, profile

RESUME = """Caleb Schulte
Austin, TX
caleblschulte0@gmail.com | (512) 555-0134
github.com/caleblschulte0-ux | linkedin.com/in/caleb-schulte
EXPERIENCE
Built a pipeline."""


def field(selector, label="", **kw):
    row = {"selector": selector, "label": label, "name": kw.pop("name", ""),
           "id": kw.pop("id", ""), "tag": kw.pop("tag", "input"),
           "type": kw.pop("type", "text"), "required": kw.pop("required", False),
           "value": ""}
    row.update(kw)
    return row


class ProfileCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        d = Path(self.tmp.name)
        env = mock.patch.dict(os.environ, {"ALETHEIA_PRIVATE_STATE": str(d)})
        env.start(); self.addCleanup(env.stop)
        for target, attr, value in ((journal, "JOURNAL_PATH", d / "j.jsonl"),
                                    (profile, "path", lambda: d / "answers.json")):
            p = mock.patch.object(target, attr, value)
            p.start(); self.addCleanup(p.stop)


class SheLearnsHimRatherThanInterrogatingHim(ProfileCase):
    def test_the_resume_already_has_most_of_it(self):
        got = profile.learn_from_resume(RESUME)
        self.assertEqual(got["email"], "caleblschulte0@gmail.com")
        self.assertEqual(got["phone"], "(512) 555-0134")
        self.assertEqual(got["city"], "Austin")
        self.assertEqual(got["state"], "TX")
        self.assertEqual(got["first_name"], "Caleb")
        self.assertEqual(got["last_name"], "Schulte")
        self.assertIn("linkedin.com/in/", got["linkedin"])
        self.assertIn("github.com/", got["github"])

    def test_it_invents_nothing_that_is_not_there(self):
        profile.learn_from_resume("Just some words about work.")
        for guessed in ("email", "phone", "city", "work_authorization"):
            self.assertIsNone(profile.answer(guessed), guessed)

    def test_what_he_told_her_outranks_what_she_read(self):
        profile.set_answer("email", "caleb@work.example", source="operator")
        profile.learn_from_resume(RESUME)
        self.assertEqual(profile.answer("email"), "caleb@work.example")

    def test_the_value_never_reaches_the_journal(self):
        """His phone number is not audit data."""
        profile.set_answer("phone", "(512) 555-0134")
        log = journal.JOURNAL_PATH.read_text(encoding="utf-8")
        self.assertIn("phone is on file", log)
        self.assertNotIn("555-0134", log)

    def test_it_lives_in_private_state_not_the_repo(self):
        from aletheia.fleet import REPO_ROOT
        ignore = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("state/private/", ignore.splitlines())

    def test_missing_says_what_it_needs_in_english(self):
        profile.learn_from_resume(RESUME)
        wanted = {m["field"]: m["means"] for m in profile.missing()}
        self.assertIn("work_authorization", wanted)
        self.assertIn("authorized to work", wanted["work_authorization"])

    def test_an_unknown_field_is_refused_rather_than_stored(self):
        with self.assertRaises(ValueError):
            profile.set_answer("favourite_colour", "green")


class SheFillsWhatSheKnows(ProfileCase):
    def setUp(self):
        super().setUp()
        profile.learn_from_resume(RESUME)
        for key, value in (("work_authorization", "Yes"),
                           ("needs_sponsorship", "No")):
            profile.set_answer(key, value, source="operator")

    def test_a_plain_text_field_is_typed(self):
        out = formfill.plan([field("#em", "Email address", required=True)])
        self.assertEqual(out["fill"][0]["value"], "caleblschulte0@gmail.com")
        self.assertEqual(out["fill"][0]["action"], "type")

    def test_first_name_beats_name(self):
        """Longest phrase wins, or every name box gets his full legal name."""
        out = formfill.plan([field("#fn", "First name")])
        self.assertEqual(out["fill"][0]["value"], "Caleb")

    def test_an_unlabelled_field_is_matched_on_its_placeholder(self):
        out = formfill.plan([field("#q8872", "GitHub URL", name="q_8872")])
        self.assertIn("github.com/", out["fill"][0]["value"])

    def test_a_dropdown_is_matched_to_ITS_options(self):
        """Selecting an option that does not exist does nothing in some
        browsers and throws in others; either way the form goes in empty."""
        out = formfill.plan([field(
            "#auth", "Are you legally authorized to work in the United States?",
            tag="select", type="select", required=True,
            options=[{"value": "Y", "text": "Yes"}, {"value": "N", "text": "No"}])])
        self.assertEqual(out["fill"][0]["action"], "select")
        self.assertEqual(out["fill"][0]["value"], "Y")

    def test_a_dropdown_with_no_matching_option_is_asked_not_forced(self):
        out = formfill.plan([field(
            "#auth", "Are you legally authorized to work?", tag="select",
            type="select", options=[{"value": "citizen", "text": "US Citizen"},
                                    {"value": "other", "text": "Other"}])])
        self.assertEqual(out["fill"], [])
        self.assertIn("none of its options match", out["ask"][0]["why"])

    def test_the_step_list_is_the_browsers_own_grammar_and_submits_nothing(self):
        from aletheia import browse
        out = formfill.plan([field("#em", "Email"), field("#fn", "First name")])
        steps = formfill.steps(out["fill"])
        self.assertEqual(browse.validate_steps(steps), [])
        self.assertFalse(any(s["action"] == "click" for s in steps))


class AFieldSheDoesNotKnowIsAQuestion(ProfileCase):
    def setUp(self):
        super().setUp()
        profile.learn_from_resume(RESUME)

    def test_a_fact_she_lacks_comes_back_to_him(self):
        out = formfill.plan([field("#pay", "Desired salary")])
        self.assertEqual(out["fill"], [])
        self.assertIn("what he wants to be paid", out["ask"][0]["why"])

    def test_a_field_she_cannot_interpret_comes_back_to_him(self):
        out = formfill.plan([field("#q99", "Section 4b", name="q_99")])
        self.assertIn("could not tell what this is asking", out["ask"][0]["why"])

    def test_an_essay_question_is_not_a_fact_on_file(self):
        out = formfill.plan([field("#why", "Why do you want to work here?",
                                   tag="textarea", type="textarea",
                                   required=True)])
        self.assertIn("written answer", out["ask"][0]["why"])

    def test_protected_characteristics_are_ALWAYS_his(self):
        """Even when the profile holds an answer. There is no setting."""
        profile.set_answer("pronouns", "he/him", source="operator")
        for label in ("Gender", "Race / Ethnicity", "Protected veteran status",
                      "Do you have a disability?",
                      "Have you ever been convicted of a felony?",
                      "Date of birth", "Social Security Number",
                      "What is your current salary?",
                      "I certify the above is true and complete.",
                      "I agree to the terms and conditions"):
            out = formfill.plan([field("#x", label)])
            self.assertEqual(out["fill"], [], label)
            self.assertIn("yours to answer, always", out["ask"][0]["why"], label)

    def test_a_file_upload_is_his_to_choose(self):
        out = formfill.plan([field("#cv", "Resume/CV", type="file",
                                   required=True)])
        self.assertEqual(out["fill"], [])
        self.assertIn("yours to choose", out["skipped"][0]["why"])

    def test_a_password_box_is_never_typed_into(self):
        out = formfill.plan([field("#pw", "Password", type="password")])
        self.assertEqual(out["fill"], [])

    def test_required_questions_are_counted_out_loud(self):
        out = formfill.plan([
            field("#felony", "Have you been convicted of a felony?",
                  required=True),
            field("#pay", "Desired salary")])
        out.update({"url": "x", "fields_found": 2})
        self.assertIn("1 of them required", formfill.spoken(out))

    def test_nothing_in_the_module_presses_anything(self):
        source = (Path(__file__).parent.parent / "aletheia" / "formfill.py"
                  ).read_text(encoding="utf-8")
        body = source.split('"""', 2)[2]
        for reach in ("interact(", "page.click", "submit()"):
            self.assertNotIn(reach, body, reach)


class ItReadsARealFormInARealBrowser(ProfileCase):
    """Rendered by Chromium, not parsed out of a string: labels come from
    <label for>, wrapping labels, aria-label, placeholders and legends, and
    only a browser resolves those the way a person sees them."""

    FORM = Path(__file__).parent / "fixtures" / "apply-form.html"

    def setUp(self):
        super().setUp()
        if not self.FORM.is_file():
            self.skipTest("form fixture missing")
        try:
            from playwright.sync_api import sync_playwright  # noqa: F401
        except ImportError:
            self.skipTest("playwright is not installed")
        self.chrome = None
        for candidate in Path("/opt/pw-browsers").glob("chromium-*/chrome-linux/chrome"):
            self.chrome = str(candidate)
            break
        profile.learn_from_resume(RESUME)
        for key, value in (("work_authorization", "Yes"),
                           ("needs_sponsorship", "No"),
                           ("willing_to_relocate", "No")):
            profile.set_answer(key, value, source="operator")

    def read(self):
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            kwargs = {"args": ["--no-sandbox"]}
            if self.chrome:
                kwargs["executable_path"] = self.chrome
            try:
                browser = pw.chromium.launch(**kwargs)
            except Exception as exc:                      # no browser binary
                self.skipTest(f"no chromium: {type(exc).__name__}")
            page = browser.new_page()
            page.goto(self.FORM.as_uri())
            found = page.evaluate(formfill.READ_FORM_JS)
            browser.close()
        return found

    def test_a_workday_shaped_form_splits_correctly(self):
        out = formfill.plan(self.read())
        filled = {f["label"]: f["value"] for f in out["fill"]}
        asked = {a["label"] for a in out["ask"]}
        self.assertEqual(filled["First name *"], "Caleb")
        self.assertEqual(filled["Email address *"], "caleblschulte0@gmail.com")
        self.assertIn("github.com/", filled["GitHub URL"])
        self.assertEqual(
            filled["Are you legally authorized to work in the United States? *"],
            "Yes")
        self.assertIn("Have you ever been convicted of a felony? *", asked)
        self.assertIn("Why do you want to work here? *", asked)
        self.assertTrue(any("Resume/CV" in s["label"] for s in out["skipped"]))


def aria(group, question, option, *, required=True, checked=False):
    """One option of a question made of divs, as `read_all` reports it."""
    return {"selector": f"#{group}-{option.lower().replace(' ', '-')}",
            "tag": "aria", "type": "radio", "name": "", "id": "",
            "group": group, "question": question, "option": option,
            "label": option, "required": required, "value": "",
            "checked": checked}


class AQuestionMadeOfDIVS(ProfileCase):
    """On a modern form "Are you legally authorized to work in the US?"
    is a pair of divs. She had the answer on file the whole time and was
    handing the question back to him on every single application."""

    def test_an_answer_she_has_on_file_is_given_not_asked(self):
        profile.set_answer("work_authorization", "Yes", source="operator")
        out = formfill.plan([
            aria("g1", "Are you legally authorized to work in the US? *", "Yes"),
            aria("g1", "Are you legally authorized to work in the US? *", "No")])
        self.assertEqual([(f["action"], f["value"]) for f in out["fill"]],
                         [("click", "Yes")])
        self.assertEqual(out["ask"], [])

    def test_a_first_word_answers_a_wordy_option(self):
        profile.set_answer("work_authorization", "Yes", source="operator")
        out = formfill.plan([
            aria("g1", "Are you legally authorized to work in the US? *",
                 "Yes, I am authorized to work for any employer"),
            aria("g1", "Are you legally authorized to work in the US? *",
                 "No, I will require sponsorship")])
        self.assertEqual([f["value"] for f in out["fill"]],
                         ["Yes, I am authorized to work for any employer"])

    def test_NO_does_not_quietly_answer_NORTH_AMERICA(self):
        """A plain `startswith` did exactly that."""
        profile.set_answer("needs_sponsorship", "No", source="operator")
        out = formfill.plan([
            aria("g2", "Which region do you need sponsorship in? *",
                 "North America"),
            aria("g2", "Which region do you need sponsorship in? *", "Europe")])
        self.assertEqual(out["fill"], [])
        self.assertEqual([a["label"] for a in out["ask"]],
                         ["Which region do you need sponsorship in? *"])

    def test_a_protected_question_stays_his_however_it_is_built(self):
        profile.set_answer("work_authorization", "Yes", source="operator")
        out = formfill.plan([
            aria("g3", "Are you a protected veteran? *", "Yes"),
            aria("g3", "Are you a protected veteran? *", "No")])
        self.assertEqual(out["fill"], [])
        self.assertEqual([a["label"] for a in out["ask"]],
                         ["Are you a protected veteran? *"])

    def test_a_multi_answer_question_is_still_his(self):
        """"Which countries do you anticipate working in" has no answer
        on file and guessing one is exactly what she must not do."""
        rows = [{"selector": f"#c{n}", "tag": "input", "type": "checkbox",
                 "name": "countries[]", "id": f"c{n}", "group": "countries",
                 "question": "Which countries? *", "option": name,
                 "label": name, "required": True, "value": "", "checked": False}
                for n, name in enumerate(("Australia", "Belgium", "Brazil"))]
        out = formfill.plan(rows)
        self.assertEqual(out["fill"], [])
        self.assertEqual(len(out["ask"]), 1)


if __name__ == "__main__":
    unittest.main()
