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

    def _approved(self, aid="browse-1"):
        policy.request(aid, "interact with the test page", "test",
                       "form is submitted", reversible=True)
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
        aid = self._approved()
        result = browse.interact(
            self.url,
            [{"action": "type", "selector": "#q", "value": "aletheia"},
             {"action": "select", "selector": "#pick", "value": "b"},
             {"action": "click", "selector": "#go"},
             {"action": "wait_for", "selector": "h1"}],
            approval_id=aid, profile=self.profile)
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

    def test_halt_blocks_even_approved_interaction(self):
        aid = self._approved("browse-4")
        policy.halt("stop", via="test")
        with self.assertRaises(policy.Halted):
            browse.interact(self.url, [{"action": "click", "selector": "#go"}],
                            approval_id=aid, profile=self.profile)


if __name__ == "__main__":
    unittest.main()
