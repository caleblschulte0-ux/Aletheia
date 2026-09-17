"""Apply anywhere, continued: the known gaps of the general browser loop, closed.

Continuity wave C3a (docs/CONTINUITY_BRIEF.md III.7-8). Each of these was a
place a real site could end a mission for no good reason, and each fix lives
in the GENERAL layer (page states, the loop, the press path), never as a
special case for one site:

- a site that asks for an emailed code AFTER the approved press (Greenhouse's
  security code, on the same form) is finished in that browser, once, with
  the site's own mail - or stops at a named boundary and never presses twice;
- a texted code and a second factor are clean boundaries: no mailbox read,
  no guessing, the step says where the code went;
- a Phone box on a form no longer turns an emailed code into a texted one;
- her own sign-in that fails is recovered through the site's password reset
  (each press still an approval), and a lock stops without trying again;
- a long question cut short by one reader and whole in another is asked once;
- the invisible reCAPTCHA badge is not a CAPTCHA to the application engine.

Loopback fixtures and a throwaway profile; browser tests skip without playwright.
"""
from __future__ import annotations

import email.utils
import http.server
import threading
import time
import unittest
import urllib.parse
from unittest import mock

from aletheia import (apply_run, browse, browser_loop, browser_mission as bm, job_skill,
                      page_state as ps, policy, secret_store, signup, verification_mail)
from tests.test_browser_loop_accounts import FakeVault
from tests.test_browser_loop_torture import LoopCase, needs_browser


def t(role, label, **kw):
    return {"id": f"t{abs(hash((role, label))) % 10_000}", "role": role, "label": label, **kw}


# ---- units: no browser -------------------------------------------------------------

class CodesAndFactorsAreReadForWhatTheyAre(unittest.TestCase):
    def state(self, text, targets):
        return ps.classify({"text": text, "targets": targets})["state"]

    def test_a_phone_box_does_not_make_an_emailed_code_a_text(self):
        text = ("Apply for this job. First name. Phone. We emailed a security code to you. "
                "Enter the security code below to submit your application.")
        targets = [t("textbox", "First Name *"), t("textbox", "Phone *"), t("textbox", "Security code"),
                   t("button", "Submit application")]
        self.assertEqual(self.state(text, targets), ps.EMAIL_VERIFICATION)

    def test_a_texted_code_is_still_a_text(self):
        for text in ("We sent a code to your phone ending in 34. Enter the code.",
                     "Enter the verification code we sent by SMS.",
                     "We texted you a 6-digit code."):
            self.assertEqual(self.state(text, [t("textbox", "Code"), t("button", "Verify")]),
                             ps.SMS_VERIFICATION, text)

    def test_an_authenticator_or_a_push_is_a_second_factor(self):
        self.assertEqual(self.state("Two-step verification. Enter the code from your authenticator app.",
                                    [t("textbox", "Code"), t("button", "Verify")]), ps.MFA_CHALLENGE)
        self.assertEqual(self.state("Check your phone to approve the sign-in request.", [t("button", "Resend")]),
                         ps.MFA_CHALLENGE)
        self.assertIn(ps.MFA_CHALLENGE, ps.STATES)

    def test_a_sign_in_page_offering_a_passkey_is_still_a_sign_in(self):
        self.assertEqual(self.state("Sign in. Or use a passkey.",
                                    [t("textbox", "Email"), t("password", "Password"), t("button", "Sign in")]),
                         ps.ACCOUNT_LOGIN)

    def test_the_code_box_is_found_by_its_words_among_other_boxes(self):
        obs = {"targets": [t("textbox", "First Name *", value="Pat"), t("textbox", "Phone *"),
                           t("textbox", "Security code")]}
        self.assertEqual(browser_loop.code_box(obs)["label"], "Security code")
        self.assertIsNone(browser_loop.code_box({"targets": [t("textbox", "First"), t("textbox", "Last")]}),
                          "with several boxes and none named for a code, nothing is guessed")
        self.assertEqual(browser_loop.code_box({"targets": [t("textbox", "Enter it here")]})["label"],
                         "Enter it here")

    def test_the_phone_hint(self):
        self.assertEqual(browser_loop.phone_hint({"text": "We sent a code to the number ending in 0134."}),
                         "the number ending in 0134")
        self.assertEqual(browser_loop.phone_hint({"text": "Enter the code."}), "")


LONG = ("Are you legally authorized to work in the United States for any employer without the need for "
        "current or future visa sponsorship, including OPT, CPT or H-1B transfer?")


class ALongQuestionIsAskedOnce(unittest.TestCase):
    def test_cut_and_whole_are_one_question(self):
        cut = LONG[:120]
        self.assertTrue(browser_loop.same_question(cut, LONG))
        self.assertTrue(browser_loop.same_question(LONG + " *", LONG))
        self.assertFalse(browser_loop.same_question("Name", "Name of your last employer"),
                         "a short label is never a prefix match")
        self.assertEqual(browser_loop.unique_questions([cut, "Phone *", LONG]), [LONG, "Phone *"],
                         "the fullest wording is kept, in first-asked order")

    def test_a_boundary_never_carries_the_same_question_twice(self):
        record = bm.open_mission("apply for the ops job", "https://jobs.example.com/1")
        stopped = browser_loop._stop(record, bm.NEEDS_YOU, "QUESTIONS", {"url": "https://jobs.example.com/1"},
                                     questions=[LONG[:120], LONG, "Pronouns"])
        self.assertEqual(stopped["boundary"]["questions"], [LONG, "Pronouns"])


