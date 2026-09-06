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
from unittest import mock

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

class OnlyHisRefusalsAreSpokenCase(unittest.TestCase):
    """Making failures audible made the planner's internal corrections
    audible too.

        "play some music"
        -> "1 step ready — Play music. Say approve to run it. claimed
            missing, but the registry has audio.route AVAILABLE — claim
            ignored; re-ask if a real step was meant here"

    That last clause is the planner telling a model it was wrong. It is
    the right thing to record and the wrong thing to say, and it carries a
    capability id into the room on the way out.
    """

    def plan(self, refused_detail, with_runnable=True):
        from aletheia import planner
        steps = []
        if with_runnable:
            steps.append({"n": 1, "status": planner.EXECUTABLE,
                          "capability": None, "command": {"kind": "note"},
                          "detail": ""})
        steps.append({"n": 2, "status": planner.REFUSED, "capability": None,
                      "command": {}, "detail": refused_detail})
        return {"intent": "plan", "summary": "Play music", "tier": "world",
                "approval": "intent-x", "steps": steps}

    INTERNAL = ("claimed missing, but the registry has audio.route AVAILABLE "
                "— claim ignored; re-ask if a real step was meant here")

    def test_an_internal_correction_is_not_spoken(self):
        said = intents.spoken(self.plan(self.INTERNAL))
        self.assertNotIn("audio.route", said)
        self.assertNotIn("claim ignored", said)
        self.assertIn("1 step ready", said)

    def test_a_refusal_that_is_about_HIM_is_always_spoken(self):
        from aletheia import webtask
        said = intents.spoken(self.plan(webtask.SPENDING_REFUSAL))
        self.assertIn("spend money", said)

    def test_a_forbidden_verb_refusal_is_spoken(self):
        said = intents.spoken(self.plan(
            "halt is not a step a plan may take — it is reached by saying it "
            "directly"))
        self.assertIn("not a step a plan may take", said)

    def test_a_plan_that_is_ONLY_an_internal_refusal_still_answers(self):
        """Silence is not an answer either."""
        said = intents.spoken(self.plan(self.INTERNAL, with_runnable=False))
        self.assertTrue(said.strip())
        self.assertNotIn("audio.route", said)
        self.assertIn("say it again", said.lower())


class TheReasonSurvivesAnyClassNameCase(unittest.TestCase):
    def test_a_class_that_does_not_end_in_error_is_still_stripped(self):
        """The first version required Error/Exception/Refused, and
        `ReasonerUnavailable: both subscription reasoning paths are
        unavailable` went straight into the room."""
        said = intents.spoken(record(
            [{"n": 1, "outcome": "failed",
              "detail": "ReasonerUnavailable: both subscription reasoning "
                        "paths are unavailable"}]))
        self.assertNotIn("ReasonerUnavailable", said)
        self.assertIn("both subscription reasoning paths", said)

    def test_ordinary_prose_with_a_colon_is_not_eaten(self):
        said = intents.spoken(record(
            [{"n": 1, "outcome": "failed",
              "detail": "the page said: try again later"}]))
        self.assertIn("the page said", said)


class TheSetupCommandIsRunnableCase(unittest.TestCase):
    """"python -m aletheia.phone_cli ready            (should say True)" is
    a command plus an aside plus a run of spaces, read out loud."""

    def test_an_inline_aside_is_dropped(self):
        step = mock.Mock()
        step.instructions.return_value = [
            "Do this first:",
            "python -m aletheia.phone_cli ready            (should say True)"]
        self.assertEqual(intents._how_command(step),
                         "python -m aletheia.phone_cli ready")

    def test_a_step_with_no_command_says_nothing_rather_than_a_fragment(self):
        step = mock.Mock()
        step.instructions.return_value = ["Only if you already run Home Assistant:"]
        self.assertEqual(intents._how_command(step), "")

    def test_the_sentence_is_punctuated(self):
        with mock.patch.object(intents, "_setup_step") as found:
            found.return_value = mock.Mock(
                instructions=lambda: ["python -m aletheia.apply room <token>"])
            said = intents._cannot_yet([{"capability": "room.scene"}], {})
        self.assertTrue(said.endswith("."), said)



if __name__ == "__main__":
    unittest.main()
