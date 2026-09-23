"""Nine everyday sentences with every frontier off (2026-09-22 evening):
"turn the volume up" said "That failed: KeyError: 'volume_up'"; "do I have
any reminders set", "lock the computer" and "close chrome" waited two
minutes on her own model; "what's my ip address" searched his contacts for
"my ip"; the disk, the internet and the open windows were answered by her
own model DENYING it could look; "open my downloads folder" became a web
page. Every one is a system call, a store, or a door she already had."""
from __future__ import annotations

import pathlib
import tempfile
import unittest
from unittest import mock

from aletheia import computer, music, quick, rule_planner, voice


class VolumeCase(unittest.TestCase):
    def test_every_key_has_a_sentence(self):
        with mock.patch("aletheia.music.press", return_value=True), \
             mock.patch("aletheia.music.player_running", return_value=True), \
             mock.patch("aletheia.journal.append"):
            for key in music.KEYS:
                with self.subTest(key=key):
                    said = music.control(key)
                    self.assertTrue(said and said[0].isupper(), said)
                    self.assertNotIn("KeyError", said)
            self.assertEqual(music.control("volume_up"), "Louder.")

    def test_the_voice_shape_names_the_key(self):
        self.assertEqual(voice.interpret("thea turn the volume up")["command"],
                         {"kind": "music", "action": "volume_up"})


class RemindersQuestionCase(unittest.TestCase):
    def test_the_yes_no_shape_reads_the_store(self):
        for said in ("thea do I have any reminders set", "thea any reminders", "thea are there any reminders coming up"):
            with self.subTest(said=said):
                self.assertEqual(voice.interpret(said)["command"], {"kind": "reminders"})


class WhatSongCase(unittest.TestCase):
    def test_she_says_what_the_media_keys_cannot_tell_her(self):
        out = voice.interpret("thea what song is this")
        self.assertIsNone(out["command"])
        self.assertIn("can't see what's playing", out["say"])


class MachineReadingsCase(unittest.TestCase):
    def test_my_ip_is_not_a_contact(self):
        out = voice.interpret("thea what's my ip address")
        self.assertNotEqual((out.get("command") or {}).get("kind"), "contacts")
        with mock.patch("aletheia.machine.ip_address", return_value="192.168.1.20"):
            self.assertIn("192.168.1.20", quick.answer("what's my ip address"))
        with mock.patch("aletheia.machine.ip_address", return_value=""):
            self.assertIn("offline", quick.answer("what is my ip"))

    def test_disk_space_is_read_not_denied(self):
        with mock.patch("aletheia.machine.disk", return_value={"total": 475 * 1024 ** 3, "free": 265 * 1024 ** 3}):
            said = quick.answer("how much disk space do I have")
        self.assertIn("265 GB free of 475 GB", said)
        with mock.patch("aletheia.machine.disk", return_value={"total": 475 * 1024 ** 3, "free": 4 * 1024 ** 3}):
            self.assertIn("tight", quick.answer("is my computer low on space"))

    def test_the_internet_is_checked_not_guessed(self):
        with mock.patch("aletheia.machine.internet_reachable", return_value=True) as probe:
            self.assertTrue(quick.answer("is the internet working").startswith("Yes"))
            probe.assert_called_once()
        with mock.patch("aletheia.machine.internet_reachable", return_value=False):
            self.assertTrue(quick.answer("am I online").startswith("No"))

    def test_open_windows_are_named_by_program(self):
        titles = ["● notes.txt - Notepad", "GitHub - Google Chrome", "Inbox - Microsoft​ Edge",
                  "Settings", "Other tab - Google Chrome"]
        with mock.patch("aletheia.machine.open_windows", return_value=titles):
            said = quick.answer("what apps are open")
        self.assertEqual(said, "Open right now: Notepad, Google Chrome, Microsoft Edge and Settings.")
        with mock.patch("aletheia.machine.open_windows", return_value=[]):
            self.assertIn("can't see", quick.answer("what's open right now"))

    def test_the_readings_never_raise(self):
        # Off Windows these come back empty rather than wrong.
        from aletheia import machine
        self.assertIsInstance(machine.open_windows(), list)
        self.assertIsInstance(machine.app_of(""), str)


class DesktopRulesCase(unittest.TestCase):
    def test_lock_is_a_door_unattended_hands_have(self):
        kind, args, summary = rule_planner.match("lock the computer")
        self.assertEqual((kind, args), ("computer_do", {"steps": [{"action": "lock_screen"}]}))
        self.assertIn("lock_screen", computer.ACT_ACTIONS)
        self.assertEqual(computer.validate_steps(args["steps"]), [])
        self.assertEqual(rule_planner.match("lock it")[0], "computer_do")

    def test_close_says_what_she_does_not_do(self):
        kind, args, _ = rule_planner.match("close chrome")
        self.assertEqual(kind, rule_planner.ANSWER)
        self.assertIn("don't close programs", args["say"])
        self.assertIn("Chrome", args["say"])
        self.assertIsNone(rule_planner.match("close the deal"))

    def test_a_named_folder_opens_in_explorer(self):
        with tempfile.TemporaryDirectory() as home:
            (pathlib.Path(home) / "Downloads").mkdir()
            with mock.patch("pathlib.Path.home", return_value=pathlib.Path(home)):
                kind, args, summary = rule_planner.match("open my downloads folder")
                self.assertEqual(kind, "computer_do")
                step = args["steps"][0]
                self.assertEqual(step["app"], "explorer.exe")
                self.assertTrue(step["arguments"][0].endswith("Downloads"))
                self.assertEqual(summary, "Open your Downloads folder")
                self.assertEqual(computer.validate_steps(args["steps"]), [])
                kind, args, _ = rule_planner.match("open my pictures folder")
                self.assertEqual(kind, rule_planner.ANSWER)
                self.assertIn("no Pictures folder", args["say"])
        self.assertIsNone(rule_planner.match("open the secret folder"))


if __name__ == "__main__":
    unittest.main()
