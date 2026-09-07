"""Browser control tests — hermetic: a fixture site served on loopback, no network."""
import http.server
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from aletheia import browse, journal, policy

# Browser control is OPTIONAL (requirements-optional.txt). On a machine
# without playwright these tests SKIP — they must never fail the suite,
# because the bootstrap gates starting the Core on the suite passing and
# an optional capability's absence must not take down the required path.
# This exact chain killed a real setup on 2026-08-26: Python 3.9 + old
# pip failed the playwright install, and the throw meant no Core at all.
BROWSER_OK, BROWSER_WHY = browse.available()
needs_browser = unittest.skipUnless(BROWSER_OK, f"browser control absent: {BROWSER_WHY}")


class TestHonestyWithoutBrowser(unittest.TestCase):
    """The one test that always runs: absence is reported, never crashed."""

    def test_available_returns_verdict_and_actionable_reason(self):
        ok, reason = browse.available()
        self.assertIsInstance(ok, bool)
        self.assertTrue(reason.strip())
        if not ok:
            self.assertTrue("playwright" in reason.lower() or "install" in reason.lower(),
                            f"reason must name the fix: {reason!r}")

FIXTURE = """<!doctype html><title>Aletheia test page</title>
<body>
  <h1>Hello from the fixture</h1>
  <p>The quick brown fox.</p>
  <a href="/other.html">another page</a>
  <form action="/other.html" method="get">
    <input id="q" name="q">
    <select id="pick" name="pick">
      <option value="a">A</option><option value="b">B</option>
    </select>
    <button id="go" type="submit">Go</button>
  </form>
</body>"""
OTHER = "<!doctype html><title>Second page</title><body><h1>You made it</h1></body>"


class BrowseCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        root = Path(cls.tmp.name)
        (root / "index.html").write_text(FIXTURE, encoding="utf-8")
        (root / "other.html").write_text(OTHER, encoding="utf-8")

        class Quiet(http.server.SimpleHTTPRequestHandler):
            def log_message(self, *a):  # keep the test output readable
                pass

        handler = lambda *a, **k: Quiet(*a, directory=str(root), **k)
        cls.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        cls.port = cls.httpd.server_address[1]
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        cls.url = f"http://127.0.0.1:{cls.port}/index.html"

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.tmp.cleanup()

    def setUp(self):
        self.state = tempfile.TemporaryDirectory()
        self.addCleanup(self.state.cleanup)
        base = Path(self.state.name)
        self.profile = base / "profile"
        for target, attr in ((journal, "JOURNAL_PATH"), (policy, "APPROVALS_DIR"),
                             (policy, "HALT_PATH")):
            p = mock.patch.object(target, attr, base / attr.lower())
            p.start(); self.addCleanup(p.stop)

    CLICK = [{"action": "click", "selector": "#go"}]

    def _approved(self, aid="browse-1", steps=None, url=None):
        """An approval BOUND to exactly this page and plan — what
        browse.interact has required since the 2026-09-03 fix."""
        policy.request(aid, browse.approval_action(url or self.url,
                                                   self.CLICK if steps is None else steps),
                       "test", "form is submitted", reversible=True)
        policy.decide(aid, "APPROVED", via="test")
        return aid


@needs_browser
class TestAvailability(BrowseCase):
    def test_reports_installed(self):
        """INSTALLED, not ready — `available()` proves an import and a file
        on disk. Whether the browser can reach anything is `reachable()`."""
        ok, reason = browse.available()
        self.assertTrue(ok, reason)
        self.assertEqual(reason, "installed")

    def test_degrades_honestly_without_playwright(self):
        import builtins
        real = builtins.__import__

        def blocked(name, *a, **k):
            if name.startswith("playwright"):
                raise ImportError("no playwright")
            return real(name, *a, **k)

        with mock.patch.object(builtins, "__import__", blocked):
            ok, reason = browse.available()
        self.assertFalse(ok)
        self.assertIn("playwright", reason)


