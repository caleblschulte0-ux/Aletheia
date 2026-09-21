"""A Workday-shaped account wall, driven by the GENERAL loop, not a driver.

His ruling: she may create accounts with his real identity, no CAPTCHA
solving and no spending, still behind the existing approval path. So there
is no Workday module: the same `browser_loop.pursue` meets an ACCOUNT_SIGNUP
page, fills it (password generated into the vault, never into a record),
stops at ONE hash-bound approval to create the account, follows the emailed
verification link when it arrives as an event, signs in with the account it
made, fills the application, and stops at a SECOND approval to submit.
The skill that knows it is a job is `job_skill`; the site knowledge that
would make a real tenant faster is `config/site_skills.json` data.
"""
from __future__ import annotations

import http.server
import json
import threading
import unittest
import urllib.parse
from unittest import mock

from aletheia import browser_loop, browser_mission as bm, job_skill, policy, secret_store, signup
from tests.test_browser_loop_torture import LoopCase, needs_browser

JOB = """<title>Data Analyst</title><h1>Data Analyst</h1><h2>Responsibilities</h2>
<p>Turn data into decisions.</p><a href="/wd/choose">Apply</a>"""
CHOOSE = """<h1>Start your application</h1>
<a href="/wd/autofill">Autofill with Resume</a> <a href="/wd/create">Apply Manually</a>"""
CREATE = """<h2>Create Account</h2><form method="POST" action="/wd/create">
<label for="e">Email Address *</label><input id="e" name="email" required>
<label for="p">Password *</label><input id="p" name="password" type="password" required>
<label for="v">Verify New Password *</label><input id="v" name="verify" type="password" required>
<button type="submit">Create Account</button></form>"""
VERIFY = """<h1>Check your email</h1><p>We sent a verification link to your email.
Verify your email to continue.</p>"""
SIGNIN = """<h2>Sign In</h2>%s<form method="POST" action="/wd/session">
<label for="e">Email Address</label><input id="e" name="email">
<label for="p">Password</label><input id="p" name="password" type="password">
<button type="submit">Sign In</button></form>"""
APPLY = """<h1>My Information</h1><form method="POST" action="/wd/submit">
<label for="fn">First Name *</label><input id="fn" name="first_name" required>
<label for="ln">Last Name *</label><input id="ln" name="last_name" required>
<label for="ph">Phone Number *</label><input id="ph" name="phone" required>
<button type="submit">Submit</button></form>"""


def _tenant(state: dict):
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
            headers = [("Location", where)] + ([("Set-Cookie", cookie)] if cookie else [])
            self._send("", 303, headers)

        def do_GET(self):
            path, _, query = self.path.partition("?")
            if path == "/wd/verify":
                if urllib.parse.parse_qs(query).get("token") == ["abc"]:
                    state["verified"] = True
                return self._go("/wd/signin")
            if path == "/wd/apply":
                if "sid=1" not in (self.headers.get("Cookie") or ""):
                    return self._go("/wd/signin")
                return self._send(APPLY)
            pages = {"/wd/job": JOB, "/wd/choose": CHOOSE, "/wd/create": CREATE,
                     "/wd/verify-email": VERIFY, "/wd/signin": SIGNIN % ""}
            self._send(pages.get(path, "<h1>404</h1>"), 200 if path in pages else 404)

        def do_POST(self):
            size = int(self.headers.get("Content-Length", "0"))
            form = {k: v[0] for k, v in urllib.parse.parse_qs(self.rfile.read(size).decode()).items()}
            state["posts"].append(self.path)
            if self.path == "/wd/create":
                if form.get("password") and form.get("password") == form.get("verify"):
                    state["accounts"].append({"email": form.get("email"), "password": form["password"]})
                return self._go("/wd/verify-email")
            if self.path == "/wd/session":
                ok = state.get("verified") and any(
                    a["email"] == form.get("email") and a["password"] == form.get("password")
                    for a in state["accounts"])
                if ok:
                    return self._go("/wd/apply", cookie="sid=1; Path=/")
                return self._send(SIGNIN % "<p>Invalid email or password.</p>")
            if self.path == "/wd/submit":
                state["application"] = form
                return self._send("<h1>Thank you for applying</h1><p>Your application was received.</p>")
            self._send("<h1>404</h1>", 404)
    return H


class FakeVault:
    def __init__(self):
        self.rows: dict[str, str] = {}

    def available(self):
        return True, "test vault"

    def put(self, name, secret, **kw):
        self.rows[name] = secret

    def get(self, name):
        return self.rows[name]

    def exists(self, name):
        return name in self.rows


@needs_browser
class AnAccountWallIsWalkedByTheGeneralLoop(LoopCase):
    def setUp(self):
        super().setUp()
        self.tenant = {"posts": [], "accounts": []}
        probe = http.server.HTTPServer(("127.0.0.1", 0), lambda *a: None)
        port = probe.server_address[1]
        probe.server_close()
        self.wd = f"http://127.0.0.1:{port}"
        server = http.server.ThreadingHTTPServer(("127.0.0.1", port), _tenant(self.tenant))
        server.daemon_threads = True
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        self.vault = FakeVault()
        for name in ("available", "put", "get", "exists"):
            patch = mock.patch.object(secret_store, name, getattr(self.vault, name))
            patch.start()
            self.addCleanup(patch.stop)

    def test_create_verify_sign_in_apply_with_two_approvals(self):
        goal, start = "apply for the data analyst job", self.wd + "/wd/job"
        first = browser_loop.pursue(goal, start, skill=job_skill.SKILL)
        self.assertBoundary(first, bm.AWAITING_APPROVAL, "ACCOUNT_CREATION_APPROVAL")
        self.assertEqual(self.tenant["posts"], [], "no account without his yes")
        password = self.vault.rows[signup.account_alias("127.0.0.1")]

        made = self.approve_and_press(first)
        self.assertEqual(len(self.tenant["accounts"]), 1)
        self.assertEqual(self.tenant["accounts"][0]["email"], "caleb@example.com")
        self.assertEqual(made["state"], bm.RUNNING, made.get("boundary"))
        self.assertEqual(signup.known_account("127.0.0.1")["username"], "caleb@example.com")

        waiting = browser_loop.pursue(goal, start, skill=job_skill.SKILL)
        self.assertBoundary(waiting, bm.NEEDS_YOU, "WAITING_FOR_LINK")
        bm.post_event(waiting["id"], "link", self.wd + "/wd/verify?token=abc")
        ready = browser_loop.resume(waiting["id"], skill=job_skill.SKILL)
        self.assertBoundary(ready, bm.AWAITING_APPROVAL, "SUBMIT_APPROVAL")
        self.assertNotIn("/wd/submit", self.tenant["posts"])

        sent = self.approve_and_press(ready)
        self.assertEqual(sent["state"], bm.DONE, sent.get("boundary"))
        self.assertEqual(self.tenant["posts"].count("/wd/create"), 1, "the account was made once")
        self.assertEqual(self.tenant["posts"].count("/wd/submit"), 1)
        self.assertEqual(self.tenant["application"]["first_name"], "Caleb")
        self.assertEqual(self.tenant["application"]["phone"], "(512) 555-0134")

        # The password lives in the vault and nowhere she writes records.
        from aletheia import stateio
        for path in stateio.private_root().rglob("*.json"):
            self.assertNotIn(password, path.read_text(encoding="utf-8"), path)
        for path in policy.APPROVALS_DIR.iterdir():
            self.assertNotIn(password, path.read_text(encoding="utf-8"))
        self.assertNotIn(password, json.dumps(sent))


if __name__ == "__main__":
    unittest.main()
