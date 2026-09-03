"""What he keeps asking for and cannot have — counted, in his own words.

Rule zero works inside one session and dissolves between them. A gap
named on Tuesday and a gap named on Friday are the same gap, and nothing
in the system knew it: `gaps.materialize` files a build task the first
time and then quietly does nothing, so a capability he has asked for
eleven times and one he mentioned once look identical on the task list
forever.

Ranked, this is a roadmap nobody wrote — not what an agent guessed would
be useful, not what a plan file said in July, but what he actually tried
to do and could not.
"""
import datetime as dt
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import demand


class DemandCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.file = Path(self.tmp.name) / "asks.jsonl"
        p = mock.patch.object(demand, "path", lambda: self.file)
        p.start(); self.addCleanup(p.stop)


class ItCountsWhatHeActuallyAskedFor(DemandCase):
    def test_the_same_gap_twice_is_one_capability_asked_twice(self):
        demand.record("message.send", "text my brother", status="NOT_BUILT")
        demand.record("message.send", "tell Dana I'm late", status="NOT_BUILT")
        rows = demand.ranked()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["times"], 2)

    def test_it_keeps_his_words_because_they_are_the_argument(self):
        """"He asked for this eleven times" is an argument; "he asked for
        message.send eleven times" is a statistic."""
        demand.record("message.send", "can you text my brother?",
                      status="NOT_BUILT")
        self.assertIn("can you text my brother?",
                      demand.ranked()[0]["in_his_words"])

    def test_the_most_asked_comes_first(self):
        for _ in range(3):
            demand.record("message.send", "text someone", status="NOT_BUILT")
        demand.record("reservation.book", "book a table", status="EXPERIMENTAL")
        self.assertEqual([r["capability"] for r in demand.ranked()],
                         ["message.send", "reservation.book"])

    def test_a_one_off_is_not_a_pattern(self):
        demand.record("reservation.book", "book a table", status="EXPERIMENTAL")
        self.assertEqual(demand.notable(), [])
        self.assertEqual(len(demand.ranked()), 1, "still recorded, just not "
                                                  "put in front of him")

    def test_it_forgets_what_is_no_longer_demand(self):
        """An ask from four months ago is history, not demand."""
        old = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=200)
               ).strftime("%Y-%m-%dT%H:%M:%SZ")
        self.file.write_text(json.dumps(
            {"at": old, "capability": "message.send", "asked": "text someone",
             "status": "NOT_BUILT", "source": "planner"}) + "\n")
        self.assertEqual(demand.ranked(), [])

    def test_it_is_bounded(self):
        """Appended, then pruned once it has grown — rewriting the whole
        ledger on every ask is quadratic in how much he asks, which is the
        wrong direction for a file whose point is that he keeps asking."""
        row = json.dumps({"at": demand.stateio.utcnow(), "capability": "x.y",
                          "asked": "a" * 100, "status": "", "source": "t"})
        self.file.write_text((row + "\n") * 4_000)
        demand.record("x.y", "one more")
        lines = self.file.read_text().strip().splitlines()
        self.assertLessEqual(len(lines), demand.MAX_RECORDS)
        self.assertGreater(len(lines), 100, "it prunes, it does not reset")


class ItCanNeverBreakARequest(DemandCase):
    def test_an_unwritable_ledger_is_silent(self):
        blocker = Path(self.tmp.name) / "blocked"
        blocker.write_text("I am a file, not a directory")
        with mock.patch.object(demand, "path", lambda: blocker / "x.jsonl"):
            self.assertIsNone(demand.record("a.b", "something"))

    def test_a_corrupt_line_does_not_break_the_ledger(self):
        self.file.write_text("not json\n" + json.dumps(
            {"at": demand.stateio.utcnow(), "capability": "a.b",
             "asked": "x", "status": "", "source": "t"}) + "\n")
        self.assertEqual(len(demand.ranked()), 1)

    def test_an_empty_capability_records_nothing(self):
        self.assertIsNone(demand.record("", "something"))


class ItIsFedByBothPathsHeCanAskThrough(DemandCase):
    def test_a_planned_gap_is_recorded_with_his_sentence(self):
        from aletheia import planner
        plan = planner.Plan(
            request="text my brother", summary="s", intent="plan",
            steps=[planner.PlannedStep(1, planner.GAP, "not built",
                                       capability="message.send"),
                   planner.PlannedStep(2, planner.EXECUTABLE, "fine",
                                       command={"kind": "note", "text": "x"})])
        self.assertEqual(demand.record_plan(plan, "text my brother"),
                         ["message.send"])
        self.assertEqual(demand.ranked()[0]["in_his_words"],
                         ["text my brother"])

    def test_the_planner_path_is_wired(self):
        from aletheia.fleet import REPO_ROOT
        body = (REPO_ROOT / "aletheia" / "intents.py").read_text(encoding="utf-8")
        self.assertIn("demand.record_plan(plan, request)", body)

    def test_a_can_you_that_never_becomes_a_plan_counts_too(self):
        """He asks, she says not yet, and until now that was the end of it."""
        from aletheia.fleet import REPO_ROOT
        body = (REPO_ROOT / "aletheia" / "converse.py").read_text(encoding="utf-8")
        self.assertIn('top["status"] != "AVAILABLE"', body)
        self.assertIn("source=\"converse\"", body)

    def test_something_she_can_do_is_not_recorded_as_demand(self):
        from aletheia import self_knowledge
        reg = {"revision": 1, "capabilities": [
            {"id": "email.send", "status": "AVAILABLE",
             "description": "Draft and send email", "module": "aletheia.mail"}]}
        top = self_knowledge.relevant("send an email", registry=reg)[0]
        self.assertEqual(top["status"], "AVAILABLE")


class HisWordsStayOnHisMachine(unittest.TestCase):
    def test_the_ledger_is_private_state_never_the_repo(self):
        self.assertIn("private", str(demand.path()))

    def test_the_default_private_store_is_not_committed(self):
        """Under the suite ALETHEIA_PRIVATE_STATE points at a throwaway
        directory, so the check that matters is the DEFAULT location — the
        one his PC uses when nothing is set."""
        from aletheia.fleet import REPO_ROOT
        ignore = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("state/private/", ignore.splitlines())


class ItRanksAndDoesNotConclude(DemandCase):
    def test_the_sentence_says_how_many_not_what_to_do(self):
        for _ in range(4):
            demand.record("message.send", "text someone", status="NOT_BUILT")
        said = demand.spoken()
        self.assertIn("message.send", said)
        self.assertIn("4 times", said)

    def test_nothing_repeated_says_nothing_repeated(self):
        self.assertIn("Nothing you have asked for repeatedly",
                      demand.spoken())


if __name__ == "__main__":
    unittest.main()
