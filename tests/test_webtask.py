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
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import computer, journal, policy, profile, webtask


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

    def wait_for_load_state(self, *a, **kw):
        pass

    def inner_text(self, *a):
        return "thank you"

    def screenshot(self, **kw):
        pass

    def close(self):
        pass


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
