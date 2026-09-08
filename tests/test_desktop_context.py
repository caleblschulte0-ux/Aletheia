"""Foreground context stays read-only, bounded, and private by default."""
import datetime as dt
import json
import unittest

from aletheia import desktop_context

NOW = dt.datetime(2026, 8, 31, 12, tzinfo=dt.timezone.utc)


class FakeBackend:
    def __init__(self):
        self.clipboard_reads = 0

    def foreground(self):
        return {"title": "Quarterly plan - token sk-abcdefghijklmnopqrstuvwx",
                "process_id": 42,
                "process_path": r"C:\\Program Files\\Editor\\editor.exe"}

    def clipboard_text(self):
        self.clipboard_reads += 1
        return "private clipboard value"


class DesktopContextCase(unittest.TestCase):
    def test_default_capture_never_reads_the_clipboard(self):
        backend = FakeBackend()
        observed = desktop_context.capture(backend, now=NOW)
        self.assertEqual(backend.clipboard_reads, 0)
        self.assertIsNone(observed.clipboard)

    def test_diagnostics_hash_private_values_instead_of_emitting_them(self):
        backend = FakeBackend()
        observed = desktop_context.capture(
            backend, now=NOW, include_clipboard=True)
        blob = json.dumps(observed.metadata())
        self.assertNotIn("Quarterly plan", blob)
        self.assertNotIn("private clipboard", blob)
        self.assertNotIn("Program Files", blob)
        self.assertIn("editor.exe", blob)

    def test_reasoning_discloses_clipboard_only_with_explicit_opt_in(self):
        observed = desktop_context.capture(
            FakeBackend(), now=NOW, include_clipboard=True)
        self.assertNotIn("text", observed.reasoning_context()["clipboard"])
        self.assertEqual(
            observed.reasoning_context(include_clipboard=True)["clipboard"]["text"],
            "private clipboard value")

    def test_invalid_backend_shape_is_refused(self):
        backend = FakeBackend()
        backend.foreground = lambda: {"title": "x", "surprise": "instruction"}
        with self.assertRaises(ValueError):
            desktop_context.capture(backend, now=NOW)


if __name__ == "__main__":
    unittest.main()
