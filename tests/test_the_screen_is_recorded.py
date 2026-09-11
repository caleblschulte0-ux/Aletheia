"""Recording one window to a video file (2026-09-11).

TikTok's app review asked for a screen capture of the app in use, and he
wanted Aletheia to make it herself. The rules for that video are the rules
for any recording on a three-screen PC: only the window, never the terminal
beside it, never the desktop.
"""
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import computer, intercom, journal, quick, screenrec

WINDOWS = [
    {"title": "Shorts Media - Profile 1 - Microsoft\u200b Edge", "minimized": False,
     "left": 1920, "top": 0, "width": 1920, "height": 1080},
    {"title": "Olathea repo investigation", "minimized": False,
     "left": 0, "top": 0, "width": 1920, "height": 1040},
    {"title": "New tab - Profile 1 - Microsoft\u200b Edge", "minimized": True,
     "left": -32000, "top": -32000, "width": 160, "height": 28},
]


class RecordingCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        d = Path(self.tmp.name)
        env = mock.patch.dict(os.environ, {"ALETHEIA_PRIVATE_STATE": str(d / "private"),
                                           "ALETHEIA_WORKSPACE": str(d / "ws")})
        env.start()
        self.addCleanup(env.stop)
        for target, attr, value in ((journal, "JOURNAL_PATH", d / "j.jsonl"),
                                    (screenrec, "ffmpeg", lambda: "ffmpeg")):
            p = mock.patch.object(target, attr, value)
            p.start()
            self.addCleanup(p.stop)
        self.spawned = []

    def start(self, window, **kw):
        return screenrec.start(window, listing=WINDOWS,
                               spawner=lambda args: self.spawned.append(args) or 4242, **kw)

    def arg(self, flag):
        args = self.spawned[-1]
        return args[args.index(flag) + 1]


class OnlyTheWindowCase(RecordingCase):
    def test_only_the_named_window_is_recorded_never_the_desktop(self):
        out = self.start("Shorts Media")
        self.assertTrue(out["started"])
        self.assertEqual(self.arg("-f"), "gdigrab")
        self.assertEqual(self.arg("-i"), "desktop")
        self.assertEqual((self.arg("-offset_x"), self.arg("-offset_y")), ("1920", "0"))
        self.assertEqual(self.arg("-video_size"), "1920x1080")
        self.assertIn("-an", self.spawned[-1])
        self.assertTrue(out["path"].endswith(".mp4"))
        self.assertIn("recordings", out["path"])

    def test_a_title_nobody_can_type_still_matches(self):
        out = self.start("shorts media - profile 1 - microsoft edge")
        self.assertEqual(out["window"], WINDOWS[0]["title"])

    def test_minimized_unknown_or_ambiguous_is_refused_not_guessed(self):
        for named in ("New tab", "Nothing like this", "|"):
            with self.subTest(named=named):
                with self.assertRaises(screenrec.RecordingError):
                    self.start(named)
        two = WINDOWS + [dict(WINDOWS[0], title="Inbox - Profile 1 - Microsoft​ Edge", left=0)]
        with self.assertRaises(screenrec.RecordingError) as caught:
            screenrec.find_window("Edge", listing=two)
        self.assertIn("say which", str(caught.exception))
        self.assertEqual(self.spawned, [])

    def test_a_minimized_window_does_not_make_a_name_ambiguous(self):
        # "Edge" is in two titles, and one of those windows is minimized.
        self.assertEqual(screenrec.find_window("Edge", listing=WINDOWS), WINDOWS[0])

    def test_alternatives_the_way_a_planner_writes_them(self):
        """Her first plan named the window "localhost|Shorts|Edge" (2026-09-11)."""
        out = self.start("localhost|Shorts|Edge", name="take")
        self.assertEqual(out["window"], WINDOWS[0]["title"])
        self.assertEqual(screenrec.find_window("^.*Shorts Media.*$", listing=WINDOWS), WINDOWS[0])
        # the first alternative that names ONE window wins; a crowded one is skipped
        two = WINDOWS + [dict(WINDOWS[1], title="Olathea notes")]
        self.assertEqual(screenrec.find_window("Olathea|Shorts", listing=two), WINDOWS[0])

    def test_a_hard_stop_loses_at_most_a_second(self):
        """Her first full take lost its last ~20s to x264's 250-frame keyframes."""
        self.start("Shorts Media")
        self.assertEqual(self.arg("-g"), str(screenrec.DEFAULT_FPS))
        self.assertEqual(self.arg("-tune"), "zerolatency")
        self.assertIn("+frag_keyframe", self.arg("-movflags"))

    def test_it_stops_by_itself(self):
        self.start("Shorts Media", max_seconds=9999)
        self.assertEqual(self.arg("-t"), str(screenrec.MAX_SECONDS))


