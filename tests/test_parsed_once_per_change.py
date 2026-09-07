"""A cache that can go stale is a lie with better latency.

Two stores are read on nearly every question she answers, and both were
parsed end to end every time:

- `journal.entries()` parses every writer file — 2,985 lines on his PC,
  24-60ms — and the sentences that read her memory call it more than once
  each ("what did you do today" 129ms, "show me the journal" 153ms).
- `notifications.all_notifications()` opened and parsed all 105 notices
  and THEN filtered by state, so asking for the unread ones paid for the
  acknowledged ones too. `presence.snapshot()` reads it, and presence is
  behind three of the sentences he says most.

Both are cached against a stat of the underlying files, which is the only
form that cannot go stale here. What these tests hold is the CORRECTNESS,
not the speed: a faster answer that is out of date is worse than the slow
one it replaced, because he cannot tell.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import journal, notifications


class TheJournalIsParsedOncePerChangeCase(unittest.TestCase):
    """Append-only is what makes this exact: a file that only ever grows
    changes both its mtime and its size on every write."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "j.jsonl"
        patch = mock.patch.object(journal, "JOURNAL_PATH", self.path)
        patch.start(); self.addCleanup(patch.stop)
        journal._PARSED.clear()
        self.addCleanup(journal._PARSED.clear)

    def test_a_new_entry_is_never_hidden(self):
        journal.append("note", "t", "first", actor="aletheia")
        self.assertEqual(len(journal.entries()), 1)
        journal.append("note", "t", "second", actor="aletheia")
        self.assertEqual(len(journal.entries()), 2,
                         "an append the cache did not see is lost history")

    def test_the_second_read_does_not_reparse(self):
        journal.append("note", "t", "first", actor="aletheia")
        journal.entries()
        with mock.patch.object(Path, "read_text",
                               side_effect=AssertionError("re-read the file")):
            self.assertEqual(len(journal.entries()), 1)

    def test_the_caller_cannot_edit_the_cache(self):
        """`entries()` is handed to callers that filter and slice it. One
        that appended to the returned list would be editing every later
        reader's history."""
        journal.append("note", "t", "first", actor="aletheia")
        rows = journal.entries()
        rows.append({"ts": "9999", "text": "not real"})
        self.assertEqual(len(journal.entries()), 1)

    def test_it_does_not_grow_without_bound(self):
        """Tests redirect JOURNAL_PATH constantly, so an unbounded dict
        would grow for the whole of a suite run."""
        for n in range(journal._PARSED_MAX + 4):
            path = Path(self.tmp.name) / f"j{n}.jsonl"
            path.write_text('{"ts":"1","kind":"note","actor":"a",'
                            '"subject":"s","text":"t"}\n', encoding="utf-8")
            journal.entries(path)
        self.assertLessEqual(len(journal._PARSED), journal._PARSED_MAX)


class NoticesAreParsedOncePerChangeCase(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patch = mock.patch.object(notifications, "NOTICES_DIR",
                                  Path(self.tmp.name))
        patch.start(); self.addCleanup(patch.stop)
        notifications._NOTICES_CACHE = None
        self.addCleanup(setattr, notifications, "_NOTICES_CACHE", None)

    def test_acknowledging_one_is_seen_immediately(self):
        """THE risk this had to be designed around. Windows does not touch
        a directory's mtime when a file inside it changes IN PLACE, and
        acknowledging a notice is exactly that — so a directory-mtime
        cache would go on reporting something he had already dealt with.
        Hence a stat per file."""
        rec = notifications.publish("reminder", "call the plumber")
        self.assertEqual(len(notifications.all_notifications(state="UNREAD")), 1)
        notifications.set_state(rec["id"], "ACKNOWLEDGED")
        self.assertEqual(len(notifications.all_notifications(state="UNREAD")), 0)

    def test_a_new_notice_is_seen_immediately(self):
        notifications.publish("reminder", "one")
        self.assertEqual(len(notifications.all_notifications()), 1)
        notifications.publish("reminder", "two")
        self.assertEqual(len(notifications.all_notifications()), 2)

    def test_the_caller_cannot_edit_the_cache(self):
        notifications.publish("reminder", "one")
        rows = notifications.all_notifications()
        rows[0]["title"] = "tampered"
        self.assertNotEqual(notifications.all_notifications()[0]["title"],
                            "tampered")

    def test_the_state_filter_still_filters(self):
        first = notifications.publish("reminder", "one")
        notifications.publish("reminder", "two")
        notifications.set_state(first["id"], "ACKNOWLEDGED")
        unread = notifications.all_notifications(state="UNREAD")
        self.assertEqual([n["body"] for n in unread], ["two"])


if __name__ == "__main__":
    unittest.main()
