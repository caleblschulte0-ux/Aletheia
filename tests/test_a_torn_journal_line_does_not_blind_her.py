"""One torn line in the journal must not stop every reader of it.

2026-09-15. The laptop hit its low-battery sleep mid-write and left a
seven-byte fragment (`.52"}`) on line 7,522 of the PC journal. From then on
`journal.entries()` raised JSONDecodeError on that one line, and the Core's
receipts check failed every beat for nineteen hours - "subsystem failing"
in the same journal it could not read. The journal is append-only and is
never edited or pruned, so the READER has to tolerate a torn line: skip it,
say so once, and hand back everything else.
"""
from __future__ import annotations

import pathlib
import tempfile
import unittest
from unittest import mock

from aletheia import journal


class ATornLineCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = pathlib.Path(tmp.name) / "journal.jsonl"
        journal._PARSED.clear()
        self.addCleanup(journal._PARSED.clear)

    def test_the_good_lines_still_come_back(self):
        self.path.write_text(
            '{"ts": "2026-09-15T00:00:01Z", "kind": "action", "text": "one"}\n'
            '.52"}\n'
            '{"ts": "2026-09-15T00:00:03Z", "kind": "action", "text": "three"}\n',
            encoding="utf-8")
        got = journal.entries(self.path)
        self.assertEqual([e["text"] for e in got], ["one", "three"])

    def test_the_tear_is_counted_not_hidden(self):
        self.path.write_text('{"ts": "2026-09-15T00:00:01Z", "kind": "action"}\nnot json\n',
                             encoding="utf-8")
        journal.entries(self.path)
        self.assertEqual(journal.torn_lines(self.path), 1)

    def test_a_clean_journal_reports_no_tears(self):
        self.path.write_text('{"ts": "2026-09-15T00:00:01Z", "kind": "action"}\n', encoding="utf-8")
        journal.entries(self.path)
        self.assertEqual(journal.torn_lines(self.path), 0)


if __name__ == "__main__":
    unittest.main()
