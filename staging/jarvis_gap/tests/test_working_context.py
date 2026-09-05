from __future__ import annotations

import datetime as dt
import tempfile
import unittest
from pathlib import Path

from staging.jarvis_gap.working_context import (
    ContextFact,
    ProjectBinding,
    WorkingContext,
    project_for_file,
)

UTC = dt.timezone.utc


class WorkingContextTests(unittest.TestCase):
    def setUp(self):
        self.now = dt.datetime(2026, 8, 30, 22, 0, tzinfo=UTC)

    def test_sensitive_diagnostics_redacted(self):
        fact = ContextFact("clipboard", "secret", "windows.clipboard", self.now)
        diagnostic = fact.diagnostic()
        self.assertNotIn("secret", repr(diagnostic))
        self.assertTrue(diagnostic["value_redacted"])

    def test_clipboard_is_reasoning_opt_in(self):
        context = WorkingContext(now=self.now)
        context.add(ContextFact("clipboard", "secret", "windows.clipboard", self.now))
        self.assertNotIn("clipboard", context.reasoning_view())
        self.assertEqual(
            context.reasoning_view(include_clipboard=True)["clipboard"]["value"],
            "secret",
        )

    def test_stale_fact_refused(self):
        context = WorkingContext(now=self.now, max_age_s=60)
        with self.assertRaisesRegex(ValueError, "stale"):
            context.add(ContextFact(
                "active_app", "Code", "windows",
                self.now - dt.timedelta(seconds=61),
            ))

    def test_ambiguous_same_time_fact_refused(self):
        context = WorkingContext(now=self.now)
        context.add(ContextFact("active_window", "A", "provider.a", self.now, 0.9))
        with self.assertRaisesRegex(LookupError, "ambiguous"):
            context.add(ContextFact("active_window", "B", "provider.b", self.now, 0.9))

    def test_project_binding_uses_longest_root(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            repo = base / "repo"
            repo.mkdir()
            selected = repo / "src.py"
            selected.write_text("x", encoding="utf-8")
            bindings = [
                ProjectBinding("broad", str(base)),
                ProjectBinding("repo", str(repo)),
            ]
            self.assertEqual(project_for_file(selected, bindings), "repo")

    def test_derive_project_keeps_provenance(self):
        with tempfile.TemporaryDirectory() as directory:
            selected = Path(directory) / "x.py"
            selected.write_text("x", encoding="utf-8")
            context = WorkingContext(now=self.now)
            context.add(ContextFact("selected_file", str(selected), "editor", self.now))
            self.assertEqual(
                context.derive_project([ProjectBinding("p", directory)]),
                "p",
            )
            self.assertEqual(
                context.reasoning_view()["project_id"]["source"],
                "derived:selected_file",
            )


if __name__ == "__main__":
    unittest.main()
