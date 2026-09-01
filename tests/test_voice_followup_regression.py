"""Regressions for the live "Working on that" -> silence failure."""
from __future__ import annotations

import json
import threading
import time
import unittest
import urllib.request
from unittest import mock

from aletheia import core, followups


EMPTY_RUNTIME = {
    "schedules": [], "reply_transitions": [], "events": [],
    "watchers": [], "intents": [], "errands": [], "failures": [],
}


class FakeSyncer:
    def __init__(self, *, code_update: bool = False):
        self.pull_calls = 0
        self.commit_calls = 0
        self.push_calls = 0
        self.code_update = code_update
        self._head_calls = 0

    def commit(self, _paths, _message):
        self.commit_calls += 1
        return True, "ok"

    def head(self):
        if not self.code_update:
            return "same"
        self._head_calls += 1
        return "old" if self._head_calls == 1 else "new"

    def pull(self):
        self.pull_calls += 1
        return True, "ok"

    def changed_paths(self, _old, _new, _limit_to=None):
        return ["aletheia/new_code.py"] if self.code_update else []

    def commit_push(self, _paths, _message):
        self.push_calls += 1
        return True, "ok"


class CoreBeatRegressionCase(unittest.TestCase):
    def setUp(self):
        followups.reset()
        self.addCleanup(followups.reset)

    def _start_common_patches(self):
        patches = (
            mock.patch.object(core.liveness, "beat"),
            mock.patch.object(core.journal, "append"),
            mock.patch("aletheia.presence.snapshot", return_value={}),
            mock.patch("aletheia.pulse.write_local_block"),
            mock.patch.object(core.intercom, "run_pending", return_value=[]),
            mock.patch("aletheia.mail.available", return_value=(False, "off")),
            mock.patch("aletheia.ics.refresh_if_due", return_value=None),
            mock.patch.object(core, "stale_code_files", return_value=[]),
        )
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_undelivered_voice_answer_defers_only_pull_not_runtime(self):
        gate = threading.Event()
        slot = followups.start(lambda: (gate.wait(5), "finished")[1])
        self.addCleanup(gate.set)
        syncer = FakeSyncer()
        status = {"enabled": True, "last_tick": None, "pull": None,
                  "push": None, "commands_executed": 0, "last_push_s": time.time()}
        self._start_common_patches()

        with mock.patch.object(core.runtime, "tick", return_value=dict(EMPTY_RUNTIME)) as tick:
            core.core_tick(syncer, {}, status)

        self.assertEqual(syncer.pull_calls, 0)
        self.assertEqual(status["update_deferred"]["voice_followups"], 1)
        tick.assert_called_once_with({})
        self.assertEqual(followups.poll(slot["id"])["state"], followups.PENDING)

    def test_restart_callback_keeps_update_reservation_until_process_exit(self):
        syncer = FakeSyncer(code_update=True)
        status = {"enabled": True, "last_tick": None, "pull": None,
                  "push": None, "commands_executed": 0}
        self._start_common_patches()

        fired = []
        result = core.core_tick(
            syncer, {}, status,
            on_code_update=lambda changed: (fired.append(changed), True)[1],
        )
        self.assertEqual(fired, [["aletheia/new_code.py"]])
        self.assertTrue(followups.update_in_progress())
        with self.assertRaises(followups.UpdateInProgress):
            followups.start(lambda: "must not be promised while exiting")
        self.assertIs(result, status)


class FollowupHttpRegressionCase(unittest.TestCase):
    def setUp(self):
        followups.reset()
        self.addCleanup(followups.reset)
        self.server = core.make_server("127.0.0.1", 0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        host, port = self.server.server_address[:2]
        self.base = f"http://{host}:{port}"
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    @staticmethod
    def _json_response(url_or_request):
        with urllib.request.urlopen(url_or_request, timeout=3) as response:
            return json.loads(response.read().decode("utf-8"))

    def _wait_ready(self, fid):
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            slot = followups.poll(fid)
            if slot["state"] != followups.PENDING:
                return slot
            time.sleep(0.01)
        self.fail("follow-up never became ready")

    def test_http_get_can_be_retried_before_ack_without_losing_answer(self):
        slot = followups.start(lambda: "finished answer")
        self._wait_ready(slot["id"])
        url = f"{self.base}/api/voice/followup?id={slot['id']}"

        first = self._json_response(url)
        second = self._json_response(url)
        self.assertEqual(first["state"], followups.READY)
        self.assertEqual(second, first)

        req = urllib.request.Request(
            f"{self.base}/api/voice/followup/ack",
            data=json.dumps({"id": slot["id"]}).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST",
        )
        ack = self._json_response(req)
        self.assertEqual(ack["state"], followups.ACKED)
        self.assertEqual(self._json_response(url)["state"], "EXPIRED")

    def test_slow_voice_request_during_update_gets_immediate_busy_not_promise(self):
        self.assertTrue(followups.begin_update())
        with mock.patch(
            "aletheia.voice.interpret",
            return_value={"command": {"kind": "intent", "text": "plan this"}, "say": None},
        ):
            req = urllib.request.Request(
                f"{self.base}/api/voice",
                data=json.dumps({"transcript": "thea plan this"}).encode("utf-8"),
                headers={"Content-Type": "application/json"}, method="POST",
            )
            answer = self._json_response(req)
        self.assertEqual(answer["outcome"], "busy")
        self.assertNotIn("followup_id", answer)
        self.assertEqual(followups.undelivered_count(), 0)


if __name__ == "__main__":
    unittest.main()
