"""He said "remember my landlord is Mr Okafor". She saved it. She recalled
it correctly one turn later. Then:

    "did you save that"
    -> "No — the journal's empty for the last 168 hours. Nothing I did
        shows as saved."

Three separate defects stacked into one flat contradiction, one turn
apart, and the last of them is the one this module exists to prevent:
she told him she had not done a thing she had just done.

1. `recollection.day` filtered on kind in (action, decision, recovery).
   `memory.remember` journals as "note" and `tasks.create` as "task" —
   the two things she does most often on his instruction, both invisible.
2. `about()` scores journal lines against the WORDS of the question. "Did
   you save that" names nothing searchable, so it matched none of them.
3. The note attached to that empty list said "nothing here means it did
   not happen". Absence is evidence for the WHOLE journal; it is not
   evidence for a search of it. A false premise handed to a model comes
   back as a confident lie.
"""
import unittest
from unittest import mock

from aletheia import recollection


def entry(kind, subject, text, actor="aletheia", ts="2026-09-06T12:00:00Z"):
    return {"ts": ts, "kind": kind, "actor": actor, "subject": subject,
            "text": text}


class WhatCountsAsDoingCase(unittest.TestCase):
    def test_remembering_something_is_something_she_did(self):
        rows = [entry("note", "memory:people.landlord",
                      'set people.landlord = "Mr Okafor" (explicit)')]
        with mock.patch.object(recollection, "_read_journal", lambda h: (rows, True)):
            said = recollection.day()
        self.assertEqual(len(said), 1)
        self.assertIn("Mr Okafor", said[0]["what"])

    def test_making_a_task_is_something_she_did(self):
        rows = [entry("task", "task:call-the-plumber", "created — call the plumber")]
        with mock.patch.object(recollection, "_read_journal", lambda h: (rows, True)):
            said = recollection.day()
        self.assertEqual(len(said), 1)
        self.assertIn("call the plumber", said[0]["what"])

    def test_things_that_happened_TO_her_are_still_excluded(self):
        rows = [entry("event", "repo:aletheia", "health red -> green"),
                entry("alert", "sentinel", "workflow failed")]
        with mock.patch.object(recollection, "_read_journal", lambda h: (rows, True)):
            self.assertEqual(recollection.day(), [])

    def test_talking_is_not_doing(self):
        """`converse` journals every answer, so once notes counted she
        started listing her own previous replies back at him."""
        rows = [entry("action", "converse", "answered a question (18 in, 226 out)"),
                entry("action", "core:intent", "done — Save what, exactly?")]
        with mock.patch.object(recollection, "_read_journal", lambda h: (rows, True)):
            self.assertEqual(recollection.day(), [])

    def test_one_act_journaled_twice_is_one_thing(self):
        """"Add a task" writes `task:<id>` from the store AND
        `core:task_new` from the command path. The store's line names the
        thing; the command's names its id. She was saying both — "Added a
        task: call the plumber; Added a task: t1"."""
        rows = [entry("task", "task:t1", "created — call the plumber"),
                entry("action", "core:task_new", "done — task t1 queued")]
        with mock.patch.object(recollection, "_read_journal", lambda h: (rows, True)):
            said = recollection.day()
        self.assertEqual(len(said), 1)
        self.assertIn("call the plumber", said[0]["what"])
        self.assertNotIn(": t1", said[0]["what"])

    def test_two_writers_that_render_identically_also_collapse(self):
        """The second net: when a task id IS its description, both lines
        render the same sentence in the same minute."""
        rows = [entry("task", "task:call-the-plumber", "created — call the plumber"),
                entry("task", "task:call-the-plumber", "created — call the plumber")]
        with mock.patch.object(recollection, "_read_journal", lambda h: (rows, True)):
            self.assertEqual(len(recollection.day()), 1)

    def test_the_same_thing_at_a_different_time_is_two_things(self):
        rows = [entry("task", "task:t1", "created — call the plumber",
                      ts="2026-09-06T09:00:00Z"),
                entry("task", "task:t2", "created — call the plumber",
                      ts="2026-09-06T17:00:00Z")]
        with mock.patch.object(recollection, "_read_journal", lambda h: (rows, True)):
            self.assertEqual(len(recollection.day()), 2)


class NothingMatchedIsNotNothingHappenedCase(unittest.TestCase):
    ROWS = [entry("note", "memory:people.landlord",
                  'set people.landlord = "Mr Okafor" (explicit)')]

    def test_a_question_that_matches_nothing_still_sees_what_she_did(self):
        with mock.patch.object(recollection, "_read_journal", lambda h: (self.ROWS, True)):
            out = recollection.for_question("did you save that")
        self.assertFalse(out["matched"])
        self.assertEqual(len(out["journal"]), 1)
        self.assertIn("Mr Okafor", out["journal"][0]["what"])

    def test_the_note_forbids_calling_it_empty(self):
        """The premise that produced the lie, named and reversed."""
        with mock.patch.object(recollection, "_read_journal", lambda h: (self.ROWS, True)):
            note = recollection.for_question("did you save that")["note"]
        self.assertIn("NOTHING IN THE JOURNAL MATCHED", note)
        self.assertIn("not say the journal is", note.replace("Do NOT", "not"))

    def test_a_question_that_DOES_match_says_so(self):
        with mock.patch.object(recollection, "_read_journal", lambda h: (self.ROWS, True)):
            out = recollection.for_question("did you do anything with the landlord")
        self.assertTrue(out["matched"])
        self.assertTrue(out["journal"])

    def test_a_genuinely_empty_journal_says_that_plainly(self):
        with mock.patch.object(recollection, "_read_journal", lambda h: ([], True)):
            out = recollection.for_question("did you save that")
        self.assertEqual(out["journal"], [])
        self.assertIn("really is empty", out["note"])

    def test_an_unreadable_journal_is_not_an_empty_one(self):
        """`_recent` swallowed the exception and returned [], so a journal
        she could not READ and a genuinely quiet week produced the same
        answer — "she has done nothing". Only one of those is about him."""
        with mock.patch.object(recollection, "_read_journal",
                               lambda h: ([], False)):
            out = recollection.for_question("did you save that")
        self.assertFalse(out["readable"])
        self.assertIn("could not be READ", out["note"])
        self.assertNotIn("did not happen", out["note"])

    def test_the_empty_note_still_forbids_inventing(self):
        with mock.patch.object(recollection, "_read_journal",
                               lambda h: ([], True)):
            note = recollection.for_question("did you save that")["note"]
        self.assertIn("Never invent", note)
        self.assertIn("did not happen", note)

    def test_a_question_that_is_not_about_her_past_carries_nothing(self):
        self.assertEqual(recollection.for_question("what is the capital of france"), {})


class TheReceiptsAreSentencesCase(unittest.TestCase):
    def test_a_memory_line_is_not_read_as_an_assignment(self):
        said = recollection._row(entry(
            "note", "memory:people.landlord",
            'set people.landlord = "Mr Okafor" (explicit)'))["what"]
        self.assertEqual(said, "Noted: landlord is Mr Okafor.")

    def test_a_subject_that_is_already_a_sentence_keeps_no_label(self):
        said = recollection._row(entry(
            "plan", "planner", "Did it: Remember the landlord's name"))["what"]
        self.assertFalse(said.startswith("planner:"))

    def test_a_subject_that_needs_its_label_keeps_it(self):
        said = recollection._row(entry(
            "event", "repo:aletheia", "health red -> green"))["what"]
        self.assertIn("repo:aletheia", said)


if __name__ == "__main__":
    unittest.main()