@needs_browser
class TestRead(BrowseCase):
    def test_reads_title_text_and_links(self):
        page = browse.read_page(self.url, profile=self.profile)
        self.assertEqual(page["title"], "Aletheia test page")
        self.assertIn("quick brown fox", page["text"])
        self.assertTrue(any(l["href"].endswith("other.html") for l in page["links"]))

    def test_read_is_journaled(self):
        browse.read_page(self.url, profile=self.profile)
        self.assertEqual(journal.entries()[-1]["subject"], "browser:read")

    def test_halt_blocks_reading(self):
        policy.halt("stop everything", via="test")
        with self.assertRaises(policy.Halted):
            browse.read_page(self.url, profile=self.profile)

    def test_screenshot_writes_a_real_png(self):
        out = Path(self.state.name) / "shot.png"
        browse.screenshot(self.url, out, profile=self.profile)
        self.assertTrue(out.exists())
        self.assertEqual(out.read_bytes()[:4], b"\x89PNG")


@needs_browser
class TestInteract(BrowseCase):
    def test_unapproved_interaction_refused_before_opening_a_browser(self):
        with self.assertRaises(policy.Halted):
            browse.interact(self.url, [{"action": "click", "selector": "#go"}],
                            approval_id="never-approved", profile=self.profile)

    def test_denied_approval_is_not_approval(self):
        policy.request("browse-2", "x", "y", "z", reversible=True)
        policy.decide("browse-2", "DENIED", via="test")
        with self.assertRaises(policy.Halted):
            browse.interact(self.url, [{"action": "click", "selector": "#go"}],
                            approval_id="browse-2", profile=self.profile)

    def test_malformed_steps_refused_before_approval_or_browser(self):
        with self.assertRaises(ValueError):
            browse.interact(self.url, [{"action": "sudo", "selector": "#go"}],
                            approval_id="anything", profile=self.profile)
        with self.assertRaises(ValueError):
            browse.interact(self.url, [{"action": "type", "selector": "#q"}],
                            approval_id="anything", profile=self.profile)

    def test_approved_interaction_fills_and_submits(self):
        steps = [{"action": "type", "selector": "#q", "value": "aletheia"},
                 {"action": "select", "selector": "#pick", "value": "b"},
                 {"action": "click", "selector": "#go"},
                 {"action": "wait_for", "selector": "h1"}]
        aid = self._approved(steps=steps)
        result = browse.interact(
            self.url, steps, approval_id=aid, profile=self.profile)
        self.assertIn("q=aletheia", result["url"])
        self.assertIn("pick=b", result["url"])
        self.assertIn("You made it", result["text"])
        self.assertEqual(len(result["steps_done"]), 4)

    def test_interaction_names_its_approval_in_the_journal(self):
        aid = self._approved("browse-3")
        browse.interact(self.url, [{"action": "click", "selector": "#go"}],
                        approval_id=aid, profile=self.profile)
        entry = journal.entries()[-1]
        self.assertEqual(entry["subject"], "browser:interact")
        self.assertIn("browse-3", entry["text"])

    def test_an_approval_for_another_plan_does_not_authorize_this_one(self):
        """The confused deputy the 2026-09-03 review found: before the fix an
        approval to click "Next" here authorized "Place order" anywhere."""
        aid = self._approved("browse-5", steps=[{"action": "click", "selector": "#harmless"}])
        with self.assertRaises(policy.Halted) as caught:
            browse.interact(self.url, [{"action": "click", "selector": "#go"}],
                            approval_id=aid, profile=self.profile)
        self.assertIn("not bound to this exact page and plan", str(caught.exception))

    def test_the_same_plan_on_another_url_is_refused(self):
        aid = self._approved("browse-6", url="https://elsewhere.example/")
        with self.assertRaises(policy.Halted):
            browse.interact(self.url, self.CLICK, approval_id=aid, profile=self.profile)

    def test_an_unbound_prose_approval_is_refused(self):
        policy.request("browse-7", "interact with the test page", "t", "c", reversible=True)
        policy.decide("browse-7", "APPROVED", via="test")
        with self.assertRaises(policy.Halted):
            browse.interact(self.url, self.CLICK, approval_id="browse-7",
                            profile=self.profile)

    def test_halt_blocks_even_approved_interaction(self):
        aid = self._approved("browse-4")
        policy.halt("stop", via="test")
        with self.assertRaises(policy.Halted):
            browse.interact(self.url, [{"action": "click", "selector": "#go"}],
                            approval_id=aid, profile=self.profile)


