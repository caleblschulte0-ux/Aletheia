"""One local model job at a time across her processes, conversation first (aletheia.local_lease)."""
import json
import os
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from pathlib import Path
from unittest import mock

from aletheia import local_brain, local_lease, local_model_pool


class LeaseCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patcher = mock.patch.dict(os.environ, {local_lease.LEASE_ENV: self.tmp.name})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_another_process_holding_it_makes_work_wait_until_it_is_released(self):
        script = textwrap.dedent(f"""
            import os, sys, time
            sys.path.insert(0, {str(Path(__file__).resolve().parent.parent)!r})
            os.environ[{local_lease.LEASE_ENV!r}] = {self.tmp.name!r}
            from aletheia import local_lease
            with local_lease.hold(what="child job", hold_s=30, purpose_name="work"):
                print("held", flush=True)
                time.sleep(2.0)
        """)
        child = subprocess.Popen([sys.executable, "-c", script], stdout=subprocess.PIPE, text=True)
        self.addCleanup(child.stdout.close)
        self.addCleanup(child.wait)
        self.assertEqual(child.stdout.readline().strip(), "held")
        self.assertEqual(local_lease.holder()["what"], "child job")
        started = time.monotonic()
        with local_lease.purpose(local_lease.WORK):
            with local_lease.hold(what="parent job", max_wait_s=20) as got:
                self.assertTrue(got["held"])
                self.assertEqual(local_lease.holder()["what"], "parent job")
        self.assertGreater(time.monotonic() - started, 1.0)
        self.assertIsNone(local_lease.holder())

    def test_work_yields_to_a_waiting_conversation_and_says_why(self):
        want = Path(self.tmp.name) / "want-1-x.json"
        want.write_text(json.dumps({"pid": os.getpid(), "at": time.time(), "what": "the room"}), encoding="utf-8")
        with local_lease.purpose(local_lease.WORK):
            with self.assertRaises(local_lease.LeaseBusy) as said:
                with local_lease.hold(what="a repair draft", max_wait_s=0.6):
                    pass
        self.assertIn("conversation is waiting", str(said.exception))

    def test_a_conversation_that_waited_its_bound_goes_ahead_rather_than_go_silent(self):
        lease = Path(self.tmp.name) / local_lease.LEASE_NAME
        lease.write_text(json.dumps({"pid": os.getpid(), "purpose": "work", "what": "a long draft", "token": "t",
                                     "expires_at": time.time() + 600}), encoding="utf-8")
        with local_lease.hold(what="an answer", max_wait_s=0.5) as got:
            self.assertFalse(got["held"])
            self.assertIn("a long draft", got["why"])
        self.assertTrue(lease.exists())                     # never removes someone else's live lease

    def test_a_dead_or_overdue_holder_is_cleared_so_a_crash_never_wedges_her_model(self):
        lease = Path(self.tmp.name) / local_lease.LEASE_NAME
        lease.write_text(json.dumps({"pid": os.getpid(), "purpose": "work", "what": "crashed", "token": "old",
                                     "expires_at": time.time() - 5}), encoding="utf-8")
        with local_lease.hold(what="fresh", max_wait_s=2) as got:
            self.assertTrue(got["held"])
            self.assertEqual(local_lease.holder()["what"], "fresh")

    def test_reentrant_in_one_thread(self):
        with local_lease.hold(what="outer") as outer:
            with local_lease.hold(what="inner", max_wait_s=0.2) as inner:
                self.assertTrue(outer["held"] and inner["held"])
        self.assertIsNone(local_lease.holder())

    def test_every_call_to_her_own_model_goes_through_the_lease(self):
        seen = []

        def fake_infer(system, text, *, context=None, config=None):
            seen.append(local_lease.holder())
            return {"ok": True}
        with mock.patch.object(local_model_pool, "room_for_role", return_value={"fits": True}), \
                mock.patch.object(local_model_pool.model_pool_config, "enabled", return_value=True), \
                mock.patch.object(local_brain, "infer_json", side_effect=fake_infer), \
                mock.patch.object(local_model_pool.training_data, "record_turn", return_value="t"):
            local_model_pool.run_json("system", "text", role="fast")
        self.assertEqual(len(seen), 1)
        self.assertIsNotNone(seen[0])
        self.assertEqual(seen[0]["purpose"], local_lease.CONVERSATION)
        self.assertIsNone(local_lease.holder())

    def test_busy_work_is_a_pool_unavailable_with_the_reason(self):
        with mock.patch.object(local_model_pool, "room_for_role", return_value={"fits": True}), \
                mock.patch.object(local_model_pool.model_pool_config, "enabled", return_value=True), \
                mock.patch.object(local_lease, "hold", side_effect=local_lease.LeaseBusy("the room is talking")), \
                mock.patch.object(local_model_pool.training_data, "record_turn", return_value="t"):
            with self.assertRaises(local_model_pool.LocalPoolUnavailable) as said:
                local_model_pool.run_json("system", "text", role="fast")
        self.assertIn("busy", str(said.exception))


if __name__ == "__main__":
    unittest.main()
