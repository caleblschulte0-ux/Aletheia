"""The general browser loop in real use: routing, mail codes, the live press,
the site's own refusal, and the application engine switch.

Wave 4b of docs/JARVIS_BRIEF.md. `browser_loop.pursue` had only ever run on
fixtures, with nothing live calling it; these hold what changed when it
started carrying real asks:

- `web_task` goes through the general loop when there is a page to start
  from, and every gate is the same (spending refused before a browser opens,
  one hash-bound approval, the ledger at every stop);
- a mission waiting on an emailed code reads it from his inbox - read only,
  that site's mail only, newer than the mission, a link only onto the same
  site - and says plainly when mail is not set up;
- his yes, arriving while the browser is still open, is pressed IN that
  session when the page still reads the same, and never pressed twice;
- after the site refuses, its own error words are in the stop and nothing
  is driven back to the button unchanged;
- the campaign's loop engine is off unless he turns it on, and says which
  engine filled each application.

Browser tests use loopback fixtures and a throwaway profile; they skip
where playwright is absent.
"""
from __future__ import annotations

import email.utils
import http.server
import os
import tempfile
import threading
import time
import unittest
import urllib.parse
from pathlib import Path
from unittest import mock

from tests.test_campaign import FORM_FIELDS
from aletheia import (apply_run, browse, browser_loop, browser_mission as bm, browser_route, campaign,
                      intercom, journal, policy, profile, runtime, verification_mail, webtask)

BROWSER_OK, BROWSER_WHY = browse.available()
needs_browser = unittest.skipUnless(BROWSER_OK, f"browser control absent: {BROWSER_WHY}")


RESUME = """Caleb Schulte
Austin, TX
caleb@example.com | (512) 555-0134
EXPERIENCE - operations lead, built partner programs and reporting pipelines for a regional team."""


def _date(offset_s: float) -> str:
    return email.utils.formatdate(time.time() + offset_s, usegmt=True)


class FakeMailbox:
    """A read-only mailbox stand-in with the transport's one read method."""

    def __init__(self, messages):
        self.messages = list(messages)
        self.calls = 0

    def fetch_recent(self, since_epoch, limit=25):
        self.calls += 1
        return list(self.messages)

    def send(self, *a, **k):            # pragma: no cover - must never be called
        raise AssertionError("a verification reader must never send")


class Isolated(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        d = self.d = Path(self.tmp.name)
        for sub in ("approvals", "webtasks", "ws", "applications"):
            (d / sub).mkdir()
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
                (apply_run, "staged_dir", lambda: d / "applications"),
                (browse, "PROFILE_DIR", d / "browser")):
            patch = mock.patch.object(target, attr, value)
            patch.start()
            self.addCleanup(patch.stop)


# ---- 1. routing ------------------------------------------------------------------------

