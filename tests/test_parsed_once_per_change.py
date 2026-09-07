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

import json

from aletheia import journal, notifications, policy, stateio


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
        stateio._PARSED_DIRS.clear()
        self.addCleanup(stateio._PARSED_DIRS.clear)

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


class OneImplementationForAllThreeCase(unittest.TestCase):
    """The same shape turned up three times — approvals (29 files to find
    1 pending), intents (17, grouped into three lists), notifications
    (114, to find 69 unread) — and each was read end to end on every
    `presence.snapshot()`. I wrote two separate caches for it before
    noticing they were one idea."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        stateio._PARSED_DIRS.clear()
        self.addCleanup(stateio._PARSED_DIRS.clear)

    def write(self, name, **fields):
        (self.dir / name).write_text(json.dumps(fields), encoding="utf-8")

    def test_a_new_file_is_seen(self):
        self.write("a.json", id="a")
        self.assertEqual(len(stateio.parsed_dir(self.dir)), 1)
        self.write("b.json", id="b")
        self.assertEqual(len(stateio.parsed_dir(self.dir)), 2)

    def test_a_file_CHANGED_IN_PLACE_is_seen(self):
        """THE rule this cache is shaped around, and the reason it is one
        function rather than three. Windows does not update a directory's
        mtime when a file inside it is rewritten, and deciding an
        approval, acknowledging a notice and advancing an intent are all
        exactly that. A directory-mtime cache would serve the old value."""
        self.write("a.json", id="a", state="PENDING")
        self.assertEqual(stateio.parsed_dir(self.dir)[0]["state"], "PENDING")
        self.write("a.json", id="a", state="APPROVED")
        self.assertEqual(stateio.parsed_dir(self.dir)[0]["state"], "APPROVED")

    def test_a_deleted_file_is_gone(self):
        self.write("a.json", id="a")
        self.assertEqual(len(stateio.parsed_dir(self.dir)), 1)
        (self.dir / "a.json").unlink()
        self.assertEqual(stateio.parsed_dir(self.dir), [])

    def test_a_torn_file_is_skipped_not_fatal(self):
        self.write("good.json", id="a")
        (self.dir / "bad.json").write_text("{not json", encoding="utf-8")
        self.assertEqual(len(stateio.parsed_dir(self.dir)), 1)

    def test_the_caller_cannot_edit_the_cache(self):
        self.write("a.json", id="a", state="PENDING")
        rows = stateio.parsed_dir(self.dir)
        rows[0]["state"] = "APPROVED"
        self.assertEqual(stateio.parsed_dir(self.dir)[0]["state"], "PENDING")

    def test_a_missing_directory_is_not_a_crash(self):
        self.assertEqual(stateio.parsed_dir(self.dir / "nope"), [])

    def test_it_does_not_grow_without_bound(self):
        for n in range(stateio._PARSED_DIRS_MAX + 4):
            room = self.dir / f"d{n}"
            room.mkdir()
            (room / "a.json").write_text('{"id":"a"}', encoding="utf-8")
            stateio.parsed_dir(room)
        self.assertLessEqual(len(stateio._PARSED_DIRS),
                             stateio._PARSED_DIRS_MAX)


class ADecidedApprovalIsNeverServedAsPendingCase(unittest.TestCase):
    """The one place where a stale read would be a SECURITY answer rather
    than a slow one. `decide()` rewrites the approval in place."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patch = mock.patch.object(policy, "APPROVALS_DIR", Path(self.tmp.name))
        patch.start(); self.addCleanup(patch.stop)
        stateio._PARSED_DIRS.clear()
        self.addCleanup(stateio._PARSED_DIRS.clear)

    def pending(self):
        return [a for a in policy.all_approvals() if a.get("state") == "PENDING"]

    def test_deciding_one_is_visible_immediately(self):
        record = policy.request(
            "ap-monitor", "browser.interact",
            reason='operator said: "buy the monitor"',
            consequence="money leaves his account",
            reversible=False)
        self.assertEqual(len(self.pending()), 1)
        policy.decide(record["id"], "APPROVED", via="test")
        self.assertEqual(self.pending(), [],
                         "a decided approval served as pending is a "
                         "security answer, not a latency one")

    def test_usable_sees_the_decision_too(self):
        record = policy.request(
            "ap-usable", "browser.interact",
            reason='operator said: "buy the monitor"',
            consequence="money leaves his account",
            reversible=False)
        policy.all_approvals()                     # warm the cache
        policy.decide(record["id"], "APPROVED", via="test")
        ok, _why = policy.usable(record["id"])
        self.assertTrue(ok)



if __name__ == "__main__":
    unittest.main()
