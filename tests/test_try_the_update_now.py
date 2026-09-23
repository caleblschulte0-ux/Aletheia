""""I haven't managed to update myself for 40 minutes" had no next step
(2026-09-23): a restart picks up nothing while the pull is refused, and
the loop tries again by itself every minute. "Try the update now" is one
beat of her own sync loop, on his tap, under the loop's own lock, and
what happened in words."""
from __future__ import annotations

import unittest
from unittest import mock

from aletheia import agenda, core, intercom, running, voice


class TryTheUpdateNowCase(unittest.TestCase):
    def test_one_beat_under_the_lock_and_the_words(self):
        beats = []

        def beat():
            beats.append(1)
            core.SYNC_STATUS["pull"] = {"ok": True, "detail": "up to date"}
        with mock.patch.dict(core._UPDATE_HOOK, {"fn": beat}), \
             mock.patch.dict(core.SYNC_STATUS, {"pull": None, "restarting": False}), \
             mock.patch("aletheia.journal.append"):
            ok, said = core.request_update_now("his tap")
        self.assertTrue(ok)
        self.assertEqual(beats, [1])
        self.assertEqual(said, "up to date")

    def test_still_stuck_says_the_reason_in_words(self):
        def beat():
            core.SYNC_STATUS["pull"] = {"ok": False, "detail": "you have unmerged files (journal-abc123.jsonl)"}
        with mock.patch.dict(core._UPDATE_HOOK, {"fn": beat}), \
             mock.patch.dict(core.SYNC_STATUS, {"pull": None}), \
             mock.patch("aletheia.journal.append"):
            ok, said = core.request_update_now("his tap")
        self.assertFalse(ok)
        self.assertTrue(said.startswith("still stuck:"), said)

    def test_nothing_running_is_refused_not_pretended(self):
        with mock.patch.dict(core._UPDATE_HOOK, {"fn": None}):
            ok, said = core.request_update_now("a test")
            self.assertFalse(ok)
            with self.assertRaises(Exception) as caught:
                intercom.execute_command({"kind": "update_now"}, {})
            self.assertIn("start her from the PC", str(caught.exception))

    def test_the_health_line_offers_it_when_stuck(self):
        state = {"parts": [{"part": "core", "up": True}], "closed": False, "halted": False,
                 "listening": True, "running_old_code": False, "tasks": {},
                 "update_stuck": {"for_s": 4000, "waiting": 3}}
        with mock.patch("aletheia.running._by_design", return_value=False):
            self.assertEqual(running.action(state), {"label": "Try the update now", "kind": "update_now"})

    def test_no_model_and_no_agenda_may_say_it_but_he_can(self):
        self.assertIn("update_now", intercom.PLANNER_FORBIDDEN)
        self.assertIn("update_now", agenda.FORBIDDEN_KINDS)
        for said in ("thea update yourself", "thea check for updates", "thea pull the latest code"):
            with self.subTest(said=said):
                self.assertEqual(voice.interpret(said)["command"]["kind"], "update_now")
        self.assertNotEqual((voice.interpret("thea update my resume").get("command") or {}).get("kind"), "update_now")


if __name__ == "__main__":
    unittest.main()
