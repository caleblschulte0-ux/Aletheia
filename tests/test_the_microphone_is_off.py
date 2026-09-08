"""OFF is the default, and there is no way to make it not the default.

His ruling, 2026-09-07: *"i don't want an always on microphone. And if I
do want that, that'll be a button I press within Aletheia once she's
turned on. That it should not be a default feature."*

Before this, `AletheiaVoice` was a logon-triggered scheduled task with a
five-minute watchdog: a microphone in his room that opened itself when he
signed in and reopened itself whenever it stopped.

Every test here is one question — can this end up listening when he did
not press the button?
"""
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import closed, ears, intercom, journal, places, voice


class EarsCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        d = Path(self.tmp.name)
        env = mock.patch.dict(os.environ, {"ALETHEIA_PRIVATE_STATE": str(d)})
        env.start()
        self.addCleanup(env.stop)
        p = mock.patch.object(journal, "JOURNAL_PATH", d / "j.jsonl")
        p.start()
        self.addCleanup(p.stop)
        # Which boot this is, is a fact about the machine. Pinning it
        # keeps these tests about the SWITCH, and stops them passing only
        # on platforms that happen to answer. `RealBootIdCase` below
        # exercises the real one.
        boot = mock.patch.object(ears, "_boot_id", return_value="boot-1")
        boot.start()
        self.addCleanup(boot.stop)


class OffIsTheDefaultCase(EarsCase):
    def test_a_machine_that_has_never_been_asked_is_not_listening(self):
        self.assertFalse(ears.listening())
        self.assertIn("off", ears.spoken().lower())

    def test_an_unreadable_marker_is_not_listening(self):
        ears.marker().parent.mkdir(parents=True, exist_ok=True)
        ears.marker().write_text("{not json", encoding="utf-8")
        self.assertFalse(ears.listening())

    def test_turning_it_on_turns_it_on(self):
        ears.turn_on(via="test")
        self.assertTrue(ears.listening())
        self.assertIn("on", ears.spoken().lower())

    def test_it_does_not_survive_a_restart(self):
        """A durable "on" is the always-on microphone by a slower route.

        He enables it once in October and every logon after that opens
        the mic by itself — which is the thing he said no to.
        """
        ears.turn_on(via="test")
        self.assertTrue(ears.listening())
        with mock.patch.object(ears, "_boot_id", return_value="boot-2"):
            self.assertFalse(ears.listening())
            # And it says WHY, rather than just "off": he did turn it on.
            self.assertIn("restarted", ears.spoken())

    def test_a_platform_that_cannot_say_which_boot_it_is_stays_off(self):
        ears.turn_on(via="test")
        with mock.patch.object(ears, "_boot_id", return_value=""):
            self.assertFalse(ears.listening(), "unknown boot opened the mic")

    def test_closing_her_closes_the_microphone(self):
        ears.turn_on(via="test")
        closed.close(reason="test", via="test")
        self.assertFalse(ears.listening())

    def test_opening_her_does_NOT_reopen_the_microphone(self):
        """"Turn Aletheia on" must not quietly mean "turn the mic on"."""
        ears.turn_on(via="test")
        closed.close(reason="test", via="test")
        closed.open_again(via="test")
        self.assertFalse(ears.listening())


class RealBootIdCase(unittest.TestCase):
    """The one place the real `_boot_id` runs, asserting only what holds
    on every platform: it is STABLE. Whether this machine can answer at
    all is the machine's business — an empty answer means the microphone
    stays off, which is the safe direction and is asserted above."""

    def test_it_is_stable_when_asked_twice(self):
        self.assertEqual(ears._boot_id(), ears._boot_id())

    def test_it_never_raises_whatever_the_platform_says(self):
        with mock.patch("builtins.open", side_effect=OSError("no /proc")):
            self.assertIsInstance(ears._boot_id(), str)


class OnlyAButtonOpensItCase(EarsCase):
    def test_a_model_may_never_compile_the_command_that_opens_it(self):
        """Same rule as halt and resume, same reason."""
        self.assertIn("mic_on", intercom.PLANNER_FORBIDDEN)

    def test_asking_out_loud_is_answered_rather_than_compiled(self):
        """A forbidden verb that reaches the planner gets SUBSTITUTED.

        CLAUDE.md: "resume yourself" ran `brief` and reported success
        while resuming nothing. So every phrasing that plainly asks for
        the switch is caught before the planner and told about the
        button.
        """
        with mock.patch.object(places, "resolve", side_effect=KeyError("none")):
            for said in ("start listening", "turn on the microphone",
                         "open your ears", "switch the mic on"):
                got = voice.interpret(said)
                self.assertIsNone(got.get("command"), said)
                self.assertIn("button", (got.get("say") or "").lower(), said)

    def test_stopping_is_allowed_from_anywhere_and_never_waits(self):
        """The kill-switch asymmetry: a stop that needs a ceremony is late."""
        with mock.patch.object(places, "resolve", side_effect=KeyError("none")):
            for said in ("stop listening", "turn the microphone off",
                         "close your ears"):
                got = voice.interpret(said)
                self.assertEqual((got.get("command") or {}).get("kind"),
                                 "mic_off", said)
        self.assertEqual(intercom.tier("mic_off"), intercom.TIER_ROUTINE)

    def test_asking_whether_it_is_on_is_read_only_and_always_answerable(self):
        self.assertEqual(intercom.tier("mic"), intercom.TIER_READ)


class TheRoomRefusesCase(EarsCase):
    def test_the_room_opens_no_microphone_when_it_is_off(self):
        """The task and the watchdog stay; what they start opens nothing."""
        from aletheia import voice_room
        with mock.patch.object(voice_room, "listen_forever",
                               side_effect=AssertionError(
                                   "the room opened a microphone while off")), \
             mock.patch.object(voice_room, "check", return_value=0), \
             mock.patch("aletheia.closed.is_closed", return_value=False), \
             mock.patch("aletheia.browser_reasoner.drop_lease", lambda: None):
            self.assertEqual(voice_room.main([]), 0)


if __name__ == "__main__":
    unittest.main()
