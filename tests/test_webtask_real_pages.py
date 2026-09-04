"""What a real page does to her — against real Chromium, on loopback.

Everything else in `test_webtask` is a double, and a double agrees with
whatever I believed when I wrote it. Every failure in this file was found
by pointing her at a page instead of reasoning about one:

- a form inside an `<iframe>` (what Greenhouse and Lever actually ship)
- "Apply" as a link that opens a NEW TAB
- an application spread over three PAGES
- a form made of DIVS: a typeahead combobox and a custom radio group,
  where nothing has an id and nothing is a `<select>`

Hermetic: a fixture site on loopback, no network. Browser control is
optional, so these SKIP where playwright is absent rather than failing
the suite — the bootstrap gates starting the Core on this suite.
"""
import http.server
import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from aletheia import browse, journal, policy, profile, webtask

BROWSER_OK, BROWSER_WHY = browse.available()
needs_browser = unittest.skipUnless(BROWSER_OK, f"browser control absent: {BROWSER_WHY}")

EMBED = """<form method="POST" action="/submit">
<label for="fn">First name *</label><input id="fn" name="first_name" required>
<label for="em">Email *</label><input id="em" name="email" type="email" required>
<label for="why">Why do you want this job? *</label>
<textarea id="why" name="why" required></textarea>
<button type="submit">Submit application</button></form>"""

WIDGET = """<form method="POST" action="/submit">
<label for="fn">First name *</label><input id="fn" name="first_name" required>
<div><span>Location *</span>
  <input class="ta" name="location" role="combobox" aria-expanded="false"
         aria-label="Location" autocomplete="off">
  <ul role="listbox" hidden><li role="option">Austin, TX</li>
      <li role="option">Boston, MA</li></ul></div>
<div><span id="wa">Are you legally authorized to work in the US? *</span>
  <div role="radiogroup" aria-labelledby="wa">
    <div role="radio" aria-checked="false">Yes</div>
    <div role="radio" aria-checked="false">No</div></div></div>
<div><span id="vet">Are you a protected veteran?</span>
  <div role="radiogroup" aria-labelledby="vet">
    <div role="radio" aria-checked="false">I am not</div>
    <div role="radio" aria-checked="false">I am</div></div></div>
<input type="hidden" name="location_value"><input type="hidden" name="work_auth">
<button type="submit">Submit application</button></form>
<script>
const box=document.querySelector('.ta'),list=document.querySelector('[role=listbox]');
const hid=document.querySelector('[name=location_value]');
box.addEventListener('input',()=>{list.hidden=false;
  for(const li of list.children) li.hidden=!li.innerText.toLowerCase()
      .includes(box.value.toLowerCase());});
for(const li of list.children) li.addEventListener('click',()=>{
  box.value=li.innerText;hid.value=li.innerText;list.hidden=true;});
for(const r of document.querySelectorAll('[role=radio]')) r.addEventListener('click',()=>{
  const g=r.closest('[role=radiogroup]');
  for(const o of g.querySelectorAll('[role=radio]')) o.setAttribute('aria-checked','false');
  r.setAttribute('aria-checked','true');
  if(g.getAttribute('aria-labelledby')==='wa')
    document.querySelector('[name=work_auth]').value=r.innerText;});
document.querySelector('form').addEventListener('submit',(e)=>{
  if(!hid.value||!document.querySelector('[name=work_auth]').value) e.preventDefault();});
</script>"""

LATE = """<style>#cookies{position:fixed;inset:0;background:rgba(0,0,0,.6);
  z-index:9999;display:flex;align-items:center;justify-content:center}
#cookies .card{background:#fff;padding:24px}</style>
<div id="cookies"><div class="card"><h3>We value your privacy</h3>
<button id="accept">Accept all</button></div></div>
<h1>Careers</h1><div id="app">Loading application…</div>
<script>
document.getElementById('accept').addEventListener('click',
  () => document.getElementById('cookies').remove());
// The form does not exist yet. It is a React app, in spirit.
setTimeout(() => { document.getElementById('app').innerHTML = `
  <form method="POST" action="/strict">
    <label for="fn">First name *</label><input id="fn" name="first_name" required>
    <label for="ph">Phone *</label><input id="ph" name="phone" required>
    <button type="submit">Submit application</button></form>`; }, 1800);
</script>"""

