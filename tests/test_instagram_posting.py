"""Posting to Instagram (his words, 2026-09-24: "I need an app or API or
whatever it requires to automatically post stuff to Instagram").

Handed the project, she found no door: `social.publish` was not a
capability. This is the door, held to the rules everything else here is
held to: the token is read from the vault by name and never written
anywhere; not set up is a refusal in words that say what only he can do,
with no shell command in it; a post is outward, so it always waits for his
approval; and what went out is a ledger she reads back.

Reviewed against Meta's current documentation 2026-09-25, and these are the
rules the review added — each one was a defect that would have reached him:

- The token says which of Meta's two routes it belongs to. `IGAA` is
  Instagram Login (`graph.instagram.com`, no Facebook Page); `EAA` is
  Facebook Login (`graph.facebook.com`). The old code sent everything to
  the Facebook host, so the easy route could not work at all.
- The API version is data. v21.0 was pinned here and is near end of life.
- The Instagram user id is DISCOVERED from the token, so he never goes
  looking for a number, and setup is ONE command.
- A caption keeps its line breaks and its hashtags. `" ".join(split())`
  collapsed them, and the collapse was visible in the post.
- A Reel is transcoded before it can be published, so the container is
  polled; ERROR is said as itself rather than waited out.
- READY means CONNECTED, checked with a live read-only call, not
  "there is a file in the vault".
"""
from __future__ import annotations

import datetime as dt
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import act, instagram, intercom, journal, setup, tools


class Fake:
    """Stands in for the Graph hosts. Records FULL urls, because the host and
    the API version are the thing under test as much as the path is."""

    def __init__(self, fail_at: str = "", statuses: list[str] | None = None,
                 me: dict | None = None):
        self.calls: list[tuple[str, str, dict]] = []
        self.fail_at = fail_at
        self.statuses = list(statuses or [])
        self.me = me or {"user_id": "17841400000000000", "username": "openrange"}

    @property
    def urls(self) -> list[str]:
        return [url for _, url, _ in self.calls]

    def post(self, url, fields):
        self.calls.append(("POST", url, dict(fields)))
        if self.fail_at and self.fail_at in url:
            raise RuntimeError("Instagram said no (400): The image is too small")
        return {"id": "1789" if url.endswith("/media") else "9001"}

    def get(self, url, params):
        self.calls.append(("GET", url, dict(params)))
        if "/me/accounts" in url:
            return {"data": [{"name": "Open Range",
                              "instagram_business_account": {"id": "17841400000000000",
                                                             "username": "openrange"}}]}
        if url.endswith("/me"):
            return dict(self.me)
        if "refresh_access_token" in url:
            return {"access_token": "IGAA-refreshed-never-logged", "expires_in": 60 * 86400}
        if "/1789" in url:
            return {"status_code": self.statuses.pop(0) if self.statuses else "FINISHED"}
        return {"username": "openrange", "account_type": "BUSINESS"}


class InstagramCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        env = mock.patch.dict(os.environ, {"ALETHEIA_PRIVATE_STATE": str(self.tmp / "private")})
        env.start(); self.addCleanup(env.stop)
        env2 = mock.patch.dict(os.environ, {}, clear=False)
        os.environ.pop(instagram.API_VERSION_ENV, None)
        env2.start(); self.addCleanup(env2.stop)
        p = mock.patch.object(journal, "JOURNAL_PATH", self.tmp / "j.jsonl")
        p.start(); self.addCleanup(p.stop)
        self.lines = []
        a = mock.patch.object(journal, "append", side_effect=lambda *args, **kw: self.lines.append((args, kw)))
        a.start(); self.addCleanup(a.stop)

    def journaled(self) -> str:
        return " ".join(str(a) for a, _ in self.lines)

    def ready(self, token: str = "IGAA-the-token-never-written"):
        instagram.configure("17841400000000000", username="openrange")
        instagram._save(route=instagram.route_of(token))
        p1 = mock.patch("aletheia.secret_store.exists", return_value=True)
        p2 = mock.patch("aletheia.secret_store.get", return_value=token)
        p1.start(); p2.start(); self.addCleanup(p1.stop); self.addCleanup(p2.stop)
        # Nothing in this file is allowed to serve a real file from the
        # internet; staging is stubbed and its own case covers the real one.
        return token


