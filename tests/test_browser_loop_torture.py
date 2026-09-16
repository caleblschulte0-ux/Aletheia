"""The browser torture suite: one general loop, many kinds of site.

Milestone 4 of docs/JARVIS_BRIEF.md: "every site succeeds or stops at a
precisely named boundary without lying, duplicating, losing progress or
asking him to redo work." And the operator's direction of 2026-09-16:
jobs are the test case, not the architecture. So the SAME `pursue` drives:

- a job application (with the job skill: profile facts and the resume), and
- a dental appointment-request wizard and a library-card signup, with the
  general skill and nothing but the goal's own inputs - no job code;

and the torture fixtures: a multi-page wizard, an account wall, a server
error then retry, a mid-run crash + resume, a duplicate submit attempt, a
CAPTCHA handoff, an emailed verification code, a site that refuses a
submission (the one case a retry is allowed).

Hermetic: local HTML on loopback, a throwaway browser profile, one browser
at a time. Skips where playwright is absent.
"""
from __future__ import annotations

import http.server
import os
import tempfile
import threading
import unittest
import urllib.parse
from pathlib import Path
from unittest import mock

from aletheia import (browse, browser_loop, browser_mission as bm, journal, job_skill,
                      page_state as ps, policy, profile, site_skills, webtask)

BROWSER_OK, BROWSER_WHY = browse.available()
needs_browser = unittest.skipUnless(BROWSER_OK, f"browser control absent: {BROWSER_WHY}")

CLINIC = """<h1>Riverside Dental</h1><p>Family dentistry since 1998.</p>
<a href="/clinic/about">About us</a> <a href="/clinic/request">Request an appointment</a>"""
STEP1 = """<h2>Appointment request</h2><p>Step 1 of 3</p>
<form method="POST" action="/clinic/step2">
<label for="nm">Full name *</label><input id="nm" name="name" required>
<label for="em">Email *</label><input id="em" name="email" type="email" required>
<button type="submit">Next</button></form>"""
STEP2 = """<h2>Appointment request</h2><p>Step 2 of 3</p>
<form method="POST" action="/clinic/review">
<label for="day">Preferred day *</label>
<select id="day" name="day" required><option value="">Choose...</option>
<option value="mon">Monday</option><option value="tue">Tuesday</option></select>
<label for="why">Reason for visit *</label><textarea id="why" name="why" required></textarea>
<fieldset><legend>Are you a new patient? *</legend>
<label><input type="radio" name="new" value="yes" required> Yes</label>
<label><input type="radio" name="new" value="no"> No</label></fieldset>
<button type="submit">Continue</button></form>"""
REVIEW = """<h2>Please review your request</h2><p>Step 3 of 3</p>
<dl><dt>Name</dt><dd>%(name)s</dd><dt>Day</dt><dd>%(day)s</dd></dl>
<form method="POST" action="/clinic/submit"><button type="submit">Submit request</button></form>"""
RECEIVED = "<h1>Thank you</h1><p>Your request has been received. We will call you.</p>"

LIBRARY = """<h1>Get a library card</h1>
<form method="POST" action="/library/create">
<label for="n">Full name *</label><input id="n" name="name" required>
<label for="e">Email *</label><input id="e" name="email" required>
<label for="a">Street address *</label><input id="a" name="street" required>
<button type="submit">Create account</button></form>"""

POSTING = """<title>Systems Engineer - Acme</title><h1>Systems Engineer</h1>
<h2>Responsibilities</h2><p>Keep unattended systems honest.</p>
<a href="/careers/42/apply">Apply for this job</a>"""
APPLY = """<h1>Apply: Systems Engineer</h1>
<form method="POST" action="/careers/submit">
<label for="fn">First name *</label><input id="fn" name="first_name" required>
<label for="ln">Last name *</label><input id="ln" name="last_name" required>
<label for="em">Email *</label><input id="em" name="email" type="email" required>
<label for="cv">Resume/CV *</label><input id="cv" type="file" name="resume" required>
<label for="wh">Why do you want to work here? *</label><textarea id="wh" name="why" required></textarea>
<button type="submit">Submit application</button></form>"""

PORTAL = """<h1>Candidate portal</h1><form method="POST" action="/portal/session">
<label for="u">Email</label><input id="u" name="username">
<label for="p">Password</label><input id="p" name="password" type="password">
<button type="submit">Sign in</button></form>"""

FLAKY_FORM = """<h1>Contact us</h1><form method="POST" action="/flaky/send">
<label for="n">Full name *</label><input id="n" name="name" required>
<label for="m">Message *</label><textarea id="m" name="message" required></textarea>
<button type="submit">Send message</button></form>"""