class ContentNavigationPrefersTheGoal(unittest.TestCase):
    def obs(self):
        return {"url": "https://shop.example.org/c", "state": ps.CONTENT,
                "targets": [{"id": "t1", "role": "link", "label": "next"},
                            {"id": "t2", "role": "link", "label": "Poetry"},
                            {"id": "t3", "role": "link", "label": "Add to basket"}],
                "_refs": {"t1": "#n", "t2": "#p", "t3": "#b"}}

    def test_a_link_the_goal_names_outranks_a_list_next(self):
        target = browser_loop.way_forward(self.obs(), "open the poetry category", browser_loop.GENERAL, {},
                                          tried=set())
        self.assertEqual(target["label"], "Poetry")
        target = browser_loop.way_forward(self.obs(), "read the terms", browser_loop.GENERAL, {}, tried=set())
        self.assertEqual(target["label"], "next", "with nothing named, Next is still a way on")

    def test_a_model_may_say_the_goal_is_reached_but_never_press(self):
        record = bm.open_mission("find a book of poems", "https://shop.example.org/")
        said = browser_loop._ask_model(lambda g, p, h: {"target": None, "done": True, "by": "ollama:qwen3:8b"},
                                       "find a book of poems", self.obs(), record)
        self.assertEqual(said, {"done": True, "by": "ollama:qwen3:8b", "why": None})
        self.assertEqual(record["last_decision"]["by"], "ollama:qwen3:8b")
        check = browser_loop._decision_validator(self.obs())
        self.assertTrue(check({"target": None, "done": True, "sure": True})["done"])
        self.assertFalse(check({"target": None, "sure": False})["done"])


# ---- browser fixtures ----------------------------------------------------------------

GH_FORM = """<title>Apply</title><h1>Operations Associate</h1>%(note)s
<form method="POST" action="/gh/submit">
<label for="fn">First Name *</label><input id="fn" name="first_name" value="%(fn)s" required>
<label for="ph">Phone *</label><input id="ph" name="phone" value="%(ph)s" required>
%(code)s<button type="submit">Submit application</button></form>"""
GH_CODE_NOTE = ("<p>We emailed a security code to you. Enter the security code below to submit "
                "your application.</p>")
GH_CODE_BOX = '<label for="sc">Security code</label><input id="sc" name="security_code">'
SMS_PAGE = """<h1>Confirm it's you</h1><p>We sent a verification code to your phone ending in 34.
Enter the code.</p><form method="POST" action="/sms/done"><label for="c">Code</label>
<input id="c" name="code"><button type="submit">Verify</button></form>"""
MFA_PAGE = """<h1>Two-step verification</h1><p>Enter the code from your authenticator app.</p>
<form method="POST" action="/mfa/done"><label for="c">Code</label><input id="c" name="code">
<button type="submit">Verify</button></form>"""
LONG_FORM = """<h1>Application</h1><form method="POST" action="/long/send">
<label for="n">Full name *</label><input id="n" name="name" required>
<label for="q">%s *</label><textarea id="q" name="q" required></textarea>
<button type="submit">Submit application</button></form>""" % LONG

SIGNIN = """<h2>Sign In</h2>%s<form method="POST" action="/acct/session">
<label for="e">Email Address</label><input id="e" name="email">
<label for="p">Password</label><input id="p" name="password" type="password">
<button type="submit">Sign In</button></form><a href="/acct/forgot">Forgot your password?</a>"""
FORGOT = """<h2>Reset your password</h2><form method="POST" action="/acct/forgot">
<label for="e">Email Address *</label><input id="e" name="email" required>
<button type="submit">Send reset link</button></form>"""
SENT = "<h1>Check your email</h1><p>Check your email for a link to reset your password.</p>"
RESET = """<h2>Choose a new password</h2><form method="POST" action="/acct/reset">
<label for="p">New password *</label><input id="p" name="password" type="password" required>
<label for="v">Confirm new password *</label><input id="v" name="verify" type="password" required>
<button type="submit">Reset password</button></form>"""
ACCT_APPLY = """<h1>Your application</h1><form method="POST" action="/acct/submit">
<label for="n">Full name *</label><input id="n" name="name" required>
<button type="submit">Submit application</button></form>"""


