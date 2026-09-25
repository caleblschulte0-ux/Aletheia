"""Posting to Instagram without Meta, because Meta shut the door.

His words, 2026-09-25, after hours of it: *"Bro I'm not seeing anywhere to do
that and all this meta account and insta account and Facebook acount shit is
so confusing your supposed to be doing this for me."*

The Graph API route is built and correct and he cannot use it. Read off his
own Business portfolio that day: *"Your account must be confirmed before you
can create a new app. Please confirm your account by adding your mobile phone
number or credit card."* That is an account-level refusal, which is why it
failed on his phone, his PC and every account he owns - and Meta's bug tool
needs the developer account he is being refused, so there is nobody to ask.

So the capability goes through the door that IS open: Instagram's own web
composer, in her dedicated browser profile, where he signs in once.
"""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import instagram, instagram_web, journal


class Fake:
    """A stand-in for a Playwright page: records what was driven."""

    def __init__(self, *, signed_in=True, missing="", shared=True):
        self.signed_in = signed_in
        self.missing = missing
        self.shared = shared
        self.did: list[str] = []
        self.typed = ""
        self.files: list[str] = []
        self.closed = False

    # -- page API used by the module -------------------------------------
    def goto(self, url, **kw):
        self.did.append(f"goto:{url}")

    def wait_for_timeout(self, ms):
        pass

    def inner_text(self, sel):
        return "Feed" if self.signed_in else "Log in or Sign up"

    def screenshot(self, path=None, **kw):
        Path(path).write_bytes(b"png")
        self.did.append("screenshot")

    def close(self):
        self.closed = True

    def wait_for_selector(self, sel, **kw):
        if not self.shared:
            raise RuntimeError("timeout waiting for " + sel)
        self.did.append(f"confirmed:{sel}")

    def locator(self, sel, **kw):
        if sel == "input[name='username']":
            return _Loc(self, sel, count=0 if self.signed_in else 1)
        if sel == "input[type='file']":
            return _Loc(self, sel, count=0 if self.missing == "file" else 1)
        if "contenteditable" in sel:
            return _Loc(self, sel, count=1)
        return _Loc(self, sel, count=0)

    def get_by_role(self, role, name=""):
        key = f"{role}:{name}"
        if name == "Create":
            return _Loc(self, key, count=0 if (not self.signed_in or self.missing == "create") else 1)
        if name == "Next":
            return _Loc(self, key, count=0 if self.missing == "next" else 1)
        if name == "Share":
            return _Loc(self, key, count=0 if self.missing == "share" else 1)
        if name.startswith("Write a caption"):
            return _Loc(self, key, count=1)
        return _Loc(self, key, count=0)


class _Loc:
    def __init__(self, page, key, count=1):
        self.page = page
        self.key = key
        self._count = count

    def count(self):
        return self._count

    @property
    def first(self):
        return self

    def click(self):
        self.page.did.append(f"click:{self.key}")

    def type(self, text, delay=0):
        self.page.typed = text
        self.page.did.append("type:caption")

    def set_input_files(self, path):
        self.page.files.append(path)
        self.page.did.append("file")

    def filter(self, **kw):
        return self

    def get_attribute(self, name):
        return None


class Ctx:
    def __init__(self, page):
        self.page = page

    def new_page(self):
        return self.page


class WebCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        env = mock.patch.dict(os.environ, {"ALETHEIA_PRIVATE_STATE": str(self.tmp / "private")})
        env.start(); self.addCleanup(env.stop)
        self.lines = []
        a = mock.patch.object(journal, "append", side_effect=lambda *x, **k: self.lines.append(x))
        a.start(); self.addCleanup(a.stop)
        self.pic = self.tmp / "sunset.jpg"
        self.pic.write_bytes(b"\xff\xd8\xff\xe0jpeg")
        # The fake page is signed in as the account HE named. Every test that
        # cares about which account overrides this with its own patch.
        w = mock.patch.object(instagram_web, "_whoami", return_value="@lieutenantmemestrong")
        w.start(); self.addCleanup(w.stop)

    def journaled(self):
        return " ".join(str(x) for x in self.lines)