class NotSetUpIsARefusalSaidToTheRoom(InstagramCase):
    def test_not_configured_says_what_is_his_without_a_command_in_it(self):
        ready, why = instagram.available()
        self.assertFalse(ready)
        self.assertIn("professional account", why)
        self.assertIn("developer app", why)
        # THE ROOM HEARS THIS. A reply that reads a shell command out loud is
        # not an answer; the exact lines live on the setup page.
        for shell in ("python -m", "instagram.token", "--provider", "secret_store", "configure <"):
            self.assertNotIn(shell, why, f"a spoken refusal must not contain {shell!r}")
        with self.assertRaises(act.Refused) as ctx:
            intercom.execute_command({"kind": "instagram_post", "media": "https://x/y.jpg",
                                      "caption": "hi"}, {}, quote="t")
        self.assertIn("isn't set up yet", str(ctx.exception))
        self.assertTrue(intercom.execute_command({"kind": "instagram_posts"}, {},
                                                 quote="t").startswith("Nothing posted to Instagram yet"))

    def test_the_setup_page_is_where_the_commands_live_and_it_is_one_of_them(self):
        step = next(s for s in setup.steps() if s.capability == "social.publish")
        text = "\n".join(step.instructions())
        word = setup.python_word()
        self.assertIn(f"{word} -m aletheia.instagram connect", text)
        # ONE command he runs, plus `status` offered as a later check, and
        # nothing else. The old checklist had three, and one of them wanted a
        # number he had no way to find.
        self.assertEqual(text.count(" -m aletheia"), 2, text)
        self.assertNotIn("secret_store put instagram.token", text)
        self.assertNotIn("configure <instagram-user-id>", text)
        # Professional account FIRST: the app cannot see a personal account.
        self.assertLess(text.index("professional account"), text.index("developers.facebook.com"))
        self.assertIn("instagram_business_content_publish", text)

    def test_the_command_he_is_handed_runs_on_his_machine(self):
        """His PATH has C:\\Python39 first and the package refuses 3.9, so
        every `python -m aletheia...` the checklist printed died on a
        traceback. The word is chosen by asking the candidates."""
        step = next(s for s in setup.steps() if s.capability == "social.publish")
        with mock.patch.object(setup, "python_word", return_value="py"):
            self.assertIn("py -m aletheia.instagram connect", "\n".join(step.instructions()))
        with mock.patch.object(setup, "python_word", return_value="python"):
            self.assertIn("python -m aletheia.instagram connect", "\n".join(step.instructions()))

    def test_the_word_is_a_candidate_new_enough_to_run_the_package(self):
        import subprocess
        from aletheia import MIN_PYTHON, proc
        self.addCleanup(setup.python_word, refresh=True)
        seen = []

        def answered(argv, **kw):
            seen.append(argv[0])
            said = "3.9" if argv[0] == "C:/old" else "3.12"
            return subprocess.CompletedProcess(argv, 0, said + "\n", "")

        # The candidate list is named here rather than inherited from the
        # platform: the RULE is "skip one that is too old, take one that is new
        # enough", and freezing Windows' own order made this red on the Linux
        # runner for a reason that had nothing to do with the rule.
        with mock.patch.object(setup, "PYTHON_CANDIDATES", ("py", "python")), \
                mock.patch("shutil.which",
                           side_effect=lambda w: {"py": "C:/old", "python": "C:/new"}.get(w)), \
                mock.patch.object(proc, "run", side_effect=answered):
            self.assertEqual(setup.python_word(refresh=True), "python")
        self.assertEqual(seen, ["C:/old", "C:/new"], "the 3.9 was asked and passed over")
        # Nothing new enough: name the running interpreter rather than guess.
        with mock.patch("shutil.which", return_value=None):
            self.assertEqual(setup.python_word(refresh=True), setup.sys.executable)
        self.assertGreaterEqual(MIN_PYTHON, (3, 10))

    def test_windows_asks_the_launcher_first_and_nothing_else_does(self):
        """On Windows a bare `python` is whatever is first on the machine PATH,
        which on his PC is the 3.9. Everywhere else `python` is tried first so
        a machine where it is already fine keeps printing the plain command."""
        self.assertEqual(setup.PYTHON_CANDIDATES[0], "py" if os.name == "nt" else "python")
        self.assertIn("python", setup.PYTHON_CANDIDATES)

    def test_the_chooser_opens_no_console_window(self):
        """It is asked by the Core, which runs under pythonw: a bare
        subprocess there flashes a black window on his screen."""
        import subprocess
        from aletheia import proc
        self.addCleanup(setup.python_word, refresh=True)
        with mock.patch("shutil.which", return_value="C:/new"), \
                mock.patch.object(proc, "run",
                                  return_value=subprocess.CompletedProcess([], 0, "3.12\n", "")), \
                mock.patch.object(subprocess, "run",
                                  side_effect=AssertionError("must go through proc.run")), \
                mock.patch.object(subprocess, "Popen",
                                  side_effect=AssertionError("must go through proc.run")):
            setup.python_word(refresh=True)

    def test_the_spoken_setup_answer_still_carries_the_command(self):
        """The rewrite broke this in exactly the way the module it lives in
        exists to prevent: `intents._how_command` matched the literal
        "python -m", so the answer became "Not yet — that one needs setting
        up first." with nothing he could act on."""
        from aletheia import intents
        said = intents._cannot_yet([{"capability": "social.publish"}], {})
        self.assertIn(f"{setup.python_word()} -m aletheia.instagram connect", said)
        self.assertIn("needs setting up", said)

    def test_a_user_id_is_a_number(self):
        with self.assertRaises(ValueError):
            instagram.configure("openrange")


class TheTokenSaysWhichRoute(InstagramCase):
    def test_igaa_goes_to_instagram_and_eaa_to_facebook(self):
        self.assertEqual(instagram.route_of("IGAAxyz"), instagram.ROUTE_IG)
        self.assertEqual(instagram.route_of("EAAxyz"), instagram.ROUTE_FB)
        self.assertTrue(instagram.base_for("IGAAxyz").startswith("https://graph.instagram.com/"))
        self.assertTrue(instagram.base_for("EAAxyz").startswith("https://graph.facebook.com/"))

    def test_an_unknown_prefix_falls_back_to_the_saved_route_then_instagram(self):
        self.assertEqual(instagram.route_of("something-else"), instagram.ROUTE_IG)
        instagram._save(route=instagram.ROUTE_FB)
        self.assertEqual(instagram.route_of("something-else"), instagram.ROUTE_FB)

    def test_an_instagram_token_posts_to_the_instagram_host(self):
        self.ready("IGAA-token")
        fake = Fake()
        instagram.publish("https://cdn.example.com/pic.jpg", "hi", transport=fake)
        self.assertTrue(fake.urls)
        for url in fake.urls:
            self.assertTrue(url.startswith("https://graph.instagram.com/"), url)

    def test_a_facebook_token_posts_to_the_facebook_host(self):
        self.ready("EAA-token")
        fake = Fake()
        instagram.publish("https://cdn.example.com/pic.jpg", "hi", transport=fake)
        self.assertTrue(fake.urls)
        for url in fake.urls:
            self.assertTrue(url.startswith("https://graph.facebook.com/"), url)

    def test_the_read_only_questions_do_not_hang_the_setup_button(self):
        """`verify` is what /api/setup calls. Two minutes of hanging there is
        a page that looks broken."""
        self.assertLess(instagram.ASK_TIMEOUT_S, 30.0)
        self.assertEqual(instagram.GraphTransport(instagram.ASK_TIMEOUT_S).timeout,
                         instagram.ASK_TIMEOUT_S)