def _site(state: dict):
    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, body, code=200, headers=()):
            raw = body.encode()
            self.send_response(code)
            for k, v in headers:
                self.send_header(k, v)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def _go(self, where, cookie=None):
            self._send("", 303, [("Location", where)] + ([("Set-Cookie", cookie)] if cookie else []))

        def do_GET(self):
            path, _, query = self.path.partition("?")
            if path == "/gh/job":
                return self._send(GH_FORM % {"note": "", "fn": "", "ph": "", "code": ""})
            if path == "/acct/apply":
                if "sid=1" not in (self.headers.get("Cookie") or ""):
                    return self._go("/acct/signin")
                return self._send(ACCT_APPLY)
            if path == "/acct/reset":
                if urllib.parse.parse_qs(query).get("token") != ["xyz"]:
                    return self._send("<h1>404</h1>", 404)
                return self._send(RESET)
            pages = {"/sms": SMS_PAGE, "/mfa": MFA_PAGE, "/long": LONG_FORM, "/acct/signin": SIGNIN % "",
                     "/acct/forgot": FORGOT, "/acct/forgot/sent": SENT}
            self._send(pages.get(path, "<h1>404</h1>"), 200 if path in pages else 404)

        def do_POST(self):
            size = int(self.headers.get("Content-Length", "0"))
            form = {k: v[0] for k, v in urllib.parse.parse_qs(self.rfile.read(size).decode()).items()}
            state["posts"].append(self.path)
            if self.path == "/gh/submit":
                if form.get("security_code") == state["code"]:
                    state["received"].append(form)
                    return self._send("<h1>Thank you for applying</h1><p>Your application has been received.</p>")
                return self._send(GH_FORM % {"note": GH_CODE_NOTE, "fn": form.get("first_name", ""),
                                             "ph": form.get("phone", ""), "code": GH_CODE_BOX})
            if self.path == "/acct/session":
                if state.get("locked"):
                    return self._send(SIGNIN % '<p class="error" role="alert">Too many attempts. '
                                               'Try again later.</p>')
                if form.get("password") == state["password"]:
                    return self._go("/acct/apply", cookie="sid=1; Path=/")
                return self._send(SIGNIN % '<p class="error" role="alert">Invalid email or password.</p>')
            if self.path == "/acct/forgot":
                state["reset_for"] = form.get("email")
                return self._go("/acct/forgot/sent")
            if self.path == "/acct/reset":
                if form.get("password") and form.get("password") == form.get("verify"):
                    state["password"] = form["password"]
                return self._go("/acct/signin")
            if self.path == "/acct/submit":
                state["received"].append(form)
                return self._send("<h1>Thank you</h1><p>Your application was received.</p>")
            self._send("<h1>Thank you</h1><p>Received.</p>")
    return H


class FakeMailbox:
    def __init__(self, messages):
        self.messages = list(messages)
        self.calls = 0

    def fetch_recent(self, since_epoch, limit=25):
        self.calls += 1
        return list(self.messages)


class AnywhereCase(LoopCase):
    def setUp(self):
        super().setUp()
        self.site = {"posts": [], "received": [], "code": "ApHIj2MW", "password": "right-one"}
        probe = http.server.HTTPServer(("127.0.0.1", 0), lambda *a: None)
        port = probe.server_address[1]
        probe.server_close()
        self.host = f"http://127.0.0.1:{port}"
        server = http.server.ThreadingHTTPServer(("127.0.0.1", port), _site(self.site))
        server.daemon_threads = True
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        self.mailbox = FakeMailbox([])
        factory = mock.patch.object(browser_loop, "code_source_factory",
                                    lambda: verification_mail.MailCodes(self.mailbox, tries=1, wait_s=0))
        factory.start()
        self.addCleanup(factory.stop)

    def mail_code(self, code):
        self.mailbox.messages.append({
            "from": "Greenhouse <no-reply@127.0.0.1>", "message_id": f"<{code}>", "subject": "Security code",
            "date": email.utils.formatdate(time.time() + 5, usegmt=True),
            "text": f"Copy and paste this code into the security code field on your application: {code}"})


@needs_browser
class ACodeAfterTheApprovedPressIsFinishedOnce(AnywhereCase):
    inputs = {"first name": "Pat", "phone": "605-555-0100"}

    def test_the_emailed_code_finishes_the_submission_in_the_same_browser(self):
        self.mail_code("ApHIj2MW")
        record = browser_loop.pursue("send the operations application", self.host + "/gh/job", inputs=self.inputs)
        self.assertBoundary(record, bm.AWAITING_APPROVAL, "SUBMIT_APPROVAL")
        done = self.approve_and_press(record)
        self.assertEqual(done["state"], bm.DONE, done.get("boundary"))
        self.assertEqual(len(self.site["received"]), 1)
        self.assertEqual(self.site["received"][0]["security_code"], "ApHIj2MW")
        self.assertEqual(self.site["posts"].count("/gh/submit"), 2, "the approved press, then the code press")
        self.assertEqual(len(done["submits"]), 1, "one submission, finished with its code")
        self.assertTrue(done.get("code_continued"))
        self.assertEqual(len(list(policy.APPROVALS_DIR.iterdir())), 1, "one approval, never a second")

    def test_no_code_is_a_named_boundary_and_never_a_second_press(self):
        record = browser_loop.pursue("send the operations application", self.host + "/gh/job", inputs=self.inputs)
        held = self.approve_and_press(record)
        self.assertBoundary(held, bm.NEEDS_YOU, "CODE_AFTER_SUBMIT")
        self.assertEqual(held["submits"][-1]["verdict"], browser_loop.VERIFICATION_REQUIRED)
        self.assertIn("code", held["boundary"]["say"])
        self.assertEqual(self.site["received"], [])
        approvals = sorted(p.name for p in policy.APPROVALS_DIR.iterdir())
        again = browser_loop.pursue("send the operations application", self.host + "/gh/job", inputs=self.inputs)
        self.assertBoundary(again, bm.NEEDS_YOU, "DUPLICATE_SUBMIT")
        self.assertEqual(sorted(p.name for p in policy.APPROVALS_DIR.iterdir()), approvals)
        self.assertEqual(self.site["posts"].count("/gh/submit"), 1)