class SignedInIsAskedLive(WebCase):
    def test_a_signed_out_browser_says_the_one_sign_in(self):
        ok, why = instagram_web.signed_in(context=Ctx(Fake(signed_in=False)))
        self.assertFalse(ok)
        self.assertIn("not signed in", why)

    def test_a_signed_in_browser_says_so(self):
        ok, why = instagram_web.signed_in(context=Ctx(Fake()))
        self.assertTrue(ok)
        self.assertIn("signed in", why)

    def test_the_setup_sentence_names_no_meta_anything(self):
        said = instagram_web.SETUP
        self.assertIn("one sign-in", said)
        for word in ("developer account", "token", "app ID", "Graph"):
            self.assertNotIn(word, said.replace("no developer account", ""))


class APostIsTheComposerDriven(WebCase):
    def test_the_whole_flow_in_order_and_a_ledger_line(self):
        page = Fake()
        row = instagram_web.publish(self.pic, "Hello\nfrom Thea", context=Ctx(page))
        self.assertEqual(page.files, [str(self.pic)])
        self.assertEqual(page.typed, "Hello\nfrom Thea", "the caption keeps its line break")
        order = [d for d in page.did if d.startswith(("click:", "file", "confirmed:"))]
        self.assertEqual(order[0], "click:link:Create")
        self.assertIn("file", order)
        self.assertEqual(order.count("click:button:Next"), 2, "crop, then filters")
        self.assertTrue(order[-1].startswith("confirmed:"))
        self.assertEqual(row["via"], "web")
        self.assertEqual(row["kind"], "IMAGE")
        self.assertTrue(page.closed, "the tab is always closed")
        # ONE ledger for both doors.
        self.assertEqual(instagram.posts()[0]["file"], str(self.pic))

    def test_a_dry_run_walks_everything_and_never_presses_share(self):
        page = Fake()
        out = instagram_web.publish(self.pic, "hi", context=Ctx(page), share=False)
        self.assertTrue(out["dry_run"])
        self.assertNotIn("click:button:Share", page.did)
        self.assertEqual(instagram.posts(), [], "a dry run is not a post")

    def test_a_screen_that_moved_is_named_and_photographed_and_posts_nothing(self):
        for missing, where in (("create", "create"), ("file", "file"),
                               ("next", "crop"), ("share", "share")):
            with self.subTest(missing=missing):
                page = Fake(missing=missing)
                with self.assertRaises(RuntimeError) as ctx:
                    instagram_web.publish(self.pic, "hi", context=Ctx(page))
                said = str(ctx.exception)
                self.assertIn(where, said, said)
                self.assertEqual(instagram.posts(), [])

    def test_share_that_never_confirms_is_not_recorded_as_posted(self):
        page = Fake(shared=False)
        with self.assertRaises(RuntimeError):
            instagram_web.publish(self.pic, "hi", context=Ctx(page))
        self.assertEqual(instagram.posts(), [])

    def test_a_missing_file_and_an_odd_type_are_refused_in_words(self):
        with self.assertRaises(RuntimeError) as ctx:
            instagram_web.publish(self.tmp / "nope.jpg", "hi", context=Ctx(Fake()))
        self.assertIn("no file at", str(ctx.exception))
        odd = self.tmp / "notes.txt"
        odd.write_text("x", encoding="utf-8")
        with self.assertRaises(RuntimeError) as ctx:
            instagram_web.publish(odd, "hi", context=Ctx(Fake()))
        self.assertIn("neither", str(ctx.exception))

    def test_a_video_is_a_reel(self):
        clip = self.tmp / "clip.mp4"
        clip.write_bytes(b"\x00")
        self.assertEqual(instagram_web.media_kind(clip), "REELS")