class TheApiVersionIsData(InstagramCase):
    def test_not_pinned_to_a_dead_version(self):
        self.assertNotEqual(instagram.DEFAULT_API_VERSION, "v21.0",
                            "v21.0 is near end of life; the default follows Meta's calendar")
        source = Path(instagram.__file__).read_text(encoding="utf-8")
        self.assertNotIn("/v21.0", source)

    def test_config_then_environment_then_default(self):
        self.assertEqual(instagram.api_version(), instagram.DEFAULT_API_VERSION)
        with mock.patch.dict(os.environ, {instagram.API_VERSION_ENV: "v26.0"}):
            self.assertEqual(instagram.api_version(), "v26.0")
            instagram._save(api_version="v24.0")
            self.assertEqual(instagram.api_version(), "v24.0")

    def test_nonsense_is_ignored_rather_than_sent(self):
        instagram._save(api_version="latest")
        self.assertEqual(instagram.api_version(), instagram.DEFAULT_API_VERSION)

    def test_the_version_is_in_every_graph_url(self):
        self.ready()
        instagram._save(api_version="v25.0")
        fake = Fake()
        instagram.publish("https://cdn.example.com/pic.jpg", "hi", transport=fake)
        for url in fake.urls:
            self.assertIn("/v25.0/", url, url)