@needs_browser
class TextedCodesAndSecondFactorsAreCleanBoundaries(AnywhereCase):
    def test_a_texted_code_never_reads_the_mailbox(self):
        record = browser_loop.pursue("confirm my sign up", self.host + "/sms", inputs={},
                                     code_source=verification_mail.MailCodes(self.mailbox, tries=1, wait_s=0))
        self.assertBoundary(record, bm.NEEDS_YOU, "WAITING_FOR_CODE")
        self.assertEqual(record["boundary"]["via"], "text")
        self.assertIn("ending in 34", record["boundary"]["step"])
        self.assertEqual(self.mailbox.calls, 0)
        browser_loop.post_code(record["id"], "481516")
        resumed = browser_loop.resume(record["id"])
        self.assertNotEqual((resumed.get("boundary") or {}).get("kind"), "WAITING_FOR_CODE")
        self.assertIn("/sms/done", self.site["posts"], "a code he relays carries it on")

    def test_an_authenticator_is_his(self):
        record = browser_loop.pursue("confirm my sign in", self.host + "/mfa", inputs={},
                                     code_source=verification_mail.MailCodes(self.mailbox, tries=1, wait_s=0))
        self.assertBoundary(record, bm.NEEDS_YOU, "WAITING_FOR_MFA")
        self.assertEqual(self.mailbox.calls, 0)
        self.assertEqual(self.site["posts"], [])


@needs_browser
class ALongQuestionOnARealPageIsAskedOnce(AnywhereCase):
    def test_the_job_skill_asks_it_once(self):
        record = browser_loop.pursue("apply for the operations job", self.host + "/long",
                                     inputs={"full name": "Pat Doe"}, skill=job_skill.SKILL)
        self.assertBoundary(record, bm.NEEDS_YOU, "QUESTIONS")
        questions = record["boundary"]["questions"]
        self.assertEqual(sum(1 for q in questions if q.startswith(LONG[:60])), 1, questions)


@needs_browser
class HerFailedSignInIsRecovered(AnywhereCase):
    def setUp(self):
        super().setUp()
        self.vault = FakeVault()
        for name in ("available", "put", "get", "exists"):
            patch = mock.patch.object(secret_store, name, getattr(self.vault, name))
            patch.start()
            self.addCleanup(patch.stop)
        self.vault.put(signup.account_alias("127.0.0.1"), "stale-password")
        signup.record_account("127.0.0.1", username="pat@example.com")

    def test_wrong_password_goes_through_the_sites_reset_with_approvals(self):
        goal, start = "send my application", self.host + "/acct/apply"
        first = browser_loop.pursue(goal, start, inputs={"full name": "Pat Doe"})
        self.assertBoundary(first, bm.AWAITING_APPROVAL, "SUBMIT_APPROVAL")
        self.assertEqual(first["boundary"]["step"], "press 'Send reset link'")
        self.assertEqual(self.site["posts"].count("/acct/session"), 1, "one wrong guess, not two")
        sent = self.approve_and_press(first)
        self.assertEqual(sent["state"], bm.RUNNING, sent.get("boundary"))
        self.assertEqual(self.site["reset_for"], "pat@example.com")

        waiting = browser_loop.pursue(goal, start)
        self.assertBoundary(waiting, bm.NEEDS_YOU, "WAITING_FOR_LINK")
        bm.post_event(waiting["id"], "link", self.host + "/acct/reset?token=xyz")
        reset = browser_loop.resume(waiting["id"])
        self.assertBoundary(reset, bm.AWAITING_APPROVAL, "SUBMIT_APPROVAL")
        self.assertEqual(reset["boundary"]["step"], "press 'Reset password'")
        new_password = self.vault.rows[signup.account_alias("127.0.0.1")]
        self.assertNotEqual(new_password, "stale-password", "a new password, in the vault before it is typed")

        after = self.approve_and_press(reset)
        self.assertEqual(after["state"], bm.RUNNING, after.get("boundary"))
        self.assertEqual(self.site["password"], new_password)
        ready = browser_loop.pursue(goal, start)
        self.assertBoundary(ready, bm.AWAITING_APPROVAL, "SUBMIT_APPROVAL")
        self.assertEqual(ready["boundary"]["step"], "press 'Submit application'")
        self.assertTrue(ready.get("recovered"))
        self.assertEqual(self.site["received"], [], "nothing sent without his yes")
        done = self.approve_and_press(ready)
        self.assertEqual(done["state"], bm.DONE, done.get("boundary"))
        self.assertEqual(self.site["received"][0]["name"], "Pat Doe")

    def test_a_lock_stops_without_trying_again(self):
        self.site["locked"] = True
        record = browser_loop.pursue("send my application", self.host + "/acct/apply",
                                     inputs={"full name": "Pat Doe"})
        self.assertBoundary(record, bm.NEEDS_YOU, "SIGN_IN_FAILED")
        self.assertIn("Too many attempts", " ".join(record["boundary"]["site_said"]))
        self.assertEqual(self.site["posts"].count("/acct/session"), 1)
        self.assertNotIn("/acct/forgot", self.site["posts"])

    def test_not_her_account_is_still_his_to_sign_in(self):
        with mock.patch.object(signup, "known_account", return_value=None):
            record = browser_loop.pursue("send my application", self.host + "/acct/apply")
        self.assertBoundary(record, bm.NEEDS_YOU, "SIGN_IN")
        self.assertEqual(self.site["posts"], [])


