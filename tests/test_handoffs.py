"""A request her session could not run becomes his decision, and then exactly that happens.

End to end with a scripted model: the session hands off a write, a real
pending approval is created through `policy`, a simulated approve runs
exactly that request once through the executor with a receipt, a second
approve does nothing, a tampered request is refused, and the session record
shows what became of it. Around that: denial and expiry are recorded, she
cannot approve her own request, spending is never filed and never runs, and
the kill switch holds an approved request back until resume.
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import agent_session as s
from aletheia import handoffs, intercom, journal, notifications, policy, stateio, tools


def scripted(*replies):
    queue = list(replies)

    def think(system, text):
        if not queue:
            raise AssertionError("the model was called more often than scripted")
        return queue.pop(0), "fake:model"
    return think


class Isolated(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        (root / "approvals").mkdir()
        for target, attr, value in ((policy, "APPROVALS_DIR", root / "approvals"),
                                    (policy, "HALT_PATH", root / "halt.json"),
                                    (journal, "JOURNAL_PATH", root / "journal.jsonl"),
                                    (notifications, "NOTICES_DIR", root / "notifications")):
            patch = mock.patch.object(target, attr, value)
            patch.start()
            self.addCleanup(patch.stop)
        env = mock.patch.dict(os.environ, {"ALETHEIA_PRIVATE_STATE": str(root / "private")})
        env.start()
        self.addCleanup(env.stop)
        self.calls = []

        def writer(args):
            self.calls.append(dict(args))
            return {"text": f"added a task: {args['text']}"}

        self.catalog = {
            "tasks.write": tools.declare(
                "tasks.write", description="Adds a task to his list.",
                input_schema={"properties": {"text": {"type": "string"}}, "required": ["text"]},
                handler=writer, capability="task.persist", risk=intercom.TIER_ROUTINE,
                writes=("tasks",), approval="operator_once"),
            "approve": tools.replace(tools.catalog()["approve"], local_model_visible=True),
        }

    def ask(self, text="call the plumber", question="add a task to call the plumber"):
        broker = s.Broker(self.catalog, halted=lambda: False, registry={"capabilities": []},
                          fleet={"repos": {}})
        think = scripted({"tool": "tasks.write", "args": {"text": text}, "why": "he asked"},
                         {"answer": "That is waiting for your approval.", "basis": "looked"})
        result = s.AgentSession(question, think=think, catalog=self.catalog, broker=broker,
                                now_line=lambda: "NOW: test", record=True).run()
        self.assertEqual(result.outcome, s.HANDED_OFF)
        entry = result.handoffs[0]
        self.assertTrue(entry["filed"], entry)
        return result, entry

    def run_approved(self, **kw):
        kw.setdefault("halted", lambda: False)
        return handoffs.run_approved(catalog=self.catalog, **kw)

    def session_record(self, result):
        return stateio.read_json(stateio.private_dir("agent-sessions") / f"{result.id}.json")


class TheWholeLoop(Isolated):
    def test_handoff_approve_execute_once_and_the_session_shows_it(self):
        result, entry = self.ask()
        self.assertEqual(self.calls, [], "nothing runs inside the session")
        approval = policy.load(entry["approval"])
        self.assertEqual(approval["state"], "PENDING")
        record = handoffs.load(entry["handoff"])
        self.assertEqual(record["request_sha256"],
                         handoffs.request_digest("tasks.write", {"text": "call the plumber"}))
        self.assertTrue(approval["requested_action"].endswith(record["request_sha256"]))
        self.assertIn("call the plumber", approval["consequence"])

        # Nothing runs before he says yes.
        self.assertEqual(self.run_approved(), [])
        self.assertEqual(self.calls, [])

        policy.decide(entry["approval"], "APPROVED", via=intercom.ACTOR)
        done = self.run_approved()
        self.assertEqual(done, [{"handoff": entry["handoff"], "outcome": handoffs.DONE}])
        self.assertEqual(self.calls, [{"text": "call the plumber"}], "exactly that request, once")
        record = handoffs.load(entry["handoff"])
        self.assertEqual(record["state"], handoffs.DONE)
        receipt = record["receipts"][-1]
        self.assertEqual((receipt["outcome"], receipt["request_sha256"]), ("ok", record["request_sha256"]))
        self.assertIn("added a task", receipt["observation"])
        saved = self.session_record(result)
        self.assertEqual(saved["handoffs"][0]["state"], handoffs.DONE)

        # A second approve is refused by policy, and a second run does nothing.
        with self.assertRaises(ValueError):
            policy.decide(entry["approval"], "APPROVED", via=intercom.ACTOR)
        self.assertEqual(self.run_approved(), [])
        self.assertEqual(len(self.calls), 1)

    def test_a_tampered_request_is_refused(self):
        _result, entry = self.ask()
        path = handoffs._path(entry["handoff"])
        record = json.loads(path.read_text(encoding="utf-8"))
        record["args"] = {"text": "delete everything"}
        path.write_text(json.dumps(record), encoding="utf-8")
        policy.decide(entry["approval"], "APPROVED", via=intercom.ACTOR)
        done = self.run_approved()
        self.assertEqual(done[0]["outcome"], handoffs.REFUSED)
        self.assertEqual(self.calls, [])
        self.assertIn("changed after it was approved", handoffs.load(entry["handoff"])["outcome"])

    def test_a_record_rehashed_to_match_still_does_not_match_the_approval(self):
        _result, entry = self.ask()
        path = handoffs._path(entry["handoff"])
        record = json.loads(path.read_text(encoding="utf-8"))
        record["args"] = {"text": "something else"}
        record["request_sha256"] = handoffs.request_digest("tasks.write", record["args"])
        path.write_text(json.dumps(record), encoding="utf-8")
        policy.decide(entry["approval"], "APPROVED", via=intercom.ACTOR)
        self.assertEqual(self.run_approved()[0]["outcome"], handoffs.REFUSED)
        self.assertEqual(self.calls, [])

    def test_the_model_is_told_it_waits_not_that_it_happened(self):
        seen = []
        broker = s.Broker(self.catalog, halted=lambda: False, registry={"capabilities": []})

        def think(system, text):
            seen.append(text)
            if len(seen) == 1:
                return {"tool": "tasks.write", "args": {"text": "x"}}, "fake"
            return {"answer": "waiting on you"}, "fake"
        s.AgentSession("add x", think=think, catalog=self.catalog, broker=broker,
                       now_line=lambda: "NOW", record=True).run()
        self.assertIn("waiting for Caleb's approval", seen[1])


class HisDecisionIsRecorded(Isolated):
    def test_denied(self):
        result, entry = self.ask()
        policy.decide(entry["approval"], "DENIED", via=intercom.ACTOR, because="not now")
        self.assertEqual(self.run_approved()[0]["outcome"], handoffs.DENIED)
        self.assertEqual(self.calls, [])
        self.assertEqual(self.session_record(result)["handoffs"][0]["state"], handoffs.DENIED)

    def test_expired(self):
        _result, entry = self.ask()
        approval = policy.load(entry["approval"])
        approval.update({"state": "EXPIRED", "expired_at": "2026-01-01T00:00:00Z",
                         "expired_because": "nobody answered it for 8 days"})
        policy.save(approval)
        self.assertEqual(self.run_approved()[0]["outcome"], handoffs.EXPIRED)
        self.assertEqual(self.calls, [])

    def test_a_yes_to_something_irreversible_goes_stale(self):
        _result, entry = self.ask()
        policy.decide(entry["approval"], "APPROVED", via=intercom.ACTOR)
        approval = policy.load(entry["approval"])
        approval.update({"reversible": False, "decided_at": "2020-01-01T00:00:00Z"})
        policy.save(approval)
        self.assertEqual(self.run_approved()[0]["outcome"], handoffs.EXPIRED)
        self.assertEqual(self.calls, [])


class SheCannotAuthoriseHerself(Isolated):
    def test_an_approval_decided_by_her_own_process_is_refused(self):
        _result, entry = self.ask()
        policy.decide(entry["approval"], "APPROVED", via="aletheia-agent-session")
        self.assertEqual(self.run_approved()[0]["outcome"], handoffs.REFUSED)
        self.assertEqual(self.calls, [])

    def test_approve_is_refused_by_the_broker_and_never_filed(self):
        broker = s.Broker(self.catalog, halted=lambda: False, registry={"capabilities": []},
                          fleet={"repos": {}})
        decision = broker.check(s.ToolRequest("approve", {"id": "handoff-abc"}))
        self.assertEqual((decision.verdict, decision.permanent), (s.REFUSED, True))
        with self.assertRaises(handoffs.NotFiled):
            handoffs.file(tool=self.catalog["approve"], args={"id": "x"}, session_id="agent-1")

    def test_a_spending_request_is_never_filed_and_never_runs(self):
        with self.assertRaises(handoffs.NotFiled):
            handoffs.file(tool=self.catalog["tasks.write"], args={"text": "buy the monitor"},
                          session_id="agent-1")
        self.assertEqual(handoffs.all_handoffs(), [])
        # Written straight to disk, hash and approval consistent: still refused.
        args = {"text": "order me a pizza"}
        digest = handoffs.request_digest("tasks.write", args)
        handoffs.save({"id": "handoff-000000000001", "approval": "handoff-000000000001",
                       "state": handoffs.AWAITING, "tool": "tasks.write", "args": args,
                       "request_sha256": digest, "session": "agent-1", "audience": "local"})
        policy.request("handoff-000000000001", handoffs.action_for("tasks.write", digest),
                       reason="r", consequence="c", reversible=True)
        policy.decide("handoff-000000000001", "APPROVED", via=intercom.ACTOR)
        self.assertEqual(self.run_approved()[0]["outcome"], handoffs.REFUSED)
        self.assertEqual(self.calls, [])


class TheKillSwitchHolds(Isolated):
    def test_halted_it_waits_and_resumed_it_runs(self):
        _result, entry = self.ask()
        policy.decide(entry["approval"], "APPROVED", via=intercom.ACTOR)
        self.assertEqual(self.run_approved(halted=lambda: True)[0]["outcome"], "halted")
        self.assertEqual(self.calls, [])
        self.assertEqual(handoffs.load(entry["handoff"])["state"], handoffs.AWAITING)
        self.assertEqual(self.run_approved()[0]["outcome"], handoffs.DONE)
        self.assertEqual(len(self.calls), 1)

    def test_the_real_halt_file_is_read_when_no_override_is_given(self):
        _result, entry = self.ask()
        policy.decide(entry["approval"], "APPROVED", via=intercom.ACTOR)
        policy.halt("test", via="operator-cli")
        self.assertEqual(handoffs.run_approved(catalog=self.catalog)[0]["outcome"], "halted")
        self.assertEqual(self.calls, [])


class NeverTwice(Isolated):
    def test_a_run_that_died_midway_is_interrupted_not_replayed(self):
        _result, entry = self.ask()
        policy.decide(entry["approval"], "APPROVED", via=intercom.ACTOR)
        record = handoffs.load(entry["handoff"])
        record.update({"state": handoffs.RUNNING, "pid": 999999})
        handoffs.save(record)
        with mock.patch("aletheia.proc.pid_alive", return_value=False):
            done = self.run_approved()
        self.assertEqual(done[0]["outcome"], handoffs.INTERRUPTED)
        self.assertEqual(self.calls, [])
        self.assertEqual(self.run_approved(), [])

    def test_the_same_request_asked_twice_is_one_question(self):
        _r1, first = self.ask()
        _r2, second = self.ask()
        self.assertEqual(first["handoff"], second["handoff"])
        self.assertEqual(len([a for a in policy.all_approvals() if a["state"] == "PENDING"]), 1)

    def test_a_session_that_records_nothing_files_nothing(self):
        broker = s.Broker(self.catalog, halted=lambda: False, registry={"capabilities": []})
        think = scripted({"tool": "tasks.write", "args": {"text": "y"}}, {"answer": "ok"})
        result = s.AgentSession("add y", think=think, catalog=self.catalog, broker=broker,
                                now_line=lambda: "NOW", record=False).run()
        self.assertNotIn("handoff", result.handoffs[0])
        self.assertEqual(policy.all_approvals(), [])


class TheCoreRunsThem(Isolated):
    def test_the_beat_starts_them_only_when_something_waits(self):
        from aletheia import runtime
        with mock.patch.object(handoffs, "start_approved", return_value=True) as start:
            self.assertEqual(runtime._run_approved_handoffs(), [])
            start.assert_not_called()
            self.ask()
            self.assertEqual(runtime._run_approved_handoffs(), [{"handoffs": 1, "started": True}])
            start.assert_called_once()

    def test_saying_yes_kicks_them_too(self):
        import inspect
        from aletheia import core
        self.assertIn("_run_approved_handoffs", inspect.getsource(core.kick_approved_work))

    def test_the_background_runner_executes_what_was_approved(self):
        _result, entry = self.ask()
        policy.decide(entry["approval"], "APPROVED", via=intercom.ACTOR)
        with mock.patch.object(handoffs, "run_approved",
                               side_effect=lambda: handoffs._run_approved(catalog=self.catalog,
                                                                         halted=lambda: False,
                                                                         timeout_s=None)):
            self.assertTrue(handoffs.start_approved())
            handoffs._BACKGROUND["thread"].join(10)
        self.assertEqual(handoffs.load(entry["handoff"])["state"], handoffs.DONE)
        self.assertEqual(len(self.calls), 1)


if __name__ == "__main__":
    unittest.main()
