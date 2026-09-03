"""Editing video, and the three things that stop it destroying work.

The last genuine zero: "I need you to edit this video" had no capability
behind it at all — not even a ticket. Video is also where a mistake is
most expensive, because a re-encode is lossy and an overwritten master is
gone, so the tests are mostly about what it refuses to do to the source.
"""
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import journal, media, policy, workspace

FFMPEG_OK, FFMPEG_WHY = media.available()
needs_ffmpeg = unittest.skipUnless(FFMPEG_OK, f"ffmpeg absent: {FFMPEG_WHY}")


def ok(*a, **k):
    return subprocess.CompletedProcess(a[0] if a else [], 0, stdout="", stderr="")


class MediaCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "ws"
        self.root.mkdir()
        env = mock.patch.dict(os.environ, {"ALETHEIA_WORKSPACE": str(self.root)})
        env.start(); self.addCleanup(env.stop)
        for target, attr, value in (
                (journal, "JOURNAL_PATH", Path(self.tmp.name) / "j.jsonl"),
                (policy, "HALT_PATH", Path(self.tmp.name) / "halt.json")):
            p = mock.patch.object(target, attr, value)
            p.start(); self.addCleanup(p.stop)
        self.have = mock.patch.object(media, "available", return_value=(True, "ok"))
        self.have.start(); self.addCleanup(self.have.stop)
        self.source = self.root / "clip.mp4"
        self.source.write_bytes(b"not really a video, but a real file")

    def made(self, name="out.mp4"):
        """Stand in for ffmpeg actually producing the output."""
        def fake(cmd, **kwargs):
            (self.root / name).write_bytes(b"rendered")
            return ok(cmd)
        return fake


class AbsenceIsReportedNotRaised(unittest.TestCase):
    """ffmpeg is a program, not a package — it cannot be installed from
    inside a run, so a caller must be able to degrade rather than crash."""

    def test_available_returns_a_verdict_and_never_raises(self):
        was, why = media.available()
        self.assertIsInstance(was, bool)
        self.assertTrue(why.strip())
        if not was:
            self.assertIn("ffmpeg", why.lower())
            self.assertIn("install", why.lower(), "an absence must say how to fix it")

    def test_every_operation_refuses_cleanly_when_ffmpeg_is_missing(self):
        with mock.patch.object(media, "available", return_value=(False, "not here")):
            with self.assertRaises(media.MediaError):
                media.run(["-i", "x"], what="anything")


class TheSourceIsNeverTouched(MediaCase):
    """A re-encode is lossy and an overwritten master is gone."""

    def test_output_must_land_in_the_workspace(self):
        for escape in ("../out.mp4", "/tmp/out.mp4", "C:/out.mp4"):
            with self.subTest(out=escape):
                with self.assertRaises(workspace.OutsideWorkspace):
                    media._destination(escape)

    def test_the_source_survives_an_operation(self):
        before = self.source.read_bytes()
        with mock.patch.object(media.proc, "run", side_effect=self.made()):
            media.trim("clip.mp4", "out.mp4", start="1", duration="2")
        self.assertEqual(self.source.read_bytes(), before, "the master is read-only")

    def test_there_is_no_flag_that_overwrites_a_source(self):
        source = (Path(__file__).parent.parent / "aletheia" / "media.py"
                  ).read_text(encoding="utf-8")
        for escape in ("in_place", "overwrite_source", "replace_source"):
            self.assertNotIn(escape, source, escape)

    def test_a_non_media_output_is_refused(self):
        with self.assertRaises(media.MediaError):
            media._destination("notes.txt")


class ItReportsFailureHonestly(MediaCase):
    """§30: 'command executed' is not 'goal achieved'."""

    def test_a_nonzero_exit_raises_with_the_reason(self):
        fail = subprocess.CompletedProcess([], 1, stdout="",
                                           stderr="x\nInvalid data found\n")
        with mock.patch.object(media.proc, "run", return_value=fail):
            with self.assertRaises(media.MediaError) as caught:
                media.trim("clip.mp4", "out.mp4")
        self.assertIn("Invalid data", str(caught.exception))

    def test_a_missing_output_is_a_failure_even_when_ffmpeg_said_nothing(self):
        with mock.patch.object(media.proc, "run", side_effect=ok):
            with self.assertRaises(media.MediaError) as caught:
                media.trim("clip.mp4", "out.mp4")
        self.assertIn("produced no file", str(caught.exception))

    def test_an_empty_output_is_also_a_failure(self):
        def empty(cmd, **kwargs):
            (self.root / "out.mp4").write_bytes(b"")
            return ok(cmd)
        with mock.patch.object(media.proc, "run", side_effect=empty):
            with self.assertRaises(media.MediaError):
                media.trim("clip.mp4", "out.mp4")

    def test_a_hung_render_is_stopped_rather_than_waited_on_forever(self):
        with mock.patch.object(media.proc, "run",
                               side_effect=subprocess.TimeoutExpired("ffmpeg", 1)):
            with self.assertRaises(media.MediaError) as caught:
                media.trim("clip.mp4", "out.mp4")
        self.assertIn("stopped", str(caught.exception))


