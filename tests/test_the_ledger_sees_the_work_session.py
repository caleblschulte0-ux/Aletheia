"""What did you do without asking me - answered about the work session too.

Live, 2026-09-18: `python -m aletheia.autonomy list` said "Nothing in the last
48 hours" while a work session had, inside that window, run two test suites,
made three mirror checkouts, drafted a document and opened a REAL PULL REQUEST
on his repository. Only a branch had ever had a line. The answer was a flat
lie, and the half that was missing contained the act he would have wanted to
hear about first.

So the work session's own routes record into the same ledger. That is only safe
if the outward ones are unmistakably outward, which is four separate things:

- they are MARKED outward on the row,
- the sentence says them FIRST and never says they stayed on this machine,
- they are never undoable by her (unchanged rule, asserted again here), and
- they are not counted against the unattended BUDGET, because recording
  something must never change what is permitted.
"""
from __future__ import annotations

import datetime as dt
import os
import tempfile
import unittest
from unittest import mock

from aletheia import autonomy, tools, work_runners, work_states as ws

NOW = dt.datetime(2026, 9, 18, 17, 0, tzinfo=dt.timezone.utc)


class LedgerCase(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="ledger-")
        self.patch = mock.patch.dict(os.environ, {"ALETHEIA_PRIVATE_STATE": self.dir})
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.ledger = mock.patch.object(autonomy, "ledger_dir",
                                        return_value=__import__("pathlib").Path(self.dir) / "unattended")
        self.ledger.start()
        self.addCleanup(self.ledger.stop)
        # The rows are written by production code with the REAL clock, and read
        # back with NOW. CLAUDE.md: "if one side of a comparison moves, both
        # sides move" - after 17:00 UTC the writes land in tomorrow's day file
        # and the reader, looking back from NOW, never sees them. Freeze the
        # ledger's own clock so the test asks the same day it answers.
        clock = mock.patch.object(autonomy, "_now", lambda now=None: (now or NOW))
        clock.start()
        self.addCleanup(clock.stop)

    def a_pull_request(self, **kw):
        return autonomy.record(tool="code_worker.open_repair_pr",
                               args={"repo": "caleblschulte0-ux/Barkly", "pr_url": "https://x/pull/9"},
                               consequence=tools.OUTWARD, session="work-t1", route="failure",
                               said="opened a pull request on Barkly with a verified repair",
                               undo={"how": autonomy.NONE, "why": "yours to close"}, now=NOW, **kw)

    def a_checkout(self, **kw):
        return autonomy.record(tool="project_checkout.checkout", args={"repo": "x"},
                               consequence=tools.REVERSIBLE_LOCAL, session="work-t1", route="failure",
                               said="made a throwaway copy of Barkly at abc1234 on this machine",
                               undo={"how": autonomy.NONE, "why": "it is discarded when the work finishes"},
                               now=NOW, **kw)


class AnOutwardActIsMarkedOutward(LedgerCase):
    def test_it_is_recorded_at_all(self):
        row = self.a_pull_request()
        self.assertEqual(row["consequence"], tools.OUTWARD)
        self.assertTrue(autonomy.is_outward(row))
        self.assertEqual([r["id"] for r in autonomy.recent(hours=48, now=NOW)], [row["id"]])

    def test_a_reversible_one_is_not_outward(self):
        self.assertFalse(autonomy.is_outward(self.a_checkout()))

    def test_an_unrecognised_consequence_fails_closed_to_outward(self):
        row = autonomy.record(tool="mystery.thing", consequence="probably_fine",
                              said="did something", now=NOW)
        self.assertEqual(row["consequence"], tools.OUTWARD)
        self.assertTrue(autonomy.is_outward(row))

    def test_a_row_with_no_consequence_at_all_is_outward(self):
        self.assertTrue(autonomy.is_outward({"said": "who knows"}))