REFUSAL = """<h1>Careers</h1><form method="POST" action="/strict">
<p>There was a problem with your application.</p>
<label for="fn">First name *</label><input id="fn" name="first_name" value="%s" required>
<label for="ph">Phone *</label><input id="ph" name="phone" value="%s" required>
<p>Phone number must be 10 digits with no punctuation.</p>
<button type="submit">Submit application</button></form>"""

ACCOUNT = """<h1>Your account</h1><p>Membership: Gold.</p>
<ul><li><a href="/statement/2026-07.pdf" download>July statement</a></li>
<li><a href="/statement/2026-08.pdf" download>August statement</a></li></ul>
<form method="POST" action="/cancel">
<button type="submit">Cancel my membership</button></form>"""

W1 = """<form method="POST" action="/w2">
<label for="fn">First name *</label><input id="fn" name="first_name" required>
<button type="submit">Next</button></form>"""
W2 = """<form method="POST" action="/w3">
<label for="ct">City</label><input id="ct" name="city">
<button type="submit">Continue</button></form>"""
W3 = """<form method="POST" action="/submit">
<label for="why">Anything else? *</label><textarea id="why" name="why" required></textarea>
<button type="submit">Submit application</button></form>"""

PORTAL = """<form method="POST" action="/session">
<label for="u">Email</label><input id="u" name="username">
<label for="p">Password</label><input id="p" name="password" type="password">
<button type="submit">Sign in</button></form>"""


def _site(base: str, got: dict):
    pages = {"/apply": f'<h1>Job</h1><iframe src="{base}/embed"></iframe>',
             "/embed": EMBED, "/widget": WIDGET, "/portal": PORTAL,
             "/": f'<h1>Careers</h1><a href="{base}/apply" target="_blank" '
                  'rel="noopener">Apply for this job</a>',
             "/w1": W1, "/w2": W2, "/w3": W3, "/late": LATE,
             "/account": ACCOUNT}

    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, body):
            raw = body.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self):
            if self.path.startswith("/statement/"):
                body = b"%PDF-1.4\n1 0 obj<</Type/Catalog>>endobj\n%%EOF\n"
                self.send_response(200)
                self.send_header("Content-Type", "application/pdf")
                self.send_header("Content-Disposition", 'attachment; filename="'
                                 + self.path.rsplit("/", 1)[-1] + '"')
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            self._send(pages.get(self.path, "<h1>404</h1>"))

        def do_POST(self):
            import urllib.parse
            size = int(self.headers.get("Content-Length", "0"))
            form = urllib.parse.parse_qs(self.rfile.read(size).decode())
            got.update({k: v[0] for k, v in form.items()})
            got["_last_post"] = self.path
            if self.path == "/cancel":
                return self._send("<h1>Your membership has been cancelled.</h1>")
            if self.path == "/strict":
                # A site that wants his number ITS way, and says so.
                digits = "".join(c for c in got.get("phone", "") if c.isdigit())
                if digits != got.get("phone", "") or len(digits) != 10:
                    return self._send(REFUSAL % (got.get("first_name", ""),
                                                 got.get("phone", "")))
            self._send({"/w2": W2, "/w3": W3}.get(
                self.path, "<h1>Thank you</h1><p>Received.</p>"))
    return H


def by_text(page: dict, want: str, kind="buttons"):
    pools = [kind] if kind != "buttons" else ["buttons", "links"]
    for pool in pools:
        for row in page.get(pool) or []:
            if want.casefold() in (row.get("text") or row.get("label") or "").casefold():
                if row.get("selector"):
                    return row
    return None


def script(*steps):
    """A stand-in for the model that picks by TEXT.

    It is handed exactly what the model is handed, so what it can reach is
    what she can SEE — not a selector I copied out of the fixture and
    quietly kept working.
    """
    todo = list(steps)

    def think(system, prompt, **kw):
        page = json.loads(prompt)["page"]
        if not todo:
            return '{"action": "done", "value": "finished"}'
        want = todo[0]
        if want[0] == "download":
            row = by_text(page, want[1])
            if row is None:
                return '{"action": "ask", "value": "no link %s"}' % want[1]
            todo.pop(0)
            return json.dumps({"action": "download", "selector": row["selector"]})
        if want[0] == "type":
            row = by_text(page, want[1], "fields")
            if row is None:
                return '{"action": "ask", "value": "no field %s"}' % want[1]
            todo.pop(0)
            return json.dumps({"action": "type", "selector": row["selector"],
                               "value": want[2]})
        row = by_text(page, want[1])
        if row is None:
            return '{"action": "ask", "value": "no control %s"}' % want[1]
        todo.pop(0)
        return json.dumps({"action": "click", "selector": row["selector"]})
    return think


