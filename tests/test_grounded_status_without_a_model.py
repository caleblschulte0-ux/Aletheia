"""A status question is answered from her stores with every model OFF.

Found live 2026-09-14, from his phone, the day the phone first reached
the Core: "give me a status update on how applying to jobs is going" came
back

    I could not plan that: ReasonerUnavailable: subscription reasoning
    and local deep reasoning are unavailable ...

The failure was not that nobody could think. It was that a question whose
answer is a file read was routed to thinking at all. These hold the
handoff's acceptance list (handoffs/claude/2026-09-14-local-status-routing.md):
Claude out, the ChatGPT browser out, the local model out, and every one of
these sentences answered from the records - and, with no records, answered
"no evidence" rather than invented, and never handed to the planner.
"""
from __future__ import annotations

import datetime as dt
import unittest
from unittest import mock

from aletheia import apply_run, campaign, current_state, intents, quick, stateio
from tests.test_current_state_v2 import Records, fresh, record

NOBODY = {"claude": {"resting_until": "2026-01-01T00:00:00Z"},
          "codex": {"resting_until": "2026-01-01T00:00:00Z", "why": "out"},
          "local": {"allowed": False, "why": "cannot run on this machine"},
          "anyone": False}


def no_planner(*_a, **_k):
    raise AssertionError("the planner was reached for a status question")


class EveryBrainOff(Records):
    """Claude, the ChatGPT browser and the deep local model are all unavailable."""

    def setUp(self):
        super().setUp()
        for target in ("aletheia.reasoner.subscription_json",
                       "aletheia.reasoner.local_json",
                       "aletheia.reasoner.local_text",
                       "aletheia.brain.plan",
                       "aletheia.planner.compile"):
            try:
                patch = mock.patch(target, side_effect=no_planner)
                patch.start()
                self.addCleanup(patch.stop)
            except AttributeError:
                pass
        minds = mock.patch.object(current_state, "thinking", return_value=dict(NOBODY))
        minds.start(); self.addCleanup(minds.stop)

    def ask(self, sentence: str) -> str:
        """Through the same door the Core uses: the fast lane, and the
        planner behind it forbidden."""
        out = intents.propose(sentence, quote=sentence, fleet={"repos": {}},
                              provider=mock.Mock(side_effect=no_planner), registry={"capabilities": []})
        self.assertTrue(out.get("fast_path"), f"{sentence!r} was not answered from the stores")
        said = out["spoken"]
        self.assertNotIn("ReasonerUnavailable", said)
        self.assertNotIn("could not plan", said)
        return said


class WithRecords(EveryBrainOff):
    def setUp(self):
        super().setUp()
        record("stripe", "SUBMITTED", staged_at=fresh(90), submitted_at=fresh(18),
               company="Stripe", job_title="Operations Analyst")
        record("figma", "SUBMITTED", staged_at=fresh(200), submitted_at=fresh(140),
               company="Figma", job_title="Ops Lead")
        record("palantir", "FAILED", staged_at=fresh(30),
               failure="the Submit button would not take a click - a CAPTCHA challenge was in front of it")
        record("brex", "NEEDS_YOU", staged_at=fresh(10),
               questions=[{"label": "Preferred shift", "required": True}])
        current_state.forget_cache()

    def test_how_is_applying_going_is_the_days_report(self):
        for sentence in ("how is applying to jobs going?",
                         "Give me a status update on how applying to jobs is going.",
                         "any progress on the job hunt", "where are we with the applications",
                         "what's the latest on the job search"):
            with self.subTest(sentence=sentence):
                said = self.ask(sentence)
                self.assertIn("2 sent", said)
                self.assertIn("1 blocked", said)
                self.assertIn("Palantir", said)

    def test_how_many_is_the_exact_count(self):
        said = self.ask("how many jobs have you applied to?")
        self.assertTrue(said.startswith("2 applications sent today"), said)
        said = self.ask("how many applications have you sent in total")
        self.assertTrue(said.startswith("2 applications sent in total"), said)

    def test_still_applying_reads_the_process_not_the_clock(self):
        said = self.ask("are you still applying?")
        self.assertTrue(said.startswith("No, nothing is running"), said)
        self.assertIn("Stripe", said)
        self.assertIn("18 minutes ago", said)
        lock = {"kind": "campaign", "pid": 424242, "count": 8, "limit": 8,
                "started_at": fresh(25)}
        stateio.write_json_atomic(campaign.LOCK_PATH, lock)
        current_state.forget_cache()
        with mock.patch("aletheia.proc.pid_alive", return_value=True):
            said = self.ask("is the job hunt still running")
        self.assertTrue(said.startswith("Yes, a batch of applications is running now"), said)
        self.assertIn("25 minutes ago", said)
        self.assertIn("8 applications", said)
        with mock.patch("aletheia.proc.pid_alive", return_value=False):
            current_state.forget_cache()
            said = self.ask("are you still sending out applications")
        self.assertTrue(said.startswith("No, nothing is running"), said)

    def test_the_last_application_when_and_what(self):
        said = self.ask("when was the last application?")
        self.assertIn("18 minutes ago", said)
        self.assertIn("Stripe", said)
        said = self.ask("what was the last job you applied to?")
        self.assertIn("Operations Analyst at Stripe", said)
        self.assertIn("18 minutes ago", said)

    def test_what_is_blocking_names_the_recorded_blockers(self):
        said = self.ask("what's blocking the job application run?")
        self.assertIn("nobody can think", said.lower())
        self.assertIn("Brex", said)
        self.assertIn("Preferred shift", said)
        self.assertIn("Palantir", said)
        self.assertIn("CAPTCHA", said)

    def test_did_anything_fail(self):
        said = self.ask("did anything fail?")
        self.assertIn("Palantir", said)

    def test_a_status_question_writes_nothing_and_runs_nothing(self):
        before = sorted(p.name for p in apply_run.staged_dir().glob("*.json"))
        with mock.patch("aletheia.campaign.start", side_effect=AssertionError("started a run")), \
             mock.patch("subprocess.run", side_effect=AssertionError("ran a command")), \
             mock.patch("subprocess.Popen", side_effect=AssertionError("ran a command")), \
             mock.patch("aletheia.policy.create_approval", side_effect=AssertionError("approval"),
                        create=True):
            for sentence in ("how's applying to jobs going", "are you still applying",
                             "how many jobs have you applied to", "when was the last application",
                             "what's blocking the job hunt"):
                self.ask(sentence)
        self.assertEqual(before, sorted(p.name for p in apply_run.staged_dir().glob("*.json")))
        self.assertFalse(campaign.LOCK_PATH.exists())


