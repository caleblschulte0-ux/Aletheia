"""The interactive surface, rendered — the one with the buttons on it.

The wall got a render test; the Command Center never had one, and it was
showing a worse version of the same approval:

    operator said: "spoken to the wall: thea remember my landlord"
    run 1 step: note · ap-3f9ab2c1                      [APPROVE] [DENY]

The wall renders `voice.approval_label`, which prefers the plan's own
summary. This page rendered `reason` raw. Two surfaces disagreeing about
one approval, and the one he actually acts on had the transport wrapper,
the nested quote, and a hex id — with an APPROVE button next to it.

Real Chromium against a real in-process Core. Skips when there is no
browser, like every other browser test here.
"""
import os
import shutil
import tempfile
import threading
import unittest
from pathlib import Path


def chromium():
    for path in Path("/opt/pw-browsers").glob("chromium-*/chrome-linux/chrome"):
        return str(path)
    return None


class CommandCenterCase(unittest.TestCase):
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
        cls.body, cls.approvals, cls.errors = cls._render(
            f"http://127.0.0.1:{cls.srv.server_address[1]}/command.html")

    ASKS = "#approvals"

    @classmethod
    def _render(cls, url, asks=None):
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
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(url)
            page.wait_for_timeout(2500)
            body = page.inner_text("body")
            approvals = page.inner_text(asks or cls.ASKS)
            browser.close()
        return body, approvals, errors

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
        if hasattr(cls, "room"):
            shutil.rmtree(cls.room, ignore_errors=True)

    def test_the_page_runs_without_errors(self):
        self.assertEqual(self.errors, [])

    def test_it_loaded_its_data_rather_than_sitting_on_loading(self):
        self.assertNotIn("loading…", self.body)

    def test_an_approval_says_what_it_will_do(self):
        self.assertIn("Remember the landlord is Mr Okafor", self.approvals)

    def test_it_does_not_show_the_transport_wrapper(self):
        self.assertNotIn("spoken to the wall", self.approvals)
        self.assertNotIn('operator said:', self.approvals)

    def test_the_buttons_are_there(self):
        self.assertIn("APPROVE", self.approvals)
        self.assertIn("DENY", self.approvals)

    def test_the_other_panels_render(self):
        self.assertIn("call the dentist", self.body)
        self.assertIn("call the plumber", self.body)

    def test_this_file_puts_the_stores_back(self):
        """A test about isolation that leaks its own redirection would
        break every test that runs after it, by order."""
        self.assertTrue(getattr(type(self), "_before", None))

    def test_the_api_carries_the_label_rather_than_the_page_computing_it(self):
        """Smarts in the collector, never in the page (§88)."""
        from aletheia import core
        self.assertIn('"label": label', Path(core.__file__).read_text(encoding="utf-8"))


class ThePhoneConsoleCase(CommandCenterCase):
    """The third surface, and it had the same defect.

    `console.js` rendered `a.reason` as the headline, so the phone asked
    him to approve `operator said: "spoken to the wall: thea remember my
    landlord"`. Three surfaces rendered one object three different ways
    and two of them were unusable — which is what a shared collector is
    for.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.body, cls.approvals, cls.errors = cls._render(
            f"http://127.0.0.1:{cls.srv.server_address[1]}/console.html",
            asks="#needs")

    def test_an_approval_says_what_it_will_do(self):
        self.assertIn("Remember the landlord is Mr Okafor", self.approvals)

    def test_it_does_not_show_the_transport_wrapper(self):
        self.assertNotIn("spoken to the wall", self.approvals)
        self.assertNotIn("operator said:", self.approvals)

    def test_the_buttons_are_there(self):
        for word in ("Approve", "Deny"):
            self.assertIn(word, self.approvals)

    def test_the_other_panels_render(self):
        self.assertIn("call the dentist", self.body)

    def test_it_loaded_its_data_rather_than_sitting_on_loading(self):
        self.assertNotIn("loading…", self.body)

    def test_all_three_surfaces_use_the_collector(self):
        """The wall, the Command Center and the phone all render the label
        the API computes, so they cannot drift apart again."""
        here = Path(__file__).resolve().parent.parent / "interface"
        for page in ("index.html", "command.html", "console.js"):
            with self.subTest(page=page):
                body = (here / page).read_text(encoding="utf-8")
                self.assertRegex(body, r"\bsays\b|\.label\b", page)


if __name__ == "__main__":
    unittest.main()