class ANetworkThatWantsAProxy(unittest.TestCase):
    """Chromium does not read HTTPS_PROXY on its own.

    On a network that requires one — a corporate network, a managed
    runner — every page came back ERR_CONNECTION_RESET while `curl` on
    the same machine was fine, and nothing said why. This only routes the
    traffic: certificate verification stays exactly as strict, because
    the answer to a proxy is never to stop checking who you are talking
    to.
    """

    def test_no_proxy_configured_means_no_proxy_argument(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            self.assertIsNone(browse._proxy_from_environment())

    def test_the_standard_variables_are_honoured(self):
        for name in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy"):
            with self.subTest(name=name):
                with mock.patch.dict("os.environ", {name: "http://127.0.0.1:8080"},
                                     clear=True):
                    self.assertEqual(browse._proxy_from_environment(),
                                     {"server": "http://127.0.0.1:8080"})

    def test_https_wins_over_http_and_bypass_is_carried(self):
        with mock.patch.dict("os.environ",
                             {"HTTP_PROXY": "http://wrong:1",
                              "HTTPS_PROXY": "http://right:2",
                              "NO_PROXY": "localhost,127.0.0.1"}, clear=True):
            self.assertEqual(browse._proxy_from_environment(),
                             {"server": "http://right:2",
                              "bypass": "localhost,127.0.0.1"})

    def test_it_never_touches_certificate_verification(self):
        source = (Path(browse.__file__)).read_text(encoding="utf-8")
        for weakening in ("ignore_https_errors", "--ignore-certificate-errors",
                          "ignoreHTTPSErrors"):
            self.assertNotIn(weakening, source,
                             "a proxy is never a reason to stop checking certificates")


class DidThatActuallyWork(unittest.TestCase):
    """A press is an action; whether the site accepted it is a different
    question, and the only honest source is what the page says next.

    She pressed Submit on a form whose phone number the site did not
    like, got "There was a problem with your application" back, and
    reported it as done — "command executed" as "goal achieved", which is
    the one thing the playbook names outright (§30)."""

    def test_a_thank_you_is_a_confirmation(self):
        self.assertEqual(
            browse.read_outcome("Thank you. Your application has been received."
                                )["verdict"], "confirmed")

    def test_the_PAST_TENSE_of_the_button_he_pressed_is_a_confirmation(self):
        """A cancellation does not confirm itself with "thank you for
        applying". It says "your membership has been cancelled", and the
        first version could not believe that sentence — so a subscription
        that really was cancelled stayed marked CANCEL_REQUESTED with a
        note saying the merchant had not confirmed."""
        for body, did in (("Your membership has been cancelled.",
                           "Cancel my membership"),
                          ("You have been unsubscribed.", "Unsubscribe"),
                          ("Your booking is confirmed.", "Book appointment"),
                          ("Your account is closed.", "Close my account")):
            with self.subTest(did=did):
                self.assertEqual(browse.read_outcome(body, did=did)["verdict"],
                                 "confirmed", body)

    def test_that_signal_YIELDS_to_a_refusal(self):
        """"Your cancellation could not be completed" contains the word
        and is the opposite of a cancellation."""
        self.assertEqual(
            browse.read_outcome("Your cancellation could not be completed.",
                                did="Cancel my membership")["verdict"],
            "rejected")

    def test_the_wrong_past_tense_proves_nothing(self):
        self.assertEqual(
            browse.read_outcome("Your booking is confirmed.",
                                did="Submit application")["verdict"],
            "submitted, unconfirmed")

    def test_a_form_handed_back_is_a_REFUSAL_not_silence(self):
        out = browse.read_outcome(
            "There was a problem with your application.\n"
            "Phone number must be 10 digits with no punctuation.")
        self.assertEqual(out["verdict"], "rejected")
        self.assertIn("Nothing was accepted", out["note"])

    def test_the_form_still_being_there_is_a_refusal_on_its_own(self):
        """Some sites say nothing at all and simply do not move."""
        self.assertEqual(
            browse.read_outcome("Apply now", form_still_there=True)["verdict"],
            "rejected")

    def test_a_page_that_says_neither_is_UNCONFIRMED_never_done(self):
        out = browse.read_outcome("Step 2 of 3")
        self.assertEqual(out["verdict"], "submitted, unconfirmed")
        self.assertIn("did not say it was received", out["note"])

    def test_a_confirmation_wins_over_a_stray_refusal_word(self):
        """A thank-you page with the word "error" in its footer is still a
        thank-you page."""
        self.assertEqual(
            browse.read_outcome("Thanks for applying. Report an error here."
                                )["verdict"], "confirmed")

    def test_both_engines_read_it_from_HERE(self):
        """Two copies of "did that work?" drift, and this is the answer
        that matters most in the system."""
        from aletheia import apply_run, webtask
        self.assertIs(apply_run.CONFIRMED_WORDS, browse.CONFIRMED_WORDS)
        for module in (apply_run, webtask):
            source = Path(module.__file__).read_text(encoding="utf-8")
            self.assertIn("read_outcome", source)
            self.assertNotIn("CONFIRMED_WORDS = (", source)




class InstalledIsNotWorkingCase(unittest.TestCase):
    """`available()` proves an import and a file on disk. That is not an
    answer to "can the browser reach a page", and it was being read as one.

    Found live 2026-09-06: in a sandbox whose proxy drops browser tunnels,
    Chromium launches perfectly and every `goto` dies with
    ERR_CONNECTION_RESET — while `setup.audit`, whose whole promise is
    "checked live rather than assumed", reported the browser as ready.
    Everything downstream would then have failed on the first real ask
    with the audit still saying it was fine.
    """

    def setUp(self):
        browse._REACHABLE_CACHE.clear()
        self.addCleanup(browse._REACHABLE_CACHE.clear)

    def session(self, goto):
        """A stand-in browser whose `goto` does whatever the test wants."""
        page = mock.MagicMock()
        page.goto.side_effect = goto
        page.title.return_value = "Example Domain"
        ctx = mock.MagicMock()
        ctx.new_page.return_value = page
        ctx.__enter__ = lambda self_: ctx
        ctx.__exit__ = lambda self_, *a: False
        return mock.patch.object(browse, "_Session", lambda *a, **k: ctx)

    def test_available_no_longer_claims_readiness_it_cannot_know(self):
        ok, why = browse.available()
        if ok:
            self.assertEqual(why, "installed")
            self.assertNotIn("ready", why)

    def test_a_browser_that_cannot_load_a_page_is_reported_as_such(self):
        with mock.patch.object(browse, "available", lambda: (True, "installed")), \
             self.session(goto=RuntimeError(
                 "Page.goto: net::ERR_CONNECTION_RESET at https://example.com/")):
            ok, why = browse.reachable()
        self.assertFalse(ok)
        # The real network error, because ERR_CONNECTION_RESET, a proxy
        # failure and a timeout have three different fixes and a class
        # name has none.
        self.assertIn("ERR_CONNECTION_RESET", why)

    def test_a_working_browser_says_what_it_loaded(self):
        with mock.patch.object(browse, "available", lambda: (True, "installed")), \
             self.session(goto=None):
            ok, why = browse.reachable()
        self.assertTrue(ok)
        self.assertIn("example.com", why)

    def test_no_browser_at_all_is_not_dressed_up_as_a_network_problem(self):
        with mock.patch.object(browse, "available",
                               lambda: (False, "playwright is not installed")):
            ok, why = browse.reachable()
        self.assertFalse(ok)
        self.assertIn("playwright", why)

    def test_the_proof_is_cached_because_it_costs_a_browser_launch(self):
        calls = []

        def counted(*a, **k):
            calls.append(1)
            raise RuntimeError("boom")

        with mock.patch.object(browse, "available", lambda: (True, "installed")), \
             mock.patch.object(browse, "_Session", counted):
            browse.reachable()
            browse.reachable()
        self.assertEqual(len(calls), 1)
        with mock.patch.object(browse, "available", lambda: (True, "installed")), \
             mock.patch.object(browse, "_Session", counted):
            browse.reachable(fresh=True)
        self.assertEqual(len(calls), 2, "fresh=True must re-prove it")

    def test_the_setup_audit_asks_the_proving_question(self):
        """The audit is what tells him what is ready. It must not be the
        thing that says a dead browser is fine."""
        from aletheia import setup
        with mock.patch.object(browse, "reachable",
                               lambda *a, **k: (False, "could not load")), \
             mock.patch.object(browse, "available", lambda: (True, "installed")):
            state, detail = setup._browser_pages()
        self.assertNotEqual(state, setup.OK)
        self.assertIn("could not load", detail)
        with mock.patch.object(browse, "reachable",
                               lambda *a, **k: (True, "loaded https://example.com")):
            state, _detail = setup._browser_pages()
        self.assertEqual(state, setup.OK)


if __name__ == "__main__":
    unittest.main()
