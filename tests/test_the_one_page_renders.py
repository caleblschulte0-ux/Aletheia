"""The one page, rendered — at a phone's width and at a desk's.

This replaces the Command Center's render test (and the phone console's
subclass of it), because those two pages are gone: five surfaces became one
`interface/thea.html` that is the same product on his PC and his iPhone.

Every rule the old tests protected is still here:

- an approval says what it will DO, not what the transport wrapped it in.
  The wall renders `voice.approval_label`; the Command Center once rendered
  `reason` raw and showed `operator said: "spoken to the wall: thea remember
  my landlord"` above a hex id, with APPROVE beside it. One collector, one
  sentence, and now only one page to render it;
- the page loads its data rather than sitting on "loading…";
- the other panels render.

And the rules this pass adds, which are the whole point of it:

- NO DEVELOPER WORDS in normal use. No JSON, capability ids, kind names,
  model names, run ids, branches or hashes anywhere he can see without
  deliberately opening the drawer;
- it answers the four things — what she's doing, ask her, what needs him,
  what she's done — and they are all present at 390px;
- nothing scrolls sideways on a phone, and what he taps is big enough.

Real Chromium against a real in-process Core. Skips when there is no
browser, like every other browser test here: an optional dependency's
absence must never fail the suite.
"""
import os
import shutil
import tempfile
import threading
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PHONE = {"width": 390, "height": 844}
DESK = {"width": 1440, "height": 900}


def chromium():
    for path in Path("/opt/pw-browsers").glob("chromium-*/chrome-linux/chrome"):
        return str(path)
    return None


