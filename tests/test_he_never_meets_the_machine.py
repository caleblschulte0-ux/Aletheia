"""Four things he was still shown, found by looking at his real state.

The page renders what the collectors hand it, so every one of these is a
wording bug in a collector and not in a page:

1. A notification BODY written for a log. Live on his phone:
   "https://jobs.ashbyhq.com/notion/c1324c38-.../application — RuntimeError:
   ApplyError: the Submit button would not take a click". `notice_line`
   cleans the heading; nothing cleaned the body.
2. A journal alert written as a diagnostic, appearing in the middle of a
   list of things she has done.
3. Half the application approvals naming a site instead of an employer,
   because two paths staged them with two different sentences.
4. Model brands. His ease-of-use brief says he should not meet one in
   normal use; CLAUDE.md says her own answers must say they are hers.
   Operator ruling: keep the disclosure, drop the brand.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import notifications, reasoner, voice


class ANotificationBodyIsReadOutToo(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self._patch = mock.patch.object(notifications, "NOTICES_DIR",
                                        Path(self._dir.name))
        self._patch.start()

    def tearDown(self):
        self._patch.stop()
        self._dir.cleanup()

    def test_the_body_goes_through_the_same_door_as_everything_spoken(self):
        notice = notifications.publish(
            "An application could not be sent",
            "https://jobs.ashbyhq.com/notion/c1324c38-abc7-4bcf-9b62-2e1f86d"
            "5aa72/application — RuntimeError: ApplyError: the Submit button "
            "would not take a click",
            priority="IMPORTANT", about=notifications.FAILED)
        for machine in ("https://", "RuntimeError", "ApplyError", "c1324c38"):
            self.assertNotIn(machine, notice["body"])
        self.assertIn("would not take a click", notice["body"])

    def test_a_line_the_door_empties_keeps_its_original(self):
        """Fails OPEN: `validate` refuses an empty body, so a notice that
        was never filed would be the thing he needed to know and never
        heard. A slightly ugly notice is a bad day."""
        notice = notifications.publish("Reminder", "https://example.com/x",
                                       priority="NORMAL")
        self.assertTrue(notice["body"].strip())

    def test_an_ordinary_body_is_left_exactly_alone(self):
        plain = "Call the dentist at 3 pm."
        self.assertEqual(
            notifications.publish("Reminder", plain)["body"], plain)


class AJournalLineIsSomethingSheReadsOut(unittest.TestCase):
    def test_a_refused_local_write_is_said_in_his_words(self):
        """It read "A local process attempted POST
        /api/voice/followup/ack without the local session secret", twice,
        in the middle of what she had done that day."""
        import inspect

        from aletheia import core
        source = inspect.getsource(core)
        self.assertNotIn("a local process attempted", source)
        self.assertIn("without proving it was you", source)


class AnApplicationIsNamedByTheEmployer(unittest.TestCase):
    RECORD = {"id": "apply-ashby-notion", "company": "Notion",
              "job_title": "Data Analyst"}

    def test_the_label_names_the_role_and_the_employer(self):
        with mock.patch("aletheia.apply_run.load_run",
                        lambda run_id: dict(self.RECORD)):
            said = voice.approval_label(
                {"id": "apply-ashby-notion-submit",
                 "capability": "application.submit",
                 "consequence": "It sends your application to this employer "
                                "under your name. There is no undo.",
                 "reason": "Submit an application at "
                           "https://jobs.ashbyhq.com/notion/c1324c38"})
        self.assertEqual(said, "Data Analyst at Notion")

    def test_a_record_that_knows_neither_falls_back(self):
        """Never a guess: an application she cannot name goes back to
        whatever the rest of `approval_label` would have said."""
        with mock.patch("aletheia.apply_run.load_run", lambda run_id: {}):
            said = voice.approval_label(
                {"id": "apply-x-submit", "capability": "application.submit",
                 "consequence": "It sends your application under your name."})
        self.assertIn("sends your application", said)

    def test_an_unreadable_record_never_raises_into_a_sentence(self):
        def gone(run_id):
            raise FileNotFoundError(run_id)

        with mock.patch("aletheia.apply_run.load_run", gone):
            said = voice.approval_label(
                {"id": "apply-x-submit", "capability": "application.submit",
                 "consequence": "It sends your application under your name."})
        self.assertTrue(said)

    def test_nothing_else_is_treated_as_an_application(self):
        self.assertEqual(voice._application_label({"id": "mail-a1e195"}), "")
        self.assertEqual(voice._application_label({}), "")


class HeNeverMeetsAModelByName(unittest.TestCase):
    """His brief: no model names in normal use. CLAUDE.md: her own answers
    must say they are hers. Both, in one clause — and the provider names
    stay in the receipts under the drawer, where nobody reads them aloud.
    """

    BRANDS = ("Claude", "Codex", "ChatGPT", "ollama", "qwen", "sonnet",
              "haiku", "opus")

    def test_the_disclosure_survives_losing_the_brand(self):
        with mock.patch.object(reasoner, "resting_until", return_value=None):
            lead = reasoner.own_model_lead()
        self.assertIn("mine", lead)
        for brand in self.BRANDS:
            self.assertNotIn(brand, lead)

    def test_it_still_says_when_they_come_back(self):
        import datetime as dt
        until = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=2)
        said = reasoner.big_models_out(until)
        self.assertIn("until", said)
        for brand in self.BRANDS:
            self.assertNotIn(brand, said)

    def test_one_implementation_for_every_sentence_that_says_it(self):
        """Eight places said this in eight wordings and every one of them
        named a company. A ninth would have drifted the same way."""
        import inspect

        from aletheia import (agent_session, current_state, intents,
                              investigate, mission_jobs, project_work)
        for module in (intents, project_work, current_state, mission_jobs,
                       investigate, agent_session):
            source = inspect.getsource(module)
            for brand in ("Claude and Codex are out", "Claude's out until",
                          "Claude is out until", "Claude could not answer",
                          "Claude and ChatGPT can't answer"):
                self.assertNotIn(brand, source, f"{module.__name__}: {brand}")

    def test_the_planner_does_not_name_the_rung_that_compiled_it(self):
        from aletheia import intents
        said = intents._own_model_line({"compiled_by": "my own model"})
        self.assertIn("myself", said)
        for brand in self.BRANDS:
            self.assertNotIn(brand, said)

    def test_a_frontier_answer_still_carries_no_disclosure_at_all(self):
        from aletheia import investigate
        self.assertNotIn("mine", investigate.spoken_answer(
            type("R", (), {"answer": "Reykjavik.", "model": "sonnet"})()))


if __name__ == "__main__":
    unittest.main()
