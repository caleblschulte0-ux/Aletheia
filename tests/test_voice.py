"""Voice on the wall: deterministic interpretation, gated execution."""
import json
import os
import time
import tempfile
import unittest
import urllib.request
from pathlib import Path
from unittest import mock

from aletheia import journal, plans, policy, reasoner, tasks, voice
from aletheia import memory


class InterpretCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        d = Path(self.tmp.name)
        for target, attr in ((policy, "APPROVALS_DIR"), (policy, "HALT_PATH"),
                             (tasks, "TASKS_DIR"), (journal, "JOURNAL_PATH")):
            p = mock.patch.object(target, attr, d / attr.lower())
            p.start(); self.addCleanup(p.stop)

    def test_wake_word_stripped_any_alias(self):
        for w in ("Thea", "theia,", "Aletheia:"):
            self.assertEqual(voice.strip_wake_word(f"{w} halt"), "halt")

    def test_halt_and_resume(self):
        self.assertEqual(voice.interpret("Thea, stop everything")["command"]["kind"], "halt")
        self.assertEqual(voice.interpret("thea resume")["command"]["kind"], "resume")

    def test_status_is_answered_not_commanded(self):
        out = voice.interpret("Thea, what's going on?")
        self.assertIsNone(out["command"])
        self.assertIn("task", out["say"])

    def test_read_a_spoken_url(self):
        out = voice.interpret("Thea, read example dot com")
        self.assertEqual(out["command"],
                         {"kind": "browse_read", "url": "https://example.com"})

    def test_read_multiword_spoken_url(self):
        out = voice.interpret("thea check hacker news dot com")
        self.assertEqual(out["command"]["url"], "https://hackernews.com")

    def test_read_without_a_domain_asks_instead_of_guessing(self):
        out = voice.interpret("Thea, read the news")
        self.assertIsNone(out["command"])
        self.assertIn("web address", out["say"])

    def test_approve_with_exactly_one_pending(self):
        policy.request("ap-1", "do thing", "why", "consequence", True)
        out = voice.interpret("Thea, approve")
        self.assertEqual(out["command"], {"kind": "approve", "id": "ap-1"})

    def test_approve_with_two_pending_reads_them_out_instead_of_refusing(self):
        # It used to say "I won't guess which one — use the Command Center",
        # which is a dead end the moment two things are pending, and two
        # things pending is now the ordinary state.
        policy.request("ap-1", "a", "r", "c", True)
        policy.request("ap-2", "b", "r", "c", True)
        out = voice.interpret("Thea, approve")
        self.assertIsNone(out["command"])
        self.assertIn("2 things waiting", out["say"])
        self.assertIn("Which one", out["say"])
        self.assertNotIn("Command Center", out["say"])

    def test_approve_the_first_needs_no_identifier(self):
        policy.request("ap-1", "a", "r", "c", True)
        policy.request("ap-2", "b", "r", "c", True)
        self.assertEqual(voice.interpret("Thea, approve the first")["command"],
                         {"kind": "approve", "id": "ap-1"})

    def test_new_task_by_voice(self):
        out = voice.interpret("Thea, add a task to water the plants")
        self.assertEqual(out["command"]["kind"], "task_new")
        self.assertEqual(out["command"]["description"], "water the plants")

    def test_unrecognized_speech_goes_to_the_planner_not_a_dead_end(self):
        # Until 2026-08-27 this became a journal note and "I don't have a
        # command for that yet" — the operator's journal is full of real
        # asks that died there. It is now an `intent`, which the planner
        # compiles into gated steps (or degrades honestly if no provider).
        out = voice.interpret("Thea, make me a sandwich")
        self.assertEqual(out["command"]["kind"], "intent")
        self.assertEqual(out["command"]["text"], "make me a sandwich")
        self.assertIsNone(out["say"])  # the receipt speaks, not a canned line

    def test_spoken_reply_reads_the_page_back(self):
        say = voice.spoken_reply(
            "browse_read", "done",
            "read https://example.com/ — Example Domain :: Illustrative examples.")
        self.assertIn("Example Domain. Illustrative examples.", say)


