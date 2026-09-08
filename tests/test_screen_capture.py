"""Photographing the desktop: the picture, and the sentence about it.

Two things needed guarding here and they fail differently. The ENCODER
can be checked anywhere, because a PNG is a PNG - and it is worth
checking properly, since every cheap assertion about a screenshot (it
has bytes, it is the right size, it decodes) passes just as happily on a
black rectangle. The CAPTURE itself only means anything on Windows with
a desktop attached, so it skips elsewhere rather than failing the suite
on a machine that has no screen.
"""
from __future__ import annotations

import datetime as dt
import struct
import unittest
import zlib

from aletheia import screen


def decode(png: bytes) -> tuple[int, int, bytes]:
    """Minimal PNG reader: enough to prove what the encoder wrote."""
    assert png[:8] == b"\x89PNG\r\n\x1a\n", "not a PNG"
    pos, width, height, idat = 8, 0, 0, b""
    while pos < len(png):
        length = struct.unpack(">I", png[pos:pos + 4])[0]
        tag = png[pos + 4:pos + 8]
        data = png[pos + 8:pos + 8 + length]
        stored = struct.unpack(">I", png[pos + 8 + length:pos + 12 + length])[0]
        if zlib.crc32(tag + data) & 0xFFFFFFFF != stored:
            raise AssertionError(f"chunk {tag!r} has a bad CRC")
        if tag == b"IHDR":
            width, height, depth, colour = struct.unpack(">IIBB", data[:10])
            assert (depth, colour) == (8, 2), "expected 8-bit truecolour"
        elif tag == b"IDAT":
            idat += data
        pos += 12 + length
    raw = zlib.decompress(idat)
    stride = width * 3
    rows = []
    for y in range(height):
        start = y * (stride + 1)
        assert raw[start] == 0, "only filter type 0 is written"
        rows.append(raw[start + 1:start + 1 + stride])
    return width, height, b"".join(rows)


class PngEncoderCase(unittest.TestCase):
    """The encoder, checked against a picture whose pixels are known."""

    def test_it_writes_back_exactly_the_pixels_it_was_given(self):
        width, height = 7, 5
        # three bytes per pixel, row major, every row distinguishable
        flat = bytearray()
        for y in range(height):
            for x in range(width):
                flat += bytes([(x * 30) % 256, (y * 50) % 256, 7])
        png = screen._png(bytes(flat), width, height)
        out_w, out_h, body = decode(png)
        self.assertEqual((out_w, out_h), (width, height))
        self.assertEqual(body, bytes(flat))

    def test_the_bytes_are_a_real_png_with_valid_checksums(self):
        flat = bytes([9, 9, 9]) * 4
        decode(screen._png(flat, 2, 2))   # decode() asserts every CRC


class ScalingCase(unittest.TestCase):
    def test_a_small_screen_is_never_scaled_up(self):
        self.assertEqual(screen._target_size(800, 600, 1024), (800, 600, 1.0))

    def test_a_wide_desktop_is_fitted_by_its_longest_edge(self):
        w, h, scale = screen._target_size(5760, 1080, 1024)
        self.assertEqual((w, h), (1024, 192))
        self.assertAlmostEqual(scale, 1024 / 5760, places=4)

    def test_an_edge_never_rounds_away_to_zero(self):
        """A pathological aspect ratio must not produce a zero-width image."""
        w, h, _ = screen._target_size(4000, 3, 100)
        self.assertGreaterEqual(h, 1)
        self.assertGreaterEqual(w, 1)


class RefusalCase(unittest.TestCase):
    def test_an_unknown_monitor_is_refused(self):
        with self.assertRaises(ValueError):
            screen.capture(monitor="the good one")

    def test_an_absurd_size_is_refused_rather_than_allocated(self):
        with self.assertRaises(ValueError):
            screen.capture(max_edge=screen.MAX_EDGE_LIMIT + 1)

    def test_a_boolean_is_not_a_size(self):
        """True is an int in Python, and 1x1 is not what anybody meant."""
        with self.assertRaises(ValueError):
            screen.capture(max_edge=True)

    def test_looking_is_not_pressing(self):
        """The module has no way to act, by construction rather than by check."""
        source = (screen.__file__ or "")
        text = open(source, encoding="utf-8").read()
        for forbidden in ("SendInput", "mouse_event", "keybd_event",
                          "SetForegroundWindow", "SetCursorPos"):
            self.assertNotIn(forbidden, text,
                             f"{forbidden} would make this able to act")


@unittest.skipUnless(screen.available(), "desktop capture is Windows-only")
class LiveCaptureCase(unittest.TestCase):
    def test_it_photographs_a_real_screen(self):
        shot = screen.capture(max_edge=320)
        self.assertLessEqual(max(shot.width, shot.height), 320)
        width, height, body = decode(shot.png)
        self.assertEqual((width, height), (shot.width, shot.height))
        self.assertEqual(len(body), width * height * 3)

    def test_the_picture_is_not_a_blank_rectangle(self):
        """Every other check here passes on a black image.

        A capture that silently returns an empty frame is the worst
        outcome, because a vision model will describe it confidently.
        """
        shot = screen.capture(max_edge=320)
        _, _, body = decode(shot.png)
        self.assertGreater(len(set(body)), 8,
                           "the captured screen has almost no distinct values, "
                           "which is what a blank capture looks like")

    def test_metadata_carries_shape_and_identity_but_never_pixels(self):
        shot = screen.capture(max_edge=320)
        meta = shot.metadata()
        self.assertEqual(meta["sha256"], shot.digest)
        self.assertEqual(meta["bytes"], len(shot.png))
        self.assertNotIn("png", meta)
        for value in meta.values():
            self.assertNotIsInstance(value, (bytes, bytearray))

    def test_the_bytes_stay_out_of_repr(self):
        """A screenshot in a traceback is his screen in a log file."""
        shot = screen.capture(max_edge=320)
        self.assertNotIn("png=", repr(shot))

    def test_captured_at_is_timezone_aware(self):
        shot = screen.capture(max_edge=320)
        self.assertIsNotNone(shot.captured_at.tzinfo)
        self.assertIsNotNone(shot.captured_at.utcoffset())
        self.assertIsInstance(shot.captured_at, dt.datetime)


if __name__ == "__main__":
    unittest.main()
