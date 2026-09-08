"""Looking at the actual screen: the switch, the ladder, and the refusals.

His ruling, 2026-09-08: *"Yes it can use Claude when needed that's the
thing - if I wanted something that's just going to ask Claude to do
everything I will just talk to Claude."* So the test that matters most
here is not that looking WORKS - it is that she does not look when she
did not have to. `TheLadderCase` is that test.

The second theme is disclosure. A screenshot cannot be redacted the way
`perception.screen` redacts text, so every path that could send one is
held to: off by default, off in a rehearsal, off after a restart, and
never journalling the pixels.
"""
from __future__ import annotations

import datetime as dt
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import eyes, journal, stateio


class LeaseCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        marker = Path(self.tmp.name) / "eyes-lease.json"
        p = mock.patch.object(eyes, "marker", lambda: marker)
        p.start(); self.addCleanup(p.stop)
        p = mock.patch.object(journal, "append")
        p.start(); self.addCleanup(p.stop)
        p = mock.patch.object(eyes, "_boot_id", lambda: "boot-1")
        p.start(); self.addCleanup(p.stop)

    def test_it_is_off_until_he_says_otherwise(self):
        """The default for a picture of his screen is no."""
        self.assertFalse(eyes.granted())

    def test_a_grant_holds_for_this_boot(self):
        eyes.grant(2)
        self.assertTrue(eyes.granted())

    def test_a_restart_ends_it(self):
        """The microphone rule: a yes does not survive a reboot."""
        eyes.grant(8)
        self.assertTrue(eyes.granted())
        with mock.patch.object(eyes, "_boot_id", lambda: "boot-2"):
            self.assertFalse(eyes.granted())

    def test_a_platform_that_cannot_say_which_boot_gets_a_no(self):
        eyes.grant(8)
        with mock.patch.object(eyes, "_boot_id", lambda: ""):
            self.assertFalse(eyes.granted())

    def test_it_expires_on_its_own(self):
        eyes.grant(1)
        stale = dict(eyes.state())
        stale["until"] = (dt.datetime.now(dt.timezone.utc)
                          - dt.timedelta(minutes=1)).isoformat()
        stateio.write_json_atomic(eyes.marker(), stale)
        self.assertFalse(eyes.granted())

    def test_a_grant_is_capped(self):
        record = eyes.grant(9999)
        self.assertLessEqual(record["hours"], eyes.MAX_HOURS)

    def test_revoking_is_immediate(self):
        eyes.grant(8)
        eyes.revoke()
        self.assertFalse(eyes.granted())

    def test_unreadable_state_is_a_no(self):
        eyes.marker().write_text("{ not json", encoding="utf-8")
        self.assertFalse(eyes.granted())

    def test_the_switch_is_explained_in_words_he_can_act_on(self):
        said = eyes.spoken()
        self.assertNotIn("lease", said.lower())
        self.assertNotIn("granted", said.lower())
        eyes.grant(3)
        self.assertIn("restart", eyes.spoken())


class TheAnswerContractCase(unittest.TestCase):
    """Describing is allowed. Instructing is refused, not trimmed."""

    def test_a_plain_answer_passes(self):
        out = eyes.validate_answer(
            {"answer": "A spreadsheet.", "confidence": 0.8, "basis": "cells"})
        self.assertEqual(out["confidence"], 0.8)

    def test_an_action_shaped_field_is_refused(self):
        for bad in ("click", "coordinates", "command", "url", "steps", "x"):
            with self.subTest(field=bad):
                with self.assertRaises(PermissionError):
                    eyes.validate_answer({"answer": "ok", "confidence": 0.5,
                                          "basis": "b", bad: "anything"})

    def test_an_unknown_field_fails_closed(self):
        with self.assertRaises(ValueError):
            eyes.validate_answer({"answer": "ok", "confidence": 0.5,
                                  "basis": "b", "surprise": 1})

    def test_a_boolean_is_not_a_confidence(self):
        """True is an int in Python, and it is not 0..1 in the sense meant."""
        with self.assertRaises(ValueError):
            eyes.validate_answer({"answer": "ok", "confidence": True,
                                  "basis": "b"})

    def test_confidence_must_be_in_range(self):
        for value in (-0.1, 1.5, "high", None):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    eyes.validate_answer({"answer": "ok", "confidence": value,
                                          "basis": "b"})

    def test_an_empty_answer_is_not_an_answer(self):
        with self.assertRaises(ValueError):
            eyes.validate_answer({"answer": "   ", "confidence": 0.9,
                                  "basis": "b"})


