"""She read the plan summary back as if the plan had worked.

Found 2026-09-06 by asking her hard things:

    "read my resume"          -> "Read the operator's resume file"
    "how many jobs are open
     at Anthropic right now"  -> "Find how many jobs are currently open
                                  at Anthropic"

Both sound like answers. Both are the QUESTION, reflected. And underneath
each one the receipt said the step had failed, with a useful reason:

    WorkspaceError: resume is not a file
    ResearchError: no readable sources were found for that question

`spoken()` filtered failures out of the answers — correctly, an error is
not an answer — and then fell back to `record["summary"]`, which is the
planner's restatement of what he ASKED for. So a failure was reported in
the confident voice of having done it.

That is §30 in its worst shape. "Never report 'command executed' as 'goal
achieved'" assumes the command at least ran; this reported a failure as
the goal itself, and he would have gone on believing his resume had been
read.
"""
import unittest

from aletheia import intents


def record(receipts, summary="Read the operator's resume file"):
    return {"read_only": True, "intent": "plan", "summary": summary,
            "steps": [], "receipts": receipts}


class TheSummaryIsNotAnAnswerCase(unittest.TestCase):
    def test_a_failed_step_says_what_went_wrong(self):
        said = intents.spoken(record(
            [{"n": 1, "outcome": "failed", "kind": "file_read",
              "detail": "WorkspaceError: resume is not a file"}]))
        self.assertIn("resume is not a file", said)
        self.assertNotIn("Read the operator's resume file", said)

    def test_the_exception_class_is_dropped_and_the_reason_kept(self):
        """`WorkspaceError` tells him nothing he can act on; the sentence
        after the colon tells him everything."""
        said = intents.spoken(record(
            [{"n": 1, "outcome": "failed",
              "detail": "ResearchError: no readable sources were found — "
                        "say it differently"}]))
        self.assertNotIn("ResearchError", said)
        self.assertIn("no readable sources", said)
        self.assertIn("say it differently", said)

    def test_a_real_answer_is_still_just_the_answer(self):
        said = intents.spoken(record(
            [{"n": 1, "outcome": "done", "detail": "Anthropic: 593 open."}]))
        self.assertEqual(said, "Anthropic: 593 open.")

    def test_a_partial_success_reports_both_halves(self):
        """Reporting only the half that worked is the same lie, smaller."""
        said = intents.spoken(record(
            [{"n": 1, "outcome": "done", "detail": "Anthropic: 593 open."},
             {"n": 2, "outcome": "failed", "detail": "ResearchError: nothing found"}]))
        self.assertIn("593 open", said)
        self.assertIn("but", said)
        self.assertIn("nothing found", said)
        self.assertNotIn(". — but", said)

    def test_a_plan_that_produced_nothing_says_exactly_that(self):
        said = intents.spoken(record([]))
        self.assertNotIn("Read the operator's resume file", said)
        self.assertIn("nothing", said.lower())

    def test_a_refusal_is_reported_as_a_refusal(self):
        said = intents.spoken(record(
            [{"n": 1, "outcome": "refused",
              "detail": "Refused: no front-door grant for that repo"}]))
        self.assertIn("front-door grant", said)
        self.assertNotIn("Refused:", said)

    def test_ids_do_not_survive_into_the_reason(self):
        said = intents.spoken(record(
            [{"n": 1, "outcome": "failed",
              "detail": "WorkspaceError: run-a1b2c3d4e5f67890 could not be read"}]))
        self.assertNotIn("a1b2c3d4e5f67890", said)

    def test_a_receipt_with_no_detail_still_produces_a_sentence(self):
        said = intents.spoken(record([{"n": 1, "outcome": "failed"}]))
        self.assertTrue(said.strip())


if __name__ == "__main__":
    unittest.main()