class WebTaskIsRoutedThroughTheGeneralLoop(Isolated):
    def test_the_engine_choice(self):
        self.assertEqual(browser_route.engine_for("renew my library card", "https://lib.example.org/renew")[0],
                         browser_route.LOOP)
        self.assertEqual(browser_route.engine_for("renew my library card", "")[0], browser_route.WEBTASK,
                         "with no start page only the older loop can search for one")
        self.assertEqual(browser_route.engine_for("download last month's statement",
                                                  "https://bank.example.com")[0], browser_route.WEBTASK)
        self.assertIsNone(browser_route.skill_for("request a dental cleaning"))
        self.assertEqual(browser_route.skill_for("apply for the systems engineer job").name, "job_application")

    def test_intercom_web_task_with_a_url_goes_to_pursue_with_the_mail_reader_and_a_hold(self):
        seen = {}

        def fake_pursue(goal, url, **kw):
            seen.update(goal=goal, url=url, **kw)
            record = bm.open_mission(goal, url)
            return bm.stop_at(record, bm.NEEDS_YOU, {"kind": "QUESTIONS", "say": "I need your answers for: X."})

        with mock.patch.object(browser_loop, "pursue", fake_pursue), \
                mock.patch.object(webtask, "run", side_effect=AssertionError("the older loop must not run")):
            said = intercom.execute_command({"kind": "web_task", "goal": "request a cleaning",
                                             "url": "https://clinic.example.com/request"},
                                            {"repos": {}})
        self.assertIn("I need your answers", said)
        self.assertEqual(seen["url"], "https://clinic.example.com/request")
        self.assertIsInstance(seen["code_source"], verification_mail.MailCodes)
        self.assertGreater(seen["hold_s"], 0)
        self.assertIsNotNone(seen["decide"], "a model may pick the way forward (never what is typed)")

    def test_no_url_keeps_the_older_loop(self):
        with mock.patch.object(webtask, "run", return_value={"state": "NEEDS_YOU", "say": "older loop"}) as run, \
                mock.patch.object(browser_loop, "pursue", side_effect=AssertionError("no start page")):
            said = intercom.execute_command({"kind": "web_task", "goal": "find the DMV renewal form"},
                                            {"repos": {}})
        self.assertEqual(said, "older loop")
        run.assert_called_once()

    def test_spending_is_refused_before_any_browser_opens_on_the_new_route(self):
        with mock.patch.object(browse, "_Session", side_effect=AssertionError("no browser")):
            said = intercom.execute_command({"kind": "web_task", "goal": "buy the monitor with my saved card",
                                             "url": "https://shop.example.com/cart"}, {"repos": {}})
        self.assertIn("spend money", said)

    def test_his_facts_never_carry_what_is_his_to_answer_on_every_form(self):
        with mock.patch.object(profile, "known", return_value={"email": "c@example.com", "gender": "male",
                                                                "first_name": "Caleb"}):
            facts = browser_route.his_facts()
        self.assertEqual(facts.get("email"), "c@example.com")
        self.assertNotIn("gender", facts)

    def test_a_stop_feeds_the_demand_ledger(self):
        from aletheia import demand
        record = bm.open_mission("renew my card", "https://lib.example.org")
        with mock.patch.object(demand, "record_attempt") as ledger:
            browser_loop._stop(record, bm.NEEDS_YOU, "SIGN_IN", {"url": "https://lib.example.org/login"})
        ledger.assert_called_once()
        self.assertEqual(ledger.call_args[0][2], "NEEDS_SIGN_IN")

    def test_his_answer_carries_the_newest_waiting_mission_on(self):
        mission = bm.stop_at(bm.open_mission("request a cleaning", "https://clinic.example.com"),
                             bm.NEEDS_YOU, {"kind": "QUESTIONS", "questions": ["Reason for visit"]})
        with mock.patch.object(browser_loop, "resume", return_value={**mission, "state": bm.AWAITING_APPROVAL,
                                                                     "boundary": {"say": "confirm it"}}) as res:
            said = intercom.execute_command({"kind": "web_task_answer",
                                             "answers": {"reason for visit": "cleaning"}}, {"repos": {}})
        self.assertEqual(said, "confirm it")
        self.assertEqual(res.call_args.kwargs["answers"], {"reason for visit": "cleaning"})


# ---- 2. mail codes -----------------------------------------------------------------------

