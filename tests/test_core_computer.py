"""Loopback Core wiring tests for the isolated Phase 7 draft."""
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

from aletheia import core, journal, policy


PLAN = [{"action": "open_app", "app": "notepad.exe"}]


class FakeBackend:
    def __init__(self):
        self.steps = []

    def perform(self, step):
        self.steps.append(step)
        return {"action": step["action"], "verified": True}


class CoreComputerCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        for module, attr, path in (
                (journal, "JOURNAL_PATH", root / "journal.jsonl"),
                (policy, "APPROVALS_DIR", root / "approvals"),
                (policy, "HALT_PATH", root / "halt.json")):
            patch = mock.patch.object(module, attr, path)
            patch.start(); self.addCleanup(patch.stop)
        self.backends = []

        def factory():
            backend = FakeBackend()
            self.backends.append(backend)
            return backend

        self.server = core.make_server(port=0, computer_backend_factory=factory)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.stop_server)

    def stop_server(self):
        self.server.shutdown()
        self.server.server_close()

    def approve(self, aid):
        from aletheia import computer
        policy.request(aid, computer.approval_action(PLAN), "test",
                       "fake backend receives a step", reversible=True)
        policy.decide(aid, "APPROVED", via="test")
        return aid

    def post(self, payload):
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/computer",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST")
        try:
            with urllib.request.urlopen(request) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode("utf-8"))

    def test_status_mirrors_the_registry_and_does_not_construct_backend(self):
        """Assert the contract, not a snapshot: this test previously froze the
        literal "NOT_BUILT" and so survived the registry going stale. It now
        fails only if the endpoint and the registry disagree."""
        from aletheia import capabilities
        with urllib.request.urlopen(
                f"http://127.0.0.1:{self.port}/api/computer/status") as response:
            body = json.loads(response.read().decode("utf-8"))
        entry = capabilities.get("computer.control")
        self.assertEqual(body["registry_status"], entry["status"])
        self.assertEqual(body["registry_notes"], entry.get("notes", ""))
        self.assertEqual(self.backends, [])  # status never builds a backend

    def test_unapproved_request_is_refused_before_backend_creation(self):
        code, body = self.post({"steps": PLAN, "approval_id": "missing"})
        self.assertEqual(code, 403)
        self.assertEqual(body["outcome"], "refused")
        self.assertEqual(self.backends, [])

    def test_malformed_plan_is_invalid_before_backend_creation(self):
        code, body = self.post({
            "steps": [{"action": "coordinate_click", "x": 1, "y": 2}],
            "approval_id": "anything"})
        self.assertEqual(code, 400)
        self.assertEqual(body["outcome"], "invalid")
        self.assertEqual(self.backends, [])

    def test_unknown_transport_field_is_refused(self):
        code, body = self.post({
            "steps": PLAN, "approval_id": "anything", "shell": "whoami"})
        self.assertEqual(code, 400)
        self.assertIn("unsupported fields", body["detail"])
        self.assertEqual(self.backends, [])

    def test_approved_request_executes_once(self):
        aid = self.approve("core-computer-once")
        code, body = self.post({"steps": PLAN, "approval_id": aid})
        self.assertEqual(code, 200)
        self.assertEqual(body["outcome"], "done")
        self.assertEqual(self.backends[0].steps, PLAN)

        code, body = self.post({"steps": PLAN, "approval_id": aid})
        self.assertEqual(code, 403)
        self.assertIn("already consumed", body["detail"])
        self.assertEqual(len(self.backends), 1)

    def test_halt_does_not_consume_approval_or_construct_backend(self):
        aid = self.approve("core-computer-halted")
        policy.halt("stop", via="test")
        code, body = self.post({"steps": PLAN, "approval_id": aid})
        self.assertEqual(code, 409)
        self.assertEqual(body["outcome"], "halted")
        self.assertEqual(self.backends, [])

        policy.resume(via="test")
        code, body = self.post({"steps": PLAN, "approval_id": aid})
        self.assertEqual(code, 200)
        self.assertEqual(body["outcome"], "done")
        self.assertEqual(len(self.backends), 1)


if __name__ == "__main__":
    unittest.main()
