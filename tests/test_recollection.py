"""What she actually did, answered from the journal instead of invented.

The other half of `self_knowledge`: that one answers "can you?" from the
registry, this one answers "did you?" from the append-only journal.

Without it, "did you send that email?" reaches a language model with no
evidence attached, and it produces a plausible sentence — because that is
what it does. A made-up "yes, I sent it at 2:15" is indistinguishable
from a true one until he opens his sent folder. There is no failure here
that looks like a failure.
"""
import datetime as dt
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import journal, recollection


def stamp(minutes_ago):
    return (dt.datetime.now(dt.timezone.utc)
            - dt.timedelta(minutes=minutes_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


class RecollectionCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "j.jsonl"
        self.path.write_text("")
        p = mock.patch.object(journal, "JOURNAL_PATH", self.path)
        p.start(); self.addCleanup(p.stop)

    def wrote(self, rows):
        import json as _json
        self.path.write_text("\n".join(_json.dumps(r) for r in rows) + "\n")


class ItAnswersFromEvidence(RecollectionCase):
    def test_it_finds_what_he_is_asking_about(self):
        self.wrote([
            {"ts": stamp(90), "kind": "action", "actor": "aletheia-mail",
             "subject": "email", "text": "sent a message to Dana about Friday"},
            {"ts": stamp(60), "kind": "action", "actor": "aletheia-pulse",
             "subject": "pulse", "text": "collected fleet health"},
        ])
        out = recollection.for_question("did you email Dana?")
        self.assertEqual(len(out["journal"]), 1)
        self.assertIn("Dana", out["journal"][0]["what"])

    def test_a_question_that_is_not_about_her_past_carries_nothing(self):
        self.wrote([{"ts": stamp(10), "kind": "action", "actor": "aletheia",
                     "subject": "x", "text": "y"}])
        self.assertEqual(recollection.for_question("why are there tides?"), {})

    def test_her_day_is_her_OWN_actions(self):
        """A list padded with things that happened TO her reads like
        activity she performed."""
        self.wrote([
            {"ts": stamp(30), "kind": "action", "actor": "aletheia-workspace",
             "subject": "workspace:write", "text": "wrote notes.md"},
            {"ts": stamp(20), "kind": "note", "actor": "operator",
             "subject": "operator", "text": "I said something"},
            {"ts": stamp(10), "kind": "event", "actor": "ci",
             "subject": "ci", "text": "a workflow ran"},
        ])
        rows = recollection.day()
        self.assertEqual(len(rows), 1)
        self.assertIn("notes.md", rows[0]["what"])

    def test_a_day_question_asks_for_the_day_not_for_matching_words(self):
        self.wrote([{"ts": stamp(30), "kind": "action", "actor": "aletheia-core",
                     "subject": "core", "text": "restarted after an update"}])
        out = recollection.for_question("what have you been doing today?")
        self.assertEqual(out["asked_about"], "her day")
        self.assertEqual(out["hours"], recollection.TODAY_HOURS)

    def test_old_entries_are_out_of_reach_by_default(self):
        self.wrote([{"ts": "2020-01-01T00:00:00Z", "kind": "action",
                     "actor": "aletheia-mail", "subject": "email",
                     "text": "sent a message to Dana"}])
        self.assertEqual(recollection.for_question("did you email Dana?")["journal"],
                         [])


class AbsenceIsAnAnswer(RecollectionCase):
    """Only sound because the journal is append-only and every action
    writes to it — which is exactly why the rule can be stated."""

    def test_nothing_found_still_carries_the_instruction_not_to_invent(self):
        self.wrote([])
        out = recollection.for_question("did you send that email?")
        self.assertEqual(out["journal"], [])
        self.assertIn("did not happen", out["note"])
        self.assertIn("Never invent", out["note"])

    def test_an_empty_day_says_so_rather_than_going_quiet(self):
        self.wrote([])
        out = recollection.for_question("what did you do today?")
        self.assertIn("do not fill it in", out["note"])

    def test_an_unreadable_journal_does_not_become_a_confident_answer(self):
        with mock.patch.object(journal, "since", side_effect=OSError("gone")):
            out = recollection.for_question("did you email Dana?")
        self.assertEqual(out["journal"], [])
        self.assertIn("Never invent", out["note"])


class ItIsHisClockNotUTC(RecollectionCase):
    def test_times_are_rendered_local(self):
        """A journal in UTC answering "what did you do this morning" is off
        by exactly the amount that makes the answer wrong."""
        self.wrote([{"ts": stamp(30), "kind": "action", "actor": "aletheia-core",
                     "subject": "core", "text": "did a thing"}])
        from aletheia import localtime
        row = recollection.day()[0]
        here = (dt.datetime.now(dt.timezone.utc)
                - dt.timedelta(minutes=30)).astimezone(localtime.operator_tz())
        self.assertIn(here.strftime("%H:%M"), row["at"])


class ItRunsInsideEveryQuestion(unittest.TestCase):
    def test_it_needs_no_model_and_no_network(self):
        import re
        from aletheia.fleet import REPO_ROOT
        body = (REPO_ROOT / "aletheia" / "recollection.py").read_text(
            encoding="utf-8")
        imported = set(re.findall(r"^\s*(?:from|import)\s+([\w.]+)", body,
                                  re.MULTILINE))
        for forbidden in ("reasoner", "urllib", "requests", "subprocess", "http"):
            self.assertFalse({m for m in imported if forbidden in m}, forbidden)

    def test_conversation_actually_attaches_it(self):
        from aletheia.fleet import REPO_ROOT
        body = (REPO_ROOT / "aletheia" / "converse.py").read_text(
            encoding="utf-8")
        self.assertIn("recollection.for_question", body)

    def test_the_prompt_carries_the_rule_that_makes_it_worth_having(self):
        from aletheia import converse
        flat = " ".join(converse.SYSTEM.split())
        self.assertIn("Only say you did something if a line in it says you did",
                      flat)
        self.assertIn("Never invent a time", flat)


if __name__ == "__main__":
    unittest.main()
