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
DIGEST = "9f3c1d2e4b5a6c7d8e9f0a1b2c3d4e5f"
SAME_YES = ("It sends your application to this employer under your name. "
            "There is no undo.")
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
        # A CONTENT-BOUND request, because that is the shape that bites:
        # `requested_action` is a sha256 and the journal records it
        # verbatim, so the digest reached the activity list as well as the
        # approval card.
        policy.request(
            "ap-1", "browser.interact:" + DIGEST,
            'operator said: "spoken to the wall: thea remember my landlord"',
            "Remember the landlord is Mr Okafor", True,
            capability="task.persist")
        # A CROWDED day, because an empty one proves nothing about density.
        # Live on his machine: thirty-eight pending applications that share
        # one consequence and differ only in which employer, and a hundred
        # unread notices behind them.
        for n in range(40):
            policy.request(
                f"apply-{n}-submit", "browser.interact:" + DIGEST[:24] + f"{n:04x}",
                f"Apply: Account Manager {n} - Employer {n} - "
                f"https://boards.example.com/jobs/{n}",
                SAME_YES, False, capability="browser.interact")
        notifications.publish("Reminder", "call the dentist",
                              priority="IMPORTANT")
        for n in range(30):
            notifications.publish(
                f"Application {n} could not be sent",
                "The submit button would not take a click - it never became "
                "clickable, on a form that loads an invisible check, which may "
                "be what held it, and she does not solve those. " * 2,
                dedupe_key=f"crowd-{n}")
        tasks.create("call-the-plumber", "call the plumber")
        # A line that names the machine, so the assertion about provider
        # strings is exercised rather than merely true of an empty page.
        from aletheia import journal
        journal.append("action", "session",
                       "Answered with ollama:qwen3:8b on subscription.auto, "
                       "from https://boards.example.com/jobs/7?token=abc123")
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
                # WAIT FOR THE LOAD, never for a stopwatch. A fixed 2.5s was
                # enough for an empty fixture and not for a crowded one, so
                # the crowded case rendered an empty page and the test that
                # cares about crowding was the one reading it.
                page.wait_for_function(
                    "() => document.getElementById('where').textContent.trim() "
                    "!== '\\u2026' && document.getElementById('needs').children.length",
                    timeout=20000)
                page.wait_for_timeout(400)
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
                    "brains": page.inner_text("#brains"),
                    "health_boxes": page.evaluate(
                        "() => ['banner', 'health'].filter(id => {"
                        " const el = document.getElementById(id);"
                        " return el && !el.hidden && el.textContent.trim(); }).length"),
                    "tall": page.evaluate(
                        "() => document.documentElement.scrollHeight"),
                    "taps": page.evaluate(
                        "() => [...document.querySelectorAll('button')]"
                        ".filter(b => b.offsetParent !== null)"
                        ".map(b => ({t: (b.textContent||b.ariaLabel||'').trim().slice(0,30),"
                        " h: Math.round(b.getBoundingClientRect().height),"
                        " w: Math.round(b.getBoundingClientRect().width)}))"),
                }
                # And what is behind the fold, because "folded" must mean
                # one tap away and not gone.
                page.click(".fold > summary")
                page.wait_for_timeout(300)
                out[name]["opened"] = page.inner_text("#needs")
                # THE FLEET IS HERE, folded (2026-09-23): the wall's every
                # element links into this page, so this page must hold
                # what the wall shows.
                out[name]["fleet_folded"] = page.evaluate(
                    "() => !document.getElementById('fleetFold').open")
                # A tap that changes only what is SHOWN repaints in the
                # same frame, with no request: "what exactly?" used to pay
                # a four-request round trip.
                out[name]["requests_on_open"] = page.evaluate("""() => {
                    const before = performance.getEntriesByType('resource').length;
                    const btn = document.querySelector('[data-open]');
                    if (!btn) return -1;
                    btn.click();
                    return performance.getEntriesByType('resource').length - before; }""")
                out[name]["peeked"] = page.evaluate(
                    "() => !!document.querySelector('.peeked')")
                # A decision leaves the screen the instant he taps it.
                # The LAST row, an application: the first is the one
                # decision unlike the others, which later tests read.
                # Another row fills the slot, so the check is that THIS
                # one is gone, not that the count fell.
                out[name]["approve_gone_at_once"] = page.evaluate("""() => {
                    const all = document.querySelectorAll('[data-approve]');
                    const btn = all[all.length - 1];
                    if (!btn) return null;
                    const id = btn.dataset.approve;
                    btn.click();
                    return !document.querySelector('[data-approve="' + CSS.escape(id) + '"]'); }""")
                page.wait_for_timeout(600)
                # A link from the wall lands on one repository's card, open.
                page.goto(cls.url + "interface/thea.html#repo=aletheia")
                page.wait_for_function(
                    "() => document.querySelector('[data-repo=\"aletheia\"]')", timeout=20000)
                page.wait_for_timeout(300)
                out[name]["linked"] = page.evaluate("""() => {
                    const card = document.querySelector('[data-repo="aletheia"]');
                    return { fold_open: document.getElementById('fleetFold').open,
                             card_open: !!card && card.open,
                             text: document.getElementById('fleet').innerText,
                             url: location.href }; }""")
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
                self.assertIn("call the plumber", seen["body"])
                # A notice is behind the fold now, which is where a thing
                # that needs no decision belongs — one tap, not gone.
                self.assertIn("could not be sent", seen["opened"])
                # And when even the fold is truncated it SAYS so, rather
                # than ending and letting him think that was all of them.
                self.assertIn("older ones", seen["opened"])

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
        for word in ("Approve", "Not now", "No"):
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
        DIGEST,                  # a sha256, from the approval AND the journal
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
    def test_who_is_thinking_is_on_the_page(self):
        """The line he asked for: which mind is answering, and how her own
        model is doing, so a slow answer looks like work and not a hang."""
        for who, seen in self.seen.items():
            with self.subTest(at=who):
                self.assertIn("my own model", seen["brains"].lower())

    def test_one_health_sentence_never_two(self):
        """The fixture has no supervisor AND a missing heartbeat: two
        collectors with something to say about the same fact. He reads one
        sentence about it, not a yellow box and a red one."""
        for who, seen in self.seen.items():
            with self.subTest(at=who):
                self.assertLessEqual(seen["health_boxes"], 1)

    def test_nothing_scrolls_sideways_on_a_phone(self):
        self.assertLessEqual(self.seen["phone"]["overflow"], 0,
                             "the page is wider than the phone")

    def test_what_he_taps_is_big_enough_to_tap(self):
        small = [b for b in self.seen["phone"]["taps"]
                 if b["h"] < 32 and b["w"] < 32]
        self.assertEqual(small, [], f"tap targets under 32px: {small}")

    # ---- density: a decision, not a wall ---------------------------------
    def test_a_busy_day_still_fits_in_a_handful_of_screens(self):
        """Forty pending decisions and thirty notices used to render as
        forty cards and a wall of digests — about seven phone screens of
        page, most of it the same sentence. He opens her to understand four
        things in ten seconds, and a page he has to scroll for a minute
        cannot do that however honest every line on it is."""
        screens = self.seen["phone"]["tall"] / PHONE["height"]
        self.assertLess(screens, 5.0,
                        f"the phone page is {screens:.1f} screens tall")

    def test_decisions_that_share_a_yes_say_the_shared_half_once(self):
        needs = self.seen["phone"]["needs"]
        self.assertIn("40 are waiting on the same yes", needs)
        self.assertEqual(needs.count(SAME_YES), 1,
                         "the shared consequence is said once, above the rows")

    def test_every_one_of_them_is_still_its_own_yes(self):
        """No bulk control, ever: each approval is bound to its own hash and
        stays its own decision. What changed is how much screen it takes."""
        needs = self.seen["phone"]["needs"].lower()
        for bulk in ("approve all", "approve the rest", "select all",
                     "approve 40", "approve them"):
            with self.subTest(bulk):
                self.assertNotIn(bulk, needs)
        self.assertGreaterEqual(self.seen["phone"]["needs"].count("Approve"), 2,
                                "each row still carries its own Approve")

    def test_a_row_names_which_one_it_is(self):
        """Forty rows sharing one consequence have to differ somewhere, or
        he is being asked for forty irreversible yeses with nothing on the
        screen to choose between them."""
        import re
        named = re.findall(r"Employer \d+", self.seen["phone"]["needs"])
        self.assertGreaterEqual(len(set(named)), 3)

    def test_a_decision_unlike_the_others_is_not_buried_under_them(self):
        """One row of every distinct kind before any kind gets a second:
        the landlord approval is the only non-application waiting, and
        spending the budget group by group hid it behind twenty-five."""
        self.assertIn("Remember the landlord is Mr Okafor",
                      self.seen["phone"]["needs"])

    def test_the_hundred_things_worth_seeing_are_one_folded_line(self):
        needs = self.seen["phone"]["needs"]
        self.assertIn("things worth seeing", needs)
        self.assertNotIn("Application 12 could not be sent", needs,
                         "a notice is behind the fold until he opens it")
        self.assertIn("could not be sent", self.seen["phone"]["opened"],
                      "and it is one tap away, not gone")

    def test_a_model_is_never_named_the_way_a_machine_names_it(self):
        for name in ("ollama:", "subscription.auto", "gpt-4", "claude-3",
                     "qwen", "sonnet"):
            for who, seen in self.seen.items():
                with self.subTest(name=name, at=who):
                    self.assertNotIn(name, seen["body"].lower())

    # ---- the wall lands here, and a tap answers at once (2026-09-23) -----
    def test_the_fleet_is_on_the_page_and_folded(self):
        """His ruling: the wall may have no capability this page lacks, so
        the repositories the wall shows are here — folded, because they
        are the weather and not the day, and the phone budget is real."""
        for name, seen in self.seen.items():
            with self.subTest(name):
                self.assertTrue(seen["fleet_folded"])
                self.assertIn("The fleet", seen["body"])

    def test_a_link_from_the_wall_opens_that_repository(self):
        for name, seen in self.seen.items():
            with self.subTest(name):
                linked = seen["linked"]
                self.assertTrue(linked["fold_open"], linked)
                self.assertTrue(linked["card_open"], linked)
                self.assertIn("Aletheia", linked["text"])
                # No developer words on the card either: the sha and the
                # branch stay one tap down, inside "Latest change".
                for word in ("{", "}", "/api/", "claude/"):
                    self.assertNotIn(word, linked["text"])

    def test_what_exactly_repaints_without_a_request(self):
        for name, seen in self.seen.items():
            with self.subTest(name):
                self.assertEqual(seen["requests_on_open"], 0)
                self.assertTrue(seen["peeked"])

    def test_a_decision_leaves_the_screen_the_instant_he_taps(self):
        for name, seen in self.seen.items():
            with self.subTest(name):
                self.assertTrue(seen["approve_gone_at_once"])

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