class SetupIsOneCommand(InstagramCase):
    def test_connect_discovers_the_id_stores_the_token_and_proves_it_live(self):
        fake = Fake()
        stored = {}
        with mock.patch("aletheia.secret_store.available", return_value=(True, "ready")), \
                mock.patch("aletheia.secret_store.put",
                           side_effect=lambda name, secret, **kw: stored.update({name: secret})), \
                mock.patch("aletheia.secret_store.exists", return_value=True), \
                mock.patch("aletheia.secret_store.get", return_value="IGAA-pasted"):
            value = instagram.connect("IGAA-pasted", transport=fake)
        self.assertEqual(stored, {instagram.TOKEN_ALIAS: "IGAA-pasted"})
        self.assertEqual(value["user_id"], "17841400000000000")
        self.assertEqual(value["username"], "openrange")
        self.assertEqual(value["route"], instagram.ROUTE_IG)
        # The id came from the token, not from him.
        self.assertIn("https://graph.instagram.com/" + instagram.api_version() + "/me", fake.urls)
        self.assertEqual(fake.calls[0][2]["fields"], "user_id,username")
        # ...and it did not say ready until Instagram confirmed the account.
        self.assertTrue(any("/17841400000000000" in u for u in fake.urls))
        self.assertNotIn("IGAA-pasted", self.journaled())

    def test_connect_does_not_echo_and_takes_the_token_from_getpass(self):
        fake = Fake()
        with mock.patch("aletheia.instagram.getpass.getpass", return_value="IGAA-typed") as asked, \
                mock.patch("aletheia.secret_store.available", return_value=(True, "ready")), \
                mock.patch("aletheia.secret_store.put"), \
                mock.patch("aletheia.secret_store.exists", return_value=True), \
                mock.patch("aletheia.secret_store.get", return_value="IGAA-typed"):
            instagram.connect(transport=fake)
        self.assertEqual(asked.call_count, 1)
        # getpass IS the no-echo read; the prompt says so to him as well.
        self.assertIn("not echoed", str(asked.call_args))

    def test_a_token_that_instagram_does_not_confirm_is_not_a_green_setup(self):
        class Denies(Fake):
            def get(self, url, params):
                self.calls.append(("GET", url, dict(params)))
                if url.endswith("/me"):
                    return dict(self.me)
                raise RuntimeError("Instagram said no (190): Error validating access token")
        with mock.patch("aletheia.secret_store.available", return_value=(True, "ready")), \
                mock.patch("aletheia.secret_store.put"), \
                mock.patch("aletheia.secret_store.exists", return_value=True), \
                mock.patch("aletheia.secret_store.get", return_value="IGAA-stale"):
            with self.assertRaises(RuntimeError) as ctx:
                instagram.connect("IGAA-stale", transport=Denies())
        self.assertIn("did not confirm", str(ctx.exception))

    def test_the_facebook_route_finds_the_account_through_the_page(self):
        fake = Fake()
        with mock.patch("aletheia.secret_store.available", return_value=(True, "ready")), \
                mock.patch("aletheia.secret_store.put"), \
                mock.patch("aletheia.secret_store.exists", return_value=True), \
                mock.patch("aletheia.secret_store.get", return_value="EAA-pasted"):
            value = instagram.connect("EAA-pasted", transport=fake)
        self.assertEqual(value["route"], instagram.ROUTE_FB)
        self.assertTrue(any("/me/accounts" in u for u in fake.urls))

    def test_two_accounts_is_a_question_and_not_a_guess(self):
        class Two(Fake):
            def get(self, url, params):
                if "/me/accounts" in url:
                    return {"data": [
                        {"name": "A", "instagram_business_account": {"id": "1", "username": "a"}},
                        {"name": "B", "instagram_business_account": {"id": "2", "username": "b"}}]}
                return super().get(url, params)
        with self.assertRaises(RuntimeError) as ctx:
            instagram.discover("EAA-x", transport=Two())
        self.assertIn("more than one", str(ctx.exception))

    def test_configured_is_not_connected(self):
        """READY has to mean she can reach his account. A vault entry and a
        saved number only prove somebody typed something."""
        self.ready()
        self.assertTrue(instagram.available()[0])
        class Revoked(Fake):
            def get(self, url, params):
                raise RuntimeError("Instagram said no (190): Error validating access token")
        ok, why = instagram.verify(transport=Revoked())
        self.assertFalse(ok)
        self.assertIn("190", why)
        # ...and the setup audit says BROKEN rather than a green tick.
        with mock.patch.object(instagram, "verify", return_value=(False, why)):
            state, said = setup._instagram()
        self.assertEqual(state, setup.BROKEN)

    def test_verify_says_the_account_and_the_days_left(self):
        self.ready()
        instagram._save(token_expires_at=(dt.datetime.now(dt.timezone.utc)
                                          + dt.timedelta(days=31)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                        token_expires_estimated=False)
        ok, why = instagram.verify(transport=Fake())
        self.assertTrue(ok)
        self.assertIn("@openrange", why)
        self.assertRegex(why, r"the token has (30|31) days left")


class APostIsTwoCallsAndALedgerLine(InstagramCase):
    def test_publish_creates_then_publishes_and_records(self):
        self.ready()
        fake = Fake()
        row = instagram.publish("https://cdn.example.com/pic.jpg", "Hello from Thea", transport=fake)
        posts = [(m, u) for m, u, _ in fake.calls if m == "POST"]
        self.assertTrue(posts[0][1].endswith("/17841400000000000/media"))
        self.assertTrue(posts[1][1].endswith("/17841400000000000/media_publish"))
        self.assertEqual(fake.calls[0][2]["image_url"], "https://cdn.example.com/pic.jpg")
        self.assertEqual(posts[1][1] and fake.calls[-1][2]["creation_id"], "1789")
        self.assertEqual(row["id"], "9001")
        self.assertEqual(row["kind"], instagram.IMAGE)
        self.assertEqual(instagram.posts()[0]["caption"], "Hello from Thea")
        self.assertIn("1 post to Instagram", instagram.spoken_posts())
        self.assertNotIn("IGAA", self.journaled(), "the token never reaches the journal")

    def test_instagram_saying_no_is_a_sentence_and_nothing_is_recorded(self):
        self.ready()
        with self.assertRaises(RuntimeError) as ctx:
            instagram.publish("https://cdn.example.com/pic.jpg", "x",
                              transport=Fake(fail_at="/media"))
        self.assertIn("Instagram said no", str(ctx.exception))
        self.assertEqual(instagram.posts(), [])

    def test_a_token_never_reaches_an_error_sentence(self):
        """A Graph GET carries the token in the query string, so anything that
        quotes a url has to scrub it — an exception is the one place a secret
        travels furthest (a log, a receipt, his screen)."""
        self.assertNotIn("IGAA-secret",
                         instagram._scrub("https://graph.instagram.com/me?access_token=IGAA-secret"))
        self.assertIn("<hidden>",
                      instagram._scrub("...?access_token=IGAA-secret&fields=x"))

    def test_http_and_nothing_are_refused_in_words(self):
        self.ready()
        with self.assertRaises(RuntimeError) as ctx:
            instagram.publish("http://cdn.example.com/pic.jpg", "x", transport=Fake())
        self.assertIn("https", str(ctx.exception))
        with self.assertRaises(RuntimeError):
            instagram.publish("", "x", transport=Fake())

    def test_a_missing_file_says_so_rather_than_being_sent_as_an_address(self):
        self.ready()
        with self.assertRaises(RuntimeError) as ctx:
            instagram.publish(str(self.tmp / "nope.jpg"), "x", transport=Fake())
        self.assertIn("no file at", str(ctx.exception))


class ACaptionKeepsItsShape(InstagramCase):
    def test_line_breaks_and_hashtags_survive(self):
        written = "Sunset over Hartford.\n\nShot on a phone.\n\n#sodak #sunset #nofilter"
        self.assertEqual(instagram.normalize_caption(written), written)

    def test_runs_of_spaces_inside_a_line_still_collapse(self):
        self.assertEqual(instagram.normalize_caption("a    b  \n  c  "), "a b\nc")

    def test_windows_line_endings_and_a_wall_of_blanks(self):
        self.assertEqual(instagram.normalize_caption("a\r\n\r\n\r\n\r\nb"), "a\n\nb")

    def test_the_caption_that_reaches_meta_is_the_one_he_wrote(self):
        self.ready()
        fake = Fake()
        written = "One.\nTwo.\n\n#three"
        instagram.publish("https://cdn.example.com/p.jpg", written, transport=fake)
        self.assertEqual(fake.calls[0][2]["caption"], written)

    def test_over_the_limit_is_a_refusal_with_the_number_in_it(self):
        self.ready()
        with self.assertRaises(RuntimeError) as ctx:
            instagram.publish("https://cdn.example.com/p.jpg", "x" * 2400, transport=Fake())
        self.assertIn(str(instagram.MAX_CAPTION), str(ctx.exception))

    def test_the_ledger_line_read_back_is_one_line_not_a_paragraph(self):
        self.ready()
        instagram.publish("https://cdn.example.com/p.jpg", "First line\nsecond line", transport=Fake())
        said = instagram.spoken_posts()
        self.assertIn("First line", said)
        self.assertNotIn("second line", said)
        self.assertNotIn("\n", said)


class AReelIsAWaitAndThenAPost(InstagramCase):
    def test_a_video_is_reels_with_video_url_and_a_polled_container(self):
        self.ready()
        fake = Fake(statuses=["IN_PROGRESS", "IN_PROGRESS", "FINISHED"])
        slept = []
        row = instagram.publish("https://cdn.example.com/clip.mp4", "watch this",
                                transport=fake, sleep=slept.append)
        self.assertEqual(row["kind"], instagram.REELS)
        first = fake.calls[0][2]
        self.assertEqual(first["media_type"], "REELS")
        self.assertEqual(first["video_url"], "https://cdn.example.com/clip.mp4")
        self.assertNotIn("image_url", first)
        checks = [u for m, u, _ in fake.calls if m == "GET" and "/1789" in u]
        self.assertEqual(len(checks), 3)
        self.assertEqual(slept, [instagram.CONTAINER_POLL_S, instagram.CONTAINER_POLL_S])
        self.assertTrue(fake.urls[-1].endswith("/media_publish"))

    def test_an_error_status_is_said_as_itself_and_never_published(self):
        self.ready()
        fake = Fake(statuses=["IN_PROGRESS", "ERROR"])
        with self.assertRaises(RuntimeError) as ctx:
            instagram.publish("https://cdn.example.com/clip.mp4", "x",
                              transport=fake, sleep=lambda s: None)
        self.assertIn("ERROR", str(ctx.exception))
        self.assertNotIn("media_publish", " ".join(fake.urls))
        self.assertEqual(instagram.posts(), [])

    def test_five_minutes_is_the_wall_and_it_says_so(self):
        self.ready()
        clock = {"t": 0.0}
        fake = Fake(statuses=["IN_PROGRESS"] * 50)
        with self.assertRaises(RuntimeError) as ctx:
            instagram._await_container("1789", instagram.REELS, "IGAA", fake,
                                       sleep=lambda s: clock.__setitem__("t", clock["t"] + s),
                                       now=lambda: clock["t"])
        self.assertIn("still processing", str(ctx.exception))
        self.assertLessEqual(clock["t"], instagram.CONTAINER_BUDGET_S[instagram.REELS])

    def test_a_container_with_no_status_goes_straight_on_to_publish(self):
        """This poll runs on the ordinary picture path too. A field Meta
        chooses not to send back must not become a minute of waiting and then
        a failure on the one thing that was working; media_publish is still
        the real gate."""
        self.ready()
        class Quiet(Fake):
            def get(self, url, params):
                self.calls.append(("GET", url, dict(params)))
                return {"id": "1789"}
        fake = Quiet()
        slept = []
        row = instagram.publish("https://cdn.example.com/pic.jpg", "hi",
                                transport=fake, sleep=slept.append)
        self.assertEqual(row["id"], "9001")
        self.assertEqual(slept, [])
        self.assertTrue(fake.urls[-1].endswith("/media_publish"))

    def test_a_status_nobody_recognises_is_refused_not_waited_out(self):
        self.ready()
        fake = Fake(statuses=["SOMETHING_NEW"])
        with self.assertRaises(RuntimeError) as ctx:
            instagram.publish("https://cdn.example.com/clip.mp4", "x",
                              transport=fake, sleep=lambda s: None)
        self.assertIn("SOMETHING_NEW", str(ctx.exception))
        self.assertNotIn("media_publish", " ".join(fake.urls))

    def test_a_forced_media_type_wins_over_the_extension(self):
        self.assertEqual(instagram.media_kind("https://x/y"), instagram.IMAGE)
        self.assertEqual(instagram.media_kind("https://x/y.mp4"), instagram.REELS)
        self.assertEqual(instagram.media_kind("https://x/y.jpg", media_type="REELS"),
                         instagram.REELS)
        self.assertEqual(instagram.media_kind("https://x/y.mp4?w=1"), instagram.REELS)


class AFileOnHisPC(InstagramCase):
    """Meta fetches media from a public https address and has NO upload for
    images at all, so a local file has to be served from somewhere. What that
    somewhere is, is a decision with consequences, so it is a named object
    with a refusal of its own rather than an implicit upload."""

    class Stub:
        def __init__(self):
            self.staged = []
            self.torn_down = 0

        def stage(self, path, kind):
            self.staged.append((Path(path).name, kind))
            return "https://staged.example.com/" + Path(path).name, self._down

        def _down(self):
            self.torn_down += 1

    def test_a_local_jpeg_is_staged_published_and_unstaged(self):
        self.ready()
        pic = self.tmp / "sunset.jpg"
        pic.write_bytes(b"\xff\xd8\xff\xe0jpegish")
        stub = self.Stub()
        fake = Fake()
        row = instagram.publish(str(pic), "hi", transport=fake, stage=stub)
        self.assertEqual(stub.staged, [("sunset.jpg", instagram.IMAGE)])
        self.assertEqual(fake.calls[0][2]["image_url"], "https://staged.example.com/sunset.jpg")
        self.assertEqual(stub.torn_down, 1, "the staged copy is removed once the post lands")
        self.assertEqual(row["file"], str(pic))
        self.assertNotIn("media_url", row)

    def test_the_staged_copy_is_removed_even_when_instagram_refuses(self):
        self.ready()
        pic = self.tmp / "sunset.jpg"
        pic.write_bytes(b"\xff\xd8\xff\xe0jpegish")
        stub = self.Stub()
        with self.assertRaises(RuntimeError):
            instagram.publish(str(pic), "hi", transport=Fake(fail_at="/media"), stage=stub)
        self.assertEqual(stub.torn_down, 1, "a failed post must not leave his file in a public place")

    def test_a_png_is_converted_to_jpeg_without_touching_his_file(self):
        self.ready()
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("Pillow is not installed")
        shot = self.tmp / "screenshot.png"
        Image.new("RGBA", (12, 12), (10, 20, 30, 255)).save(shot)
        before = shot.read_bytes()
        stub = self.Stub()
        row = instagram.publish(str(shot), "hi", transport=Fake(), stage=stub)
        self.assertEqual(stub.staged, [("screenshot.jpg", instagram.IMAGE)])
        self.assertEqual(shot.read_bytes(), before, "HIS file is never rewritten")
        self.assertEqual(row["converted_from"], "png")
        self.assertEqual(row["file"], str(shot))

    def test_staging_turned_off_refuses_in_words_and_posts_nothing(self):
        self.ready()
        instagram._save(staging="off")
        pic = self.tmp / "sunset.jpg"
        pic.write_bytes(b"\xff\xd8\xff\xe0jpegish")
        fake = Fake()
        with self.assertRaises(RuntimeError) as ctx:
            instagram.publish(str(pic), "hi", transport=fake)
        said = str(ctx.exception)
        self.assertIn("public https address", said)
        self.assertEqual(fake.calls, [])
        self.assertIsInstance(instagram.stager(), instagram.NoStager)

    def test_the_real_stager_refuses_a_file_it_cannot_serve_as_media(self):
        """The content type is the real attempt, not an assumption: handing
        Instagram an address that serves a 404 page is a post that fails with
        nothing said, and the staged copy has to come back down either way.
        Measured 2026-09-25 against the live host: a .png is served
        image/png, a .mp4 application/octet-stream — so a picture is held to
        image/* and a video may be octet-stream."""
        stager = instagram.GithubStager("caleb/repo", token="gh-x")
        pic = self.tmp / "sunset.jpg"
        pic.write_bytes(b"\xff\xd8\xff\xe0jpegish")
        removed = []

        def staged(kind, served):
            removed.clear()
            with mock.patch.object(stager, "_ensure_branch", return_value=True), \
                    mock.patch.object(stager, "_sha_of", return_value=""), \
                    mock.patch.object(stager, "_call", return_value={"content": {"sha": "abc"}}), \
                    mock.patch.object(stager, "content_type", return_value=served), \
                    mock.patch.object(stager, "_remove",
                                      side_effect=lambda w, s, **kw: removed.append(w)):
                return stager.stage(pic, kind)

        with self.assertRaises(RuntimeError) as ctx:
            staged(instagram.IMAGE, "text/html")
        self.assertIn("nothing was posted", str(ctx.exception))
        self.assertEqual(len(removed), 1)
        with self.assertRaises(RuntimeError):
            staged(instagram.IMAGE, "application/octet-stream")
        url, _ = staged(instagram.REELS, "application/octet-stream")
        self.assertTrue(url.startswith("https://raw.githubusercontent.com/"))

    def test_the_same_file_twice_replaces_its_own_copy(self):
        """The name is the content hash, so a second post of the same picture
        finds the first still there; the Contents API answers 422 without the
        existing blob's sha."""
        stager = instagram.GithubStager("caleb/repo", token="gh-x")
        pic = self.tmp / "sunset.jpg"
        pic.write_bytes(b"\xff\xd8\xff\xe0jpegish")
        sent = {}
        with mock.patch.object(stager, "_ensure_branch", return_value=True), \
                mock.patch.object(stager, "_sha_of", return_value="earlier-blob"), \
                mock.patch.object(stager, "_call",
                                  side_effect=lambda m, p, b=None: sent.update({"body": b})
                                  or {"content": {"sha": "abc"}}), \
                mock.patch.object(stager, "content_type", return_value="image/jpeg"):
            stager.stage(pic, instagram.IMAGE)
        self.assertEqual(sent["body"]["sha"], "earlier-blob")

    def test_a_branch_that_was_already_there_is_not_deleted(self):
        """Tearing down may delete the branch only when this post made it —
        otherwise a second post's file goes with it."""
        stager = instagram.GithubStager("caleb/repo", token="gh-x")
        pic = self.tmp / "sunset.jpg"
        pic.write_bytes(b"\xff\xd8\xff\xe0jpegish")
        deletes = []
        with mock.patch.object(stager, "_ensure_branch", return_value=False), \
                mock.patch.object(stager, "_sha_of", return_value=""), \
                mock.patch.object(stager, "_call",
                                  side_effect=lambda m, p, b=None: deletes.append((m, p))
                                  or {"content": {"sha": "abc"}}), \
                mock.patch.object(stager, "content_type", return_value="image/jpeg"):
            _, teardown = stager.stage(pic, instagram.IMAGE)
            deletes.clear()
            teardown()
        self.assertTrue(any(m == "DELETE" and "contents/" in p for m, p in deletes))
        self.assertFalse(any("git/refs/heads" in p for m, p in deletes))

    def test_the_type_check_retries_while_the_file_appears(self):
        """A file committed a moment ago takes a beat to reach the raw host,
        and reading that 404 as a bad file would be a lie about his media."""
        import urllib.error
        stager = instagram.GithubStager("caleb/repo", token="gh-x")
        attempts = {"n": 0}

        class OK:
            headers = {"Content-Type": "image/jpeg"}

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def flaky(req, timeout=None):
            attempts["n"] += 1
            if attempts["n"] < 3:
                raise urllib.error.HTTPError(req.full_url, 404, "Not Found", {}, None)
            return OK()

        with mock.patch("aletheia.instagram.urllib.request.urlopen", side_effect=flaky):
            self.assertEqual(stager.content_type("https://x/y.jpg", sleep=lambda s: None),
                             "image/jpeg")
        self.assertEqual(attempts["n"], 3)
        with mock.patch("aletheia.instagram.urllib.request.urlopen",
                        side_effect=urllib.error.URLError("gone")):
            with self.assertRaises(RuntimeError) as ctx:
                stager.content_type("https://x/y.jpg", tries=2, sleep=lambda s: None)
        self.assertIn("could not be read back", str(ctx.exception))

    def test_the_real_stager_names_the_file_by_its_own_hash_and_caps_the_size(self):
        stager = instagram.GithubStager("caleb/repo", token="gh-x")
        pic = self.tmp / "sunset.jpg"
        pic.write_bytes(b"\xff\xd8\xff\xe0jpegish")
        seen = {}
        with mock.patch.object(stager, "_ensure_branch", return_value=True), \
                mock.patch.object(stager, "_sha_of", return_value=""), \
                mock.patch.object(stager, "_call",
                                  side_effect=lambda m, p, b=None: seen.update({"path": p, "body": b})
                                  or {"content": {"sha": "abc"}}), \
                mock.patch.object(stager, "content_type", return_value="image/jpeg"):
            url, teardown = stager.stage(pic, instagram.IMAGE)
        import hashlib
        expected = hashlib.sha256(pic.read_bytes()).hexdigest()[:24] + ".jpg"
        self.assertIn(expected, url)
        self.assertNotIn("sunset", url, "his filename is not part of a public address")
        self.assertTrue(url.startswith("https://raw.githubusercontent.com/caleb/repo/"
                                       + instagram.STAGE_BRANCH + "/"))
        self.assertEqual(seen["body"]["branch"], instagram.STAGE_BRANCH)
        big = self.tmp / "huge.jpg"
        big.write_bytes(b"x" * (instagram.STAGE_MAX_BYTES + 1))
        with self.assertRaises(RuntimeError) as ctx:
            stager.stage(big, instagram.IMAGE)
        self.assertIn("MB", str(ctx.exception))

    def test_the_staging_repo_comes_from_the_registry_not_a_literal(self):
        from aletheia import fleet
        registry = fleet.load_fleet()
        expected = f"{registry['owner']}/{registry['repos']['aletheia']['github']}"
        self.assertEqual(instagram.GithubStager().repo, expected)
        source = Path(instagram.__file__).read_text(encoding="utf-8")
        self.assertNotIn(registry["owner"] + "/", source,
                         "the owner and repo name live in config/fleet.json, not in code")
        instagram._save(staging_repo="someone/else")
        self.assertEqual(instagram.GithubStager().repo, "someone/else")

    def test_a_failed_unstage_is_loud_rather_than_silent(self):
        stager = instagram.GithubStager("caleb/repo", token="gh-x")
        with mock.patch.object(stager, "_call", side_effect=RuntimeError("GitHub said no (404)")):
            stager._remove("thea-media/x.jpg", "abc", drop_branch=True)
        self.assertIn("it is still public", self.journaled())


class TheTokenRefreshesItself(InstagramCase):
    def stamp(self, **delta):
        return (dt.datetime.now(dt.timezone.utc) + dt.timedelta(**delta)).strftime("%Y-%m-%dT%H:%M:%SZ")

    def test_due_only_when_it_is_old_enough_and_close_enough(self):
        self.ready()
        instagram._save(token_set_at=self.stamp(hours=-1), token_expires_at=self.stamp(days=1))
        self.assertFalse(instagram.refresh_due(), "Meta refuses a token under 24 hours old")
        instagram._save(token_set_at=self.stamp(days=-40), token_expires_at=self.stamp(days=20))
        self.assertFalse(instagram.refresh_due(), "20 days left is not yet")
        instagram._save(token_expires_at=self.stamp(days=3))
        self.assertTrue(instagram.refresh_due())

    def test_a_facebook_route_does_not_pretend_to_refresh_this_way(self):
        self.ready("EAA-token")
        instagram._save(token_set_at=self.stamp(days=-40), token_expires_at=self.stamp(days=1))
        self.assertFalse(instagram.refresh_due())
        with self.assertRaises(RuntimeError) as ctx:
            instagram.refresh_token(transport=Fake())
        self.assertIn("IGAA", str(ctx.exception))

    def test_the_refresh_is_unversioned_stores_the_new_token_and_journals_the_fact(self):
        self.ready()
        instagram._save(token_set_at=self.stamp(days=-40), token_expires_at=self.stamp(days=2))
        fake = Fake()
        stored = {}
        with mock.patch("aletheia.secret_store.put",
                        side_effect=lambda n, s, **kw: stored.update({n: s})):
            value = instagram.refresh_if_due(transport=fake)
        url = next(u for _, u, _ in fake.calls if "refresh_access_token" in u)
        self.assertEqual(url, "https://graph.instagram.com/refresh_access_token")
        self.assertEqual(fake.calls[0][2]["grant_type"], "ig_refresh_token")
        self.assertEqual(stored[instagram.TOKEN_ALIAS], "IGAA-refreshed-never-logged")
        self.assertFalse(value["token_expires_estimated"])
        self.assertIn("refreshed the Instagram access token", self.journaled())
        self.assertNotIn("IGAA-refreshed", self.journaled(), "the token is never journaled")

    def test_not_due_is_an_honest_no_op_and_a_second_look_is_rate_limited(self):
        self.assertIsNone(instagram.refresh_if_due())      # not set up at all
        self.ready()
        instagram._save(token_set_at=self.stamp(days=-40), token_expires_at=self.stamp(days=2))
        with mock.patch("aletheia.secret_store.put"):
            self.assertIsNotNone(instagram.refresh_if_due(transport=Fake()))
        instagram._save(token_expires_at=self.stamp(days=2))
        self.assertIsNone(instagram.refresh_if_due(transport=Fake()),
                          "one attempt per window, so a failing token is not a call every minute")

    def test_a_refusal_is_an_alert_and_not_an_exception_into_the_beat(self):
        self.ready()
        instagram._save(token_set_at=self.stamp(days=-40), token_expires_at=self.stamp(days=2))
        class Broken(Fake):
            def get(self, url, params):
                raise RuntimeError("Instagram said no (190): token expired")
        self.assertIsNone(instagram.refresh_if_due(transport=Broken()))
        self.assertIn("could not refresh the Instagram token", self.journaled())

    def test_the_core_beat_is_the_caller(self):
        from aletheia import core
        source = Path(core.__file__).read_text(encoding="utf-8")
        self.assertIn("instagram.refresh_if_due()", source,
                      "a token that refreshes only when someone runs a command is not scheduled")


class HeSaysItInOneBreath(unittest.TestCase):
    def test_post_a_picture_to_instagram_saying(self):
        from aletheia import voice
        out = voice.interpret("thea post https://cdn.example.com/Pic.jpg to instagram saying Hello from Sioux Falls")
        self.assertEqual(out["command"], {"kind": "instagram_post",
                                          "media": "https://cdn.example.com/Pic.jpg",
                                          "caption": "Hello from Sioux Falls"})

    def test_a_file_on_his_pc_is_a_sentence_too(self):
        from aletheia import voice
        out = voice.interpret(r"thea post C:\Users\caleb\Documents\Aletheia\Sunset.jpg to instagram")
        self.assertEqual(out["command"]["kind"], "instagram_post")
        self.assertEqual(out["command"]["media"], r"C:\Users\caleb\Documents\Aletheia\Sunset.jpg")
        self.assertEqual(voice.interpret("thea post clip.mp4 to instagram saying new one")["command"],
                         {"kind": "instagram_post", "media": "clip.mp4", "caption": "new one"})

    def test_a_bare_word_is_not_guessed_into_a_post(self):
        from aletheia import voice
        out = voice.interpret("thea post something to instagram")
        self.assertNotEqual((out or {}).get("command", {}).get("kind"), "instagram_post")

    def test_the_ledger_questions(self):
        from aletheia import voice
        self.assertEqual(voice.interpret("thea what have you posted to instagram")["command"],
                         {"kind": "instagram_posts"})
        self.assertEqual(voice.interpret("thea did the post go out")["command"],
                         {"kind": "instagram_posts"})


class ItIsOutwardAndHisToApprove(unittest.TestCase):
    def test_the_kind_is_world_tier_outward_and_pc_only(self):
        self.assertIn("instagram_post", tools.OUTWARD_ALWAYS)
        self.assertEqual(intercom.tier("instagram_post"), intercom.TIER_WORLD)
        self.assertEqual(intercom.tier("instagram_posts"), intercom.TIER_READ)
        self.assertIn("instagram_post", intercom.LOCAL_KINDS)
        self.assertNotIn("instagram_post", intercom.PLANNER_FORBIDDEN,
                         "a plan may propose a post; his approval sends it")

    def test_the_grammar_asks_for_media_not_only_a_url(self):
        required, optional = intercom.KIND_ARGS["instagram_post"]
        self.assertEqual(required, {"media"})
        self.assertEqual(optional, {"caption", "media_type"})
        self.assertFalse(required & optional)

    def test_a_rehearsal_posts_nothing(self):
        # The world-tier gate refuses before the handler is reached.
        with mock.patch("aletheia.instagram.available", return_value=(True, "ready")), \
                mock.patch.object(intercom, "rehearsing", return_value=True), \
                mock.patch("aletheia.instagram.publish", side_effect=AssertionError("must not post")):
            with self.assertRaises(act.Refused) as ctx:
                intercom.execute_command({"kind": "instagram_post", "media": "https://x/y.jpg",
                                          "caption": "hi"}, {}, quote="t")
        self.assertIn("rehearsal", str(ctx.exception))


class TheCharterIsHisAndSaysWhatIsLeft(unittest.TestCase):
    """His correction of a model's draft (§ draft charters are drafts). The
    order was wrong in a way that would have wasted an evening: a Meta app
    cannot see a personal Instagram account, and the draft's last step was
    "write documentation" rather than the step that connects it."""

    def charter(self) -> dict:
        return json.loads(Path("plans/instagram-auto-post-setup.json").read_text(encoding="utf-8"))

    def test_the_professional_account_is_step_one(self):
        steps = self.charter()["steps"]
        self.assertIn("professional account", steps[0]["text"])
        self.assertEqual(steps[0]["owner"], "caleb")

    def test_the_app_step_names_the_exact_route(self):
        text = self.charter()["steps"][1]["text"]
        for phrase in ("Business", "use case", "Instagram business login", "Generate token",
                       "instagram_business_content_publish"):
            self.assertIn(phrase, text)

    def test_the_last_thing_that_is_his_is_the_connect_command(self):
        steps = self.charter()["steps"]
        his = [s for s in steps if s["owner"] == "caleb"]
        self.assertIn("python -m aletheia.instagram connect", his[-1]["text"])
        self.assertEqual(len(his), 3, "three things are his, and the count is the promise")

    def test_her_step_is_a_real_post_and_not_documentation(self):
        last = self.charter()["steps"][-1]
        self.assertEqual(last["owner"], "thea")
        self.assertIn("approval", last["text"])
        self.assertNotIn("documentation", last["text"].lower())


if __name__ == "__main__":
    unittest.main()