GUARDED = """<h1>Newsletter</h1><form method="POST" action="/guarded/join">
<label for="e">Email *</label><input id="e" name="email" required>
%s<button type="submit">Join the list</button></form>"""
CAPTCHA_BOX = '<div class="g-recaptcha" style="width:300px;height:80px;border:1px solid">I\'m not a robot</div>'

VERIFY1 = """<h1>Volunteer sign-up</h1><form method="POST" action="/volunteer/code">
<label for="e">Email *</label><input id="e" name="email" required>
<button type="submit">Next</button></form>"""
VERIFY2 = """<h1>Check your inbox</h1><p>We emailed you a verification code. Enter the code below.</p>
<form method="POST" action="/volunteer/final"><label for="c">Code</label><input id="c" name="code">
<button type="submit">Verify</button></form>"""
VERIFY3 = """<h1>Almost done</h1><form method="POST" action="/volunteer/done">
<label for="s">Preferred shift *</label><input id="s" name="shift" required>
<button type="submit">Submit</button></form>"""

PICKY = """<h1>Feedback</h1>%s<form method="POST" action="/picky/send">
<label for="z">Zip code *</label><input id="z" name="zip" value="%s" required>
<button type="submit">Send feedback</button></form>"""


def _site(state: dict):
    got = state["got"]

    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, body, code=200):
            raw = body.encode()
            self.send_response(code)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self):
            path = self.path.split("?")[0]
            state["hits"][path] = state["hits"].get(path, 0) + 1
            if path == "/flaky" and state["hits"][path] == 1:
                return self._send("<h1>Internal Server Error</h1>", 500)
            if path == "/guarded":
                return self._send(GUARDED % ("" if state.get("solved") else CAPTCHA_BOX))
            if path == "/picky":
                return self._send(PICKY % ("", ""))
            pages = {"/clinic": CLINIC, "/clinic/request": STEP1, "/clinic/about": "<p>About</p>",
                     "/library/card": LIBRARY, "/careers/42": POSTING, "/careers/42/apply": APPLY,
                     "/portal/apply": PORTAL, "/flaky": FLAKY_FORM, "/volunteer": VERIFY1}
            self._send(pages.get(path, "<h1>404</h1>"), 200 if path in pages else 404)

        def do_POST(self):
            size = int(self.headers.get("Content-Length", "0"))
            form = urllib.parse.parse_qs(self.rfile.read(size).decode())
            got.update({k: v[0] for k, v in form.items()})
            state["posts"].append(self.path)
            if self.path == "/clinic/step2":
                return self._send(STEP2)
            if self.path == "/clinic/review":
                return self._send(REVIEW % {"name": got.get("name", ""), "day": got.get("day", "")})
            if self.path == "/volunteer/code":
                return self._send(VERIFY2)
            if self.path == "/volunteer/final":
                ok = got.get("code") == "731904"
                return self._send(VERIFY3 if ok else VERIFY2)
            if self.path == "/flaky/send" and state.get("send_fails"):
                return self._send("<h1>502 Bad Gateway</h1><p>Server error</p>", 502)
            if self.path == "/picky/send" and not state.get("picky_ok"):
                state["picky_ok"] = True
                return self._send(PICKY % ("<p>There was a problem: zip code is invalid.</p>",
                                           got.get("zip", "")))
            if self.path == "/library/create":
                return self._send("<h1>Your account has been created</h1><p>Welcome.</p>")
            self._send(RECEIVED)
    return H


