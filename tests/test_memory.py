import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import journal, memory


class MemoryCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        for target, attr in ((memory, "MEMORY_DIR"), (journal, "JOURNAL_PATH")):
            p = mock.patch.object(target, attr, base / attr.lower())
            p.start(); self.addCleanup(p.stop)


class TestMemory(MemoryCase):
    def test_remember_recall_why(self):
        memory.remember("preferences", "after_work", "after 17:30 on workdays",
                        source="explicit operator correction")
        self.assertEqual(memory.recall("preferences", "after_work"),
                         "after 17:30 on workdays")
        why = memory.why("preferences", "after_work")
        self.assertIn("explicit", why)
        self.assertIn("operator correction", why)

    def test_correction_overwrites_but_records_replacement(self):
        memory.remember("preferences", "after_work", "after 5pm",
                        source="guessed from calendar", kind="inferred")
        memory.remember("preferences", "after_work", "after 17:30",
                        source="operator said so")
        self.assertEqual(memory.recall("preferences", "after_work"), "after 17:30")
        note = journal.entries()[-1]["text"]
        self.assertIn("replaced inferred", note)

    def test_provenance_is_required(self):
        with self.assertRaises(ValueError):
            memory.remember("identity", "name", "Caleb", source="   ")

    def test_unknown_domain_refused(self):
        with self.assertRaises(ValueError):
            memory.remember("vibes", "x", 1, source="test")

    def test_no_memory_is_honest(self):
        self.assertIsNone(memory.recall("people", "brant"))
        self.assertIn("no memory", memory.why("people", "brant"))

    def test_forget_is_journaled(self):
        memory.remember("people", "brant", {"relationship": "friend"}, source="operator")
        self.assertTrue(memory.forget("people", "brant"))
        self.assertIsNone(memory.recall("people", "brant"))
        self.assertEqual(journal.entries()[-1]["text"], "forgotten")


if __name__ == "__main__":
    unittest.main()