class RealPageCase(unittest.TestCase):
    def setUp(self):
        self.got: dict = {}
        self.server = http.server.HTTPServer(("127.0.0.1", 0), lambda *a: None)
        self.server.server_close()
        port = self.server.server_address[1]
        self.base = f"http://127.0.0.1:{port}"
        self.server = http.server.HTTPServer(
            ("127.0.0.1", port), _site(self.base, self.got))
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.shutdown)

        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        d = Path(self.tmp.name)
        (d / "approvals").mkdir()
        (d / "webtasks").mkdir()
        env = mock.patch.dict(os.environ, {"ALETHEIA_PRIVATE_STATE": str(d),
                                           "ALETHEIA_WORKSPACE": str(d / "ws")})
        env.start(); self.addCleanup(env.stop)
        (d / "ws").mkdir()
        for target, attr, value in (
                (journal, "JOURNAL_PATH", d / "j.jsonl"),
                (policy, "APPROVALS_DIR", d / "approvals"),
                (policy, "HALT_PATH", d / "halt.json"),
                (profile, "path", lambda: d / "answers.json"),
                (webtask, "runs_dir", lambda: d / "webtasks"),
                (browse, "PROFILE_DIR", d / "browser")):
            patch = mock.patch.object(target, attr, value)
            patch.start(); self.addCleanup(patch.stop)
        profile.learn_from_resume(
            "Caleb Schulte\nAustin, TX\ncaleb@example.com | (512) 555-0134")

    def drive(self, path, goal, *steps, budget=10):
        return webtask.run(goal, start_url=self.base + path, budget=budget,
                           think=script(*steps))

    def press(self, record):
        policy.decide(record["approval"], "APPROVED", via="phone")
        return webtask.commit(record["id"])


@needs_browser
class AnEmbeddedFormIsReachedAndSubmitted(RealPageCase):
    """Greenhouse and Lever ship the application as an `<iframe>`, and
    "Apply" is a link that opens a new tab. Before this she stood on the
    careers page and said "I don't see any form fields"."""

    def test_careers_page_to_new_tab_to_iframe_to_a_received_application(self):
        out = self.drive(
            "/", "Apply for this job with my details. For why I want the job "
                 "say: I build unattended systems with quality gates.",
            ("click", "Apply for this job"),
            ("type", "Why do you want this job", "I build unattended systems "
                                                 "with quality gates."),
            ("click", "Submit application"))
        self.assertEqual(out["state"], webtask.COMMIT, out.get("say"))
        self.assertTrue(out["button_selector"].startswith("@frame"),
                        f"the button is inside the frame: {out['button_selector']}")
        self.assertIn({"action": "new_tab", "selector": ""}, out["typed"])
        self.press(out)
        self.assertEqual(self.got.get("_last_post"), "/submit")
        self.assertEqual(self.got.get("first_name"), "Caleb")
        self.assertEqual(self.got.get("email"), "caleb@example.com")
        self.assertEqual(self.got.get("why"),
                         "I build unattended systems with quality gates.")


@needs_browser
class AThreePageApplicationArrivesWHOLE(RealPageCase):
    """The press replays the ROUTE. Re-opening the last page instead left
    two thirds of an application on the server and no way to finish it."""

    def test_every_page_reaches_the_server(self):
        out = self.drive(
            "/w1", "Complete this application. For anything else say: I build "
                   "unattended systems with quality gates.",
            ("click", "Next"), ("click", "Continue"),
            ("type", "Anything else", "I build unattended systems with quality gates."),
            ("click", "Submit application"))
        self.assertEqual(out["state"], webtask.COMMIT, out.get("say"))
        self.assertEqual(out["replay_from"], self.base + "/w1")
        self.press(out)
        self.assertEqual(self.got.get("_last_post"), "/submit")
        self.assertEqual(self.got.get("first_name"), "Caleb")
        self.assertEqual(self.got.get("city"), "Austin")
        self.assertEqual(self.got.get("why"),
                         "I build unattended systems with quality gates.")