class VerificationCodesComeFromHisInbox(Isolated):
    def mission(self, url="https://volunteer.example.org/signup"):
        return bm.open_mission("sign me up to volunteer", url)

    def test_the_code_from_that_site_after_the_mission_started(self):
        record = self.mission()
        box = FakeMailbox([
            {"from": "Volunteer <no-reply@volunteer.example.org>", "date": _date(-3600),
             "message_id": "<old>", "subject": "Your code", "text": "Your verification code is 111111"},
            {"from": "Someone <x@elsewhere.example.com>", "date": _date(5),
             "message_id": "<other>", "subject": "Code", "text": "Your verification code is 999999"},
            {"from": "Volunteer <no-reply@mail.example.org>", "date": _date(5),
             "message_id": "<new>", "subject": "Verify", "text": "Your verification code is 731904."},
        ])
        source = verification_mail.MailCodes(box, tries=1, wait_s=0)
        self.assertEqual(source(record, "email"), "731904")
        self.assertIn("<new>", record["mail_used"])

    def test_an_older_code_or_another_sites_mail_is_never_taken(self):
        record = self.mission()
        box = FakeMailbox([
            {"from": "no-reply@volunteer.example.org", "date": _date(-3600), "message_id": "<old>",
             "text": "Your verification code is 111111"},
            {"from": "no-reply@phish.example.net", "date": _date(5), "message_id": "<x>",
             "text": "Your verification code is 222222"}])
        slept = []
        source = verification_mail.MailCodes(box, tries=2, wait_s=7, sleep=slept.append)
        self.assertEqual(source(record, "email"), "")
        self.assertEqual(slept, [7], "it polls, then says what it watched for")
        self.assertIn("has not arrived", source.why(record))

    def test_a_reviewed_sender_domain_for_the_family(self):
        record = bm.open_mission("apply for this job", "https://job-boards.greenhouse.io/acme/jobs/1")
        box = FakeMailbox([{"from": "Greenhouse <no-reply@us.greenhouse-mail.io>", "date": _date(5),
                            "message_id": "<gh>", "subject": "Security code for your application to Acme",
                            "text": "Copy and paste this code into the security code field on your "
                                    "application: ApHIj2MW"}])
        self.assertEqual(verification_mail.MailCodes(box, tries=1, wait_s=0)(record, "email"), "ApHIj2MW")

    def test_a_link_only_onto_the_same_site(self):
        record = self.mission()
        box = FakeMailbox([{"from": "no-reply@volunteer.example.org", "date": _date(5), "message_id": "<l>",
                            "text": "", "links": ["https://tracker.example.net/verify?t=1",
                                                  "https://volunteer.example.org/verify?token=abc"]}])
        self.assertEqual(verification_mail.MailCodes(box, tries=1, wait_s=0)(record, "link"),
                         "https://volunteer.example.org/verify?token=abc")
        only_elsewhere = FakeMailbox([{"from": "no-reply@volunteer.example.org", "date": _date(5),
                                       "message_id": "<m>", "links": ["https://evil.example.net/verify?t=1"]}])
        self.assertEqual(verification_mail.MailCodes(only_elsewhere, tries=1, wait_s=0)(
            self.mission("https://volunteer.example.org/other"), "link"), "")

    def test_mail_not_set_up_is_said_plainly(self):
        record = self.mission()
        source = verification_mail.MailCodes(tries=1, wait_s=0,
                                             configured=lambda: (False, "mail isn't set up yet"))
        self.assertEqual(source(record, "email"), "")
        self.assertIn("can't read your mail", source.why(record))
        self.assertIn("mail isn't set up", browser_loop._source_why(source, record))

    def test_sender_rules(self):
        self.assertTrue(verification_mail.sender_allowed("a@jobs.acme.com", "https://careers.acme.com/x"))
        self.assertFalse(verification_mail.sender_allowed("a@acme.com.evil.io", "https://careers.acme.com/x"))
        self.assertFalse(verification_mail.sender_allowed("a@other.co.uk", "https://acme.co.uk/x"))
        self.assertEqual(verification_mail.code_in("Use code: 4821 to continue"), "4821")
        self.assertEqual(verification_mail.code_in("please verify your email"), "")


# ---- fixtures for the browser tests ----------------------------------------------------------

VERIFY1 = """<h1>Volunteer sign-up</h1><form method="POST" action="/volunteer/code">
<label for="e">Email *</label><input id="e" name="email" required>
<button type="submit">Next</button></form>"""
VERIFY2 = """<h1>Check your inbox</h1><p>We emailed you a verification code. Enter the code below.</p>
<form method="POST" action="/volunteer/final"><label for="c">Code</label><input id="c" name="code">
<button type="submit">Verify</button></form>"""
VERIFY3 = """<h1>Almost done</h1><form method="POST" action="/volunteer/done">
<label for="s">Preferred shift *</label><input id="s" name="shift" required>
<button type="submit">Submit</button></form>"""
CONTACT = """<h1>Contact the clinic</h1><form method="POST" action="/contact/send">
<label for="n">Full name *</label><input id="n" name="name" required>
<label for="m">Message *</label><textarea id="m" name="message" required></textarea>
<button type="submit">Send message</button></form>"""
PICKY = """<h1>Feedback</h1>%s<form method="POST" action="/picky/send">
<label for="z">Zip code *</label><input id="z" name="zip" value="%s" required>
<button type="submit">Send feedback</button></form>"""
THANKS = "<h1>Thank you</h1><p>Your message has been received.</p>"
# A site header with a Create account LINK and a Donate link, a search box, and
# an appearance toggle - the shape a real Wikipedia page had on 2026-09-16.
ENCYCLOPEDIA = """<header><a href="/donate">Donate</a> <a href="/signup">Create account</a>
<label><input type="checkbox" id="menu"> Main menu</label>
<form action="/search" method="GET"><input id="q" name="q" aria-label="Search the encyclopedia">
<button type="submit" style="display:none">Search</button></form></header>
<h1>Main page</h1><p>Welcome.</p>"""


