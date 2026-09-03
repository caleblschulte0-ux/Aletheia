"""She writes the thing, instead of writing a description of the thing.

    "summarize my resume into three bullets and save it as summary.md"
      → file_write(path="summary.md",
                   text="Three-bullet summary of resume, generated from
                         the resume content retrieved above.")

EXECUTABLE. Validating clean. And it would have put that exact sentence
in his file — not a summary, a note promising one.

The cause is structural. The planner is a COMPILER, and
`file_write(path, text)` demands the finished text as an argument at
compile time, before anything has been read. So "write me a note about X
and save it" had only two outcomes available: a clarifying question or a
placeholder, and which one it got was luck.
"""
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import compose, journal, policy, workspace


class ComposeCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        d = Path(self.tmp.name)
        self.ws = d / "ws"
        self.ws.mkdir()
        env = mock.patch.dict(os.environ, {"ALETHEIA_WORKSPACE": str(self.ws),
                                           "ALETHEIA_PRIVATE_STATE": str(d)})
        env.start(); self.addCleanup(env.stop)
        for target, attr, value in ((journal, "JOURNAL_PATH", d / "j.jsonl"),
                                    (policy, "HALT_PATH", d / "halt.json")):
            p = mock.patch.object(target, attr, value)
            p.start(); self.addCleanup(p.stop)

    def writes(self, text="- one\n- two\n- three"):
        seen = {}

        def fake(system, prompt, **kwargs):
            seen["system"] = system
            seen["prompt"] = prompt
            return text
        self.seen = seen
        return fake


class ItProducesTheDocument(ComposeCase):
    def test_the_file_holds_the_content_not_a_promise_of_it(self):
        out = compose.compose("three bullets about the plan", "summary.md",
                              think=self.writes())
        self.assertEqual((self.ws / "summary.md").read_text(),
                         "- one\n- two\n- three")
        self.assertEqual(out["chars"], len("- one\n- two\n- three"))

    def test_the_sources_are_really_read_before_it_writes(self):
        """The whole point: at execution time the file exists to be read."""
        (self.ws / "resume.md").write_text("Ran a six-video-a-day pipeline.")
        compose.compose("summarise it", "summary.md", sources=["resume.md"],
                        think=self.writes())
        self.assertIn("Ran a six-video-a-day pipeline.", self.seen["prompt"])

    def test_it_is_told_to_produce_the_document_and_nothing_else(self):
        compose.compose("a note", "note.md", think=self.writes())
        flat = " ".join(self.seen["system"].split())
        self.assertIn("DOCUMENT ITSELF and nothing else", flat)
        self.assertIn("no preamble", flat)

    def test_overwriting_keeps_the_previous_version(self):
        compose.compose("v1", "note.md", think=self.writes("first"))
        out = compose.compose("v2", "note.md", think=self.writes("second"))
        self.assertFalse(out["created"])
        self.assertTrue(out["previous"])
        self.assertEqual((self.ws / "note.md").read_text(), "second")


class ItNeverPretends(ComposeCase):
    def test_every_source_unreadable_writes_NOTHING(self):
        """Composing anyway is exactly the confident placeholder this
        module exists to abolish."""
        with self.assertRaises(compose.ComposeError) as caught:
            compose.compose("summarise it", "summary.md",
                            sources=["nope.md"], think=self.writes())
        self.assertIn("could not read", str(caught.exception))
        self.assertIn("Nothing was saved", str(caught.exception))
        self.assertFalse((self.ws / "summary.md").exists())

    def test_one_source_missing_is_declared_not_hidden(self):
        (self.ws / "a.md").write_text("real content")
        out = compose.compose("summarise", "s.md", sources=["a.md", "nope.md"],
                              think=self.writes())
        self.assertEqual(len(out["composed_from"]), 1)
        self.assertTrue(out["unreadable"])
        self.assertIn("do not invent the rest", self.seen["prompt"])

    def test_a_model_that_refuses_does_not_become_a_file(self):
        with self.assertRaises(compose.ComposeError):
            compose.compose("something impossible", "x.md",
                            think=self.writes("CANNOT WRITE: I have no idea "
                                              "what the backup plan is."))
        self.assertFalse((self.ws / "x.md").exists())

    def test_an_unreachable_model_saves_nothing_and_says_why(self):
        def dead(*a, **k):
            raise RuntimeError("Claude CLI is not on PATH")
        with self.assertRaises(compose.ComposeError) as caught:
            compose.compose("a note", "x.md", think=dead)
        self.assertIn("Claude CLI is not on PATH", str(caught.exception))
        self.assertIn("Nothing was saved", str(caught.exception))

    def test_an_empty_answer_is_not_an_empty_file(self):
        with self.assertRaises(compose.ComposeError):
            compose.compose("a note", "x.md", think=self.writes("   "))
        self.assertFalse((self.ws / "x.md").exists())


class ItAddsNoREACH(ComposeCase):
    """Same directory, same version history, same undo. Nothing wider."""

    def test_it_cannot_write_outside_the_workspace(self):
        with self.assertRaises(workspace.OutsideWorkspace):
            compose.compose("a note", "../escaped.md", think=self.writes())

    def test_an_absolute_path_is_refused_like_any_other_write(self):
        with self.assertRaises(workspace.OutsideWorkspace):
            compose.compose("a note", "/etc/passwd", think=self.writes())

    def test_a_halt_stops_it(self):
        policy.halt("stopped", via="test")
        with self.assertRaises(Exception):
            compose.compose("a note", "x.md", think=self.writes())

    def test_it_writes_through_workspace_rather_than_its_own_file_io(self):
        source = (Path(__file__).parent.parent / "aletheia" / "compose.py"
                  ).read_text(encoding="utf-8")
        self.assertIn("workspace.write(", source)
        for raw in ("open(", "write_text(", "Path("):
            self.assertNotIn(raw, source, raw)

    def test_the_instruction_is_bounded(self):
        with self.assertRaises(ValueError):
            compose.compose("x" * 9_000, "x.md", think=self.writes())
        for empty in ("", "   "):
            with self.assertRaises(ValueError):
                compose.compose(empty, "x.md", think=self.writes())
            with self.assertRaises(ValueError):
                compose.compose("a note", empty, think=self.writes())

    def test_it_reads_at_most_three_sources(self):
        for i in range(5):
            (self.ws / f"f{i}.md").write_text(f"content {i}")
        out = compose.compose("compare", "s.md",
                              sources=[f"f{i}.md" for i in range(5)],
                              think=self.writes())
        self.assertEqual(len(out["composed_from"]), compose.MAX_SOURCES)


class TheGrammarSteersTowardIt(unittest.TestCase):
    def test_the_kind_exists_and_is_local_and_routine(self):
        from aletheia import intercom
        self.assertIn("compose", intercom.KIND_ARGS)
        self.assertIn("compose", intercom.LOCAL_KINDS)
        self.assertIn("compose", intercom.ROUTINE_KINDS)

    def test_the_note_tells_the_planner_which_one_to_use(self):
        """Without this it keeps reaching for file_write and pasting a
        description of the document into the document."""
        from aletheia import intercom
        note = intercom.KIND_NOTES["compose"]
        self.assertIn("NOT file_write", note)
        self.assertIn("written when the step RUNS", note)

    def test_the_planner_can_see_it(self):
        from aletheia import planner
        self.assertIn("compose(", planner.grammar_brief())


if __name__ == "__main__":
    unittest.main()