class TheLadderCase(unittest.TestCase):
    """The point of the module: do not look if you did not have to.

    "If I wanted something that's just going to ask Claude to do
    everything I will just talk to Claude."
    """

    def setUp(self):
        p = mock.patch.object(eyes, "granted", lambda: True)
        p.start(); self.addCleanup(p.stop)

    def test_a_confident_read_never_photographs_anything(self):
        tree = {"answer": "Firefox.", "confidence": 0.99, "basis": "title"}
        with mock.patch.object(eyes, "look",
                               side_effect=AssertionError("photographed anyway")):
            out = eyes.answer("what am I using", describe=lambda q: tree)
        self.assertFalse(out["looked"])
        self.assertEqual(out["how"], "screen-text")

    def test_a_weak_read_escalates_to_the_pixels(self):
        tree = {"answer": "Something.", "confidence": 0.2, "basis": "not much"}
        seen = {"answer": "A bar chart.", "confidence": 0.9, "basis": "bars",
                "saw": {"sha256": "abc"}}
        with mock.patch.object(eyes, "look", return_value=seen) as looked:
            out = eyes.answer("what does the chart show", describe=lambda q: tree)
        self.assertTrue(looked.called)
        self.assertTrue(out["looked"])
        self.assertEqual(out["how"], "pixels")

    def test_the_floor_is_the_only_thing_that_decides(self):
        just_over = {"answer": "x", "confidence": eyes.TREE_CONFIDENCE_FLOOR,
                     "basis": "b"}
        with mock.patch.object(eyes, "look",
                               side_effect=AssertionError("should not look")):
            self.assertFalse(eyes.answer("q", describe=lambda q: just_over)["looked"])

    def test_a_read_that_raises_still_gets_a_look(self):
        """Failing to read is the clearest case for looking, not a refusal."""
        seen = {"answer": "A photo of a dog.", "confidence": 0.9, "basis": "dog"}
        def boom(_q):
            raise RuntimeError("accessibility tree unavailable")
        with mock.patch.object(eyes, "look", return_value=seen):
            out = eyes.answer("what is this", describe=boom)
        self.assertTrue(out["looked"])

    def test_without_the_switch_the_weak_answer_comes_back_honestly(self):
        tree = {"answer": "I can't tell.", "confidence": 0.1, "basis": "n/a"}
        with mock.patch.object(eyes, "granted", lambda: False), \
             mock.patch.object(eyes, "look",
                               side_effect=AssertionError("looked while off")):
            out = eyes.answer("what's in the picture", describe=lambda q: tree)
        self.assertFalse(out["looked"])
        self.assertIs(out["could_look"], False)

    def test_with_nothing_to_read_and_the_switch_off_it_says_so(self):
        def boom(_q):
            raise RuntimeError("no tree")
        with mock.patch.object(eyes, "granted", lambda: False):
            with self.assertRaises(eyes.NotGranted):
                eyes.answer("what is this", describe=boom)


class RefusalCase(unittest.TestCase):
    def test_looking_is_refused_while_the_switch_is_off(self):
        with mock.patch.object(eyes, "granted", lambda: False):
            with self.assertRaises(eyes.NotGranted):
                eyes.look("what is this")

    def test_a_rehearsal_never_photographs_his_screen(self):
        """`talk --sandbox` redirects stores; a screenshot is not a store.

        Without this, auditing "what's in this picture" would take a real
        photograph of his screen and send it to Anthropic for real.
        """
        with mock.patch.object(eyes, "granted", lambda: True), \
             mock.patch.dict(os.environ, {"ALETHEIA_REHEARSAL": "1"}), \
             mock.patch("aletheia.screen.capture",
                        side_effect=AssertionError("captured in a rehearsal")):
            with self.assertRaises(eyes.EyesUnavailable):
                eyes.look("what is this")

    def test_an_empty_question_is_refused_before_anything_is_captured(self):
        with mock.patch.object(eyes, "granted", lambda: True), \
             mock.patch("aletheia.screen.capture",
                        side_effect=AssertionError("captured for no question")):
            with self.assertRaises(ValueError):
                eyes.look("   ")


class DisclosureCase(unittest.TestCase):
    def test_the_journal_records_that_it_happened_never_what_was_seen(self):
        shot = mock.Mock(png=b"\x89PNG-not-really", width=800, height=600,
                         digest="d" * 64)
        shot.metadata.return_value = {"sha256": "d" * 64, "bytes": 15}
        answered = {"answer": "A bank statement showing 4321.",
                    "confidence": 0.9, "basis": "the page"}
        with mock.patch.object(eyes, "granted", lambda: True), \
             mock.patch("aletheia.screen.capture", return_value=shot), \
             mock.patch.object(eyes, "_ask_claude_about", return_value=answered), \
             mock.patch.object(journal, "append") as appended:
            eyes.look("what is this")
        line = " ".join(str(a) for a in appended.call_args[0])
        self.assertIn("d" * 12, line)          # the digest identifies it
        self.assertNotIn("4321", line)         # the CONTENT never appears
        self.assertNotIn("PNG", line)

    def test_the_screenshot_does_not_outlive_the_question(self):
        """Even when the look fails, the picture is not left on disk."""
        shot = mock.Mock(png=b"bytes", width=10, height=10, digest="e" * 64)
        shot.metadata.return_value = {}
        seen = {}

        def remember(path):
            seen["dir"] = path
            return True

        with mock.patch.object(eyes, "granted", lambda: True), \
             mock.patch("aletheia.screen.capture", return_value=shot), \
             mock.patch.object(eyes, "_ask_claude_about",
                               side_effect=eyes.EyesUnavailable("nope")), \
             mock.patch("aletheia.reasoner._discard_workdir", remember), \
             mock.patch.object(journal, "append"):
            with self.assertRaises(eyes.EyesUnavailable):
                eyes.look("what is this")
        self.assertIn("dir", seen, "the working directory was never discarded")


if __name__ == "__main__":
    unittest.main()