class LoopCase(unittest.TestCase):
    def setUp(self):
        self.state = {"got": {}, "hits": {}, "posts": []}
        probe = http.server.HTTPServer(("127.0.0.1", 0), lambda *a: None)
        port = probe.server_address[1]
        probe.server_close()
        self.base = f"http://127.0.0.1:{port}"
        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", port), _site(self.state))
        self.server.daemon_threads = True
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        d = Path(self.tmp.name)
        (d / "approvals").mkdir()
        (d / "webtasks").mkdir()
        (d / "ws").mkdir()
        env = mock.patch.dict(os.environ, {"ALETHEIA_PRIVATE_STATE": str(d),
                                           "ALETHEIA_WORKSPACE": str(d / "ws")})
        env.start()
        self.addCleanup(env.stop)
        self.resume_file = d / "resume.pdf"
        self.resume_file.write_bytes(b"%PDF-1.4\n%%EOF\n")
        for target, attr, value in (
                (journal, "JOURNAL_PATH", d / "j.jsonl"),
                (policy, "APPROVALS_DIR", d / "approvals"),
                (policy, "HALT_PATH", d / "halt.json"),
                (profile, "path", lambda: d / "answers.json"),
                (webtask, "runs_dir", lambda: d / "webtasks"),
                (webtask, "documents", lambda: {"resume": str(self.resume_file)}),
                (browse, "PROFILE_DIR", d / "browser")):
            patch = mock.patch.object(target, attr, value)
            patch.start()
            self.addCleanup(patch.stop)
        profile.learn_from_resume("Caleb Schulte\nAustin, TX\ncaleb@example.com | (512) 555-0134")

    def url(self, path):
        return self.base + path

    def approve_and_press(self, record):
        policy.decide(record["approval"], "APPROVED", via="phone")
        return browser_loop.commit(record["id"])

    def assertBoundary(self, record, state, kind):
        self.assertEqual(record["state"], state, record.get("boundary"))
        self.assertEqual((record.get("boundary") or {}).get("kind"), kind, record.get("boundary"))
        self.assertTrue((record.get("boundary") or {}).get("say"), "a boundary says what is left")


CLINIC_INPUTS = {"full name": "Caleb Schulte", "email": "caleb@example.com",
                 "preferred day": "Tuesday", "reason for visit": "Routine cleaning",
                 "new patient": "Yes"}


@needs_browser
class TheSameLoopDrivesANonJobWizard(LoopCase):
    """No job code: the general skill, the goal's own inputs, a dental office."""

    def test_content_to_wizard_to_review_to_approval_to_receipt(self):
        record = browser_loop.pursue("request a dental cleaning appointment", self.url("/clinic"),
                                     inputs=CLINIC_INPUTS)
        self.assertBoundary(record, bm.AWAITING_APPROVAL, "SUBMIT_APPROVAL")
        self.assertEqual(record["skill"], "general")
        names = [c["name"] for c in record["checkpoints"]]
        for name in (bm.OBSERVED, bm.FILLED, bm.REVIEW_REACHED):
            self.assertIn(name, names)
        self.assertNotIn("/clinic/submit", self.state["posts"], "nothing was sent before his yes")
        done = self.approve_and_press(record)
        self.assertEqual(done["state"], bm.DONE, done.get("boundary"))
        self.assertIn(bm.RECEIPT_VERIFIED, [c["name"] for c in done["checkpoints"]])
        self.assertEqual(self.state["posts"].count("/clinic/submit"), 1)
        self.assertEqual(self.state["got"].get("name"), "Caleb Schulte")
        self.assertEqual(self.state["got"].get("day"), "tue")
        self.assertEqual(self.state["got"].get("why"), "Routine cleaning")
        self.assertEqual(self.state["got"].get("new"), "yes")
        # and what it learned is data for the next goal on this site
        skill = site_skills.for_domain(self.base)
        self.assertTrue(skill["page_states"])


@needs_browser
class ALibraryCardStopsAtAccountCreation(LoopCase):
    def test_account_creation_is_an_approval_not_a_click(self):
        record = browser_loop.pursue("get me a library card", self.url("/library/card"),
                                     inputs={"full name": "Caleb Schulte", "email": "caleb@example.com",
                                             "street address": "1 Main St"})
        self.assertBoundary(record, bm.AWAITING_APPROVAL, "ACCOUNT_CREATION_APPROVAL")
        self.assertEqual(self.state["posts"], [], "no account is made without his yes")
        approval = policy.load(record["approval"])
        self.assertEqual(approval["state"], "PENDING")
        self.assertTrue(approval["requested_action"].startswith("browser.interact:"),
                        "the existing hash-bound approval, not a new kind")


@needs_browser
class TheSameLoopDrivesAJobApplication(LoopCase):
    def test_posting_to_form_with_profile_and_resume(self):
        record = browser_loop.pursue(
            "apply for the systems engineer job", self.url("/careers/42"),
            inputs={"why do you want to work here": "I build unattended systems with quality gates."},
            skill=job_skill.SKILL)
        self.assertBoundary(record, bm.AWAITING_APPROVAL, "SUBMIT_APPROVAL")
        self.assertEqual(record["skill"], "job_application")
        done = self.approve_and_press(record)
        self.assertEqual(done["state"], bm.DONE, done.get("boundary"))
        got = self.state["got"]
        self.assertEqual((got.get("first_name"), got.get("last_name"), got.get("email")),
                         ("Caleb", "Schulte", "caleb@example.com"))
        self.assertEqual(got.get("why"), "I build unattended systems with quality gates.")
        self.assertEqual(got.get("resume"), "resume.pdf")


