import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import intercom, journal, memory, plans, policy, tasks
from aletheia.fleet import load_fleet
from tests.test_capabilities import RecordingAPI


def _cmd(cid="20260825-test", kind="note", **args):
    command = {"kind": kind, **args}
    return {
        "id": cid,
        "filed": "2026-08-25T16:00:00Z",
        "by": "chatgpt",
        "relayed_from": "operator",
        "operator_quote": "do the thing",
        "command": command,
    }


class IntercomCase(unittest.TestCase):
    def setUp(self):
        self.fleet = load_fleet()
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)
        for target, attr in ((journal, "JOURNAL_PATH"), (plans, "PLANS_DIR"),
                             (tasks, "TASKS_DIR"), (memory, "MEMORY_DIR"),
                             (policy, "APPROVALS_DIR"), (policy, "HALT_PATH")):
            p = mock.patch.object(target, attr, self.dir / attr.lower())
            p.start(); self.addCleanup(p.stop)

    def _write(self, payload, name=None):
        name = name or f"{payload['id']}.json"
        path = self.dir / name
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path


class TestValidation(IntercomCase):
    def test_valid_note_passes(self):
        p = self._write(_cmd(text="remember the milk"))
        self.assertEqual(intercom.validate_command(p, self.fleet), [])

    def test_unknown_kind_refused(self):
        p = self._write(_cmd(kind="shell", text="rm -rf"))
        problems = intercom.validate_command(p, self.fleet)
        self.assertTrue(any("named slots" in x for x in problems))

    def test_missing_operator_quote_refused(self):
        c = _cmd(text="hi"); c["operator_quote"] = "  "
        problems = intercom.validate_command(self._write(c), self.fleet)
        self.assertTrue(any("operator_quote" in x for x in problems))

    def test_extra_args_refused(self):
        p = self._write(_cmd(kind="dispatch", repo="aletheia",
                             workflow="pulse.yml", script="evil.py"))
        problems = intercom.validate_command(p, self.fleet)
        self.assertTrue(any("unexpected args" in x for x in problems))

    def test_only_operator_relay_accepted(self):
        c = _cmd(text="hi"); c["relayed_from"] = "chatgpt"
        problems = intercom.validate_command(self._write(c), self.fleet)
        self.assertTrue(any("operator" in x for x in problems))


class TestExecution(IntercomCase):
    def test_note_journals_with_relay_actor(self):
        self._write(_cmd(text="remember the milk"))
        results = intercom.run_pending(self.fleet, request=RecordingAPI(),
                                       commands_dir=self.dir)
        self.assertEqual(results[0]["outcome"], "done")
        actors = {e["actor"] for e in journal.entries()}
        self.assertEqual(actors, {intercom.ACTOR})

    def test_ungranted_dispatch_gets_refused_receipt(self):
        self._write(_cmd(kind="dispatch", repo="shorts_pipeline", workflow="daily.yml"))
        api = RecordingAPI()
        results = intercom.run_pending(self.fleet, request=api, commands_dir=self.dir)
        self.assertEqual(results[0]["outcome"], "refused")
        self.assertEqual([c for c in api.calls if c[0] != "GET"], [])

    def test_granted_dispatch_executes(self):
        self._write(_cmd(kind="dispatch", repo="aletheia", workflow="pulse.yml"))
        api = RecordingAPI()
        results = intercom.run_pending(self.fleet, request=api, commands_dir=self.dir)
        self.assertEqual(results[0]["outcome"], "done")
        self.assertIn("/actions/workflows/pulse.yml/dispatches", api.calls[0][1])

    def test_plan_commands_round_trip(self):
        self._write(_cmd("20260825-a", kind="plan_new", slug="trip",
                         title="Trip", goal="go somewhere warm"))
        self._write(_cmd("20260825-b", kind="plan_add_step", slug="trip", text="pick dates"))
        self._write(_cmd("20260825-c", kind="plan_step", slug="trip", n=1, state="done"))
        results = intercom.run_pending(self.fleet, request=RecordingAPI(),
                                       commands_dir=self.dir)
        self.assertEqual([r["outcome"] for r in results], ["done"] * 3)
        self.assertEqual(plans.progress(plans.load("trip")), (1, 1))

    def test_receipts_make_execution_idempotent(self):
        self._write(_cmd(text="once only"))
        intercom.run_pending(self.fleet, request=RecordingAPI(), commands_dir=self.dir)
        again = intercom.run_pending(self.fleet, request=RecordingAPI(), commands_dir=self.dir)
        self.assertEqual(again, [])
        self.assertEqual(len(journal.entries()), 2)  # note + action, not doubled

    def test_task_commands_create_durable_state(self):
        self._write(_cmd("20260825-t1", kind="task_new", id="call-dentist",
                         description="Call the dentist about a cleaning"))
        self._write(_cmd("20260825-t2", kind="task_status", id="call-dentist",
                         state="WAITING_EXTERNAL", note="left a voicemail"))
        results = intercom.run_pending(self.fleet, request=RecordingAPI(),
                                       commands_dir=self.dir)
        self.assertEqual([r["outcome"] for r in results], ["done", "done"])
        t = tasks.load("call-dentist")
        self.assertEqual(t["status"], "WAITING_EXTERNAL")
        self.assertEqual(t["result"], "left a voicemail")

    def test_halt_by_voice_then_only_resume_executes(self):
        self._write(_cmd("20260825-h", kind="halt", reason="stop everything"))
        results = intercom.run_pending(self.fleet, request=RecordingAPI(),
                                       commands_dir=self.dir)
        self.assertEqual(results[0]["outcome"], "done")
        # while halted, an action command is held...
        self._write(_cmd("20260825-x", kind="dispatch", repo="aletheia",
                         workflow="pulse.yml"))
        results = intercom.run_pending(self.fleet, request=RecordingAPI(),
                                       commands_dir=self.dir)
        self.assertEqual(results[0]["outcome"], "halted")
        # ...and a resume goes through and lifts it
        self._write(_cmd("20260825-r", kind="resume"))
        results = intercom.run_pending(self.fleet, request=RecordingAPI(),
                                       commands_dir=self.dir)
        self.assertEqual(results[0]["outcome"], "done")
        self.assertIsNone(policy.halted())

    def test_approve_by_voice_decides_the_approval(self):
        policy.request("delegate-fix-shorts", "delegate", "why", "worker acts",
                       reversible=True)
        self._write(_cmd("20260825-a", kind="approve", id="delegate-fix-shorts"))
        results = intercom.run_pending(self.fleet, request=RecordingAPI(),
                                       commands_dir=self.dir)
        self.assertEqual(results[0]["outcome"], "done")
        self.assertTrue(policy.is_approved("delegate-fix-shorts"))

    def test_remember_by_voice_carries_operator_provenance(self):
        c = _cmd("20260825-m", kind="remember", domain="preferences",
                 key="after_work", value="after 17:30 on workdays")
        c["operator_quote"] = "when I say after work I mean after 5:30"
        self._write(c)
        results = intercom.run_pending(self.fleet, request=RecordingAPI(),
                                       commands_dir=self.dir)
        self.assertEqual(results[0]["outcome"], "done")
        self.assertIn("after 5:30", memory.why("preferences", "after_work"))

    def test_invalid_command_gets_invalid_receipt_not_crash(self):
        (self.dir / "20260825-bad.json").write_text("{not json", encoding="utf-8")
        results = intercom.run_pending(self.fleet, request=RecordingAPI(),
                                       commands_dir=self.dir)
        self.assertEqual(results[0]["outcome"], "invalid")


if __name__ == "__main__":
    unittest.main()
