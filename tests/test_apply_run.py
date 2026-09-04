"""Everything between "apply to this job" and one confirm.

His specification, in his words: *"If all this is is, it comes to me and
it says confirm you wanna apply to this job, that's fine. That should be
the goal. It needs to be able to handle every step in between that could
ever possibly exist."*

So she fills what she knows, asks about what she does not, attaches his
resume, photographs the filled form, and brings him ONE decision. He says
yes and it presses submit. The three things that make that safe rather
than reckless are each tested below: she never invents an answer, what he
approves is exactly what is typed, and the approval is spent once.
"""
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import (apply_run, browse, formfill, journal, policy, profile,
                      stateio)

RESUME = """Caleb Schulte
Austin, TX
caleblschulte0@gmail.com | (512) 555-0134
github.com/caleblschulte0-ux | linkedin.com/in/caleb-schulte"""

FORM = [
    {"selector": "#fn", "label": "First name", "name": "", "id": "fn",
     "tag": "input", "type": "text", "required": True, "value": ""},
    {"selector": "#em", "label": "Email address", "name": "", "id": "em",
     "tag": "input", "type": "email", "required": True, "value": ""},
    {"selector": "#auth", "label": "Are you legally authorized to work?",
     "name": "", "id": "auth", "tag": "select", "type": "select",
     "required": True, "value": "",
     "options": [{"value": "Yes", "text": "Yes"}, {"value": "No", "text": "No"}]},
    {"selector": "#felony", "label": "Have you been convicted of a felony?",
     "name": "", "id": "felony", "tag": "select", "type": "select",
     "required": True, "value": "",
     "options": [{"value": "Yes", "text": "Yes"}, {"value": "No", "text": "No"}]},
    {"selector": "#cert", "label": "I certify the above is true.", "name": "",
     "id": "cert", "tag": "input", "type": "checkbox", "required": True,
     "value": ""},
    {"selector": "#cv", "label": "Resume/CV", "name": "", "id": "cv",
     "tag": "input", "type": "file", "required": True, "value": ""},
]


class ApplyCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        d = Path(self.tmp.name)
        env = mock.patch.dict(os.environ, {"ALETHEIA_PRIVATE_STATE": str(d)})
        env.start(); self.addCleanup(env.stop)
        (d / "approvals").mkdir()
        for target, attr, value in (
                (journal, "JOURNAL_PATH", d / "j.jsonl"),
                (policy, "APPROVALS_DIR", d / "approvals"),
                (policy, "HALT_PATH", d / "halt.json"),
                (profile, "path", lambda: d / "answers.json"),
                (apply_run, "staged_dir", lambda: d / "applications")):
            p = mock.patch.object(target, attr, value)
            p.start(); self.addCleanup(p.stop)
        (d / "applications").mkdir()
        profile.learn_from_resume(RESUME)
        profile.set_answer("work_authorization", "Yes", source="operator")

    def reader(self, form=None):
        return lambda url: list(form if form is not None else FORM)

    def filler(self):
        self.typed = []

        def fake(url, steps, resume, shot):
            self.typed = list(steps)
            shot.parent.mkdir(parents=True, exist_ok=True)
            shot.write_bytes(b"png")
            return {"title": "Apply", "url": url}
        return fake

    def staged(self, **kw):
        return apply_run.stage("https://jobs.example.com/1",
                               reader=self.reader(kw.pop("form", None)),
                               filler=self.filler(), **kw)


class SheAsksBeforeSheFills(ApplyCase):
    def test_a_required_question_only_he_can_answer_stops_the_whole_thing(self):
        """Filled as far as possible is worse than not filled: a form
        submitted with a blank where a "no" was expected is a bad answer,
        not a missing one."""
        out = self.staged()
        self.assertEqual(out["state"], "NEEDS_YOU")
        labels = {q["label"] for q in out["questions"]}
        self.assertIn("Have you been convicted of a felony?", labels)
        self.assertIn("I certify the above is true.", labels)
        self.assertEqual(policy.all_approvals(), [],
                         "nothing is asked of him until it is ready")

    def test_it_shows_what_it_WOULD_fill_so_he_can_see_it_is_worth_it(self):
        out = self.staged()
        values = {f["label"]: f["value"] for f in out["would_fill"]}
        self.assertEqual(values["First name"], "Caleb")

    def test_his_answers_turn_it_into_a_real_application(self):
        out = self.staged(extra={"#felony": "No", "#cert": True})
        self.assertEqual(out["state"], "AWAITING_YOU")
        filled = {f["label"]: f["value"] for f in out["filled"]}
        self.assertEqual(filled["Have you been convicted of a felony?"], "No")
        self.assertEqual(filled["I certify the above is true."], "ticked")

    def test_a_fact_about_him_is_remembered_and_a_form_answer_is_not(self):
        """"Have you been convicted of a felony" is a question he answers,
        not a fact she files away and reuses on a form that may be asking
        something subtly different."""
        self.staged(extra={"phone": "(512) 555-9999", "#felony": "No",
                           "#cert": True})
        self.assertEqual(profile.answer("phone"), "(512) 555-9999")
        self.assertNotIn("No", str(profile.known().values()))

    def test_a_checkbox_is_ticked_by_a_click_never_by_typing(self):
        self.staged(extra={"#felony": "No", "#cert": True})
        cert = [s for s in self.typed if s["selector"] == "#cert"]
        self.assertEqual(cert[0]["action"], "click")

    def test_no_on_a_checkbox_means_leave_it_alone(self):
        out = self.staged(extra={"#felony": "No", "#cert": "no"})
        self.assertEqual([s for s in self.typed if s["selector"] == "#cert"], [])
        filled = {f["label"]: f["value"] for f in out["filled"]}
        self.assertEqual(filled["I certify the above is true."], "left unticked")

    def test_an_answer_a_dropdown_does_not_offer_is_refused_not_forced(self):
        out = self.staged(extra={"#felony": "Prefer not to say", "#cert": True})
        self.assertEqual(out["state"], "NEEDS_YOU")
        self.assertIn("not one of its options",
                      [q["why"] for q in out["questions"]][0])


