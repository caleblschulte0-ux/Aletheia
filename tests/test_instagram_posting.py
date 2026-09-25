"""Posting to Instagram (his words, 2026-09-24: "I need an app or API or
whatever it requires to automatically post stuff to Instagram").

Handed the project, she found no door: `social.publish` was not a
capability. This is the door, held to the rules everything else here is
held to: the token is read from the vault by name and never written
anywhere; not set up is a refusal in words that say what only he can do;
a post is outward, so it always waits for his approval; and what went out
is a ledger she reads back.
"""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import act, instagram, intercom, journal, tools


class Fake:
    def __init__(self, fail_at: str = ""):
        self.calls = []
        self.fail_at = fail_at

    def post(self, path, fields):
        self.calls.append((path, dict(fields)))
        if self.fail_at and path.endswith(self.fail_at):
            raise RuntimeError("Instagram said no (400): The image is too small")
        return {"id": "1789" if path.endswith("/media") else "9001"}


class InstagramCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        d = Path(tmp.name)
        env = mock.patch.dict(os.environ, {"ALETHEIA_PRIVATE_STATE": str(d / "private")})
        env.start(); self.addCleanup(env.stop)
        p = mock.patch.object(journal, "JOURNAL_PATH", d / "j.jsonl")
        p.start(); self.addCleanup(p.stop)
        self.lines = []
        a = mock.patch.object(journal, "append", side_effect=lambda *args, **kw: self.lines.append((args, kw)))
        a.start(); self.addCleanup(a.stop)

    def ready(self):
        instagram.configure("17841400000000000", username="openrange")
        p1 = mock.patch("aletheia.secret_store.exists", return_value=True)
        p2 = mock.patch("aletheia.secret_store.get", return_value="EAAB-the-token-never-written")
        p1.start(); p2.start(); self.addCleanup(p1.stop); self.addCleanup(p2.stop)


class NotSetUpIsARefusalThatSaysWhatIsHis(InstagramCase):
    def test_not_configured_says_the_setup(self):
        ready, why = instagram.available()
        self.assertFalse(ready)
        self.assertIn("professional account", why)
        self.assertIn("instagram.token", why)
        with self.assertRaises(act.Refused) as ctx:
            intercom.execute_command({"kind": "instagram_post", "image_url": "https://x/y.jpg", "caption": "hi"}, {}, quote="t")
        self.assertIn("isn't set up yet", str(ctx.exception))
        self.assertTrue(intercom.execute_command({"kind": "instagram_posts"}, {}, quote="t").startswith("Nothing posted to Instagram yet"))

    def test_a_user_id_is_a_number(self):
        with self.assertRaises(ValueError):
            instagram.configure("openrange")


class APostIsTwoCallsAndALedgerLine(InstagramCase):
    def test_publish_creates_then_publishes_and_records(self):
        self.ready()
        fake = Fake()
        row = instagram.publish("https://cdn.example.com/pic.jpg", "Hello   from Thea", transport=fake)
        self.assertEqual([c[0] for c in fake.calls], ["17841400000000000/media", "17841400000000000/media_publish"])
        self.assertEqual(fake.calls[0][1]["caption"], "Hello from Thea")
        self.assertEqual(fake.calls[1][1]["creation_id"], "1789")
        self.assertEqual(row["id"], "9001")
        self.assertEqual(instagram.posts()[0]["caption"], "Hello from Thea")
        self.assertIn("1 post to Instagram", instagram.spoken_posts())
        text = " ".join(str(a) for a, _ in self.lines)
        self.assertNotIn("EAAB", text, "the token never reaches the journal")

    def test_instagram_saying_no_is_a_sentence_and_nothing_is_recorded(self):
        self.ready()
        with self.assertRaises(RuntimeError) as ctx:
            instagram.publish("https://cdn.example.com/pic.jpg", "x", transport=Fake(fail_at="/media"))
        self.assertIn("Instagram said no", str(ctx.exception))
        self.assertEqual(instagram.posts(), [])

    def test_only_a_public_https_picture(self):
        self.ready()
        with self.assertRaises(RuntimeError):
            instagram.publish("C:/Users/caleb/pic.jpg", "x", transport=Fake())


class HeSaysItInOneBreath(unittest.TestCase):
    def test_post_a_picture_to_instagram_saying(self):
        from aletheia import voice
        out = voice.interpret("thea post https://cdn.example.com/Pic.jpg to instagram saying Hello from Sioux Falls")
        self.assertEqual(out["command"], {"kind": "instagram_post", "image_url": "https://cdn.example.com/Pic.jpg",
                                          "caption": "Hello from Sioux Falls"})
        self.assertEqual(voice.interpret("thea what have you posted to instagram")["command"], {"kind": "instagram_posts"})
        self.assertEqual(voice.interpret("thea did the post go out")["command"], {"kind": "instagram_posts"})


class ItIsOutwardAndHisToApprove(unittest.TestCase):
    def test_the_kind_is_world_tier_outward_and_pc_only(self):
        self.assertIn("instagram_post", tools.OUTWARD_ALWAYS)
        self.assertEqual(intercom.tier("instagram_post"), intercom.TIER_WORLD)
        self.assertEqual(intercom.tier("instagram_posts"), intercom.TIER_READ)
        self.assertIn("instagram_post", intercom.LOCAL_KINDS)
        self.assertNotIn("instagram_post", intercom.PLANNER_FORBIDDEN, "a plan may propose a post; his approval sends it")

    def test_a_rehearsal_posts_nothing(self):
        # The world-tier gate refuses before the handler is reached.
        with mock.patch("aletheia.instagram.available", return_value=(True, "ready")), \
                mock.patch.object(intercom, "rehearsing", return_value=True), \
                mock.patch("aletheia.instagram.publish", side_effect=AssertionError("must not post")):
            with self.assertRaises(act.Refused) as ctx:
                intercom.execute_command({"kind": "instagram_post", "image_url": "https://x/y.jpg", "caption": "hi"}, {}, quote="t")
        self.assertIn("rehearsal", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
