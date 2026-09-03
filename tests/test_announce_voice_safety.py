"""Spoken room interruptions are opt-in even though notifications stay live."""
import unittest
from pathlib import Path
from unittest import mock

from aletheia import announce


class AnnounceSafetyCase(unittest.TestCase):
    def test_default_config_never_speaks_first(self):
        self.assertFalse(announce.DEFAULT_CONFIG["enabled"])

    def test_default_disabled_config_does_not_even_read_notifications(self):
        with mock.patch.object(announce.policy, "halted", return_value=False), \
             mock.patch.object(announce.notifications, "all_notifications") as notices:
            self.assertEqual(announce.pending(config=dict(announce.DEFAULT_CONFIG)), [])
        notices.assert_not_called()


class TheRoomIsWhereItActuallyHAPPENS(unittest.TestCase):
    """The capability registry named `voice_room.listen_forever` as this
    module's caller from the day it was written, and that function did not
    mention `announce` at all: an AVAILABLE entry pointing at a caller that
    did not exist. Wired now — and still silent by default, because the
    default config is disabled and a disabled config does not even read the
    notification store."""

    def test_the_room_loop_really_calls_it(self):
        from aletheia.fleet import REPO_ROOT
        body = (REPO_ROOT / "aletheia" / "voice_room.py").read_text(encoding="utf-8")
        self.assertIn("announce.speak_pending", body)

    def test_the_registry_entry_names_a_caller_that_exists(self):
        import json
        from aletheia.fleet import REPO_ROOT
        registry = json.loads(
            (REPO_ROOT / "config" / "capabilities.json").read_text(encoding="utf-8"))
        entry = next(c for c in registry["capabilities"] if c["id"] == "announce.speak")
        self.assertEqual(entry["status"], "AVAILABLE")
        room = (REPO_ROOT / "aletheia" / "voice_room.py").read_text(encoding="utf-8")
        self.assertIn("listen_forever", entry["caller"])
        self.assertIn("def listen_forever", room)

    def test_wiring_it_did_not_make_her_speak_first_by_default(self):
        self.assertFalse(announce.DEFAULT_CONFIG["enabled"])

    def test_the_room_docstring_no_longer_claims_what_is_no_longer_true(self):
        from aletheia import voice_room
        doc = voice_room.listen_forever.__doc__ or ""
        self.assertIn("opt-in", doc.lower())


class ThereIsAnOnSwitCH(unittest.TestCase):
    """Wiring `speak_pending` into the room was only half the fix. The
    feature is off by default — correctly, she must not start talking at him
    unasked — and until this existed there was NO WAY to turn it on short of
    hand-writing ~/.aletheia/announce.json. A capability with no on-switch
    is not opt-in, it is unavailable with extra steps."""

    def setUp(self):
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cfg = Path(self.tmp.name) / "announce.json"
        p = mock.patch.object(announce, "CONFIG_FILE", self.cfg)
        p.start(); self.addCleanup(p.stop)
        j = mock.patch.object(announce.journal, "append")
        j.start(); self.addCleanup(j.stop)

    def test_it_can_be_turned_on_and_back_off(self):
        self.assertTrue(announce.set_enabled(True)["enabled"])
        self.assertTrue(announce.load_config()["enabled"])
        self.assertFalse(announce.set_enabled(False)["enabled"])

    def test_quiet_hours_are_settable_and_validated(self):
        announce.set_quiet_hours("23:00", "08:00")
        self.assertEqual(announce.load_config()["quiet_from"], "23:00")
        with self.assertRaises(Exception):
            announce.set_quiet_hours("not a time", "08:00")

    def test_turning_it_on_is_journaled(self):
        announce.set_enabled(True, via="test")
        announce.journal.append.assert_called()

    def test_he_can_say_it_rather_than_edit_a_file(self):
        """A setting only reachable by hand-editing JSON is not reachable."""
        from aletheia import intercom
        self.assertIn("announce_set", intercom.KIND_ARGS)
        self.assertIn("announce_set", intercom.ROUTINE_KINDS)
        self.assertIn("announce_set", intercom.KIND_NOTES)

    def test_saying_it_really_changes_the_setting(self):
        from aletheia import intercom
        said = intercom.execute_command(
            {"kind": "announce_set", "on": True}, fleet={}, quote="he said so")
        self.assertTrue(announce.load_config()["enabled"])
        self.assertIn("speak up", said)
        intercom.execute_command({"kind": "announce_set", "on": False},
                                 fleet={}, quote="he said so")
        self.assertFalse(announce.load_config()["enabled"])

    def test_the_off_state_says_how_to_turn_it_on(self):
        """"I don't speak up on my own" with no next step is a dead end."""
        self.assertIn("start telling me", announce.spoken())


if __name__ == "__main__":
    unittest.main()