class WithNoRecords(EveryBrainOff):
    def test_no_evidence_is_said_as_no_evidence(self):
        for sentence, expected in (
                ("how's applying to jobs going", "No applications today"),
                ("how many jobs have you applied to", "None so far"),
                ("are you still applying", "No, nothing is running"),
                ("when was the last application", "not sent an application yet"),
                ("what was the last job you applied to", "not sent an application yet"),
                ("what's blocking the job hunt", "nobody can think")):
            with self.subTest(sentence=sentence):
                said = self.ask(sentence)
                self.assertIn(expected.lower(), said.lower())
                for invented in ("17", "23", "succeeded", "completed"):
                    self.assertNotIn(invented, said)


class WhyWithNothingRecordedIsNotAnswered(Records):
    """"Why is the job hunt stopped" with no blocker on record goes to the
    investigator, which reads the journal and the receipts. The fast lane
    only ever removes latency; a quick "nothing here" would remove that."""

    def test_blocking_with_nothing_recorded_steps_aside(self):
        with mock.patch.object(current_state, "thinking", return_value={
                "claude": {"resting_until": None}, "codex": {"resting_until": None},
                "local": {"allowed": True, "why": "ok"}, "anyone": True}):
            self.assertIsNone(quick.answer("what's blocking the job hunt"))
            self.assertIsNone(quick.answer("why is the job hunt stopped"))


class TheSubjectPicksTheStore(unittest.TestCase):
    def test_the_shapes_and_subjects(self):
        for sentence, expected in (
                ("how's applying to jobs going", ("going", "applying to jobs")),
                ("give me a status update on the job hunt", ("going", "the job hunt")),
                ("are you still applying", ("still", "applying")),
                ("is the job search still going", ("still", "the job search")),
                ("how many jobs have you applied to", ("count", "the job hunt")),
                ("how many jobs have you applied to in total", ("count_total", "the job hunt")),
                ("when was the last application", ("last_when", "application")),
                ("what was the last job you applied to", ("last_what", "job")),
                ("what's blocking the job hunt", ("blocking", "the job hunt")),
                ("why aren't you applying", ("blocking", "applying")),
                ("is the shorts pipeline running", ("repo", "shorts")),
                ("how's the trader doing", ("repo", "trader"))):
            with self.subTest(sentence=sentence):
                self.assertEqual(quick.status_of(sentence), expected)

    def test_a_subject_no_store_knows_is_the_planners(self):
        """"Is my car running" matches the shape and no store; the answer is
        None, which is the planner - never a repo row for something else."""
        with mock.patch.object(current_state, "repo_words", return_value=None):
            for sentence in ("is my car running", "how's the wedding planning going",
                             "is the oven still on"):
                with self.subTest(sentence=sentence):
                    self.assertIsNone(quick.answer(sentence))

    def test_a_repo_is_answered_from_the_pulse(self):
        import json
        from aletheia import pulse
        latest = {"repos": {"shorts_pipeline": {"github": "Shorts-pipeline", "health": "red",
                                                "commit": {"date": fresh(30)},
                                                "workflows": {"third.yml": {"conclusion": "failure"},
                                                              "daily.yml": {"conclusion": "success"}}},
                            "schwab_trader": {"github": "schwab-trader", "health": "green",
                                              "commit": {"date": fresh(60 * 30)}, "workflows": {}}}}
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "latest.json").write_text(json.dumps(latest), encoding="utf-8")
            with mock.patch.object(pulse, "PULSE_DIR", Path(tmp)):
                said = quick.answer("is the shorts pipeline running")
                self.assertIn("Shorts-pipeline is not healthy", said)
                self.assertIn("third", said)
                self.assertIn("30 minutes ago", said)
                said = quick.answer("how's the trader doing")
                self.assertIn("schwab-trader is healthy", said)
                self.assertIsNone(quick.answer("is the toaster running"))

    def test_her_own_status_is_herself_not_the_repository(self):
        with mock.patch.object(quick, "_doing", return_value="Nothing right now."):
            self.assertEqual(quick.answer("what is the status of aletheia"), "Nothing right now.")
            self.assertEqual(quick.answer("is aletheia running"), "Nothing right now.")


if __name__ == "__main__":
    unittest.main()
