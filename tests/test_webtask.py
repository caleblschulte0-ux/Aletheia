"""Any request that means "go do this on the web".

His correction: *"this applying to jobs thing is an example — it's an
example of something where you need to access a document on my computer,
do multiple steps on a browser, shit like that."*

I had been hand-building verticals. `apply_run` drives a job application
and nothing else; the next request needing six clicks on a website would
have wanted another module. That ceiling was the defect. This is the
general thing underneath all of them: look at the page, do one step, look
again — with his profile and his files available, and three refusals that
make it safe to point at a live site.
"""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import (computer, journal, notifications, policy, profile,
                      webtask)


class FakePage:
    """A page that records what was done to it."""

    def __init__(self, fields=(), buttons=(), url="https://x.example/form"):
        self._fields = [dict(f) for f in fields]
        self._buttons = [dict(b) for b in buttons]
        self.url = url
        self.did = []

    # -- what webtask calls --
    def goto(self, url, **kw):
        self.url = url
        self.did.append(("goto", url))

    def title(self):
        return "A page"

    def evaluate(self, script):
        if "buttons" in script and "links" in script:
            return {"title": "A page", "url": self.url, "text": "some text",
                    "buttons": self._buttons, "links": []}
        if "checkValidity" in script:
            # The page's own verdict on whether it will go, which is what
            # `formfill.blocking` asks for.
            return {"invalid": [{"label": f["label"], "name": f.get("name", ""),
                                 "why": "required"}
                                for f in self._fields
                                if f.get("required")
                                and not (f.get("value") or "").strip()
                                and f.get("type") not in ("file", "hidden",
                                                          "submit")],
                    "groups": list(getattr(self, "_groups", []))}
        if "tag: 'aria'" in script:
            # The ARIA read is a SECOND pass over the same document. A
            # double that answers both with the same rows reports every
            # field twice, which is not a bug in the page — it is a bug in
            # the double, and it cost half an hour of reading a real diff.
            return list(getattr(self, "_aria", []))
        return self._fields

    def _set(self, selector, value):
        for field in self._fields:
            if field["selector"] == selector:
                field["value"] = value
                return field
        raise AssertionError(f"no field {selector}")

    def fill(self, selector, value):
        self._set(selector, value)
        self.did.append(("fill", selector, value))

    def select_option(self, selector, value=None, label=None):
        self._set(selector, label or value)
        self.did.append(("select", selector, label or value))

    def check(self, selector):
        field = self._set(selector, "checked")
        field["checked"] = True
        self.did.append(("check", selector))

    def uncheck(self, selector):
        self._set(selector, "")
        self.did.append(("uncheck", selector))

    def set_input_files(self, selector, path):
        self.did.append(("attach", selector, path))

    def click(self, selector):
        self.did.append(("click", selector))

    def query_selector(self, css):
        for row in self._fields + self._buttons:
            if row["selector"] == css:
                return FakeEl(row.get("text") or row.get("label") or "")
        for row in getattr(self, "_links", []):
            if row.get("selector") == css:
                return FakeEl(row.get("text", ""))
        return None

    def is_closed(self):
        return False

    def wait_for_timeout(self, ms):
        pass

    def wait_for_load_state(self, *a, **kw):
        pass

    def inner_text(self, *a):
        return "thank you"

    def screenshot(self, **kw):
        pass

    def close(self):
        pass


class FakeEl:
    def __init__(self, text):
        self.text = text

    def inner_text(self):
        return self.text

    def get_attribute(self, name):
        return None


class FakeFrame(FakePage):
    """An embedded document: same verbs, different tree."""


class FakeFramed(FakePage):
    """A page with an <iframe> in it — what an ATS embed actually is."""

    def __init__(self, inner, fields=(), buttons=(), url="https://x.example/apply"):
        super().__init__(fields, buttons, url=url)
        self.inner = inner
        self.frames = [self, inner]


