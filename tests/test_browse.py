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
    def test_reports_ready(self):
        ok, reason = browse.available()
        self.assertTrue(ok, reason)

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


if __name__ == "__main__":
    unittest.main()