@needs_browser
class TheInvisibleBadgeIsNotACaptchaToTheEngine(LoopCase):
    def test_badge_versus_widget(self):
        with browse._Session() as ctx:
            page = ctx.new_page()
            try:
                page.set_content('<div class="grecaptcha-badge" style="width:256px;height:60px">'
                                 '<iframe src="http://127.0.0.1:9/recaptcha/api2/anchor?k=x&size=invisible">'
                                 '</iframe></div><script src="http://127.0.0.1:9/recaptcha/enterprise.js'
                                 '?render=key"></script>')
                self.assertEqual(apply_run._captcha_on(page), "")
                page.set_content('<div class="g-recaptcha" data-sitekey="x" style="width:304px;height:78px">'
                                 '</div>')
                self.assertEqual(apply_run._captcha_on(page), "recaptcha")
                page.set_content('<script src="http://127.0.0.1:9/hcaptcha.com/1/api.js"></script>')
                self.assertEqual(apply_run._captcha_on(page), "hcaptcha",
                                 "an invisible hCaptcha still counts (it blocked Lever's clicks)")
            finally:
                page.close()



# ---- what the live proof matrix found (2026-09-17) -----------------------------------

class TheFormReaderReadsWhatTheLiveSitesSaid(unittest.TestCase):
    def test_an_id_is_words_so_first_name_is_not_the_full_name(self):
        from aletheia import formfill
        known = {"first_name": "Jordan", "last_name": "Testperson", "legal_name": "Jordan Testperson",
                 "email": "j@example.com", "phone": "(605) 555-0142"}
        rows = [{"selector": f"#x{i}", "tag": "input", "type": "text", "name": "", "id": code, "label": "",
                 "required": False, "value": ""}
                for i, code in enumerate(["info.firstName", "info.middleName", "info.lastName", "info.email"])]
        got = {f["label"]: (f["profile_field"], f["value"]) for f in formfill.plan(rows, answers=known)["fill"]}
        self.assertEqual(got["info.firstName"], ("first_name", "Jordan"))
        self.assertEqual(got["info.lastName"], ("last_name", "Testperson"))
        self.assertNotIn("info.middleName", got, "a middle name is never his full name")
        self.assertEqual(browser_loop.code_words("info.firstName"), "info first name")

    def test_a_question_that_mentions_the_phone_is_not_asking_for_his_number(self):
        from aletheia import formfill
        self.assertIsNone(formfill.match_field(
            {"label": "How much experience do you have providing Customer Service over the phone?*"}))
        self.assertIsNone(formfill.match_field(
            {"label": "Regarding providing customer service over the phone, what do you enjoy the most?"}))
        self.assertEqual(formfill.match_field({"label": "What is your phone number?"}), "phone")
        self.assertEqual(formfill.match_field({"label": "Phone*"}), "phone")

    def test_an_asterisk_is_required_and_a_nameless_button_is_never_the_one_approved(self):
        self.assertTrue(browser_loop._marked_required({"label": "Are you fluent in English and Spanish?*"}))
        self.assertFalse(browser_loop._marked_required({"label": "Who referred you?"}))
        obs = {"state": ps.FORM, "targets": [
            {"id": "t1", "role": "textbox", "label": "Name"}, {"id": "t2", "role": "button", "label": ""},
            {"id": "t3", "role": "button", "label": "SHARE"},
            {"id": "t4", "role": "link", "label": "Submit Application"}]}
        self.assertEqual(browser_loop.final_control(obs, "apply for the job")["label"], "Submit Application")
        obs["targets"] = obs["targets"][:2]
        self.assertIsNone(browser_loop.final_control(obs, "apply for the job"))


CONSENT_POSTING = """<title>Administrative Assistant</title><h1>Administrative Assistant</h1>
<p>Description. Responsibilities: answer phones.</p>
<label for="share">Link to This Job</label><input id="share" readonly value="https://example.org/careers/167">
<a href="/lv/apply">Apply</a>
<div id="onetrust-consent-sdk" style="position:fixed;bottom:0;width:100%%;background:#eee">
  <label><input type="checkbox" id="tc"> Targeting Cookies</label>
  <button id="icon1" style="width:20px;height:20px"></button>
  <button id="acc">Accept All Cookies</button><button id="rej">Reject All</button></div>"""
