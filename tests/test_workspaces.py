"""A worker's memory has to survive the thing that answered it.

The point of the runtime is that closing a Claude window does not lose
the project. So these tests are mostly about persistence, boundedness,
and keeping the transcript out of the brief.
"""
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import agents, journal, policy, workspaces


class WorkspaceCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        d = Path(self.tmp.name)
        env = mock.patch.dict(os.environ, {"ALETHEIA_PRIVATE_STATE": str(d)})
        env.start()
        self.addCleanup(env.stop)
        for patch in (mock.patch.object(journal, "JOURNAL_PATH", d / "j.jsonl"),
                      mock.patch.object(policy, "HALT_PATH", d / "halt.json"),
                      mock.patch.object(policy, "APPROVALS_DIR", d / "approvals")):
            patch.start()
            self.addCleanup(patch.stop)
        agents.spawn("barkly", name="Barkly Engineer",
                     mission="get Barkly launch-ready",
                     project="barkly", agent_type="project",
                     capabilities=agents.root_record()["capabilities"][:2])


class ItOutlivesTheWindowCase(WorkspaceCase):
    def test_what_it_learns_is_still_there_next_time(self):
        workspaces.remember("barkly", "decision",
                            "Postgres over SQLite: two writers")
        # A brand-new process would read exactly this.
        self.assertIn("Postgres over SQLite",
                      workspaces.brief("barkly"))

    def test_the_brief_says_who_it_is_and_what_it_is_for(self):
        said = workspaces.brief("barkly")
        self.assertIn("Barkly Engineer", said)
        self.assertIn("get Barkly launch-ready", said)

    def test_an_empty_workspace_still_proves_the_workspace(self):
        """Absence of rows is not absence of a project.

        The same rule as the empty-store lesson in CLAUDE.md: a model
        told nothing concludes there is nothing.
        """
        said = workspaces.brief("barkly")
        self.assertIn("Nothing recorded", said)

    def test_the_same_fact_twice_is_recorded_once(self):
        for _ in range(3):
            workspaces.remember("barkly", "fact", "the API is FastAPI")
        self.assertEqual(len(workspaces.entries("barkly", "fact")), 1)

    def test_an_answered_question_stops_being_carried(self):
        workspaces.remember("barkly", "question", "which database?")
        self.assertTrue(workspaces.resolve("barkly", "which database?"))
        self.assertEqual(workspaces.entries("barkly", "question"), [])
        self.assertFalse(workspaces.resolve("barkly", "never asked"))


class TheTranscriptIsNotContextCase(WorkspaceCase):
    def test_a_run_is_recorded_and_never_reaches_the_brief(self):
        """A model handed its own previous output agrees with it."""
        workspaces.record_run(
            "barkly",
            {"role": "builder", "question": "SECRET-TRANSCRIPT-MARKER"},
            {"state": "COMPLETED", "provider": "claude"})
        self.assertNotIn("SECRET-TRANSCRIPT-MARKER", workspaces.brief("barkly"))
        self.assertEqual(len(workspaces.load("barkly")["transcript"]), 1)

    def test_the_transcript_rotates_rather_than_growing_forever(self):
        for i in range(workspaces.MAX_TRANSCRIPT + 20):
            workspaces.record_run("barkly", {"role": "r", "question": f"q{i}"},
                                  {"state": "COMPLETED"})
        self.assertEqual(len(workspaces.load("barkly")["transcript"]),
                         workspaces.MAX_TRANSCRIPT)


class BoundedCase(WorkspaceCase):
    def test_the_brief_stays_inside_its_budget(self):
        for i in range(60):
            workspaces.remember("barkly", "fact", f"fact number {i} " + "x" * 200)
        said = workspaces.brief("barkly")
        self.assertLessEqual(len(said.encode("utf-8")),
                             workspaces.BRIEF_BUDGET_BYTES + 200)

    def test_it_drops_whole_entries_and_never_half_a_sentence(self):
        """A truncated decision reads as a complete one. That is the bug."""
        for i in range(60):
            workspaces.remember("barkly", "fact", f"fact number {i} " + "y" * 200)
        for line in workspaces.brief("barkly").splitlines():
            if line.startswith("- ["):
                self.assertTrue(line.endswith("y"), f"sliced: {line[-40:]!r}")

    def test_the_open_question_is_the_last_thing_dropped(self):
        """It is usually what the assignment is about."""
        workspaces.remember("barkly", "question", "UNIQUE-OPEN-QUESTION")
        for i in range(60):
            workspaces.remember("barkly", "fact", f"noise {i} " + "z" * 200)
        self.assertIn("UNIQUE-OPEN-QUESTION", workspaces.brief("barkly"))

    def test_distilled_knowledge_is_capped_too(self):
        for i in range(workspaces.MAX_ENTRIES + 20):
            workspaces.remember("barkly", "fact", f"fact {i}")
        self.assertEqual(len(workspaces.entries("barkly")),
                         workspaces.MAX_ENTRIES)

    def test_a_kind_it_does_not_know_is_refused(self):
        with self.assertRaises(ValueError):
            workspaces.remember("barkly", "vibes", "something")
        with self.assertRaises(ValueError):
            workspaces.remember("barkly", "fact", "   ")


if __name__ == "__main__":
    unittest.main()
