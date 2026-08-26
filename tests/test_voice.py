"""Voice on the wall: deterministic interpretation, gated execution."""
import json
import tempfile
import unittest
import urllib.request
from pathlib import Path
from unittest import mock

from aletheia import journal, plans, policy, tasks, voice
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

    def test_approve_with_two_pending_refuses_to_guess(self):
        policy.request("ap-1", "a", "r", "c", True)
        policy.request("ap-2", "b", "r", "c", True)
        out = voice.interpret("Thea, approve")
        self.assertIsNone(out["command"])
        self.assertIn("won't guess", out["say"])

    def test_new_task_by_voice(self):
        out = voice.interpret("Thea, add a task to water the plants")
        self.assertEqual(out["command"]["kind"], "task_new")
        self.assertEqual(out["command"]["description"], "water the plants")

    def test_unrecognized_becomes_a_note_and_says_so(self):
        out = voice.interpret("Thea, make me a sandwich")
        self.assertEqual(out["command"]["kind"], "note")
        self.assertIn("unmatched", out["command"]["text"])
        self.assertIn("don't have a command", out["say"])

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

    def test_note_fallback_journals_the_words(self):
        res = self.post_voice("Thea, make me a sandwich")
        self.assertEqual(res["outcome"], "done")
        self.assertIn("don't have a command", res["say"])
        texts = [e["text"] for e in journal.entries()]
        self.assertTrue(any("sandwich" in t for t in texts))

    def test_voice_pages_carry_the_ears(self):
        from aletheia.fleet import REPO_ROOT
        for page in ("index.html", "command.html"):
            html = (REPO_ROOT / "interface" / page).read_text(encoding="utf-8")
            self.assertIn("voice.js", html, page)


if __name__ == "__main__":
    unittest.main()
