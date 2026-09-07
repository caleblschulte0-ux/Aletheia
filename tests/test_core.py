import json
import tempfile
import threading
import time
import unittest
import urllib.request
from pathlib import Path
from unittest import mock

from aletheia import access
from aletheia import core, followups, journal, memory, notifications, plans, policy, speech, tasks


class CoreCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        base = Path(cls.tmp.name)
        cls.patches = [
            mock.patch.object(journal, "JOURNAL_PATH", base / "j.jsonl"),
            mock.patch.object(tasks, "TASKS_DIR", base / "tasks"),
            mock.patch.object(plans, "PLANS_DIR", base / "plans"),
            mock.patch.object(memory, "MEMORY_DIR", base / "memory"),
            mock.patch.object(policy, "APPROVALS_DIR", base / "approvals"),
            mock.patch.object(policy, "HALT_PATH", base / "halt.json"),
            mock.patch.object(notifications, "NOTICES_DIR", base / "notices"),
            mock.patch.object(followups, "records_dir", return_value=base / "followups"),
        ]
        for p in cls.patches:
            p.start()
        cls.server = core.make_server(port=0)  # ephemeral port
        cls.port = cls.server.server_address[1]
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        for p in cls.patches:
            p.stop()
        cls.tmp.cleanup()

    def _get(self, path):
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}{path}") as r:
            return json.loads(r.read().decode("utf-8"))

    def _post(self, payload, path="/api/command"):
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{path}",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json",
                     "X-Aletheia-Local": access.local_secret()}, method="POST")
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read().decode("utf-8"))

    def test_status_answers(self):
        s = self._get("/api/status")
        self.assertIn("tasks", s)
        self.assertIsNone(s["halted"])

    def test_command_roundtrip_creates_durable_task(self):
        res = self._post({"kind": "task_new", "id": "from-core",
                          "description": "created through the local Core"})
        self.assertEqual(res["outcome"], "done")
        self.assertEqual(tasks.load("from-core")["status"], "QUEUED")
        ids = [t["id"] for t in self._get("/api/tasks")]
        self.assertIn("from-core", ids)

    def test_unknown_kind_is_invalid_not_crash(self):
        res = self._post({"kind": "shell", "cmd": "rm -rf"})
        self.assertEqual(res["outcome"], "invalid")

    def test_halt_resume_through_the_api(self):
        self.assertEqual(self._post({"kind": "halt", "reason": "test"})["outcome"], "done")
        held = self._post({"kind": "note", "text": "should not land"})
        self.assertEqual(held["outcome"], "halted")
        self.assertEqual(self._post({"kind": "resume"})["outcome"], "done")

    def test_serves_the_interfaces(self):
        for path in ("/", "/command.html"):
            with urllib.request.urlopen(f"http://127.0.0.1:{self.port}{path}") as r:
                self.assertEqual(r.status, 200)
                self.assertIn(b"ALETHEIA", r.read())

    def test_no_path_escape(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(
                f"http://127.0.0.1:{self.port}/interface/../CLAUDE.md")
        self.assertEqual(ctx.exception.code, 404)

    def test_operating_system_endpoints_answer(self):
        state = self._get("/api/state")
        self.assertIn("needs_attention", state)
        self.assertIn("halted", state)
        # shape, not emptiness: these endpoints read the machine's real
        # private stores, which legitimately hold operator state
        self.assertIsInstance(self._get("/api/events"), list)
        self.assertIsInstance(self._get("/api/watchers"), list)
        self.assertIsInstance(self._get("/api/schedules"), list)
        self.assertIn("at", self._get("/api/runtime"))

    def test_notification_publish_and_ack_roundtrip(self):
        notice = notifications.publish("Test", "core ack roundtrip", dedupe_key="core-test")
        listed = self._get("/api/notifications?state=UNREAD")
        self.assertIn(notice["id"], [n["id"] for n in listed])
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/notifications/ack",
            data=json.dumps({"id": notice["id"]}).encode("utf-8"),
            headers={"Content-Type": "application/json",
                     "X-Aletheia-Local": access.local_secret()}, method="POST")
        with urllib.request.urlopen(req) as r:
            self.assertEqual(json.loads(r.read())["state"], "ACKNOWLEDGED")
        self.assertEqual(notifications.load(notice["id"])["state"], "ACKNOWLEDGED")

    def test_refuses_non_loopback_bind(self):
        with self.assertRaises(ValueError):
            core.make_server(host="0.0.0.0", port=0)

    def test_arbitrary_ask_acknowledges_then_delivers_the_answer(self):
        with mock.patch.object(
                core, "run_command",
                return_value={"outcome": "done", "detail": "Eventual answer."}):
            first = self._post({"text": "take your time"}, path="/api/ask")
            self.assertEqual(first["outcome"], "thinking")
            # Against the CONTRACT, not a frozen literal: the line is
            # `speech.ack_line`, so a question gets "Let me look." and an
            # instruction gets "Working on it.". "Take your time" is an
            # instruction.
            self.assertEqual(first["say"], speech.ACK_ACTION)
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                result = self._get(
                    f"/api/voice/followup?id={first['followup_id']}")
                if result["state"] != followups.PENDING:
                    break
                time.sleep(0.01)
            else:
                self.fail("typed ask never produced its follow-up")
        self.assertEqual(result["state"], followups.READY)
        self.assertEqual(result["say"], "Eventual answer.")


if __name__ == "__main__":
    unittest.main()


class CommandGrammarSingleSource(CoreCase):
    """/api/kinds serves the intercom validator's grammar, and the
    Command Center holds NO copy of it — the page once hardcoded a KINDS
    map that drifted the day browse kinds landed."""

    def test_api_kinds_is_the_validator_grammar(self):
        from aletheia import intercom
        kinds = self._get("/api/kinds")
        self.assertEqual(set(kinds), set(intercom.KIND_ARGS))
        for kind, (req, opt) in intercom.KIND_ARGS.items():
            self.assertEqual(kinds[kind], [sorted(req), sorted(opt)])

    def test_command_center_has_no_hardcoded_grammar(self):
        from aletheia.fleet import REPO_ROOT
        html = (REPO_ROOT / "interface" / "command.html").read_text(encoding="utf-8")
        self.assertIn("/api/kinds", html)
        self.assertNotIn("plan_add_step", html,
                         "command.html restates the kind grammar — it must render /api/kinds")

    def test_command_center_waits_for_async_answers_and_surfaces_errors(self):
        from aletheia.fleet import REPO_ROOT
        html = (REPO_ROOT / "interface" / "command.html").read_text(encoding="utf-8")
        self.assertIn('api("/api/ask"', html)
        self.assertIn("waitForFollowup", html)
        self.assertIn("catch (err)", html)