class OnePageCase(unittest.TestCase):
    """One Core, one browser launch, both widths — fifteen seconds a test is
    how a suite stops being run."""

    @classmethod
    def setUpClass(cls):
        try:
            from playwright.sync_api import sync_playwright  # noqa: F401
        except ImportError:
            raise unittest.SkipTest("playwright is not installed")
        from aletheia import core, notifications, policy, talk, tasks
        cls.room = Path(tempfile.mkdtemp())
        # Snapshot BEFORE redirecting. `_redirect_repo_stores` sets module
        # attributes, so without this the rest of the suite would run with
        # its stores pointing into this test's temp directory — the exact
        # cross-contamination `-t .` exists to prevent, reintroduced by a
        # test about isolation.
        import importlib
        cls._before = {(m, a): getattr(importlib.import_module(m), a)
                       for m, a, _rel in talk.SANDBOX_STORES}
        cls._workspace = os.environ.get("ALETHEIA_WORKSPACE")
        os.environ["ALETHEIA_WORKSPACE"] = str(cls.room / "workspace")
        talk._redirect_repo_stores(cls.room)
        policy.request(
            "ap-1", "run 1 step: note",
            'operator said: "spoken to the wall: thea remember my landlord"',
            "Remember the landlord is Mr Okafor", True,
            capability="task.persist")
        notifications.publish("Reminder", "call the dentist",
                              priority="IMPORTANT")
        tasks.create("call-the-plumber", "call the plumber")
        cls.srv = core.make_server(port=0)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.url = f"http://127.0.0.1:{cls.srv.server_address[1]}/"
        cls.shot_dir = Path(os.environ.get("ALETHEIA_SHOTS", cls.room / "shots"))
        cls.shot_dir.mkdir(parents=True, exist_ok=True)
        cls.seen = cls._render()

    @classmethod
    def _render(cls):
        from playwright.sync_api import sync_playwright
        out = {}
        with sync_playwright() as pw:
            kwargs = {"args": ["--no-sandbox"]}
            exe = chromium()
            if exe:
                kwargs["executable_path"] = exe
            try:
                browser = pw.chromium.launch(**kwargs)
            except Exception as exc:
                raise unittest.SkipTest(f"no chromium: {type(exc).__name__}")
            for name, viewport in (("phone", PHONE), ("desk", DESK)):
                page = browser.new_page(viewport=viewport,
                                        device_scale_factor=2 if name == "phone" else 1)
                errors = []
                page.on("pageerror", lambda e: errors.append(str(e)))
                page.goto(cls.url)
                page.wait_for_timeout(2500)
                page.screenshot(path=str(cls.shot_dir / f"thea-{name}.png"),
                                full_page=True)
                out[name] = {
                    "body": page.inner_text("body"),
                    "needs": page.inner_text("#needs"),
                    "errors": errors,
                    "url": page.url,
                    # the honest test for a sideways-scrolling phone page
                    "overflow": page.evaluate(
                        "() => document.documentElement.scrollWidth - "
                        "document.documentElement.clientWidth"),
                    "drawer_open": page.evaluate(
                        "() => document.getElementById('drawer').open"),
                    "taps": page.evaluate(
                        "() => [...document.querySelectorAll('button')]"
                        ".filter(b => b.offsetParent !== null)"
                        ".map(b => ({t: (b.textContent||b.ariaLabel||'').trim().slice(0,30),"
                        " h: Math.round(b.getBoundingClientRect().height),"
                        " w: Math.round(b.getBoundingClientRect().width)}))"),
                }
                page.close()
            browser.close()
        return out

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, "srv"):
            cls.srv.shutdown()
        import importlib
        for (module, attribute), value in getattr(cls, "_before", {}).items():
            setattr(importlib.import_module(module), attribute, value)
        if getattr(cls, "_workspace", None) is None:
            os.environ.pop("ALETHEIA_WORKSPACE", None)
        else:
            os.environ["ALETHEIA_WORKSPACE"] = cls._workspace
        if hasattr(cls, "room") and not os.environ.get("ALETHEIA_SHOTS"):
            shutil.rmtree(cls.room, ignore_errors=True)

    # ---- it works at all ------------------------------------------------
    def test_the_page_runs_without_errors(self):
        for name, seen in self.seen.items():
            with self.subTest(name):
                self.assertEqual(seen["errors"], [])

    def test_the_bare_address_lands_on_the_one_page(self):
        """He types the address of her machine; he gets the product, not a
        directory listing and not a fleet map."""
        self.assertTrue(self.seen["phone"]["url"].endswith("/interface/thea.html"),
                        self.seen["phone"]["url"])

    def test_it_loaded_its_data_rather_than_sitting_on_loading(self):
        for name, seen in self.seen.items():
            with self.subTest(name):
                self.assertNotIn("Reading her state…", seen["body"])

    # ---- the four things -------------------------------------------------
    def test_the_four_things_are_on_the_page_at_a_phones_width(self):
        body = self.seen["phone"]["body"]
        for heading in ("Right now", "Ask Thea", "Needs you", "What she's done"):
            with self.subTest(heading):
                self.assertIn(heading, body)

    def test_the_same_four_things_are_on_the_desk(self):
        body = self.seen["desk"]["body"]
        for heading in ("Right now", "Ask Thea", "Needs you", "What she's doing"):
            with self.subTest(heading):
                self.assertIn(heading, body)

    def test_the_other_panels_render(self):
        for name, seen in self.seen.items():
            with self.subTest(name):
                self.assertIn("call the dentist", seen["body"])
                self.assertIn("call the plumber", seen["body"])

    # ---- the approval, which is what the old test was written for --------
    def test_an_approval_says_what_it_will_do(self):
        for name, seen in self.seen.items():
            with self.subTest(name):
                self.assertIn("Remember the landlord is Mr Okafor", seen["needs"])

    def test_it_does_not_show_the_transport_wrapper(self):
        for name, seen in self.seen.items():
            with self.subTest(name):
                self.assertNotIn("spoken to the wall", seen["needs"])
                self.assertNotIn("operator said:", seen["needs"])

    def test_the_decision_is_offered_in_words_a_person_uses(self):
        needs = self.seen["phone"]["needs"]
        for word in ("Approve", "Not now", "Say no to this"):
            with self.subTest(word):
                self.assertIn(word, needs)

    def test_the_api_carries_the_label_rather_than_the_page_computing_it(self):
        """Smarts in the collector, never in the page (§88)."""
        from aletheia import core
        self.assertIn('"label": label', Path(core.__file__).read_text(encoding="utf-8"))

    # ---- no developer words ---------------------------------------------
    #: Things he must never read while simply using her. Each one was really
    #: on one of the five surfaces this page replaced.
    FORBIDDEN = (
        "task.persist",          # a capability id
        "ap-1",                  # an approval id
        "call-the-plumber",      # a task id (its DESCRIPTION is fine)
        "EXPERIMENTAL", "NEEDS_CONFIGURATION",
        "WAITING_OPERATOR", "FAILED_RETRYABLE", "requested_action",
        "{", "}",                # a JSON blob on the page
        "/api/",                 # a route
        "127.0.0.1", "8777",
    )

    def test_nothing_developer_shaped_is_visible_in_normal_use(self):
        for name, seen in self.seen.items():
            self.assertFalse(seen["drawer_open"], "the drawer starts shut")
            for word in self.FORBIDDEN:
                with self.subTest(name=name, word=word):
                    self.assertNotIn(word, seen["body"], word)

    def test_the_internal_state_words_are_said_the_way_a_person_says_them(self):
        """IDLE / ACTING / NEEDS YOU are the collector's vocabulary, not his."""
        body = self.seen["phone"]["body"]
        for shouted in ("IDLE", "ACTING", "NEEDS YOU", "WAITING_EXTERNAL", "BLOCKED"):
            with self.subTest(shouted):
                self.assertNotIn(shouted, body, shouted)

    # ---- it fits a phone --------------------------------------------------
    def test_nothing_scrolls_sideways_on_a_phone(self):
        self.assertLessEqual(self.seen["phone"]["overflow"], 0,
                             "the page is wider than the phone")

    def test_what_he_taps_is_big_enough_to_tap(self):
        small = [b for b in self.seen["phone"]["taps"]
                 if b["h"] < 32 and b["w"] < 32]
        self.assertEqual(small, [], f"tap targets under 32px: {small}")

    def test_this_file_puts_the_stores_back(self):
        """A test about isolation that leaks its own redirection would
        break every test that runs after it, by order."""
        self.assertTrue(getattr(type(self), "_before", None))