class TheRouteIsChosenByWhatIsAvailable(WebCase):
    def test_no_token_means_her_browser(self):
        self.assertEqual(instagram.route(), instagram.ROUTE_WEB)
        self.assertFalse(instagram.api_configured())

    def test_a_token_takes_the_api_back(self):
        instagram.configure("17841400000000000", username="openrange")
        with mock.patch("aletheia.secret_store.exists", return_value=True):
            self.assertTrue(instagram.api_configured())
            self.assertEqual(instagram.route(), instagram.ROUTE_IG)

    def test_publish_goes_through_the_browser_when_there_is_no_token(self):
        page = Fake()
        with mock.patch("aletheia.instagram_web.available", return_value=(True, "ok")), \
                mock.patch("aletheia.instagram_web.publish",
                           side_effect=lambda m, c: {"via": "web", "file": str(m)}) as drove:
            row = instagram.publish(str(self.pic), "hi")
        self.assertEqual(row["via"], "web")
        self.assertEqual(drove.call_count, 1)

    def test_a_web_address_is_refused_on_the_browser_route_in_words(self):
        with mock.patch("aletheia.instagram_web.available", return_value=(True, "ok")):
            with self.assertRaises(RuntimeError) as ctx:
                instagram.publish("https://cdn.example.com/p.jpg", "hi")
        self.assertIn("file from this PC", str(ctx.exception))


class HisPersonalAccountIsNeverTouched(WebCase):
    """His ruling, 2026-09-25: *"I want us to set up lenient memestrong to
    auto post using the verified meta way. Never touch my personal account
    ever."* It is a test and not only a note because the way it was learned
    was a session switching his PERSONAL account to a Business account on a
    name match, which made his profile public and cannot be fully undone."""

    def test_the_personal_handle_is_refused_by_name(self):
        with self.assertRaises(RuntimeError) as ctx:
            instagram.check_account("caleb_schulte_1")
        said = str(ctx.exception)
        self.assertIn("personal account", said)
        self.assertIn("never touch", said.lower())
        self.assertIn(instagram.POSTING_ACCOUNT, said)

    def test_the_posting_account_is_the_one_he_named(self):
        self.assertEqual(instagram.posting_account(), "lieutenantmemestrong")
        self.assertIn("caleb_schulte_1", instagram.NEVER_TOUCH)
        instagram.check_account("lieutenantmemestrong")      # does not raise
        instagram.check_account("@LieutenantMemestrong")     # nor case/@ variants

    def test_an_unknown_or_unreadable_handle_fails_CLOSED(self):
        for handle in ("", "   ", "somebody_else"):
            with self.subTest(handle=handle):
                with self.assertRaises(RuntimeError):
                    instagram.check_account(handle)

    def test_he_can_point_it_at_another_account_but_not_at_the_blocked_one(self):
        instagram._save(account="openrangeinteractive")
        self.assertEqual(instagram.posting_account(), "openrangeinteractive")
        instagram.check_account("openrangeinteractive")
        instagram._save(account="caleb_schulte_1")
        with self.assertRaises(RuntimeError):
            instagram.check_account("caleb_schulte_1")

    def test_the_wrong_account_never_reaches_a_share_button(self):
        page = Fake()
        with mock.patch("aletheia.instagram_web._whoami", return_value="@caleb_schulte_1"):
            with self.assertRaises(RuntimeError) as ctx:
                instagram_web.publish(self.pic, "hi", context=Ctx(page))
        self.assertIn("personal account", str(ctx.exception))
        self.assertNotIn("click:link:Create", page.did, "it stops before the composer")
        self.assertNotIn("click:button:Share", page.did)
        self.assertEqual(instagram.posts(), [])

    def test_signed_in_reports_the_wrong_account_as_not_ready(self):
        with mock.patch("aletheia.instagram_web._whoami", return_value="@caleb_schulte_1"):
            ok, why = instagram_web.signed_in(context=Ctx(Fake()))
        self.assertFalse(ok)
        self.assertIn("personal account", why)


class ItIsStillHisApproval(unittest.TestCase):
    def test_the_gate_did_not_move(self):
        from aletheia import intercom, tools
        self.assertIn("instagram_post", tools.OUTWARD_ALWAYS)
        self.assertEqual(intercom.tier("instagram_post"), intercom.TIER_WORLD)

    def test_the_module_never_presses_share_on_its_own(self):
        source = Path(instagram_web.__file__).read_text(encoding="utf-8")
        self.assertIn("share: bool = True", source)
        self.assertIn("if not share:", source)


if __name__ == "__main__":
    unittest.main()