def _site(state: dict):
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
            pages = {"/volunteer": VERIFY1, "/contact": CONTACT, "/picky": PICKY % ("", ""),
                     "/wiki": ENCYCLOPEDIA,
                     "/search": "<h1>Search results</h1><p>Ada Lovelace was a mathematician.</p>"}
            self._send(pages.get(path, "<h1>404</h1>"), 200 if path in pages else 404)

        def do_POST(self):
            size = int(self.headers.get("Content-Length", "0"))
            form = urllib.parse.parse_qs(self.rfile.read(size).decode())
            state["got"].update({k: v[0] for k, v in form.items()})
            state["posts"].append(self.path)
            if self.path == "/volunteer/code":
                state["code"] = "58" + str(len(state["posts"])).zfill(4)     # a fresh code per visit
                return self._send(VERIFY2)
            if self.path == "/volunteer/final":
                return self._send(VERIFY3 if state["got"].get("code") == state.get("code") else VERIFY2)
            if self.path == "/picky/send":
                if state["got"].get("zip", "").isdigit() and len(state["got"]["zip"]) == 5 \
                        and not state.get("always_refuse"):
                    return self._send(THANKS)
                return self._send(PICKY % ('<div role="alert">There was a problem: zip code must be 5 '
                                           'digits.</div>', state["got"].get("zip", "")))
            self._send(THANKS)
    return H


class BrowserCase(Isolated):
    def setUp(self):
        super().setUp()
        self.state = {"got": {}, "posts": []}
        probe = http.server.HTTPServer(("127.0.0.1", 0), lambda *a: None)
        port = probe.server_address[1]
        probe.server_close()
        self.base = f"http://127.0.0.1:{port}"
        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", port), _site(self.state))
        self.server.daemon_threads = True
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def url(self, path):
        return self.base + path

    def approve_on_first_poll(self):
        """Stand-in for his yes arriving while the session holds: the first
        poll finds the pending approval and he approves it."""
        def fake_sleep(_seconds):
            for record in bm.all_missions(bm.AWAITING_APPROVAL):
                if policy.load(record["approval"]).get("state") == "PENDING":
                    policy.decide(record["approval"], "APPROVED", via="phone")
        return mock.patch.object(browser_loop, "_sleep", fake_sleep)


@needs_browser
class AnEmailedCodeIsReadWithoutHim(BrowserCase):
    def test_the_mission_reads_its_code_and_reaches_the_approval(self):
        start = time.time()

        class Box:
            def __init__(inner):
                inner.sent = []

            def fetch_recent(inner, since, limit=25):
                if not self.state.get("code"):
                    return []
                return [{"from": "no-reply@127.0.0.1", "date": email.utils.formatdate(start + 2, usegmt=True),
                         "message_id": "<c1>", "subject": "Your code",
                         "text": f"Your verification code is {self.state['code']}"}]

        source = verification_mail.MailCodes(Box(), tries=1, wait_s=0)
        record = browser_loop.pursue("sign me up to volunteer", self.url("/volunteer"),
                                     inputs={"email": "caleb@example.com", "preferred shift": "Saturday"},
                                     code_source=source)
        self.assertEqual(record["state"], bm.AWAITING_APPROVAL, record.get("boundary"))
        self.assertEqual(self.state["got"].get("code"), self.state["code"])
        self.assertTrue(any("from his inbox" in h["did"] for h in record["history"]))
        self.assertNotIn("/volunteer/done", self.state["posts"], "nothing sent before his yes")

    def test_mail_not_set_up_stops_and_says_so(self):
        source = verification_mail.MailCodes(tries=1, wait_s=0, configured=lambda: (False, "mail isn't set up yet"))
        record = browser_loop.pursue("sign me up to volunteer", self.url("/volunteer"),
                                     inputs={"email": "caleb@example.com"}, code_source=source)
        self.assertEqual(record["boundary"]["kind"], "WAITING_FOR_CODE")
        self.assertIn("can't read your mail", record["boundary"]["say"])


