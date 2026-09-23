"""The wall is the surface he reads from across a room, and nothing
checked that it renders what the pulse contains.

It is a PURE view of `state/pulse/latest.json` — the smarts live in the
collectors — so the only thing worth testing here is exactly that: put a
pulse in front of it and see whether the words come out. That caught the
change it was written for: `presence` began carrying `says` (the body of
a notice whose title is a category), and the page was still printing
`title`, so two reminders rendered as the word "Reminder", twice.

Real Chromium, over real HTTP, because the page fetches — `file://`
blocks that, and the page says so honestly rather than looking broken.
Skips when there is no browser, like every other browser test here: an
optional dependency's absence must never fail the suite.
"""
import functools
import http.server
import json
import re
import shutil
import tempfile
import threading
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

NOW = {
    "generated_at": "2026-09-06T22:00:00Z", "halted": False,
    "heartbeat_age_s": 2.0,
    "waiting_on_you": [{"label": "File a GitHub issue about the wall",
                        "since": "2026-09-06T21:00:00Z"}],
    "waiting_count": 1,
    "notifications": [
        {"title": "Reminder", "body": "call the dentist",
         "says": "call the dentist", "priority": "IMPORTANT",
         "at": "2026-09-06T21:55:00Z"},
        {"title": "Reminder", "body": "pick up the kids",
         "says": "pick up the kids", "priority": "IMPORTANT",
         "at": "2026-09-06T21:56:00Z"}],
    "meetings": [], "working": [], "next_appointment": None,
    "headline": "call the dentist",
}


def chromium():
    for path in Path("/opt/pw-browsers").glob("chromium-*/chrome-linux/chrome"):
        return str(path)
    return None


class TheWallCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from playwright.sync_api import sync_playwright  # noqa: F401
        except ImportError:
            raise unittest.SkipTest("playwright is not installed")
        cls.room = Path(tempfile.mkdtemp())
        shutil.copytree(REPO / "interface", cls.room / "interface")
        (cls.room / "state" / "pulse").mkdir(parents=True)
        pulse = json.loads(
            (REPO / "state" / "pulse" / "latest.json").read_text(encoding="utf-8"))
        pulse["now"] = NOW
        (cls.room / "state" / "pulse" / "latest.json").write_text(
            json.dumps(pulse), encoding="utf-8")

        class Quiet(http.server.SimpleHTTPRequestHandler):
            def log_message(self, *a):
                pass

        handler = functools.partial(Quiet, directory=str(cls.room))
        cls.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.url = f"http://127.0.0.1:{cls.srv.server_address[1]}/interface/wall.html"
        cls.body, cls.errors = cls._render()

    @classmethod
    def _render(cls):
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            kwargs = {"args": ["--no-sandbox"]}
            exe = chromium()
            if exe:
                kwargs["executable_path"] = exe
            try:
                browser = pw.chromium.launch(**kwargs)
            except Exception as exc:
                raise unittest.SkipTest(f"no chromium: {type(exc).__name__}")
            page = browser.new_page(viewport={"width": 1280, "height": 800})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(cls.url)
            page.wait_for_timeout(2000)
            body = page.inner_text("body")
            # Where a click goes: every href on the page, and the panels.
            cls.links = page.evaluate(
                "() => [...document.querySelectorAll('a[href]')].map(a => a.getAttribute('href'))")
            cls.panels = page.evaluate(
                "() => [...document.querySelectorAll('.panel')].map(p => p.dataset.repo)")
            browser.close()
        return body, errors

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, "srv"):
            cls.srv.shutdown()
        if hasattr(cls, "room"):
            shutil.rmtree(cls.room, ignore_errors=True)

    def test_the_page_runs_without_errors(self):
        self.assertEqual(self.errors, [])

    def test_it_read_the_pulse_at_all(self):
        """The failure mode this guards: a page that loads, looks fine, and
        is showing nothing."""
        self.assertNotIn("awaiting pulse", self.body)
        self.assertNotIn("NO SIGNAL", self.body)

    def test_a_notice_shows_what_it_is_about_not_its_category(self):
        """Every reminder is titled "Reminder". The page printed `title`."""
        self.assertIn("call the dentist", self.body)
        self.assertIn("pick up the kids", self.body)

    def test_both_notices_survive_to_the_screen(self):
        self.assertNotEqual(self.body.count("call the dentist"), 0)
        self.assertNotEqual(self.body.count("pick up the kids"), 0)

    def test_what_needs_him_is_named(self):
        self.assertIn("File a GitHub issue", self.body)

    # ---- everything he would click goes somewhere (2026-09-23) ------------
    def test_every_repository_on_the_wall_is_a_link_into_the_thea_page(self):
        """His words: "if I click on shorts pipeline, something should pop
        up." A panel, its node on the map and its line in the ticker all
        land on that repository's card on the Thea page."""
        self.assertTrue(self.panels, "no repository panels rendered")
        for repo in self.panels:
            with self.subTest(repo=repo):
                self.assertIn(f"thea.html#repo={repo}", self.links)

    def test_a_fault_is_a_link_to_that_fault(self):
        pulse = json.loads((REPO / "state" / "pulse" / "latest.json").read_text(encoding="utf-8"))
        for alert in pulse.get("alerts") or []:
            with self.subTest(repo=alert.get("repo")):
                self.assertIn(f"thea.html#fault={alert['repo']}", self.links)

    def test_what_is_waiting_on_him_links_to_where_he_answers_it(self):
        self.assertTrue(any(h.startswith("thea.html#need") for h in self.links), self.links)

    def test_no_link_on_the_wall_is_root_absolute(self):
        """The wall is also published on GitHub Pages under a project path,
        where "/interface/..." is a 404. The one link it used to have was."""
        for href in self.links:
            with self.subTest(href=href):
                self.assertFalse(href.startswith("/"), href)

    def test_the_wall_has_no_capability_the_thea_page_lacks(self):
        """A control on the wall would be one. Every link goes to the Thea
        page; there is no form and no POST here apart from the shared
        push-to-talk pill, which the Thea page has too."""
        for href in self.links:
            with self.subTest(href=href):
                self.assertTrue(href.startswith("thea.html"), href)
        self.assertNotIn("<form", (REPO / "interface" / "wall.html").read_text(encoding="utf-8"))

    def test_the_published_copy_carries_the_scripts_it_loads(self):
        """pages.yml copied wall.html and not voice.js, so the published
        wall requested a script that was not there."""
        wall = (REPO / "interface" / "wall.html").read_text(encoding="utf-8")
        pages = (REPO / ".github" / "workflows" / "pages.yml").read_text(encoding="utf-8")
        for script in re.findall(r'<script src="([^"]+)"', wall):
            with self.subTest(script=script):
                self.assertIn(script, pages)


if __name__ == "__main__":
    unittest.main()