class StartAndStopCase(RecordingCase):
    def test_one_recording_at_a_time(self):
        self.start("Shorts Media")
        with mock.patch.object(screenrec, "_alive", return_value=True):
            again = self.start("Olathea")
        self.assertFalse(again["started"])
        self.assertEqual(len(self.spawned), 1)

    def test_stop_says_where_the_file_is_and_how_long(self):
        out = self.start("Shorts Media", name="shorts-media-tiktok-review")
        order = []
        with mock.patch.object(screenrec, "_alive", return_value=True):
            done = screenrec.stop(killer=lambda pid: order.append(("kill", pid)),
                                  sleeper=lambda s: order.append(("wait", s)),
                                  finisher=lambda path: 71.0)
        self.assertTrue(done["stopped"])
        self.assertEqual(order, [("wait", screenrec.TAIL_S), ("kill", 4242)],
                         "the last moment on screen gets written before the hard stop")
        self.assertEqual(done["seconds"], 71.0)
        self.assertEqual(done["path"], out["path"])
        self.assertTrue(done["path"].endswith("shorts-media-tiktok-review.mp4"))
        self.assertIsNone(screenrec.current())

    @unittest.skipUnless(os.name == "nt", "console windows are a Windows thing")
    def test_no_helper_process_opens_a_console_window_on_camera(self):
        """His real retake ended with a black tasklist window over the app."""
        calls = []

        def fake_run(args, **kwargs):
            calls.append((args[0], kwargs.get("creationflags", 0)))
            return mock.Mock(stdout="", stderr="", returncode=0)

        with mock.patch.object(screenrec.subprocess, "run", fake_run):
            screenrec._alive(4242)
            screenrec._kill(4242)
            video = Path(self.tmp.name) / "take.mp4"
            video.write_bytes(b"not really a video")
            screenrec._finish(video)
        self.assertEqual({name for name, _ in calls} >= {"tasklist", "taskkill"}, True)
        for name, flags in calls:
            with self.subTest(process=name):
                self.assertTrue(flags & screenrec.subprocess.CREATE_NO_WINDOW, name)

    def test_stopping_nothing_says_so(self):
        self.assertFalse(screenrec.stop()["stopped"])


class SheCanBeToldToCase(RecordingCase):
    def test_the_kinds_are_wired(self):
        for kind in ("screen_record", "screen_record_stop", "recording"):
            self.assertIn(kind, intercom.KIND_ARGS)
            self.assertIn(kind, intercom.LOCAL_KINDS)
            self.assertIn(kind, intercom.KIND_NOTES)
        self.assertIn("recording", intercom.READ_ONLY_KINDS)
        self.assertIn("screen_record", intercom.ROUTINE_KINDS)
        group = next(kinds for kinds in quick.GROUPS.values() if "screenshot" in kinds) \
            if hasattr(quick, "GROUPS") else ()
        if group:
            self.assertIn("screen_record", group)

    def test_asking_while_nothing_records(self):
        self.assertEqual(intercom.execute_command({"kind": "recording"}, {}),
                         "I'm not recording anything.")

    def test_the_view_keys_a_recorded_demo_needs(self):
        for key in ("f11", "ctrl+shift+r", "ctrl+0"):
            self.assertIn(key, computer.SAFE_HOTKEYS)
        for key in ("enter", "alt+f4", "ctrl+w"):
            self.assertNotIn(key, computer.SAFE_HOTKEYS)


if __name__ == "__main__":
    unittest.main()