@needs_browser
class HisYesIsPressedInTheLiveSession(BrowserCase):
    def test_an_expiring_code_survives_because_nothing_is_replayed(self):
        """The volunteer site issues a NEW code on every visit, so the replay
        press would fail. Pressed in the held session, it goes through once."""
        code = {}

        def source(record, via):
            return self.state.get("code", "")

        with self.approve_on_first_poll():
            record = browser_loop.pursue("sign me up to volunteer", self.url("/volunteer"),
                                         inputs={"email": "caleb@example.com", "preferred shift": "Saturday"},
                                         code_source=source, hold_s=30)
        self.assertEqual(record["state"], bm.DONE, record.get("boundary"))
        self.assertEqual(self.state["posts"].count("/volunteer/done"), 1)
        self.assertEqual(self.state["posts"].count("/volunteer/code"), 1, "the route was not replayed")
        self.assertTrue(any("live session" in h["did"] for h in record["history"]))
        # never a second press: not by the command, not by the beat
        with self.assertRaises(Exception):
            browser_loop.commit(record["id"])
        self.assertEqual(runtime.press_approved_web_tasks(), [])
        self.assertEqual(self.state["posts"].count("/volunteer/done"), 1)
        del code

    def test_a_page_that_changed_falls_back_to_the_replay_and_still_presses_once(self):
        real = browser_loop.page_digest
        calls = {"n": 0}

        def drifting(obs, button):
            calls["n"] += 1
            return real(obs, button) + ("-changed" if calls["n"] > 1 else "")

        with self.approve_on_first_poll(), mock.patch.object(browser_loop, "page_digest", drifting):
            record = browser_loop.pursue("send the clinic a message", self.url("/contact"),
                                         inputs={"full name": "Caleb Schulte", "message": "Hello"}, hold_s=30)
        self.assertEqual(record["state"], bm.AWAITING_APPROVAL, "not pressed live")
        self.assertNotIn("/contact/send", self.state["posts"])
        run = webtask.load_run(record["webtask_run"])
        self.assertNotIn("held_live_until", run, "the hold is released for the beat")
        pressed = runtime.press_approved_web_tasks()
        self.assertEqual(len(pressed), 1)
        self.assertEqual(self.state["posts"].count("/contact/send"), 1)
        self.assertEqual(runtime.press_approved_web_tasks(), [])
        self.assertEqual(self.state["posts"].count("/contact/send"), 1)

    def test_the_beat_leaves_a_held_approval_alone(self):
        record = {"id": "x", "held_live_until": "2999-01-01T00:00:00+00:00"}
        self.assertTrue(runtime._held_live(record))
        self.assertFalse(runtime._held_live({"held_live_until": "2000-01-01T00:00:00+00:00"}))