class TheSentenceStopsClaimingEverythingStayedHere(LedgerCase):
    def test_the_outward_one_is_said_first_and_said_to_be_unreturnable(self):
        self.a_checkout()
        self.a_pull_request()
        said = autonomy.spoken(hours=48)
        self.assertLess(said.index("pull request"), said.index("throwaway copy"), said)
        self.assertIn("cannot take", said)
        head = said[:said.index("Also,")]
        self.assertIn("pull request", head)
        self.assertNotIn("stayed on this machine", head, said)

    def test_the_reversible_ones_keep_their_sentence_about_themselves(self):
        self.a_checkout()
        self.a_pull_request()
        said = autonomy.spoken(hours=48)
        self.assertIn("reversible and stayed on this machine", said)
        # ... and that claim is made about the reversible ones only.
        tail = said[said.index("reversible and stayed"):]
        self.assertNotIn("pull request", tail, said)

    def test_with_nothing_outward_the_old_sentence_is_unchanged(self):
        self.a_checkout()
        said = autonomy.spoken(hours=48)
        self.assertIn("every one of those was reversible and stayed on this machine", said)
        self.assertNotIn("reached beyond", said)

    def test_an_empty_ledger_still_says_nothing_happened(self):
        self.assertIn("Nothing in the last", autonomy.spoken(hours=48))

    def test_no_identifier_is_ever_read_out(self):
        row = self.a_pull_request()
        self.assertNotIn(row["id"], autonomy.spoken(hours=48))


class RecordingSomethingDoesNotChangeWhatIsPermitted(LedgerCase):
    def test_an_outward_row_does_not_eat_the_unattended_budget(self):
        before = autonomy.counts(session="work-t1", now=NOW)
        for _ in range(5):
            self.a_pull_request()
        after = autonomy.counts(session="work-t1", now=NOW)
        self.assertEqual(before["day"], after["day"])
        self.assertEqual(before["session"], after["session"])

    def test_a_reversible_row_still_does(self):
        before = autonomy.counts(session="work-t1", now=NOW)
        self.a_checkout()
        after = autonomy.counts(session="work-t1", now=NOW)
        self.assertEqual(after["day"], before["day"] + 1)
        self.assertEqual(after["session"], before["session"] + 1)


class SheStillCannotTakeBackWhatLeftTheMachine(LedgerCase):
    def test_undo_refuses_a_pull_request_by_name(self):
        row = self.a_pull_request()
        with mock.patch.object(autonomy, "_days", return_value=[NOW.date().isoformat()]):
            with self.assertRaises(autonomy.UndoRefused) as said:
                autonomy.undo(row["id"], now=NOW)
        self.assertIn("reached the world", str(said.exception))

    def test_the_screen_offers_no_undo_command_for_it(self):
        self.a_pull_request()
        self.a_checkout()
        block = autonomy.summary(hours=48, now=NOW)
        outward = [a for a in block["actions"] if a["outward"]]
        self.assertEqual(len(outward), 1)
        self.assertEqual(outward[0]["undo"], "")
        self.assertIn("reached beyond this machine", outward[0]["why_not_undoable"])
        self.assertEqual(block["outward"], 1)