LV_APPLY = """<title>Apply</title><h1>Application</h1><p>Upload your resume below.</p>
<form method="POST" action="/lv/send">
<label>First Name (required)</label><input id="info.firstName" required>
<label>Middle Name</label><input id="info.middleName">
<label for="q1">How much experience do you have providing customer service over the phone?*</label>
<textarea id="q1" name="q1"></textarea>
<div>Choose File*</div><input type="file">
<button type="button">SHARE</button>
<a href="#" id="go" onclick="document.forms[0].submit();return false;">Submit Application</a></form>"""


@needs_browser
class WhatTheMatrixFoundOnRealPagesStaysFixed(AnywhereCase):
    def setUp(self):
        super().setUp()
        self.site["pages"] = {"/lv/posting": CONSENT_POSTING, "/lv/apply": LV_APPLY}

    def serve(self):
        pages = self.site["pages"]
        original = self.site
        import http.server as hs

        class H(hs.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                body = pages.get(self.path.split("?")[0], "<h1>404</h1>").encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self):
                original["posts"].append(self.path)
                body = b"<h1>Thank you</h1>"
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
        probe = hs.HTTPServer(("127.0.0.1", 0), lambda *a: None)
        port = probe.server_address[1]
        probe.server_close()
        server = hs.ThreadingHTTPServer(("127.0.0.1", port), H)
        server.daemon_threads = True
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return f"http://127.0.0.1:{port}"

    def test_a_posting_behind_a_cookie_banner_to_a_form_with_honest_questions(self):
        from aletheia import profile
        base = self.serve()
        with mock.patch.object(profile, "known", return_value={
                "first_name": "Pat", "last_name": "Doe", "legal_name": "Pat Doe", "phone": "(605) 555-0100"}):
            record = browser_loop.pursue("apply for the administrative assistant job", base + "/lv/posting",
                                         inputs={}, skill=job_skill.SKILL)
        self.assertBoundary(record, bm.NEEDS_YOU, "QUESTIONS")
        self.assertTrue(any("Reject All" in h["did"] for h in record["history"]),
                        "the banner was closed by its least-consenting button")
        self.assertFalse(any("Accept" in h["did"] for h in record["history"]))
        values = {r["selector"]: r.get("value") for r in record["route"] if r["action"] == "type"}
        self.assertEqual(values.get(r"#info\.firstName"), "Pat")
        self.assertNotIn(r"#info\.middleName", values)
        self.assertNotIn("#q1", values, "a question about the phone never gets his number")
        self.assertTrue(record["attached"], "the one unnamed file box on a resume page takes the resume")
        self.assertIn("How much experience do you have providing customer service over the phone?*",
                      record["boundary"]["questions"])
        self.assertEqual(self.site["posts"], [])



# ---- the second half of the matrix (Workday, UltiPro, Avature, Jane Street, a city form) ----

class TheSecondHalfOfTheMatrixUnits(unittest.TestCase):
    def test_a_renumbered_page_does_not_make_a_tried_control_new(self):
        obs1 = {"_refs": {"t3": "a[href='/apply']"}}
        obs2 = {"_refs": {"t9": "a[href='/apply']"}}
        self.assertEqual(browser_loop.tried_key(obs1, {"id": "t3"}), browser_loop.tried_key(obs2, {"id": "t9"}))

    def test_a_closed_posting_is_a_stop_for_the_job_skill_only(self):
        obs = {"state": ps.CONTENT, "title": "Customer Service Supervisor",
               "text": "Posting Details Posted: April 2, 2026 Closed: April 7, 2026 Full-Time Remote"}
        stop = job_skill.SKILL.boundary(obs)
        self.assertEqual(stop["kind"], "POSTING_CLOSED")
        self.assertIsNone(browser_loop.GENERAL.boundary(obs), "the general loop knows nothing of postings")
        self.assertIsNone(job_skill.SKILL.boundary({"state": ps.CONTENT, "text": "We closed deals. Apply now."}))

    def test_signing_in_somewhere_else_is_a_sign_in_not_a_button_to_approve(self):
        for label in ("Apply With LinkedIn", "Dropbox", "Indeed Resume", "Google Drive", "Sign in with Google"):
            self.assertEqual(ps.control_kind(label, on_form=True), ps.SIGN_IN, label)
        self.assertEqual(ps.control_kind("Upload a resume", on_form=True), ps.OTHER)
        self.assertEqual(ps.control_kind("Submit application", on_form=True), ps.COMMIT)

    def test_an_address_line_naming_three_things_is_none_of_them(self):
        from aletheia import formfill
        self.assertIsNone(formfill.match_field({"label": "City, State, Zip Code"}))
        self.assertEqual(formfill.match_field({"label": "Zip Code"}), "postal_code")
        self.assertIsNone(browser_loop.match_key("City, State, Zip Code", {"zip code": "57104"}))
        poisoned = {"field_aliases": {"city state zip code": "zip code", "given name": "first_name"}}
        self.assertIsNone(browser_loop.match_key("City, State, Zip Code", {"zip code": "57104"}, poisoned),
                          "a learned alias the rules now refuse is not trusted")
        self.assertEqual(browser_loop.match_key("Given name", {"first_name": "Pat"}, poisoned), "first_name")
        self.assertEqual(browser_loop.match_key("Your email address", {"email address": "x"}), "email address")

    def test_the_job_skill_does_not_type_what_the_page_already_holds(self):
        obs = {"state": ps.FORM, "url": "https://x.example/apply", "title": "Apply", "text": "",
               "targets": [{"id": "t1", "role": "textbox", "label": "First Name *", "value": "Pat", "required": True}],
               "_refs": {"t1": "#fn"},
               "_raw": [{"selector": "#fn", "tag": "input", "type": "text", "label": "First Name *",
                         "required": True, "value": "Pat"}]}
        from aletheia import profile
        with mock.patch.object(profile, "known", return_value={"first_name": "Pat"}):
            planned = job_skill.SKILL.plan(obs, {"inputs": {}, "attached": []}, {})
        self.assertEqual(planned["fill"], [], "a resumed page is not refilled")