@needs_browser
class TheSitesOwnRefusalIsRead(BrowserCase):
    def test_the_error_words_are_in_the_stop_and_nothing_is_resubmitted_blindly(self):
        goal, start = "send feedback", self.url("/picky")
        record = browser_loop.pursue(goal, start, inputs={"zip code": "5710"})
        policy.decide(record["approval"], "APPROVED", via="phone")
        refused = browser_loop.commit(record["id"])
        self.assertEqual(refused["state"], bm.REJECTED, refused.get("boundary"))
        self.assertTrue(any("5 digits" in line for line in refused["boundary"]["site_said"]),
                        refused["boundary"])
        self.assertIn("5 digits", refused["boundary"]["say"])

        approvals = sorted(p.name for p in policy.APPROVALS_DIR.iterdir())
        again = browser_loop.pursue(goal, start)
        self.assertEqual(again["state"], bm.REJECTED)
        self.assertEqual(again["boundary"]["kind"], "REJECTED")
        self.assertIn("5 digits", again["boundary"]["say"])
        self.assertEqual(sorted(p.name for p in policy.APPROVALS_DIR.iterdir()), approvals,
                         "no new approval for the same answers the site refused")
        self.assertEqual(self.state["posts"].count("/picky/send"), 1)

        fixed = browser_loop.resume(again["id"], answers={"zip code": "57104"})
        self.assertEqual(fixed["state"], bm.AWAITING_APPROVAL, fixed.get("boundary"))
        self.assertNotEqual(fixed["approval"], record["approval"])
        policy.decide(fixed["approval"], "APPROVED", via="phone")
        self.assertEqual(browser_loop.commit(fixed["id"])["state"], bm.DONE)
        self.assertEqual(self.state["got"]["zip"], "57104")

    def test_a_retry_he_asks_for_carries_what_the_site_said_into_the_approval(self):
        self.state["always_refuse"] = True
        goal, start = "send feedback", self.url("/picky")
        record = browser_loop.pursue(goal, start, inputs={"zip code": "57104"})
        policy.decide(record["approval"], "APPROVED", via="phone")
        browser_loop.commit(record["id"])
        again = browser_loop.resume(record["id"], retry=True)
        self.assertEqual(again["state"], bm.AWAITING_APPROVAL, again.get("boundary"))
        self.assertIn("5 digits", policy.load(again["approval"]).get("reason", ""))


@needs_browser
class ASiteSearchIsReadingNotAnAccount(BrowserCase):
    def test_a_search_goal_runs_the_search_and_is_done_without_any_approval(self):
        record = browser_loop.pursue("search the encyclopedia for Ada Lovelace", self.url("/wiki"),
                                     inputs={"search the encyclopedia": "Ada Lovelace"})
        self.assertEqual(record["state"], bm.DONE, record.get("boundary"))
        self.assertIn("/search", record["result"]["url"])
        self.assertFalse(record.get("approval"), "a header's Create account link is not this goal's button")
        self.assertEqual(sorted(p.name for p in policy.APPROVALS_DIR.iterdir()), [])

    def test_the_final_button_of_a_goal(self):
        obs = {"state": "FORM", "targets": [
            {"id": "t1", "role": "textbox", "label": "Email"},
            {"id": "t2", "role": "link", "label": "Create account"},
            {"id": "t3", "role": "button", "label": "Send message"}]}
        self.assertEqual(browser_loop.final_control(obs, "send the clinic a message")["label"], "Send message")
        obs["targets"] = obs["targets"][:2]
        self.assertIsNone(browser_loop.final_control(obs, "send the clinic a message"))
        self.assertEqual(browser_loop.final_control(obs, "make me an account")["label"], "Create account")


# ---- 5. the campaign's engine switch --------------------------------------------------------