class ItIsNotAShell(MediaCase):
    def test_ffmpeg_is_invoked_with_an_argument_list(self):
        seen = {}

        def capture(cmd, **kwargs):
            seen["cmd"] = cmd
            (self.root / "out.mp4").write_bytes(b"x")
            return ok(cmd)

        with mock.patch.object(media.proc, "run", side_effect=capture):
            media.trim("clip.mp4", "out.mp4", start="1")
        self.assertIsInstance(seen["cmd"], list,
                              "a list, never a shell string — a filename with a "
                              "quote in it is a filename, not an injection")
        self.assertEqual(seen["cmd"][0], "ffmpeg")

    def test_a_filename_with_a_quote_stays_one_argument(self):
        awkward = self.root / "it's a clip.mp4"
        awkward.write_bytes(b"x")
        seen = {}

        def capture(cmd, **kwargs):
            seen["cmd"] = cmd
            (self.root / "out.mp4").write_bytes(b"x")
            return ok(cmd)

        with mock.patch.object(media.proc, "run", side_effect=capture):
            media.trim("it's a clip.mp4", "out.mp4")
        self.assertIn(str(awkward), seen["cmd"])


class TheOperationsBehave(MediaCase):
    def test_trim_refuses_both_an_end_and_a_duration(self):
        with self.assertRaises(media.MediaError):
            media.trim("clip.mp4", "out.mp4", end="5", duration="5")

    def test_trim_re_encodes_rather_than_stream_copying(self):
        """A stream copy cuts only on keyframes, so 'start at 1:05' silently
        becomes 1:03 and the clip is wrong in a way nobody notices."""
        seen = {}

        def capture(cmd, **kwargs):
            seen["cmd"] = cmd
            (self.root / "out.mp4").write_bytes(b"x")
            return ok(cmd)

        with mock.patch.object(media.proc, "run", side_effect=capture):
            media.trim("clip.mp4", "out.mp4", start="1:05", duration="10")
        self.assertIn("libx264", seen["cmd"])
        self.assertNotIn("copy", seen["cmd"])

    def test_joining_needs_at_least_two_files(self):
        with self.assertRaises(media.MediaError):
            media.join(["clip.mp4"], "out.mp4")

    def test_joining_cleans_up_its_input_list(self):
        second = self.root / "clip2.mp4"
        second.write_bytes(b"also a file")
        with mock.patch.object(media.proc, "run", side_effect=self.made()):
            media.join(["clip.mp4", "clip2.mp4"], "out.mp4")
        self.assertEqual(list(self.root.glob(".*-inputs.txt")), [],
                         "the temporary concat list is not left behind")

    def test_extracting_audio_must_produce_an_audio_file(self):
        with self.assertRaises(media.MediaError):
            media.extract_audio("clip.mp4", "out.mp4")

    def test_subtitles_must_be_a_subtitle_format(self):
        with self.assertRaises(media.MediaError):
            media.burn_subtitles("clip.mp4", "clip.mp4", "out.mp4")

    def test_convert_validates_the_height(self):
        for bad in (0, 10, 99_999, 1.5):
            with self.subTest(height=bad):
                with self.assertRaises(media.MediaError):
                    media.convert("clip.mp4", "out.mp4", height=bad)


class ItStopsWhenToldTo(MediaCase):
    def test_halt_prevents_a_render(self):
        policy.halt("stop", via="test")
        with mock.patch.object(media.proc, "run", side_effect=self.made()) as run:
            with self.assertRaises(policy.Halted):
                media.trim("clip.mp4", "out.mp4")
        run.assert_not_called()


@needs_ffmpeg
class AgainstRealFfmpeg(MediaCase):
    """Runs only where ffmpeg exists. Proves the argument shapes are right
    rather than merely well-mocked."""

    def test_a_generated_clip_can_be_trimmed_and_probed(self):
        src = self.root / "generated.mp4"
        subprocess.run(
            ["ffmpeg", "-nostdin", "-y", "-f", "lavfi", "-i",
             "testsrc=duration=3:size=128x128:rate=10", str(src)],
            capture_output=True, check=True, timeout=120)
        media.trim("generated.mp4", "cut.mp4", start="0", duration="1")
        info = media.probe("cut.mp4")
        self.assertLess(info["seconds"], 3)
        self.assertTrue(info["video"])


if __name__ == "__main__":
    unittest.main()