@needs_browser
class AnAccountWallIsANamedBoundary(LoopCase):
    def test_sign_in_stops_before_typing_anything(self):
        record = browser_loop.pursue("apply on the portal", self.url("/portal/apply"),
                                     inputs={"email": "caleb@example.com"})
        self.assertBoundary(record, bm.NEEDS_YOU, "SIGN_IN")
        self.assertEqual(record["boundary"]["page_state"], ps.ACCOUNT_LOGIN)
        self.assertEqual(self.state["posts"], [])


@needs_browser
class AServerErrorIsLookedAtAgain(LoopCase):
    def test_a_500_then_the_form(self):
        record = browser_loop.pursue("send the clinic a message", self.url("/flaky"),
                                     inputs={"full name": "Caleb Schulte", "message": "Hello"})
        self.assertBoundary(record, bm.AWAITING_APPROVAL, "SUBMIT_APPROVAL")
        self.assertGreaterEqual(self.state["hits"]["/flaky"], 2, "observation was retried")
        self.assertTrue(any("looking again" in h["did"] for h in record["history"]))


@needs_browser
class AMidRunCrashResumes(LoopCase):
    def test_the_route_is_replayed_not_redone(self):
        def crash(step, record):
            if step == 4:
                raise RuntimeError("the process died")
        with self.assertRaises(RuntimeError):
            browser_loop.pursue("request a dental cleaning appointment", self.url("/clinic"),
                                inputs=CLINIC_INPUTS, on_step=crash)
        mid = bm.mission_id("request a dental cleaning appointment", self.url("/clinic"))
        crashed = bm.load(mid)
        self.assertEqual(crashed["state"], bm.RUNNING)
        self.assertTrue(crashed["route"], "the route survived the crash")
        before = len(crashed["checkpoints"])
        record = browser_loop.resume(mid, force=True)
        self.assertBoundary(record, bm.AWAITING_APPROVAL, "SUBMIT_APPROVAL")
        self.assertGreater(len(record["checkpoints"]), before)
        self.assertEqual(record["checkpoints"][:before], crashed["checkpoints"][:before],
                         "checkpoints from before the crash are kept, not restarted")
        self.assertTrue(any("resumed: replaying" in h["did"] for h in record["history"]))


@needs_browser
class ADuplicateSubmitIsRefused(LoopCase):
    def test_a_confirmed_submission_is_never_pressed_again(self):
        goal, start = "request a dental cleaning appointment", self.url("/clinic")
        record = browser_loop.pursue(goal, start, inputs=CLINIC_INPUTS)
        done = self.approve_and_press(record)
        self.assertEqual(done["state"], bm.DONE)
        with self.assertRaises(Exception):
            browser_loop.commit(done["id"])
        again = browser_loop.pursue(goal, start, inputs=CLINIC_INPUTS)
        self.assertEqual(again["state"], bm.DONE)
        self.assertEqual(self.state["posts"].count("/clinic/submit"), 1)

    def test_a_server_error_after_the_press_is_not_proof_it_failed(self):
        self.state["send_fails"] = True
        goal, start = "send the clinic a message", self.url("/flaky")
        record = browser_loop.pursue(goal, start, inputs={"full name": "Caleb Schulte", "message": "Hi"})
        after = self.approve_and_press(record)
        self.assertEqual(after["state"], bm.SUBMITTED_UNCONFIRMED, after.get("boundary"))
        self.assertEqual(after["submits"][-1]["verdict"], "error")
        # Someone (or a bug) puts it back to RUNNING: the invariant still holds
        # at the gate, and no second approval is filed.
        after["state"] = bm.RUNNING
        bm.save(after)
        approvals_before = sorted(p.name for p in policy.APPROVALS_DIR.iterdir())
        again = browser_loop.pursue(goal, start)
        self.assertBoundary(again, bm.NEEDS_YOU, "DUPLICATE_SUBMIT")
        self.assertEqual(sorted(p.name for p in policy.APPROVALS_DIR.iterdir()), approvals_before)
        self.assertEqual(self.state["posts"].count("/flaky/send"), 1)

    def test_a_site_that_hands_it_back_may_be_tried_again_with_a_fresh_yes(self):
        goal, start = "send feedback", self.url("/picky")
        record = browser_loop.pursue(goal, start, inputs={"zip code": "57104"})
        first = self.approve_and_press(record)
        self.assertEqual(first["state"], bm.REJECTED, first.get("boundary"))
        again = browser_loop.pursue(goal, start)
        self.assertBoundary(again, bm.AWAITING_APPROVAL, "SUBMIT_APPROVAL")
        self.assertNotEqual(again["approval"], record["approval"], "a retry asks him again")