@needs_browser
class AFormMadeOfDIVS(RealPageCase):
    """A typeahead and a custom radio group: nothing has an id, nothing is
    a `<select>`, and the values the form actually posts are hidden inputs
    the widgets set. She could see the box to type a city into and not one
    of the cities."""

    def test_she_can_see_the_answers_and_the_question_they_answer(self):
        with browse._Session() as ctx:
            page = ctx.new_page()
            page.goto(self.base + "/widget", wait_until="domcontentloaded")
            seen = webtask.observe(page)
        yes = by_text(seen, "Yes")
        self.assertIsNotNone(yes, "a <div role=radio> is an answer she can click")
        self.assertEqual(yes["role"], "radio")
        self.assertEqual(yes["question"],
                         "Are you legally authorized to work in the US? *")
        self.assertIs(yes["checked"], False)

    def test_a_typeahead_and_a_div_radio_group_reach_the_server(self):
        out = self.drive(
            "/widget", "Fill in this application with my details and submit it.",
            ("type", "Location", "Austin"),
            ("click", "Austin, TX"), ("click", "Yes"),
            ("click", "Submit application"))
        self.assertEqual(out["state"], webtask.COMMIT, out.get("say"))
        self.press(out)
        # The hidden values the widgets set — the proof the CLICKS landed,
        # not just that something was typed in a box.
        self.assertEqual(self.got.get("location_value"), "Austin, TX")
        self.assertEqual(self.got.get("work_auth"), "Yes")

    def test_a_protected_question_is_never_answered_by_a_click_either(self):
        out = self.drive("/widget", "Fill in this application and submit it.",
                         ("click", "I am not"))
        self.assertEqual(out["state"], webtask.ASK)
        self.assertIn("yours to answer", out["say"])
        self.assertIn("protected veteran", out["say"])


@needs_browser
class ThePagesOwnVerdictOnWhetherItWillGO(RealPageCase):
    """Her own reading of "required and empty" missed everything the
    browser knows and everything a question made of divs is. So a run
    reported success while the site refused the submit, and an
    application sat AWAITING HIS CONFIRMATION that could never be sent."""

    def look(self, path="/widget"):
        with browse._Session() as ctx:
            page = ctx.new_page()
            page.goto(self.base + path, wait_until="domcontentloaded")
            yield page

    def test_a_required_div_question_with_nothing_picked_is_BLOCKING(self):
        for page in self.look():
            said = [b["label"] for b in webtask.formfill.blocking(page)]
        self.assertIn("Are you legally authorized to work in the US? *", said)

    def test_a_half_made_typeahead_choice_is_not_a_choice(self):
        """Typing "Austin" and never picking "Austin, TX" leaves the value
        the widget actually posts empty — with the list still open, which
        is exactly how a person can see it is unfinished."""
        for page in self.look():
            page.fill("[name=location]", "Austin")
            half = [b["label"] for b in webtask.formfill.blocking(page)]
            page.click("[role=option]")
            whole = [b["label"] for b in webtask.formfill.blocking(page)]
        self.assertTrue(any("Location" in label for label in half), half)
        self.assertFalse(any("Location" in label for label in whole), whole)

    def test_the_application_filler_answers_it_from_his_PROFILE(self):
        from aletheia import apply_run
        profile.set_answer("work_authorization", "Yes", source="operator")
        with mock.patch.object(apply_run, "staged_dir",
                               lambda: Path(self.tmp.name) / "applications"):
            (Path(self.tmp.name) / "applications").mkdir(exist_ok=True)
            record = apply_run.stage(self.base + "/widget")
        answered = {f["label"]: f["value"]
                    for f in (record.get("filled")
                              or record.get("would_fill") or [])}
        self.assertEqual(
            answered.get("Are you legally authorized to work in the US? *"),
            "Yes", record.get("say"))

    def test_it_refuses_to_STAGE_a_form_that_cannot_go(self):
        """Everything she could answer, answered — and the form still
        will not go, because the location was never picked. That is a
        question, not an approval waiting for him."""
        from aletheia import apply_run
        profile.set_answer("work_authorization", "Yes", source="operator")
        with mock.patch.object(apply_run, "staged_dir",
                               lambda: Path(self.tmp.name) / "applications"):
            (Path(self.tmp.name) / "applications").mkdir(exist_ok=True)
            record = apply_run.stage(self.base + "/widget")
        self.assertEqual(record["state"], "NEEDS_YOU")
        self.assertEqual(record["approval"], "")
        self.assertIn("will not go", record["say"])


@needs_browser
class APageThatIsNotThereYet(RealPageCase):
    """`domcontentloaded` fires before a React application has rendered
    anything, and every real applicant tracking system is one. She looked
    at a careers page before its form existed and the only reason she did
    not give up was that the model happened to be slower than the page —
    a coincidence, not a design."""

    def test_she_waits_for_the_form_to_actually_exist(self):
        with browse._Session() as ctx:
            page = ctx.new_page()
            page.goto(self.base + "/late", wait_until="domcontentloaded")
            straight_away = webtask.formfill.read_all(page)
            webtask.settle(page)
            after = [f["selector"] for f in webtask.formfill.read_all(page)]
        self.assertEqual(straight_away, [], "the form really is not there yet")
        self.assertEqual(after, ["#fn", "#ph"])