class TheRoutesRecord(LedgerCase):
    """The work session's own acts, not only the broker's tools."""

    def item(self):
        return {"id": "w-9", "source": "tasks", "title": "fix the red CI on Barkly",
                "state": ws.READY, "native_state": "OPEN", "payload": {}}

    def test_a_mirror_checkout_is_reversible_local(self):
        row = work_runners._note_checkout(self.item(), {"path": "/tmp/x", "base_sha": "abc1234def"},
                                          repo="caleblschulte0-ux/Barkly", route="failure")
        self.assertEqual(row["consequence"], tools.REVERSIBLE_LOCAL)
        self.assertIn("throwaway copy of Barkly", row["said"])
        self.assertIn("abc1234", row["said"])

    def test_a_test_run_is_reversible_local_and_says_there_is_nothing_to_take_back(self):
        row = work_runners._note_tests(self.item(), what="the tests for x", command="python -m unittest",
                                       passed=True, seconds=12.0, route="verify")
        self.assertEqual(row["consequence"], tools.REVERSIBLE_LOCAL)
        self.assertIn("running tests changed nothing", row["undo"]["why"])

    def test_a_packet_is_reversible_local(self):
        row = work_runners._note_packet(self.item(), packet_id="packet-1", repo="x", route="packet")
        self.assertEqual(row["consequence"], tools.REVERSIBLE_LOCAL)

    def test_a_pull_request_is_outward_and_never_called_reversible(self):
        row = work_runners._note_outward(self.item(), tool="code_worker.open_repair_pr",
                                         args={"pr_url": "https://x/pull/1"},
                                         said="opened a pull request on Barkly",
                                         route="failure", why_not="yours to close")
        self.assertEqual(row["consequence"], tools.OUTWARD)
        self.assertNotIn(row["consequence"], tools.UNATTENDED)
        self.assertTrue(autonomy.is_outward(row))

    def test_a_notification_reaches_him_and_nobody_else(self):
        row = work_runners._note_visible(self.item(), tool="notifications.publish", args={},
                                         said="told you about something only you can do",
                                         route="his", why_not="you have already seen it")
        self.assertEqual(row["consequence"], tools.VISIBLE_TO_HIM)
        self.assertFalse(autonomy.is_outward(row))

    def test_every_id_lands_on_the_outcome_so_the_report_and_the_ledger_agree(self):
        it = self.item()

        def handler(item, where, now):
            work_runners._note_checkout(item, {"path": "/tmp/x", "base_sha": "abc"},
                                        repo="x/y", route="failure")
            work_runners._note_outward(item, tool="code_worker.open_repair_pr", args={},
                                       said="opened a pull request", route="failure",
                                       why_not="yours to close")
            return {"state": ws.BLOCKED_USER, "reason": "r", "next": "n", "did": "d", "kind": "repaired"}

        with mock.patch.object(work_runners, "_journal"), \
                mock.patch.object(work_runners, "_frontier_ok", return_value=False), \
                mock.patch.object(work_runners, "current_session", return_value={"id": "s"}), \
                mock.patch.object(work_runners, "route",
                                  return_value={"route": "failure", "why": "red"}), \
                mock.patch.object(work_runners, "_failure", side_effect=handler):
            out = work_runners.run(it, NOW)
        ids = out["evidence"]["unattended"]
        self.assertEqual(len(ids), 2)
        rows = {r["id"]: r for r in autonomy.recent(hours=48, now=NOW)}
        self.assertEqual({rows[i]["consequence"] for i in ids},
                         {tools.REVERSIBLE_LOCAL, tools.OUTWARD})

    def test_a_ledger_that_cannot_be_written_never_breaks_the_work(self):
        with mock.patch.object(autonomy, "record", side_effect=OSError("no disk")):
            row = work_runners._note_checkout(self.item(), {"path": "/tmp/x"}, repo="x", route="failure")
        self.assertFalse(row.get("id"))
        self.assertIn("OSError", row["why"])


class TheSessionReportSaysTheSameThing(LedgerCase):
    """One implementation. The report used to write its own sentence."""

    def test_it_does_not_call_a_pull_request_reversible_and_on_this_machine(self):
        from aletheia import project_work
        out = self.a_pull_request()
        local = self.a_checkout()
        record = {"receipts": [{"title": "fix the red CI", "kind": "repaired",
                                "evidence": {"unattended": [out["id"], local["id"]]}}]}
        said = project_work.unattended_words(record)
        self.assertIn("pull request", said)
        head = said[:said.index("Also,")]
        self.assertNotIn("stayed on this machine", head, said)
        self.assertIn("without asking me", said)

    def test_a_session_with_only_reversible_work_reads_as_it_did(self):
        from aletheia import project_work
        local = self.a_checkout()
        record = {"receipts": [{"title": "x", "evidence": {"unattended": [local["id"]]}}]}
        said = project_work.unattended_words(record)
        self.assertIn("reversible", said)
        self.assertIn("this machine", said)
        self.assertNotIn("reached beyond", said)


if __name__ == "__main__":
    unittest.main()