@needs_browser
class ACaptchaIsHandedOffAndResumed(LoopCase):
    def test_everything_allowed_then_the_exact_step_then_carry_on(self):
        goal, start = "join the newsletter", self.url("/guarded")
        record = browser_loop.pursue(goal, start, inputs={"email": "caleb@example.com"})
        self.assertBoundary(record, bm.NEEDS_YOU, ps.CAPTCHA)
        self.assertEqual(record["mode"], browser_loop.ASSISTED)
        self.assertIn(bm.FILLED, [c["name"] for c in record["checkpoints"]],
                      "what was allowed was done before stopping")
        self.state["solved"] = True          # he passed the check himself
        resumed = browser_loop.resume(record["id"], done="captcha")
        self.assertBoundary(resumed, bm.AWAITING_APPROVAL, "SUBMIT_APPROVAL")
        skill = site_skills.for_domain(self.base)
        self.assertIn(ps.CAPTCHA, [b["kind"] for b in skill["boundaries"]])


@needs_browser
class AVerificationCodeArrivesAsAnEvent(LoopCase):
    def test_wait_for_the_code_then_carry_on(self):
        goal, start = "sign me up to volunteer", self.url("/volunteer")
        inputs = {"email": "caleb@example.com", "preferred shift": "Saturday morning"}
        record = browser_loop.pursue(goal, start, inputs=inputs)
        self.assertBoundary(record, bm.NEEDS_YOU, "WAITING_FOR_CODE")
        browser_loop.post_code(record["id"], "731904")
        resumed = browser_loop.resume(record["id"])
        self.assertBoundary(resumed, bm.AWAITING_APPROVAL, "SUBMIT_APPROVAL")
        self.assertEqual(self.state["got"].get("code"), "731904")


@needs_browser
class AQuestionIsAskedOnceAndHisAnswerCarriesOn(LoopCase):
    def test_questions_then_answers_then_approval_and_nothing_asked_twice(self):
        goal, start = "request a dental cleaning appointment", self.url("/clinic")
        partial = {k: v for k, v in CLINIC_INPUTS.items() if k != "reason for visit"}
        record = browser_loop.pursue(goal, start, inputs=partial)
        self.assertBoundary(record, bm.NEEDS_YOU, "QUESTIONS")
        self.assertEqual(record["boundary"]["questions"], ["Reason for visit *"],
                         "exactly what is missing, and nothing he already gave")

        # A tool-level action may not type a value that is not his.
        from aletheia import browser_tools
        refused = browser_tools._act({"mission": record["id"], "act": "fill",
                                      "target": {"role": "textbox", "label": "Reason for visit"},
                                      "value": "a plausible reason I made up"})
        self.assertFalse(refused["done"])
        self.assertIn("will not type a guess", refused["problem"])
        self.assertNotIn("_refs", refused["page"])
        self.assertTrue(all("selector" not in t for t in refused["page"]["targets"]))

        done = browser_loop.resume(record["id"], answers={"reason for visit": "Routine cleaning"})
        self.assertBoundary(done, bm.AWAITING_APPROVAL, "SUBMIT_APPROVAL")


@needs_browser
class ObservingIsReadingOnly(LoopCase):
    def test_the_observe_tool_returns_semantic_targets_and_a_state(self):
        from aletheia import browser_tools
        seen = browser_tools._observe({"url": self.url("/library/card")})
        self.assertEqual(seen["state"], ps.FORM)
        labels = {(t["role"], t["label"]) for t in seen["targets"]}
        self.assertIn(("textbox", "Full name *"), labels)
        self.assertIn(("button", "Create account"), labels)
        self.assertTrue(all("selector" not in t for t in seen["targets"]))
        self.assertEqual(self.state["posts"], [])


@needs_browser
class AManualOnlySiteIsNeverOpened(LoopCase):
    def test_indeed_is_his(self):
        with mock.patch.object(browse, "_Session", side_effect=AssertionError("opened a browser")):
            record = browser_loop.pursue("apply to this job", "https://www.indeed.com/viewjob?jk=1")
        self.assertBoundary(record, bm.MANUAL_ONLY, "MANUAL_ONLY")


if __name__ == "__main__":
    unittest.main()