CITY = """<h1>Employment Application</h1><form onsubmit="return false">
<input type="text" id="c_last" placeholder="Last Name" data-required_mark="required">
<input type="text" id="c_first" placeholder="First Name" data-required_mark="required">
<input type="text" id="c_where" placeholder="City, State, Zip Code" data-required_mark="required">
<input type="text" id="c_salary" placeholder="Desired Salary Range" data-required_mark="required">
<button type="submit">Submit</button></form>"""
STYLED = """<title>Apply</title><h1>Accounting Coordinator</h1><form method="POST" action="/js/send">
<label for="n">Full name *</label><input id="n" name="name" required>
<fieldset><legend>Are you currently a student? *</legend>
<label style="position:relative"><input type="radio" name="student" id="student-true" value="true" required
  style="position:absolute;opacity:0;width:0;height:0"><span>Yes</span></label>
<label style="position:relative"><input type="radio" name="student" id="student-false" value="false"
  style="position:absolute;opacity:0;width:0;height:0"><span>No</span></label></fieldset>
<div>School email</div><input type="email" name="university_email" id="university_email" required>
<label for="uer">If you do not have a school email, please provide a reason</label>
<input id="university_email_reason" name="university_email_reason" style="display:none">
<button type="submit" class="v4-button submit g-recaptcha" data-sitekey="x" style="width:200px;height:40px">Submit</button>
</form>"""
PASSWORD_PAGE = """<h1>Sign in</h1><form><label for="u">Email</label><input id="u" value="pat@example.com">
<label for="pw">Password</label><input id="pw" type="password" value="hunter2-secret">
<button type="submit">Sign in</button></form>"""
CLOSED = """<title>Supervisor</title><h1>Customer Service Supervisor</h1><p>Posted: April 2, 2026</p>
<p>Closed: April 7, 2026</p><a href="/elsewhere">Accessibility Accommodation for Applicants</a>"""


@needs_browser
class TheSecondHalfOfTheMatrixOnFixtures(WhatTheMatrixFoundOnRealPagesStaysFixed):
    def setUp(self):
        super().setUp()
        self.site["pages"].update({"/city": CITY, "/js": STYLED, "/closed": CLOSED, "/pw": PASSWORD_PAGE})

    def test_a_scripted_required_mark_is_a_question_not_everything_filled(self):
        base = self.serve()
        record = browser_loop.pursue("fill out the city employment application", base + "/city",
                                     inputs={"last name": "Doe", "first name": "Pat", "zip code": "57104"})
        self.assertBoundary(record, bm.NEEDS_YOU, "QUESTIONS")
        self.assertIn("City, State, Zip Code", record["boundary"]["questions"])
        self.assertIn("Desired Salary Range", record["boundary"]["questions"])
        self.assertNotIn("57104", [r.get("value") for r in record["route"]])

    def test_styled_radios_a_worded_twin_a_button_bound_recaptcha_and_no_password_in_sight(self):
        base = self.serve()
        record = browser_loop.pursue("apply for the accounting coordinator job", base + "/js",
                                     inputs={"full name": "Pat Doe", "are you currently a student": "No"})
        self.assertBoundary(record, bm.NEEDS_YOU, "QUESTIONS")
        self.assertNotEqual(record["boundary"]["kind"], ps.CAPTCHA,
                            "a submit button carrying g-recaptcha is the invisible check, not a wall")
        self.assertIn("university email", record["boundary"]["questions"],
                      "a visible box named only in code is asked, in words")
        self.assertIn({"action": "click", "selector": "#student-false", "value": "No"},
                      [{k: r.get(k) for k in ("action", "selector", "value")} for r in record["route"]])
        from aletheia import browse as _b
        with _b._Session() as ctx:
            page = ctx.new_page()
            browser_loop._load(page, base + "/pw")
            seen = browser_loop.for_model(browser_loop.look(page))
            page.close()
        self.assertNotIn("hunter2-secret", str(seen), "a password's value never reaches a model")
        done = browser_loop.resume(record["id"], answers={"university email": "pat@example.edu"})
        self.assertBoundary(done, bm.AWAITING_APPROVAL, "SUBMIT_APPROVAL")
        self.assertEqual(sum(1 for r in done["route"] if r.get("selector") == "#student-false"), 1,
                         "the replayed choice is not chosen again")

    def test_a_closed_posting_stops_before_any_wandering(self):
        base = self.serve()
        record = browser_loop.pursue("apply for the customer service supervisor job", base + "/closed",
                                     inputs={}, skill=job_skill.SKILL,
                                     decide=lambda *a: self.fail("no model is asked on a closed posting"))
        self.assertBoundary(record, bm.NEEDS_YOU, "POSTING_CLOSED")
        self.assertEqual(record["route"], [])