@needs_browser
class ARefusalIsNotADeadEndEither(RealPageCase):
    """The whole loop, against a site that refuses: she applies, it hands
    the form back, she says so honestly, and "try that again" reads what
    it said, fixes it, and brings him a new confirmation."""

    def apply(self, run_id=""):
        return webtask.run(
            "Apply for this job with my details.", start_url=self.base + "/late",
            budget=8, run_id=run_id,
            think=script(("click", "Accept all"), ("click", "Submit application")))

    def test_a_refused_application_is_reported_as_refused_and_then_FIXED(self):
        first = self.apply()
        self.assertEqual(first["state"], webtask.COMMIT, first.get("say"))
        done = self.press(first)
        # 1. It really was refused, and she says so rather than "done".
        self.assertEqual(done["state"], "REJECTED")
        self.assertEqual(done["result"]["verdict"], "rejected")
        self.assertEqual(self.got.get("phone"), "(512) 555-0134")
        self.assertIn("handed it back", done["say"])

        # 2. "Try that again" reads what the site said and corrects it —
        #    the same fact, punctuated the way the site wants.
        again = webtask.retry(done["id"], think=script(
            ("click", "Accept all"),
            ("type", "Phone", "5125550134"),
            ("click", "Submit application")))
        self.assertEqual(again["state"], webtask.COMMIT, again.get("say"))
        self.assertIn({"action": "type", "selector": "#ph",
                       "value": "5125550134"}, again["typed"])

        # 3. And it needed a fresh yes, then it went through.
        self.assertEqual(policy.load(again["approval"])["state"], "PENDING")
        landed = self.press(again)
        self.assertEqual(landed["result"]["verdict"], "confirmed")
        self.assertEqual(self.got.get("phone"), "5125550134")


@needs_browser
class NotEveryTaskIsAFORM(RealPageCase):
    """"Download last month's statement and put it in my workspace" and
    "cancel my gym membership" are the other two shapes he named, and
    neither of them types anything into anything."""

    def test_files_the_page_offers_land_in_HER_workspace_and_she_says_where(self):
        out = self.drive(
            "/account", "Download my statements into my workspace.",
            ("download", "July statement"), ("download", "August statement"))
        self.assertEqual(out["state"], webtask.DONE, out.get("say"))
        self.assertEqual([Path(d).name for d in out["downloaded"]],
                         ["2026-07.pdf", "2026-08.pdf"])
        for path in out["downloaded"]:
            self.assertTrue(Path(path).is_file())
            self.assertTrue(Path(path).read_bytes().startswith(b"%PDF"))
        # WHERE, not just what: "Saved: 2026-07.pdf" is a file he then has
        # to go and find.
        self.assertIn(str(Path(out["downloaded"][0]).parent), out["say"])

    def test_ENDING_something_waits_for_him_like_anything_else(self):
        """The list of irreversible words only had words for CREATING an
        obligation, so "Cancel my membership" was a button she would have
        pressed on her own."""
        out = self.drive("/account", "Cancel my gym membership.",
                         ("click", "Cancel my membership"))
        self.assertEqual(out["state"], webtask.COMMIT, out.get("say"))
        self.assertEqual(out["button"], "Cancel my membership")
        self.assertEqual(self.got, {}, "and nothing was cancelled")
        # It typed nothing, so it must not claim it filled anything in.
        self.assertNotIn("Everything is filled in", out["say"])
        self.assertIn("not something I can undo", out["say"])

    def test_and_it_only_happens_once_he_says_so(self):
        out = self.drive("/account", "Cancel my gym membership.",
                         ("click", "Cancel my membership"))
        self.press(out)
        self.assertEqual(self.got.get("_last_post"), "/cancel")


@needs_browser
class ASignInWallStopsHerBeforeSheTypes(RealPageCase):
    def test_she_names_the_one_command_and_leaves_nothing_behind(self):
        out = self.drive("/portal", "Check my account", ("click", "Sign in"))
        self.assertEqual(out["state"], webtask.SIGN_IN)
        self.assertIn("python -m aletheia.browse login", out["say"])
        self.assertEqual(self.got, {})


if __name__ == "__main__":
    unittest.main()