class TheLoopEngineIsHisSwitch(Isolated):
    def test_off_by_default_and_the_cli_flips_it(self):
        self.assertFalse(apply_run.loop_engine_on())
        self.assertFalse(apply_run.uses_loop("https://careers.acme.com/jobs/1"))
        with mock.patch("sys.stdout"):
            self.assertEqual(apply_run.main(["engine", "on"]), 0)
        self.assertTrue(apply_run.loop_engine_on())
        self.assertTrue(apply_run.uses_loop("https://careers.acme.com/jobs/1"))
        self.assertFalse(apply_run.uses_loop("https://job-boards.greenhouse.io/acme/jobs/1"),
                         "a site with a specialised adapter keeps it")
        self.assertFalse(apply_run.uses_loop("https://x.example.com/a", provider="lever"))
        with mock.patch("sys.stdout"):
            apply_run.main(["engine", "off"])
        self.assertFalse(apply_run.loop_engine_on())

    def fake_pursue(self, state=bm.AWAITING_APPROVAL, boundary=None):
        def pursue(goal, url, **kw):
            record = bm.open_mission(goal, url, inputs=kw.get("inputs"), skill="job_application")
            record["approval"] = "apr-1" if state == bm.AWAITING_APPROVAL else None
            return bm.stop_at(record, state, boundary or {"kind": "SUBMIT_APPROVAL", "say": "confirm it"})
        return pursue

    def test_a_loop_application_says_its_engine_and_is_never_sent_by_the_form_path(self):
        record = apply_run.stage_via_loop("https://careers.acme.com/jobs/1", note="Apply: Ops",
                                          pursue=self.fake_pursue(), code_source=lambda r, v: "")
        self.assertEqual(record["engine"], apply_run.ENGINE_LOOP)
        self.assertEqual(record["state"], "AWAITING_YOU")
        self.assertTrue(record["mission"].startswith("bm-apply-for-this-job"))
        with self.assertRaises(apply_run.ApplyError):
            apply_run.submit(record["id"])
        from aletheia import authority
        with mock.patch.object(authority, "satisfy", side_effect=AssertionError("never on the grant")), \
                mock.patch.object(runtime, "_submit_in_its_own_process",
                                  side_effect=AssertionError("never the form path")):
            self.assertEqual(runtime.send_approved_applications(), [])

    def test_questions_stop_as_needs_you(self):
        record = apply_run.stage_via_loop(
            "https://careers.acme.com/jobs/2", pursue=self.fake_pursue(
                bm.NEEDS_YOU, {"kind": "QUESTIONS", "questions": ["Years in sales *"], "say": "answers"}),
            code_source=lambda r, v: "")
        self.assertEqual(record["state"], "NEEDS_YOU")
        self.assertEqual(record["questions"][0]["label"], "Years in sales *")

    def test_the_form_engine_records_its_engine_too(self):
        fields = [{"selector": "#fn", "label": "First name", "name": "", "id": "fn", "tag": "input",
                   "type": "text", "required": True, "value": ""},
                  {"selector": "#q", "label": "Why this job?", "name": "", "id": "q", "tag": "textarea",
                   "type": "textarea", "required": True, "value": ""}]
        profile.learn_from_resume("Caleb Schulte\ncaleb@example.com")
        record = apply_run.stage("https://job-boards.greenhouse.io/acme/jobs/9", reader=lambda u: list(fields))
        self.assertEqual(record["engine"], apply_run.ENGINE_FORMFILL)

    def campaign_run(self):
        pages = [{"url": "https://careers.acme.com/jobs/7", "title": "Ops — Acme", "extract": "posting"}]
        return campaign.run("operations", count=1, finder=lambda q, limit=9: pages,
                            reader=lambda src: (list(src), []),
                            opener=lambda url: (list(FORM_FIELDS), []),
                            json_think=False, fit_think=False, draft_essays_too=False)

    def test_campaign_with_the_switch_off_never_touches_the_loop(self):
        (Path(os.environ["ALETHEIA_WORKSPACE"]) / "resume.md").write_text(RESUME, encoding="utf-8")
        staged = {"id": "apply-x", "state": "NEEDS_YOU", "url": "u", "questions": [], "say": "x"}
        with mock.patch.object(apply_run, "stage_via_loop", side_effect=AssertionError("switch is off")), \
                mock.patch.object(apply_run, "stage", return_value=staged) as stage:
            self.campaign_run()
        stage.assert_called()

    def test_campaign_with_the_switch_on_uses_the_loop_for_an_unadapted_site(self):
        (Path(os.environ["ALETHEIA_WORKSPACE"]) / "resume.md").write_text(RESUME, encoding="utf-8")
        apply_run.set_loop_engine(True, by="test")
        staged = {"id": "apply-y", "state": "AWAITING_YOU", "url": "https://careers.acme.com/jobs/7",
                  "engine": apply_run.ENGINE_LOOP, "questions": []}
        with mock.patch.object(apply_run, "stage_via_loop", return_value=staged) as loop, \
                mock.patch.object(apply_run, "stage", side_effect=AssertionError("unadapted site")):
            out = self.campaign_run()
        loop.assert_called_once()
        self.assertEqual(out["ready"][0]["engine"], apply_run.ENGINE_LOOP)


if __name__ == "__main__":
    unittest.main()