class VoiceEndpointCase(unittest.TestCase):
    """POST /api/voice through a live Core, same fixture style as test_core."""

    @classmethod
    def setUpClass(cls):
        from aletheia import core
        cls.tmp = tempfile.TemporaryDirectory()
        d = Path(cls.tmp.name)
        cls.patches = [
            mock.patch.object(journal, "JOURNAL_PATH", d / "journal.jsonl"),
            mock.patch.object(policy, "APPROVALS_DIR", d / "approvals"),
            mock.patch.object(policy, "HALT_PATH", d / "halt.json"),
            mock.patch.object(tasks, "TASKS_DIR", d / "tasks"),
            mock.patch.object(plans, "PLANS_DIR", d / "plans"),
            mock.patch.object(memory, "MEMORY_DIR", d / "memory"),
            # An intent reaches the planner, which reaches a real model and
            # writes a real intent record. Both belong in this fixture, not
            # in the operator's state directory and not over the network:
            # a suite that spends 20s and a subscription call per run is a
            # suite people stop running.
            mock.patch.dict(os.environ,
                            {"ALETHEIA_PRIVATE_STATE": str(d / "private")}),
            mock.patch.object(
                reasoner, "_run_cli",
                return_value=json.dumps({
                    "intent": "plan", "summary": "note it down",
                    "steps": [{"kind": "note", "text": "make a sandwich"}]})),
        ]
        for p in cls.patches:
            p.start()
        cls.server = core.make_server(port=0)
        cls.port = cls.server.server_address[1]
        import threading
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        for p in cls.patches:
            p.stop()
        cls.tmp.cleanup()

    def post_voice(self, transcript):
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/voice",
            data=json.dumps({"transcript": transcript}).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read().decode("utf-8"))

    def test_status_question_answers_without_executing(self):
        res = self.post_voice("Thea, what's going on?")
        self.assertEqual(res["outcome"], "answered")
        self.assertTrue(res["say"])

    def test_halt_then_resume_by_voice(self):
        res = self.post_voice("Thea, stop everything")
        self.assertEqual(res["outcome"], "done")
        self.assertIn("Halted", res["say"])
        self.assertTrue(policy.halted())
        res = self.post_voice("Thea, resume")
        self.assertEqual(res["say"], "Resumed.")
        self.assertFalse(policy.halted())

    def test_an_arbitrary_ask_is_acknowledged_immediately_and_thought_about(self):
        # The old behaviour was to journal the sentence and say "I don't
        # have a command for that yet". It now goes to the planner — which
        # takes ten to thirty seconds, so the ROOM must not be held open
        # that long: she answers now and delivers the real sentence later.
        from aletheia import followups
        started = time.monotonic()
        res = self.post_voice("Thea, make me a sandwich")
        elapsed = time.monotonic() - started
        self.assertEqual(res["outcome"], "thinking")
        self.assertLess(elapsed, 2.0, "the room was held open while she thought")
        self.assertTrue(res["say"])
        self.assertTrue(res["followup_id"])
        # and the real answer is collectable from that slot
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            slot = followups.poll(res["followup_id"])
            if slot["state"] != followups.PENDING:
                break
            time.sleep(0.5)
        self.assertIn(slot["state"], (followups.READY, followups.FAILED))
        self.assertTrue(slot["say"])

    def test_voice_pages_carry_the_ears(self):
        from aletheia.fleet import REPO_ROOT
        for page in ("index.html", "command.html"):
            html = (REPO_ROOT / "interface" / page).read_text(encoding="utf-8")
            self.assertIn("voice.js", html, page)


if __name__ == "__main__":
    unittest.main()


class AttentionAnsweredWithoutAModel(unittest.TestCase):
    """Ported from PR #75 after review. "What needs my attention?" reads
    durable local queues; routing it through the planner cost ~90 seconds
    and a model call to answer from state we already hold."""

    def test_phrases_answer_locally_and_never_reach_the_planner(self):
        for phrase in ("Thea, what needs my attention?",
                       "thea does anything need my attention",
                       "Thea, what do I need to deal with?"):
            with self.subTest(phrase=phrase):
                out = voice.interpret(phrase)
                self.assertIsNone(out["command"],
                                  "must not compile to an intent/planner call")
                self.assertTrue(out["say"].strip())

    def test_quiet_state_says_so_rather_than_inventing(self):
        empty = {"halted": None, "needs_attention": {
            "pending_approvals": [], "waiting_operator": [], "blocked_tasks": [],
            "overdue_replies": [], "unread_notifications": 0}}
        with mock.patch("aletheia.current_state.snapshot", return_value=empty), \
             mock.patch("aletheia.core.status_payload",
                        return_value={"pulse": {"alerts": 0}}):
            self.assertIn("Nothing needs your attention",
                          voice.interpret("Thea, what needs my attention?")["say"])


class TheWallCollectsTheAnswerItWasPromised(unittest.TestCase):
    """The operator's live report: he asked Thea something, was told she
    was working on it, and never received the finished answer.

    POST /api/voice answers immediately with an acknowledgement and a
    `followup_id` because the planner takes ten to thirty seconds. The
    ROOM MICROPHONE collected that slot. The WALL — the surface he
    actually uses — spoke the acknowledgement and stopped, so the real
    sentence was written and never delivered. Silence is the bug.
    """

    def script(self):
        from aletheia.fleet import REPO_ROOT
        return (REPO_ROOT / "interface" / "voice.js").read_text(encoding="utf-8")

    def test_the_wall_polls_the_followup_slot(self):
        body = self.script()
        self.assertIn("/api/voice/followup", body,
                      "the wall never collects the answer it promised")
        self.assertIn("res.followup_id", body,
                      "collection must be driven by the id the Core returned")

    def test_a_failed_slot_is_spoken_rather_than_swallowed(self):
        body = self.script()
        self.assertIn("FAILED", body,
                      "a failure that says nothing is the same bug wearing a hat")

    def test_polling_gives_up_out_loud_instead_of_hanging_forever(self):
        body = self.script()
        self.assertIn("deadline", body)
        self.assertRegex(body, r"taking longer|notifications",
                         "an expired wait must still say something")

    def test_thinking_is_not_painted_as_an_error(self):
        body = self.script()
        self.assertIn('state === "thinking"', body,
                      "an unknown state falls through to the error colour, which "
                      "would tell him she is broken while she is thinking")