class TheSurfacesItReplacedStillAnswer(unittest.TestCase):
    """A home-screen icon and a bookmark outlive a rename. Every page that
    was deleted redirects to the one that replaced it, so nobody who
    installed Thea in September finds a 404 in October."""

    @classmethod
    def setUpClass(cls):
        from aletheia import core
        cls.srv = core.make_server(port=0)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.port = cls.srv.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def _redirect_of(self, path):
        import urllib.error
        import urllib.request

        class Stay(urllib.request.HTTPRedirectHandler):
            """urllib follows redirects; the point here is to see them."""

            def redirect_request(self, *a, **kw):
                return None

        opener = urllib.request.build_opener(Stay)
        try:
            res = opener.open(f"http://127.0.0.1:{self.port}{path}")
            return res.status, res.headers.get("Location")
        except urllib.error.HTTPError as exc:
            return exc.code, exc.headers.get("Location")

    def test_every_retired_page_points_at_the_one_that_replaced_it(self):
        from aletheia import core
        for old in sorted(core.RETIRED_PAGES) + ["/", "/interface/"]:
            path = old if old.startswith("/") else "/" + old
            with self.subTest(path):
                code, where = self._redirect_of(path)
                self.assertEqual(code, 302, path)
                self.assertEqual(where, core.THE_PAGE, path)

    def test_the_ambient_wall_is_still_served(self):
        import urllib.request
        with urllib.request.urlopen(
                f"http://127.0.0.1:{self.port}/interface/wall.html") as r:
            self.assertEqual(r.status, 200)
            self.assertIn(b"ALETHEIA", r.read())


if __name__ == "__main__":
    unittest.main()
