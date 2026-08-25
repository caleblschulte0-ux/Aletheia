import json
import tempfile
import threading
import unittest
import urllib.request
from pathlib import Path
from unittest import mock

from aletheia import core, journal, memory, plans, policy, tasks


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

    def _post(self, payload):
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/command",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST")
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

    def test_refuses_non_loopback_bind(self):
        with self.assertRaises(ValueError):
            core.make_server(host="0.0.0.0", port=0)


if __name__ == "__main__":
    unittest.main()