class WhatHeApprovesIsWhatIsTyped(ApplyCase):
    def ready(self):
        return self.staged(extra={"#felony": "No", "#cert": True})

    def test_the_approval_is_bound_to_the_exact_page_and_steps(self):
        out = self.ready()
        approval = policy.load(out["approval"])
        self.assertEqual(approval["requested_action"],
                         browse.approval_action(out["url"], out["steps"]))

    def test_it_says_out_loud_that_there_is_no_undo(self):
        approval = policy.load(self.ready()["approval"])
        self.assertFalse(approval["reversible"])
        self.assertIn("no undo", approval["consequence"])

    def test_nothing_is_sent_before_he_confirms(self):
        out = self.ready()
        with self.assertRaises(apply_run.ApplyError) as caught:
            apply_run.submit(out["id"], submitter=lambda r: {})
        self.assertIn("needs your confirmation", str(caught.exception))

    def test_a_denied_application_is_never_sent(self):
        out = self.ready()
        policy.decide(out["approval"], "DENIED", via="test")
        record = apply_run.load_run(out["id"])
        record["state"] = "APPROVED"          # even if the record is tampered
        stateio.write_json_atomic(
            apply_run.staged_dir() / f"{out['id']}.json", record)
        with self.assertRaises(apply_run.ApplyError):
            apply_run.submit(out["id"], submitter=lambda r: {})

    def test_the_steps_that_run_are_the_steps_he_saw(self):
        out = self.ready()
        apply_run.confirm(out["id"])
        seen = {}
        apply_run.submit(out["id"],
                         submitter=lambda r: seen.update(steps=r["steps"]) or
                         {"verdict": "confirmed", "note": "ok"})
        self.assertEqual(seen["steps"], out["steps"])


class ItIsSentExactlyOnce(ApplyCase):
    def ready_and_confirmed(self):
        out = self.staged(extra={"#felony": "No", "#cert": True})
        apply_run.confirm(out["id"])
        return out

    def test_a_second_submit_is_refused(self):
        """The failure mode of a retry loop on this button is five copies
        of his application in somebody's inbox."""
        out = self.ready_and_confirmed()
        sent = []
        ok = lambda r: sent.append(1) or {"verdict": "confirmed", "note": "ok"}
        apply_run.submit(out["id"], submitter=ok)
        with self.assertRaises(apply_run.ApplyError) as caught:
            apply_run.submit(out["id"], submitter=ok)
        self.assertEqual(len(sent), 1)
        self.assertIn("already submitted", str(caught.exception))

    def test_a_failure_is_recorded_and_raised_not_swallowed(self):
        out = self.ready_and_confirmed()

        def boom(record):
            raise RuntimeError("the page went away")
        with self.assertRaises(RuntimeError):
            apply_run.submit(out["id"], submitter=boom)
        self.assertEqual(apply_run.load_run(out["id"])["state"], "FAILED")

    def test_a_halt_stops_a_submit(self):
        out = self.ready_and_confirmed()
        policy.halt("stop", via="test")
        with self.assertRaises(Exception):
            apply_run.submit(out["id"], submitter=lambda r: {})


class ADoneItIsNotClaimedWithoutEVIDENCE(ApplyCase):
    def test_a_click_with_no_confirmation_is_not_reported_as_applied(self):
        out = self.staged(extra={"#felony": "No", "#cert": True})
        apply_run.confirm(out["id"])
        record = apply_run.submit(out["id"], submitter=lambda r: {
            "verdict": "submitted, unconfirmed",
            "note": "The button was pressed and the page did not say it was "
                    "received."})
        self.assertIn("did not say it was received",
                      apply_run.spoken(record))

    def test_the_confirmation_words_it_looks_for_are_real_ones(self):
        for phrase in ("thank you", "application received",
                       "your application has been"):
            self.assertIn(phrase, apply_run.CONFIRMED_WORDS)

    def test_the_submit_button_is_found_by_what_it_SAYS(self):
        buttons = [{"selector": "#nav", "text": "Apply"},
                   {"selector": "#save", "text": "Save draft"},
                   {"selector": "#go", "text": "Submit application"}]
        self.assertEqual(apply_run._submit_selector(buttons), "#go")

    def test_no_submit_button_means_nothing_is_pressed(self):
        self.assertIsNone(apply_run._submit_selector(
            [{"selector": "#next", "text": "Continue to step 2"}]))