class FakeSession:
    def __init__(self, page):
        self.page = page

    def __call__(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def new_page(self):
        return self.page

    @property
    def pages(self):
        return [self.page] + list(getattr(self, "opened", []))


def field(selector, label, **kw):
    row = {"selector": selector, "label": label, "name": "", "id": selector[1:],
           "tag": kw.pop("tag", "input"), "type": kw.pop("type", "text"),
           "required": kw.pop("required", False), "value": kw.pop("value", "")}
    row.update(kw)
    return row


class WebTaskCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        d = Path(self.tmp.name)
        self.ws = d / "ws"
        self.ws.mkdir()
        env = mock.patch.dict(os.environ, {"ALETHEIA_PRIVATE_STATE": str(d),
                                           "ALETHEIA_WORKSPACE": str(self.ws)})
        env.start(); self.addCleanup(env.stop)
        (d / "approvals").mkdir()
        for target, attr, value in (
                (journal, "JOURNAL_PATH", d / "j.jsonl"),
                (policy, "APPROVALS_DIR", d / "approvals"),
                (policy, "HALT_PATH", d / "halt.json"),
                (profile, "path", lambda: d / "answers.json"),
                # Its directory is bound at import, so without this every
                # test in the run shares one notification store — and a
                # dedupe key from another test silently swallows the
                # notification this one is asserting on.
                (notifications, "NOTICES_DIR", d / "notices"),
                (webtask, "runs_dir", lambda: d / "webtasks")):
            p = mock.patch.object(target, attr, value)
            p.start(); self.addCleanup(p.stop)
        (d / "webtasks").mkdir()
        available = mock.patch.object(webtask.browse, "available",
                                      return_value=(True, "ready"))
        available.start(); self.addCleanup(available.stop)
        profile.learn_from_resume(
            "Caleb Schulte\nAustin, TX\ncaleb@example.com | (512) 555-0134")

    def brain(self, *replies):
        answers = list(replies)

        def think(system, prompt, **kw):
            return answers.pop(0) if answers else '{"action": "done", "value": "x"}'
        return think

    def go(self, page, goal, *replies, budget=4):
        return webtask.run(goal, start_url="https://x.example/form",
                           budget=budget, think=self.brain(*replies),
                           session=FakeSession(page))


class SheDoesTheStepsHerself(WebTaskCase):
    def test_what_she_knows_is_filled_with_no_model_call_at_all(self):
        """`formfill` maps a form to his profile in milliseconds and is
        simply better at it than a model. The model is for judgment — which
        button, which page — not for copying his email into a box."""
        page = FakePage([field("#em", "Email address"),
                         field("#fn", "First name")])
        called = []

        def think(*a, **kw):
            called.append(1)
            return '{"action": "done", "value": "filled"}'
        webtask.run("fill this in", start_url="https://x.example/form",
                    budget=2, think=think, session=FakeSession(page))
        self.assertIn(("fill", "#em", "caleb@example.com"), page.did)
        self.assertIn(("fill", "#fn", "Caleb"), page.did)
        self.assertEqual(len(called), 1, "one call, for the decision, not the typing")

    def test_a_judgement_question_is_answered_from_his_own_words(self):
        page = FakePage([field("#why", "Why do you want this?", tag="textarea",
                               type="textarea", required=True)])
        self.go(page, "Fill it in. For why do you want this say: I build "
                      "unattended systems.",
                '{"action":"fill","values":{"#why":"I build unattended systems."}}',
                '{"action":"done","value":"filled"}')
        self.assertIn(("fill", "#why", "I build unattended systems."), page.did)

    def test_a_checkbox_is_CHECKED_not_typed_into(self):
        """A required certification box read as filled because its `value`
        is "on" whether or not it is ticked. The browser refused the submit
        and the run reported success while the employer got nothing."""
        page = FakePage([field("#cert", "I certify this is true",
                               type="checkbox", required=True)])
        self.go(page, "tick the certification box",
                '{"action":"fill","values":{"#cert":"yes"}}',
                '{"action":"done","value":"done"}')
        self.assertIn(("check", "#cert"), page.did)

    def test_a_file_comes_off_HIS_computer(self):
        (self.ws / "resume.txt").write_text("his resume")
        page = FakePage([field("#cv", "Resume", type="file", required=True)])
        self.go(page, "attach my resume",
                '{"action":"attach","selector":"#cv","value":"resume.txt"}',
                '{"action":"done","value":"attached"}')
        self.assertTrue(any(d[0] == "attach" and d[1] == "#cv" for d in page.did))

    def test_a_document_where_he_actually_keeps_it(self):
        """The two halves of her disagreed: "summarise the lease on my
        desktop" worked and "attach the lease on my desktop" came back as
        "that is not one of your files"."""
        home = tempfile.TemporaryDirectory()
        self.addCleanup(home.cleanup)
        lease = Path(home.name) / "Desktop" / "lease.pdf"
        lease.parent.mkdir(parents=True)
        lease.write_bytes(b"%PDF-1.4")
        with mock.patch("pathlib.Path.home", staticmethod(lambda: Path(home.name))):
            held = webtask.documents()
        self.assertEqual(held.get("lease.pdf"), str(lease))

    def test_what_she_may_UPLOAD_is_narrower_than_what_she_may_read(self):
        """A document is a thing you send somebody. A .env is not."""
        home = tempfile.TemporaryDirectory()
        self.addCleanup(home.cleanup)
        desk = Path(home.name) / "Desktop"
        desk.mkdir(parents=True)
        for name in ("lease.pdf", "secrets.env", "id_rsa", "keys.key"):
            (desk / name).write_text("x")
        with mock.patch("pathlib.Path.home", staticmethod(lambda: Path(home.name))):
            held = webtask.documents()
        self.assertIn("lease.pdf", held)
        for name in ("secrets.env", "id_rsa", "keys.key"):
            self.assertNotIn(name, held)

    def test_the_approval_says_WHAT_IS_BEING_SENT(self):
        """A file leaving his computer for somebody else's is the part he
        most needs to see before he says yes."""
        page = FakePage([field("#cv", "Resume", type="file"),
                         field("#fn", "First name *", required=True)],
                        [{"selector": "#go", "text": "Submit application"}])
        out = self.go(page, "Apply with my resume",
                      '{"action": "attach", "selector": "#cv", "value": "resume"}',
                      '{"action": "click", "selector": "#go"}')
        self.assertEqual(out["state"], webtask.COMMIT, out.get("say"))
        self.assertIn("sending", policy.load(out["approval"])["reason"])

    def test_a_file_she_was_not_given_is_refused(self):
        page = FakePage([field("#cv", "Resume", type="file")])
        out = self.go(page, "attach something",
                      '{"action":"attach","selector":"#cv","value":"/etc/passwd"}')
        self.assertEqual(out["state"], webtask.ASK)
        self.assertFalse(any(d[0] == "attach" for d in page.did))


class SheCannotInventAFactAboutHim(WebTaskCase):
    """A model asked to fill a form will produce a plausible phone number
    without hesitating. This is checked in CODE, not asked for in a prompt,
    because a prompt is a request."""

    def test_a_value_that_is_neither_his_nor_his_words_is_refused(self):
        page = FakePage([field("#dob", "Date of birth", required=True)])
        out = self.go(page, "fill in this form",
                      '{"action":"fill","values":{"#dob":"1994-03-12"}}')
        self.assertEqual(out["state"], webtask.ASK)
        self.assertIn("Date of birth", out["say"])
        self.assertFalse(any(d[0] == "fill" for d in page.did))

    def test_a_fact_from_his_profile_is_allowed(self):
        page = FakePage([field("#p", "Phone")])
        self.go(page, "fill it in", '{"action":"done","value":"ok"}')
        self.assertIn(("fill", "#p", "(512) 555-0134"), page.did)

    def test_a_sentence_HE_dictated_is_his(self):
        """The first version refused it: the essay was a substring of his
        request rather than the whole request, so the one thing he had
        explicitly dictated came back as a question."""
        allowed = webtask._permitted_values("say: I build unattended systems")
        self.assertTrue(webtask._value_is_his(
            "I build unattended systems", allowed, [],
            "say: I build unattended systems"))

    def test_yes_and_no_are_answers_not_personal_facts(self):
        allowed = webtask._permitted_values("fill it in")
        for word in ("Yes", "no", "N/A"):
            self.assertTrue(webtask._value_is_his(word, allowed, []), word)


class SheStopsBeforeAnythingThatCOMMITS(WebTaskCase):
    def submitting_page(self, **extra):
        return FakePage(
            [field("#em", "Email address"), dict(field("#why", "Why?",
             tag="textarea", type="textarea"), value="already", **extra)],
            [{"selector": "#go", "text": "Submit application"}])

    def test_a_submit_button_becomes_one_approval(self):
        page = self.submitting_page()
        out = self.go(page, "fill it in and submit",
                      '{"action":"click","selector":"#go"}')
        self.assertEqual(out["state"], webtask.COMMIT)
        self.assertEqual(out["button"], "Submit application")
        self.assertNotIn(("click", "#go"), page.did)
        self.assertEqual(policy.load(out["approval"])["state"], "PENDING")

    def test_the_approval_carries_everything_typed_to_get_there(self):
        """The first version collected only steps whose action was "type" —
        and once filling was batched that list was EMPTY, so pressing
        submit would have re-opened a blank form and sent it."""
        page = self.submitting_page()
        out = self.go(page, "fill it in and submit",
                      '{"action":"click","selector":"#go"}')
        self.assertTrue(out["typed"])
        self.assertTrue(any(s["selector"] == "#em" for s in out["typed"]))

    def test_it_says_out_loud_there_is_no_undo(self):
        page = self.submitting_page()
        out = self.go(page, "submit it", '{"action":"click","selector":"#go"}')
        approval = policy.load(out["approval"])
        self.assertFalse(approval["reversible"])
        self.assertIn("undo", approval["consequence"])

    def test_a_required_field_still_empty_stops_it_before_the_button(self):
        """The browser would refuse the submit and the run would report
        success while nothing was sent."""
        page = FakePage([field("#why", "Why?", required=True, tag="textarea",
                               type="textarea")],
                        [{"selector": "#go", "text": "Submit"}])
        out = self.go(page, "submit it", '{"action":"click","selector":"#go"}')
        self.assertEqual(out["state"], webtask.ASK)
        self.assertIn("Why?", out["say"])

    def test_nothing_is_pressed_before_he_confirms(self):
        page = self.submitting_page()
        out = self.go(page, "submit it", '{"action":"click","selector":"#go"}')
        with self.assertRaises(webtask.WebTaskError):
            webtask.commit(out["id"], presser=lambda r: {})

    def test_it_is_pressed_once(self):
        page = self.submitting_page()
        out = self.go(page, "submit it", '{"action":"click","selector":"#go"}')
        policy.decide(out["approval"], "APPROVED", via="phone")
        pressed = []
        webtask.commit(out["id"], presser=lambda r: pressed.append(1) or {"url": "x"})
        with self.assertRaises(webtask.WebTaskError):
            webtask.commit(out["id"], presser=lambda r: pressed.append(1) or {})
        self.assertEqual(len(pressed), 1)


class MoneyIsRefusedNotGATED(WebTaskCase):
    """His one line that has never moved. "Confirm you want to spend $400"
    is a question this system does not ask."""

    def test_a_goal_about_spending_never_opens_a_browser(self):
        out = webtask.run("buy me a keyboard on amazon",
                          session=FakeSession(FakePage()),
                          think=lambda *a, **k: '{"action":"done"}')
        self.assertEqual(out["state"], webtask.REFUSED)
        self.assertEqual(out["steps"], [])

    def test_a_pay_button_stops_the_run_with_no_approval_offered(self):
        page = FakePage([field("#em", "Email address")],
                        [{"selector": "#pay", "text": "Place order"}])
        out = self.go(page, "finish the checkout",
                      '{"action":"click","selector":"#pay"}')
        self.assertEqual(out["state"], webtask.REFUSED)
        self.assertNotIn("approval", out)
        self.assertEqual(policy.all_approvals(), [])

    def test_the_committing_words_are_the_desktops_own(self):
        """One list, so the browser and the desktop cannot disagree about
        what commits."""
        for word in ("submit", "send", "delete", "confirm", "place order"):
            self.assertTrue(computer.committing_label(f"X {word} Y"), word)


class ItCannotRunAway(WebTaskCase):
    def test_the_budget_ends_it(self):
        page = FakePage([field("#a", "Note")])
        out = self.go(page, "do something forever",
                      *['{"action":"goto","value":"https://x.example/1"}'] * 6,
                      budget=3)
        self.assertEqual(out["state"], webtask.BUDGET)
        self.assertLessEqual(len(out["steps"]), 3)

    def test_a_halt_stops_it_before_it_opens_anything(self):
        policy.halt("stop", via="test")
        with self.assertRaises(Exception):
            self.go(FakePage(), "do a thing", '{"action":"done"}')

    def test_every_run_is_journaled(self):
        self.go(FakePage([field("#a", "Note")]), "do a thing",
                '{"action":"done","value":"did it"}')
        self.assertIn("webtask", journal.JOURNAL_PATH.read_text(encoding="utf-8"))

    def test_a_brain_that_returns_nonsense_asks_him_rather_than_guessing(self):
        out = self.go(FakePage([field("#a", "Note")]), "do a thing",
                      "I am not JSON at all")
        self.assertEqual(out["state"], webtask.ASK)


class SheCanSAVEAFileToo(WebTaskCase):
    def test_a_download_lands_in_her_workspace(self):
        """A download is not permission to put a file anywhere on his disk."""
        saved = {}

        class Caught:
            value = type("D", (), {
                "suggested_filename": "statement.pdf",
                "save_as": lambda self, path: saved.update(path=path)})()

            def __enter__(self): return self
            def __exit__(self, *a): return False

        page = FakePage([field("#a", "Note")],
                        [{"selector": "#dl", "text": "Download statement"}])
        page.expect_download = lambda **kw: Caught()
        out = self.go(page, "download my statement",
                      '{"action":"download","selector":"#dl"}',
                      '{"action":"done","value":"got it"}')
        self.assertIn("statement.pdf", saved["path"])
        self.assertIn(str(self.ws), saved["path"])
        self.assertEqual(out["state"], webtask.DONE)
        self.assertIn("statement.pdf", out["say"])

    def test_a_failed_download_is_a_step_not_a_crash(self):
        page = FakePage([field("#a", "Note")],
                        [{"selector": "#dl", "text": "Download"}])

        def boom(**kw):
            raise RuntimeError("no download started")
        page.expect_download = boom
        out = self.go(page, "download it",
                      '{"action":"download","selector":"#dl"}',
                      '{"action":"done","value":"nothing to get"}')
        self.assertEqual(out["state"], webtask.DONE)
        self.assertTrue(any("download failed" in e["result"]
                            for e in out["steps"]))


class FakeWizard(FakePage):
    """Three pages, the shape Workday actually is: each button REPLACES
    the whole form, so page three cannot be reached by opening its URL."""

    def __init__(self, pages, base="https://x.example"):
        self.pages = pages
        self.base = base
        self.received = {}
        self.submitted = None
        self.did = []
        self._open(0)

    def _url_for(self, index):
        return f"{self.base}/" if index == 0 else f"{self.base}/step{index + 1}"

    def _open(self, index):
        self.index = index
        fields, buttons = self.pages[index]
        self._fields = [dict(f) for f in fields]
        self._buttons = [dict(b) for b in buttons]
        self.url = self._url_for(index)

    def goto(self, url, **kw):
        self.did.append(("goto", url))
        for i in range(len(self.pages)):
            if self._url_for(i) == url:
                return self._open(i)
        raise AssertionError(f"no page at {url}")

    def click(self, selector):
        self.did.append(("click", selector))
        if not any(b["selector"] == selector for b in self._buttons):
            raise AssertionError(f"no button {selector} on {self.url}")
        for row in self._fields:
            if (row.get("value") or ""):
                self.received[row["selector"]] = row["value"]
        if self.index + 1 < len(self.pages):
            self._open(self.index + 1)
        else:
            self.submitted = dict(self.received)


class AWizardIsWalkedThroughNotJumpedInto(WebTaskCase):
    """Three pages, and the commit replays the WHOLE route.

    The first version bound the approval to the page it happened to be
    standing on and re-opened that page to press the button. Against the
    real three-page server it filled two pages, waited for him, and then
    died on `waiting for locator "#fn"` — page one's field, typed onto
    page three. The employer received the first two pages and never the
    third, and the run reported the press as a failure only after the
    site already had half an application. The route is the unit, not the
    page.
    """

    PAGES = [
        ([field("#fn", "First name *", required=True),
          field("#ln", "Last name *", required=True)],
         [{"selector": "button[type=submit]", "text": "Next"}]),
        ([field("#ph", "Phone")],
         [{"selector": "button[type=submit]", "text": "Continue"}]),
        ([field("#why", "Anything else? *", tag="textarea", required=True),
          field("#cert", "I certify this is true.", type="checkbox",
                required=True, checked=False)],
         [{"selector": "button[type=submit]", "text": "Submit application"}]),
    ]
    GOAL = ("Fill in this three page application with my details. For "
            "anything else say: I build unattended systems with quality "
            "gates. Tick the certification box and submit it.")

    def walk(self):
        wizard = FakeWizard(self.PAGES)
        out = webtask.run(
            self.GOAL, start_url="https://x.example/", budget=6,
            think=self.brain(
                '{"action": "click", "selector": "button[type=submit]"}',
                '{"action": "click", "selector": "button[type=submit]"}',
                '{"action": "fill", "values": {"#why": "I build unattended '
                'systems with quality gates.", "#cert": "yes"}}',
                '{"action": "click", "selector": "button[type=submit]"}'),
            session=FakeSession(wizard))
        return wizard, out

    def test_the_route_is_recorded_not_just_the_last_page(self):
        _, out = self.walk()
        self.assertEqual(out["state"], webtask.COMMIT, out.get("say"))
        self.assertEqual(out["replay_from"], "https://x.example/")
        self.assertEqual(out["url"], "https://x.example/step3")
        # Every page's values AND the clicks that carried her between them.
        self.assertEqual(
            [(s["action"], s["selector"]) for s in out["typed"]],
            [("type", "#fn"), ("type", "#ln"), ("click", "button[type=submit]"),
             ("type", "#ph"), ("click", "button[type=submit]"),
             ("type", "#why"), ("check", "#cert")])

    def test_the_approval_is_bound_to_where_the_route_STARTS(self):
        """Otherwise the press replays a route onto the wrong page."""
        _, out = self.walk()
        approval = policy.load(out["approval"])
        self.assertEqual(approval["requested_action"],
                         webtask.browse.approval_action(
                             "https://x.example/",
                             out["typed"] + [{"action": "click",
                                              "selector": "button[type=submit]"}]))

    def test_pressing_it_walks_all_three_pages_and_the_site_gets_ALL_of_it(self):
        wizard, out = self.walk()
        policy.decide(out["approval"], "APPROVED", via="phone")
        wizard.received, wizard.submitted, wizard.did = {}, None, []
        with mock.patch.object(webtask.browse, "_Session", FakeSession(wizard)):
            done = webtask.commit(out["id"])
        self.assertEqual(done["state"], "COMMITTED")
        self.assertEqual(wizard.submitted,
                         {"#fn": "Caleb", "#ln": "Schulte",
                          "#ph": "(512) 555-0134",
                          "#why": "I build unattended systems with quality gates.",
                          "#cert": "checked"})
        self.assertEqual([d for d in wizard.did if d[0] == "goto"],
                         [("goto", "https://x.example/")])


class AFormInsideAnIframeIsStillAForm(WebTaskCase):
    """Greenhouse and Lever both ship their application as an `<iframe>`.

    Pointed at a careers page whose form was one frame away, she read the
    top document, found no inputs and said *"I don't see any form fields"*
    — with the entire application sitting right there. Reading only the
    top document is the same defect as reading only the last page of a
    wizard: the thing she was sent to do is one level away from where she
    is standing.
    """

    def framed(self):
        inner = FakeFrame(
            [field("#fn", "First name *", required=True),
             field("#em", "Email *", required=True),
             field("#why", "Why do you want this job? *", tag="textarea",
                   required=True)],
            [{"selector": "button[type=submit]", "text": "Submit application"}],
            url="https://x.example/embed")
        page = FakeFramed(inner, [], [], url="https://x.example/apply")
        return page, inner

    def run_it(self, *replies, budget=4):
        page, inner = self.framed()
        out = webtask.run(
            "Apply for this job with my details. For why I want the job say: "
            "I build unattended systems with quality gates.",
            start_url="https://x.example/apply", budget=budget,
            think=self.brain(*replies), session=FakeSession(page))
        return page, inner, out

    def test_the_fields_in_the_frame_are_seen_and_carry_the_frame_with_them(self):
        _, inner, out = self.run_it(
            '{"action": "done", "value": "filled"}')
        page, _ = self.framed()
        # Read from the top document, this page has no fields at all.
        self.assertEqual(page.evaluate(webtask.formfill.READ_FORM_JS), [])
        # Read properly, every field is there and says which frame it is in.
        self.assertEqual([f["selector"] for f in webtask.read_forms(page)],
                         ["@frame1|#fn", "@frame1|#em", "@frame1|#why"])
        # And what she knows goes into the FRAME, not the page.
        self.assertEqual([d for d in inner.did if d[0] == "fill"][:2],
                         [("fill", "#fn", "Caleb"),
                          ("fill", "#em", "caleb@example.com")])
        self.assertEqual([d for d in out["steps"] if d["step"]["action"] == "known"][0]
                         ["result"].startswith("filled 2"), True)

    def test_the_submit_button_INSIDE_the_frame_is_the_one_she_stops_at(self):
        _, _, out = self.run_it(
            '{"action": "fill", "values": {"@frame1|#why": "I build unattended '
            'systems with quality gates."}}',
            '{"action": "click", "selector": "@frame1|button[type=submit]"}')
        self.assertEqual(out["state"], webtask.COMMIT, out.get("say"))
        self.assertEqual(out["button"], "Submit application")
        self.assertEqual(out["button_selector"], "@frame1|button[type=submit]")

    def test_pressing_it_reaches_into_the_frame_not_the_page(self):
        page, inner, out = self.run_it(
            '{"action": "fill", "values": {"@frame1|#why": "I build unattended '
            'systems with quality gates."}}',
            '{"action": "click", "selector": "@frame1|button[type=submit]"}')
        policy.decide(out["approval"], "APPROVED", via="phone")
        page.did, inner.did = [], []
        with mock.patch.object(webtask.browse, "_Session", FakeSession(page)):
            webtask.commit(out["id"])
        self.assertIn(("click", "button[type=submit]"), inner.did)
        self.assertNotIn(("click", "button[type=submit]"), page.did)

    def test_an_element_is_found_in_whatever_frame_actually_holds_it(self):
        """The index is a hint; being there is the truth. A frame attaches
        after `domcontentloaded` and then navigates, so right after a load
        frame 1 exists and is empty."""
        page, inner = self.framed()
        where, css = webtask._resolve(page, "@frame4|#fn")
        self.assertIs(where, inner)
        self.assertEqual(css, "#fn")

    def test_a_page_with_no_frames_at_all_behaves_exactly_as_before(self):
        plain = FakePage([field("#a", "First name")], [])
        self.assertEqual(webtask._frames(plain), [plain])
        self.assertEqual(webtask._resolve(plain, "#a"), (plain, "#a"))


class AnApplyLinkIsAControlToo(WebTaskCase):
    """"Apply for this job" is an `<a target="_blank">` on most of the
    internet. Refusing to click one because it is not a `<button>`, and
    then not following the tab it opens, together made the first live run
    stand on the careers page describing it."""

    def test_a_link_is_clicked_not_refused(self):
        page = FakePage([], [])
        page._links = [{"selector": "a[href='/apply']", "text": "Apply for this job"}]
        out = self.go(page, "Apply for this job",
                      """{"action": "click", "selector": "a[href='/apply']"}""",
                      '{"action": "done", "value": "clicked"}')
        self.assertIn(("click", "a[href='/apply']"), page.did)
        self.assertEqual(out["state"], webtask.DONE)

    def test_a_selector_that_is_on_no_page_at_all_is_still_refused(self):
        page = FakePage([], [])
        out = self.go(page, "Apply for this job",
                      '{"action": "click", "selector": "#nope"}',
                      '{"action": "done", "value": "gave up on it"}')
        self.assertNotIn(("click", "#nope"), page.did)
        self.assertIn("no such control", out["steps"][0]["result"])

    def test_a_click_that_opens_a_new_tab_is_FOLLOWED(self):
        page = FakePage([], [])
        page._links = [{"selector": "a#apply", "text": "Apply for this job"}]
        opened = FakePage([field("#fn", "First name *", required=True)], [],
                          url="https://x.example/form2")
        session = FakeSession(page)
        session.opened = []
        original = page.click

        def click(selector):
            original(selector)
            session.opened.append(opened)      # the popup, a beat later
        page.click = click

        out = webtask.run(
            "Apply for this job", start_url="https://x.example/form",
            budget=3, think=self.brain(
                '{"action": "click", "selector": "a#apply"}',
                '{"action": "done", "value": "done"}'),
            session=session)
        self.assertIn("opened a new tab", out["steps"][0]["result"])
        # And she is now working on the tab that opened.
        self.assertEqual(out["url"], "https://x.example/form2")
        self.assertIn(("fill", "#fn", "Caleb"), opened.did)


class ADoorSheMayNotWalkThrough(WebTaskCase):
    """Two walls, and they are different in kind: one he can fix once,
    one nobody should be defeating."""

    def test_a_sign_in_wall_names_the_ONE_command_that_fixes_it_for_good(self):
        page = FakePage([field("#u", "Email"),
                         field("#p", "Password", type="password")],
                        [{"selector": "#go", "text": "Sign in"}],
                        url="https://portal.example/login")
        out = self.go(page, "Check my account on the portal",
                      '{"action": "done", "value": "should not get here"}')
        self.assertEqual(out["state"], webtask.SIGN_IN)
        self.assertIn("python -m aletheia.browse login", out["say"])
        self.assertIn(out["url"], out["say"])
        self.assertEqual([d for d in page.did if d[0] == "fill"], [])

    def test_she_never_types_a_password_she_was_never_given(self):
        page = FakePage([field("#p", "Password", type="password")], [])
        self.go(page, "Sign in for me",
                '{"action": "type", "selector": "#p", "value": "hunter2"}')
        self.assertEqual([d for d in page.did if d[0] == "fill"], [])

    def test_a_human_check_is_NAMED_and_never_attempted(self):
        page = FakePage([], [], url="https://x.example/check")
        page.evaluate = lambda script: (
            {"title": "Security check", "url": page.url,
             "text": "Verify you are human before continuing.",
             "buttons": [], "links": []} if "buttons" in script else [])
        out = self.go(page, "Open my account",
                      '{"action": "done", "value": "should not get here"}')
        self.assertEqual(out["state"], webtask.HUMAN_CHECK)
        self.assertIn("cannot answer that one for you", out["say"])
        self.assertEqual(page.did, [("goto", "https://x.example/form")])


class WhatHeSaidYesToIsTheROUTE(WebTaskCase):
    """`policy.request` is idempotent on the approval id. Keyed on the run
    alone, a second run of the same goal — a different route, a different
    button — inherits the yes he gave the first one and presses it."""

    def form(self, label):
        return FakePage([field("#fn", "First name *", required=True)],
                        [{"selector": "#go", "text": label}])

    def test_a_different_route_gets_a_different_approval(self):
        first = self.go(self.form("Submit application"), "Apply for me",
                        '{"action": "click", "selector": "#go"}')
        page = self.form("Submit application")
        page._fields.append(field("#ln", "Last name *", required=True))
        second = webtask.run(
            "Apply for me", start_url="https://x.example/form", budget=4,
            think=self.brain('{"action": "click", "selector": "#go"}'),
            session=FakeSession(page))
        self.assertEqual(first["id"], second["id"])
        self.assertNotEqual(first["approval"], second["approval"])

    def test_a_yes_for_one_route_cannot_press_another(self):
        out = self.go(self.form("Submit application"), "Apply for me",
                      '{"action": "click", "selector": "#go"}')
        policy.decide(out["approval"], "APPROVED", via="phone")
        record = webtask.load_run(out["id"])
        record["typed"].append({"action": "type", "selector": "#x",
                                "value": "something he never saw"})
        webtask.stateio.write_json_atomic(webtask._record_path(out["id"]), record)
        with self.assertRaises(webtask.WebTaskError) as caught:
            webtask.commit(out["id"], presser=lambda r: {})
        self.assertIn("different route", str(caught.exception))

    def test_the_SAME_route_run_twice_cannot_press_twice_on_one_yes(self):
        """The digest stops a different route inheriting his yes; it does
        not stop the same one. A second run overwrites the record with a
        fresh AWAITING_YOU while the old approval is still APPROVED — and
        that is a second application to the same job, pressed silently."""
        first = self.go(self.form("Submit application"), "Apply for me",
                        '{"action": "click", "selector": "#go"}')
        policy.decide(first["approval"], "APPROVED", via="phone")
        webtask.commit(first["id"], presser=lambda r: {"url": "x"})
        again = self.go(self.form("Submit application"), "Apply for me",
                        '{"action": "click", "selector": "#go"}')
        self.assertEqual(again["approval"], first["approval"])   # same route
        self.assertEqual(policy.load(again["approval"])["state"], "APPROVED")
        pressed = []
        with self.assertRaises(webtask.WebTaskError) as caught:
            webtask.commit(again["id"], presser=lambda r: pressed.append(1))
        self.assertIn("already been used", str(caught.exception))
        self.assertEqual(pressed, [])

    def test_a_press_that_FAILED_also_needs_a_fresh_yes(self):
        """Otherwise a broken press becomes a retry loop nobody agreed to."""
        out = self.go(self.form("Submit application"), "Apply for me",
                      '{"action": "click", "selector": "#go"}')
        policy.decide(out["approval"], "APPROVED", via="phone")

        def boom(record):
            raise RuntimeError("the site fell over")
        with self.assertRaises(RuntimeError):
            webtask.commit(out["id"], presser=boom)
        record = webtask.load_run(out["id"])
        record["state"] = webtask.COMMIT
        webtask.stateio.write_json_atomic(webtask._record_path(out["id"]), record)
        with self.assertRaises(webtask.WebTaskError) as caught:
            webtask.commit(out["id"], presser=lambda r: {})
        self.assertIn("already been used", str(caught.exception))

    def test_two_different_goals_are_two_different_runs(self):
        """The slug alone collided: the same sentence ending in Stripe and
        ending in Databricks share their first 28 characters, so the second
        run overwrote the first one's record and left a pending approval
        pointing at a route that no longer existed."""
        one = self.go(self.form("Submit application"),
                      "Apply for the senior systems engineer job at Stripe",
                      '{"action": "click", "selector": "#go"}')
        two = self.go(self.form("Submit application"),
                      "Apply for the senior systems engineer job at Databricks",
                      '{"action": "click", "selector": "#go"}')
        self.assertNotEqual(one["id"], two["id"])
        self.assertEqual(webtask.load_run(one["id"])["goal"], one["goal"])

    def test_the_same_goal_on_the_same_page_is_the_same_run(self):
        one = self.go(self.form("Submit application"), "Apply for me",
                      '{"action": "click", "selector": "#go"}')
        two = self.go(self.form("Submit application"), "Apply for me",
                      '{"action": "click", "selector": "#go"}')
        self.assertEqual(one["id"], two["id"])

    def test_navigation_is_part_of_the_route(self):
        """Without the goto in it, the press replays onto the page he was
        given rather than the one she navigated to."""
        page = FakePage([field("#fn", "First name *", required=True)],
                        [{"selector": "#go", "text": "Submit application"}])
        out = webtask.run(
            "Apply on the other page", start_url="https://x.example/form",
            budget=4,
            think=self.brain(
                '{"action": "goto", "value": "https://x.example/real"}',
                '{"action": "click", "selector": "#go"}'),
            session=FakeSession(page))
        self.assertEqual(out["state"], webtask.COMMIT, out.get("say"))
        self.assertIn({"action": "goto", "selector": "",
                       "value": "https://x.example/real"}, out["typed"])
        self.assertEqual(out["replay_from"], "https://x.example/form")


class HeTapsApproveAndSomethingActuallyHAPPENS(WebTaskCase):
    """The whole capability used to end in a question nobody could answer.

    She drives the site, stops at the button, says *"confirm it and I will
    press it"* — and the only thing on earth that could press it was
    `python -m aletheia.webtask commit` typed at a terminal. He taps
    Approve on his phone and nothing happens, forever. That is the exact
    shape of defect this repo calls building a capability and leaving it
    unwired, hiding inside a feature that otherwise works.
    """

    def waiting(self):
        page = FakePage([field("#fn", "First name *", required=True)],
                        [{"selector": "#go", "text": "Submit application"}])
        return self.go(page, "Apply for me",
                       '{"action": "click", "selector": "#go"}')

    def test_an_unapproved_run_is_left_alone_by_the_beat(self):
        from aletheia import runtime
        out = self.waiting()
        with mock.patch.object(webtask, "_press") as press:
            self.assertEqual(runtime.press_approved_web_tasks(), [])
        press.assert_not_called()
        self.assertEqual(policy.load(out["approval"])["state"], "PENDING")

    def test_approving_it_presses_it_on_the_next_beat(self):
        from aletheia import notifications, runtime
        out = self.waiting()
        policy.decide(out["approval"], "APPROVED", via="phone")
        with mock.patch.object(webtask, "_press",
                               return_value={"url": "https://x.example/done",
                                             "evidence": "Thank you"}):
            pressed = runtime.press_approved_web_tasks()
        self.assertEqual([p["web_task"] for p in pressed], [out["id"]])
        self.assertEqual(webtask.load_run(out["id"])["state"], "COMMITTED")
        self.assertTrue(any("Pressed" in n["title"]
                            for n in notifications.all_notifications()))

    def test_it_is_pressed_once_however_many_beats_run(self):
        from aletheia import runtime
        out = self.waiting()
        policy.decide(out["approval"], "APPROVED", via="phone")
        with mock.patch.object(webtask, "_press",
                               return_value={"url": "x"}) as press:
            for _ in range(4):
                runtime.press_approved_web_tasks()
        self.assertEqual(press.call_count, 1)

    def test_a_failure_tells_him_rather_than_retrying(self):
        from aletheia import notifications, runtime
        out = self.waiting()
        policy.decide(out["approval"], "APPROVED", via="phone")
        with mock.patch.object(webtask, "_press",
                               side_effect=RuntimeError("the page went away")):
            self.assertEqual(runtime.press_approved_web_tasks(), [])
        self.assertIn("I could not press it",
                      [n["title"] for n in notifications.all_notifications()])
        self.assertEqual(webtask.load_run(out["id"])["state"], "FAILED")


class ARefusalIsNotADeadEnd(WebTaskCase):
    """The site handed the form back saying "phone must be 10 digits with
    no punctuation". She reported it as done, and when that was fixed she
    said *"read what it wants and I will fix it and try again"* — with
    nothing behind it, which is a promise, not a capability. Three
    separate defects stood between her and keeping it."""

    def waiting(self, extra=()):
        page = FakePage([field("#fn", "First name *", required=True),
                         field("#ph", "Phone *", required=True), *extra],
                        [{"selector": "#go", "text": "Submit application"}])
        out = self.go(page, "Apply for me",
                      '{"action": "click", "selector": "#go"}')
        return page, out

    def refuse(self, out, said="There was a problem with your application. "
                              "Phone number must be 10 digits."):
        policy.decide(out["approval"], "APPROVED", via="phone")
        return webtask.commit(out["id"], presser=lambda r: {
            "url": "https://x.example/form", "evidence": said,
            **webtask.browse.read_outcome(said)})

    def test_a_refused_press_is_its_own_state_not_COMMITTED(self):
        _, out = self.waiting()
        done = self.refuse(out)
        self.assertEqual(done["state"], "REJECTED")
        self.assertEqual(done["result"]["verdict"], "rejected")
        self.assertIn("handed it back", done["say"])

    def test_the_beat_says_it_would_not_go_through(self):
        from aletheia import notifications, runtime
        _, out = self.waiting()
        policy.decide(out["approval"], "APPROVED", via="phone")
        said = "There was a problem with your application."
        with mock.patch.object(webtask, "_press", return_value={
                "url": "x", "evidence": said,
                **webtask.browse.read_outcome(said)}):
            pressed = runtime.press_approved_web_tasks()
        self.assertEqual([p["verdict"] for p in pressed], ["rejected"])
        titles = [n["title"] for n in notifications.all_notifications()]
        self.assertTrue(any("would not go through" in t for t in titles), titles)
        self.assertFalse(any(t.startswith("Done") for t in titles), titles)

    def test_only_a_REFUSED_run_may_be_tried_again(self):
        """A refusal means nothing was accepted, so nothing can be
        duplicated. Anything else could be a second application."""
        _, out = self.waiting()
        with self.assertRaises(webtask.WebTaskError) as caught:
            webtask.retry(out["id"])
        self.assertIn("only a run the site refused", str(caught.exception))

    def test_the_retry_carries_what_the_site_SAID(self):
        """Without it a retry is the same attempt again, which is not a
        retry, it is a loop with extra steps."""
        _, out = self.waiting()
        self.refuse(out)
        seen = {}

        def think(system, prompt, **kw):
            seen.update(json.loads(prompt))
            return '{"action": "done", "value": "ok"}'
        page = FakePage([field("#fn", "First name *", required=True)],
                        [{"selector": "#go", "text": "Submit application"}])
        again = webtask.retry(out["id"], think=think, session=FakeSession(page))
        self.assertIn("Phone number must be 10 digits",
                      seen["the_site_REFUSED_this_last_time_and_said"])
        self.assertNotEqual(again["id"], out["id"])
        self.assertEqual(again["attempt"], 2)

    def test_a_retry_still_needs_a_FRESH_yes(self):
        _, out = self.waiting()
        self.refuse(out)
        page = FakePage([field("#fn", "First name *", required=True, value="x"),
                         field("#ph", "Phone *", required=True, value="x")],
                        [{"selector": "#go", "text": "Submit application"}])
        again = webtask.run(out["goal"], start_url="https://x.example/form",
                            budget=3, run_id=out["id"] + "--try2", attempt=2,
                            think=self.brain(
                                '{"action": "click", "selector": "#go"}'),
                            session=FakeSession(page))
        self.assertEqual(again["state"], webtask.COMMIT)
        self.assertEqual(policy.load(again["approval"])["state"], "PENDING")


class TheSameFactPunctuatedTheirWay(WebTaskCase):
    """"10 digits, no punctuation" is asking for his phone number, not for
    a new one — and the gate refused it, so a rejection he could have
    fixed came back as a question he had already answered."""

    def test_his_number_without_its_punctuation_is_still_his(self):
        allowed = {"(512) 555-0134"}
        for shape in ("5125550134", "512-555-0134", "512.555.0134"):
            with self.subTest(shape=shape):
                self.assertTrue(webtask._value_is_his(shape, allowed, []))

    def test_a_DIFFERENT_number_is_still_refused(self):
        self.assertFalse(
            webtask._value_is_his("5125550135", {"(512) 555-0134"}, []))

    def test_what_she_knows_fills_blanks_and_does_not_argue(self):
        """The site said reformat it, the model obeyed, and the
        deterministic pass put his punctuated number straight back on the
        next round — the two of them overwrote each other until the
        budget ran out."""
        page = FakePage([field("#ph", "Phone", required=True)],
                        [{"selector": "#go", "text": "Next"}])
        out = self.go(page, "Apply for me",
                      '{"action": "fill", "values": {"#ph": "5125550134"}}',
                      '{"action": "done", "value": "ok"}', budget=4)
        self.assertEqual(out["state"], webtask.DONE, out.get("say"))
        typed = [d for d in page.did if d[0] == "fill"]
        self.assertEqual(typed[0], ("fill", "#ph", "(512) 555-0134"))
        self.assertEqual(typed[-1], ("fill", "#ph", "5125550134"))
        self.assertEqual(len(typed), 2, "and then it stops arguing")

    def test_a_third_write_to_one_field_is_refused(self):
        """The guard is still there: a model that rephrases its own essay
        three times burns the budget and changes nothing."""
        page = FakePage([field("#why", "Why? *", tag="textarea", required=True)],
                        [])
        out = self.go(page, "Apply for me. For why say: I build systems.",
                      '{"action": "fill", "values": {"#why": "I build systems."}}',
                      '{"action": "fill", "values": {"#why": "I build systems"}}',
                      '{"action": "fill", "values": {"#why": "I build systems!"}}',
                      '{"action": "done", "value": "ok"}', budget=6)
        self.assertEqual(len([d for d in page.did if d[0] == "fill"]), 2)


class GoingRoundInCirclesIsNotThinking(WebTaskCase):
    def test_rounds_that_change_nothing_end_the_run_with_a_question(self):
        """Eleven rounds of "nothing left to fill" and a run that reported
        OUT_OF_STEPS with no idea why."""
        page = FakePage([field("#fn", "First name", value="Caleb")], [])
        out = self.go(page, "Do the thing",
                      *['{"action": "fill", "values": {}}'] * 8, budget=8)
        self.assertEqual(out["state"], webtask.ASK)
        self.assertIn("round in circles", out["say"])
        self.assertLess(len(out["steps"]), 8)


class SheDoesNotAskHimTheSameThingTwice(WebTaskCase):
    """The two ways a run stops short — "I ran out of steps" and "only you
    can answer this" — ended the same way: the page closed with the run
    and everything already typed went with it. Starting again meant
    watching her fill the same eleven fields and ask the same three
    questions. Every real application has questions only he can answer,
    so that was not an edge case, it was the normal path."""

    def form(self, values=()):
        page = FakePage([field("#fn", "First name *", required=True),
                         field("#sal", "Desired annual salary in USD *",
                               required=True),
                         field("#how", "How did you hear about us? *",
                               required=True)],
                        [{"selector": "#go", "text": "Submit application"}])
        for selector, value in values:
            page._set(selector, value)
        return page

    def stops(self, page=None):
        return self.go(page or self.form(), "Fill in this application",
                       '{"action": "ask", "value": "What salary, and how did '
                       'you hear about us?"}')

    def test_a_run_that_stops_to_ASK_keeps_what_it_had_already_done(self):
        out = self.stops()
        self.assertEqual(out["state"], webtask.ASK)
        self.assertEqual([(t["action"], t["selector"]) for t in out["typed"]],
                         [("type", "#fn")])
        self.assertEqual(out["replay_from"], "https://x.example/form")

    def test_his_answers_are_typed_in_and_she_carries_on(self):
        out = self.stops()
        page = self.form()
        more = webtask.carry_on(
            out["id"],
            answers={"salary": "120000", "hear about us": "A friend"},
            think=self.brain('{"action": "click", "selector": "#go"}'),
            session=FakeSession(page))
        self.assertEqual(more["state"], webtask.COMMIT, more.get("say"))
        self.assertIn(("fill", "#sal", "120000"), page.did)
        self.assertIn(("fill", "#how", "A friend"), page.did)

    def test_it_puts_the_page_BACK_before_carrying_on(self):
        """Not starting again: the route is replayed first, which is what
        makes a two-page form survive being stopped on page two."""
        out = self.stops()
        page = self.form()
        webtask.carry_on(out["id"], answers={"salary": "120000"},
                         think=self.brain('{"action": "done", "value": "ok"}'),
                         session=FakeSession(page))
        self.assertEqual(page.did[:2],
                         [("goto", "https://x.example/form"),
                          ("fill", "#fn", "Caleb")])

    def test_an_answer_HE_gave_passes_the_gate_that_stops_invention(self):
        """The gate exists to stop a model inventing a fact about him, not
        to stop him supplying one. "120000" is on no profile anywhere."""
        out = self.stops()
        page = self.form()
        more = webtask.carry_on(
            out["id"], answers={"salary": "120000"},
            think=self.brain(
                '{"action": "fill", "values": {"#how": "120000"}}',
                '{"action": "done", "value": "ok"}'),
            session=FakeSession(page))
        self.assertEqual(more["state"], webtask.DONE, more.get("say"))
        self.assertIn(("fill", "#how", "120000"), page.did)

    def test_a_question_that_matches_no_field_is_SAID_not_swallowed(self):
        out = self.stops()
        more = webtask.carry_on(
            out["id"], answers={"your favourite colour": "blue"},
            think=self.brain('{"action": "done", "value": "ok"}'),
            session=FakeSession(self.form()))
        self.assertTrue(any("no field for" in step["result"]
                            for step in more["steps"]), more["steps"])

    def test_running_out_of_steps_is_picked_up_too(self):
        page = self.form()
        out = self.go(page, "Fill in this application",
                      *['{"action": "fill", "values": {}}'] * 2, budget=2)
        self.assertEqual(out["state"], webtask.BUDGET)
        self.assertIn("carry on", out["say"])
        more = webtask.carry_on(
            out["id"], think=self.brain('{"action": "done", "value": "ok"}'),
            session=FakeSession(self.form()))
        self.assertEqual(more["state"], webtask.DONE)

    def test_it_is_the_SAME_run_not_a_new_one(self):
        out = self.stops()
        more = webtask.carry_on(
            out["id"], think=self.brain('{"action": "done", "value": "ok"}'),
            session=FakeSession(self.form()))
        self.assertEqual(more["id"], out["id"])

    def test_there_is_nothing_to_carry_on_from_a_finished_run(self):
        page = self.form([("#sal", "1"), ("#how", "x")])
        out = self.go(page, "Fill in this application",
                      '{"action": "click", "selector": "#go"}')
        self.assertEqual(out["state"], webtask.COMMIT)
        with self.assertRaises(webtask.WebTaskError) as caught:
            webtask.carry_on(out["id"])
        self.assertIn("nothing waiting", str(caught.exception))

    def test_carrying_on_still_stops_at_the_button(self):
        """It is not a bypass: the same loop, the same button, the same one
        confirmation."""
        out = self.stops()
        more = webtask.carry_on(
            out["id"], answers={"salary": "1", "hear about us": "x"},
            think=self.brain('{"action": "click", "selector": "#go"}'),
            session=FakeSession(self.form()))
        self.assertEqual(more["state"], webtask.COMMIT)
        self.assertEqual(policy.load(more["approval"])["state"], "PENDING")

    def test_a_page_that_moved_on_is_said_not_crashed(self):
        out = self.stops()
        page = FakePage([], [])          # the fields are gone
        more = webtask.carry_on(
            out["id"], think=self.brain('{"action": "done", "value": "ok"}'),
            session=FakeSession(page))
        self.assertEqual(more["state"], webtask.ASK)
        self.assertIn("could not put that page back", more["say"])

    def test_a_crash_in_the_middle_is_not_a_total_loss(self):
        """The record was written once, at the end. The Core restarts
        itself on every code update and its supervisor restarts it on a
        crash, so a restart in the middle threw away eleven filled fields
        and two pages of navigation — and the only evidence it had ever
        happened was a browser that was gone."""
        page = self.form()

        def think(system, prompt, **kw):
            raise KeyboardInterrupt("the Core went down")
        with self.assertRaises(KeyboardInterrupt):
            webtask.run("Fill in this application",
                        start_url="https://x.example/form", budget=4,
                        think=think, session=FakeSession(page))
        run_id = [r["id"] for r in webtask.all_runs()][0]
        mid = webtask.load_run(run_id)
        self.assertEqual(mid["state"], "RUNNING")
        # What she had already done, on disk, mid-flight.
        self.assertEqual([t["selector"] for t in mid["typed"]], ["#fn"])

    def test_a_run_that_is_still_going_is_LEFT_ALONE(self):
        page = self.form()

        def think(system, prompt, **kw):
            raise KeyboardInterrupt("the Core went down")
        with self.assertRaises(KeyboardInterrupt):
            webtask.run("Fill in this application",
                        start_url="https://x.example/form", budget=4,
                        think=think, session=FakeSession(page))
        run_id = [r["id"] for r in webtask.all_runs()][0]
        with self.assertRaises(webtask.WebTaskError) as caught:
            webtask.carry_on(run_id)
        self.assertIn("running right now", str(caught.exception))

    def test_but_a_LEFTOVER_running_record_is_picked_up(self):
        page = self.form()

        def think(system, prompt, **kw):
            raise KeyboardInterrupt("the Core went down")
        with self.assertRaises(KeyboardInterrupt):
            webtask.run("Fill in this application",
                        start_url="https://x.example/form", budget=4,
                        think=think, session=FakeSession(page))
        run_id = [r["id"] for r in webtask.all_runs()][0]
        stale = webtask.load_run(run_id)
        stale["beat"] = "2020-01-01T00:00:00Z"
        webtask.stateio.write_json_atomic(webtask._record_path(run_id), stale)
        more = webtask.carry_on(
            run_id, think=self.brain('{"action": "done", "value": "ok"}'),
            session=FakeSession(self.form()))
        self.assertEqual(more["state"], webtask.DONE)

    def test_he_can_just_say_it(self):
        from aletheia import intercom, planner
        self.assertIn("web_task_answer", intercom.KIND_ARGS)
        self.assertIn("web_task_answer", planner.grammar_brief())


class HeCanJustSayIt(unittest.TestCase):
    def test_the_kind_exists_and_the_planner_can_see_it(self):
        from aletheia import intercom, planner
        self.assertIn("web_task", intercom.KIND_ARGS)
        self.assertIn("web_task", intercom.LOCAL_KINDS)
        self.assertIn("web_task(", planner.grammar_brief())

    def test_the_note_tells_it_to_prefer_this_over_naming_a_gap(self):
        from aletheia import intercom
        note = intercom.KIND_NOTES["web_task"]
        self.assertIn("CATCH-ALL", note)
        self.assertIn("rather than inventing a gap", note)

    def test_the_prompt_itself_says_a_website_is_never_a_gap(self):
        """A kind note is guidance; this is the rule, in the header, because
        emitting a gap for something a website does is the most common way
        this system says "I can't" about something it can do."""
        from aletheia import planner
        flat = " ".join(planner.PROMPT_HEADER.split())
        self.assertIn("BROWSER AND A MOUSE", flat)
        self.assertIn("NEVER A GAP", flat)
        self.assertIn("Only name a gap when no website could do it at all",
                      flat)


if __name__ == "__main__":
    unittest.main()