SCRIPTED = """<title>Practice</title><h1>Complete Web Form</h1><form onsubmit="return false">
<label for="fn">First name</label><input id="fn">
<a id="go" href="#" role="button" onclick="setTimeout(function(){location.href='/thanks'}, 700); return false;">Submit</a>
</form>"""
THANKS = "<h1>Thanks for submitting your form</h1><div class='alert alert-success'>The form was successfully submitted!</div>"


@needs_browser
class APressReadsTheConfirmationNotTheFormBeforeIt(TheSecondHalfOfTheMatrixOnFixtures):
    def setUp(self):
        super().setUp()
        self.site["pages"].update({"/practice": SCRIPTED, "/thanks": THANKS})

    def test_a_script_that_navigates_after_the_press_is_read_after_it_arrives(self):
        base = self.serve()
        record = browser_loop.pursue("rehearse the practice form", base + "/practice", inputs={"first name": "Pat"})
        self.assertBoundary(record, bm.AWAITING_APPROVAL, "SUBMIT_APPROVAL")
        done = self.approve_and_press(record)
        self.assertEqual(done["state"], bm.DONE, done.get("boundary"))
        self.assertIn("successfully submitted", done["submits"][-1]["evidence"],
                      "the evidence is the confirmation page, not the form a moment before it")

    def test_a_live_success_reading_with_stale_evidence_is_not_a_confirmation(self):
        record = bm.open_mission("rehearse the practice form", "https://practice.example.org/form")
        record = bm.checkpoint(record, bm.REVIEW_REACHED, url="https://practice.example.org/form")
        record["gate"] = {"button": "Submit", "kind": ps.COMMIT, "url": "https://practice.example.org/form"}
        bm.begin_submit(record, button="Submit", url="https://practice.example.org/form")
        out = browser_loop.after_press({"mission": record["id"], "button": "Submit"},
                                       {"verdict": "submitted, unconfirmed", "page_state": ps.SUCCESS,
                                        "evidence": "Complete Web Form First name Submit",
                                        "url": "https://practice.example.org/thanks"})
        self.assertNotEqual(out.get("verdict"), "confirmed")
        self.assertNotEqual(bm.load(record["id"])["state"], bm.DONE)



class TheRoutineDecisionIsSmallEnoughForHerFastModel(unittest.TestCase):
    def test_a_real_sized_page_prompt_goes_to_the_fast_role(self):
        from aletheia import local_model_pool
        page = {"title": "Philosophy | Books to Scrape - Sandbox", "state": ps.CONTENT,
                "targets": [{"id": f"t{i}", "role": "link", "label": f"A fairly long book title number {i} here"}
                            for i in range(1, 70)],
                "text": "Philosophy results. " * 60}
        text = browser_loop.compact_page("find the Marcus Aurelius book in the philosophy section", page,
                                         [{"did": "followed 'Philosophy' (chosen by the page's own words)"}])
        self.assertLessEqual(len(text), browser_loop.LOCAL_PROMPT_CHARS)
        self.assertEqual(local_model_pool.choose_role(text), "fast",
                         "a routine browser decision never asks the model that does not fit")
        self.assertIn("GOAL: find the Marcus Aurelius book", text)
        self.assertIn("t1 link", text, "the targets at the top of the page are kept")

    def test_a_link_back_to_a_visited_page_is_not_a_way_forward(self):
        obs = {"url": "https://books.example/catalogue/meditations/index.html", "state": ps.CONTENT,
               "targets": [{"id": "t1", "role": "link", "label": "Philosophy",
                            "href": "https://books.example/catalogue/category/philosophy/index.html"}],
               "_refs": {"t1": "#crumb"}}
        goal = "find the Marcus Aurelius book in the philosophy section"
        self.assertIsNotNone(browser_loop.way_forward(obs, goal, browser_loop.GENERAL, {}, tried=set()))
        self.assertIsNone(browser_loop.way_forward(
            obs, goal, browser_loop.GENERAL, {}, tried=set(),
            visited={"https://books.example/catalogue/category/philosophy/index.html"}))


if __name__ == "__main__":
    unittest.main()