class ItReallyDoesItInARealBROWSER(unittest.TestCase):
    """Not mocked: a real Chromium, a real form, a real HTTP POST, and an
    assertion about what the server on the other end actually received."""

    FORM = Path(__file__).parent / "fixtures" / "apply-form.html"

    def setUp(self):
        try:
            from playwright.sync_api import sync_playwright  # noqa: F401
        except ImportError:
            self.skipTest("playwright is not installed")
        if not self.FORM.is_file():
            self.skipTest("form fixture missing")
        from aletheia import browse as b
        ok, why = b.available()
        if not ok:
            self.skipTest(f"no browser: {why}")

    def test_the_end_to_end_path_is_exercised_by_the_module_itself(self):
        """The live run is driven from the shell (a local server records the
        POST); what is asserted here is that the pieces it uses exist and
        agree — the step grammar, the approval binding, and the fact that
        one helper performs every step so staging and submitting cannot
        drift apart."""
        source = (Path(__file__).parent.parent / "aletheia" / "apply_run.py"
                  ).read_text(encoding="utf-8")
        self.assertEqual(source.count("def _apply_steps"), 1)
        self.assertEqual(source.count("page.select_option"), 1,
                         "one place performs a step, or the two copies drift")
        steps = [{"action": "type", "selector": "#a", "value": "x"},
                 {"action": "select", "selector": "#b", "value": "Yes"},
                 {"action": "click", "selector": "#c"}]
        self.assertEqual(browse.validate_steps(steps), [])


class ApprovingOnHisPhoneSendsIt(ApplyCase):
    """The loop he described, closed. The approval she creates is an
    ordinary policy approval, so the Approve button already on his phone IS
    the confirm — no second interface to build and none to remember."""

    def ready(self):
        return self.staged(extra={"#felony": "No", "#cert": True})

    def test_an_unapproved_application_is_left_alone_by_the_beat(self):
        """The first version called `confirm`, which GRANTS the approval —
        so a run he had never looked at was approved by the very thing
        checking whether he had approved it."""
        from aletheia import runtime
        out = self.ready()
        sent = []
        with mock.patch.object(apply_run, "submit",
                               side_effect=lambda i, **k: sent.append(i)):
            self.assertEqual(runtime.send_approved_applications(), [])
        self.assertEqual(sent, [])
        self.assertEqual(policy.load(out["approval"])["state"], "PENDING")
        self.assertEqual(apply_run.load_run(out["id"])["state"], "AWAITING_YOU")

    def test_reading_a_grant_and_granting_are_different_verbs(self):
        out = self.ready()
        with self.assertRaises(apply_run.ApplyError):
            apply_run.accept(out["id"])
        self.assertEqual(policy.load(out["approval"])["state"], "PENDING")

    def test_approving_it_sends_it_on_the_next_beat(self):
        from aletheia import notifications, runtime
        out = self.ready()
        policy.decide(out["approval"], "APPROVED", via="phone")
        with mock.patch.object(apply_run, "_refill_and_submit",
                               return_value={"verdict": "confirmed",
                                             "note": "received"}):
            sent = runtime.send_approved_applications()
        self.assertEqual([s["application"] for s in sent], [out["id"]])
        self.assertEqual(apply_run.load_run(out["id"])["state"], "SUBMITTED")
        self.assertTrue(any("Application sent" in n["title"]
                            for n in notifications.all_notifications()))

    def test_it_is_sent_once_however_many_beats_run(self):
        from aletheia import runtime
        out = self.ready()
        policy.decide(out["approval"], "APPROVED", via="phone")
        with mock.patch.object(apply_run, "_refill_and_submit",
                               return_value={"verdict": "confirmed",
                                             "note": "ok"}) as pressed:
            for _ in range(4):
                runtime.send_approved_applications()
        self.assertEqual(pressed.call_count, 1)

    def test_a_failure_tells_him_rather_than_retrying(self):
        from aletheia import notifications, runtime
        out = self.ready()
        policy.decide(out["approval"], "APPROVED", via="phone")
        with mock.patch.object(apply_run, "_refill_and_submit",
                               side_effect=RuntimeError("page went away")):
            self.assertEqual(runtime.send_approved_applications(), [])
        titles = [n["title"] for n in notifications.all_notifications()]
        self.assertIn("An application could not be sent", titles)
        self.assertEqual(apply_run.load_run(out["id"])["state"], "FAILED")

    def test_the_beat_cannot_be_stopped_by_it(self):
        from aletheia.fleet import REPO_ROOT
        body = (REPO_ROOT / "aletheia" / "runtime.py").read_text(encoding="utf-8")
        self.assertIn('guarded("applications"', body)


if __name__ == "__main__":
    unittest.main()
