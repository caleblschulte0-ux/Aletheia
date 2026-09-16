"""What she is doing is read from every goal, not only job applications.

Operator direction, 2026-09-16: jobs are the current test case, not the
architecture. These hold that `current_state` (the browser, the agent's
"what am I doing", usage) and mission control (cards, needs, Eyes, ribbon)
read general browser missions, AgentSession runs and the requests they
handed to him - with a goal that has nothing to do with jobs.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import browser_mission as bm
from aletheia import current_state, handoffs, journal, mission_browser, mission_control as mc
from aletheia import mission_sessions, policy, reasoner, stateio

GOAL = "request a library card"
URL = "https://library.example.org/card"


def ago(minutes: float) -> str:
    return (dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M:%SZ")


class Isolated(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        env = mock.patch.dict(os.environ, {"ALETHEIA_PRIVATE_STATE": str(root / "private")})
        env.start()
        self.addCleanup(env.stop)
        for target, attr, value in ((journal, "JOURNAL_PATH", root / "journal.jsonl"),
                                    (policy, "APPROVALS_DIR", root / "approvals"),
                                    (policy, "HALT_PATH", root / "halt.json")):
            p = mock.patch.object(target, attr, value)
            p.start()
            self.addCleanup(p.stop)
        minds = mock.patch.object(current_state, "thinking", return_value={
            "claude": {"resting_until": None}, "codex": {"resting_until": None},
            "local": {"allowed": False, "why": "off"}, "anyone": True})
        minds.start()
        self.addCleanup(minds.stop)
        for module in (current_state, mc):
            module.forget_cache()
            self.addCleanup(module.forget_cache)

    def mission(self, state=bm.RUNNING, *, checkpoint=bm.FILLED, beat_minutes_ago=1.0, boundary=None):
        record = bm.open_mission(GOAL, URL, inputs={"name": "Caleb"})
        bm.checkpoint(record, checkpoint, url=URL + "/form")
        if boundary is not None:
            record = bm.stop_at(record, state, boundary)
        else:
            record["state"] = state
            bm.save(record)
        record["beat"] = ago(beat_minutes_ago)
        stateio.write_json_atomic(bm._path(record["id"]), record)
        return record

    def captcha(self):
        return self.mission(bm.NEEDS_YOU, boundary={"kind": "CAPTCHA", "url": URL + "/verify",
                                                    "say": "A human check is in the way."})


class TheBrowserIsAnyGoal(Isolated):
    def test_a_goal_being_driven_is_what_the_browser_is_doing(self):
        record = self.mission()
        browsing = current_state.browser()
        self.assertTrue(browsing["active"])
        self.assertEqual((browsing["source"], browsing["mission"], browsing["purpose"]),
                         ("browser_mission", record["id"], GOAL))
        self.assertEqual(browsing["site"], "library.example.org")
        self.assertEqual(browsing["stage"], "filling the form")
        agent = current_state.agent(browsing=browsing, pending_approvals=[])
        self.assertEqual((agent["state"], agent["mission"]), ("ACTING", GOAL))
        self.assertIn("filling the form at library.example.org", current_state.agent_words(agent))

    def test_a_run_nobody_has_touched_is_a_crash_not_activity(self):
        self.mission(beat_minutes_ago=bm.STALE_AFTER_MIN + 5)
        self.assertFalse(current_state.browser()["active"])

    def test_a_named_stop_waits_on_him(self):
        self.captcha()
        browsing = current_state.browser()
        self.assertFalse(browsing["active"])
        self.assertEqual(browsing["waiting"][0]["said"], "stopped at CAPTCHA on library.example.org")
        agent = current_state.agent(browsing=browsing, pending_approvals=[])
        self.assertEqual(agent["state"], "NEEDS YOU")
        self.assertIn("1 browser goal (stopped at CAPTCHA on library.example.org)", agent["step"])

    def test_the_snapshot_carries_the_new_sections(self):
        self.mission()
        snap = current_state.snapshot()
        for key in ("agent_sessions", "power", "usage"):
            self.assertIn(key, snap)
        self.assertEqual(snap["browser"]["source"], "browser_mission")


class HerSessionsAndWhatTheyHandedOver(Isolated):
    def session(self, *, pid=None, minutes=1.0, outcome="running"):
        path = stateio.private_dir("agent-sessions") / "agent-0123456789.json"
        stateio.write_json_atomic(path, {"id": "agent-0123456789", "question": "when does the library close",
                                         "outcome": outcome, "started_at": ago(minutes), "saved_at": ago(minutes),
                                         "pid": pid or os.getpid(), "handoffs": []})

    def handoff(self, state, **extra):
        record = {"id": "handoff-aaaaaaaaaaaa", "approval": "handoff-aaaaaaaaaaaa", "state": state,
                  "tool": "browser.pursue", "args": {"goal": GOAL, "url": URL},
                  "request_sha256": handoffs.request_digest("browser.pursue", {"goal": GOAL, "url": URL}),
                  "session": "agent-0123456789", "question": "get me a library card",
                  "consequence": "Run browser.pursue with goal “request a library card”",
                  "created_at": ago(30), **extra}
        handoffs.save(record)
        return record

    def test_a_running_session_is_thinking(self):
        self.session()
        agent = current_state.agent(pending_approvals=[])
        self.assertEqual(agent["state"], "THINKING")
        self.assertIn("when does the library close", agent["step"])

    def test_a_session_whose_process_died_is_not_running(self):
        self.session()
        with mock.patch("aletheia.proc.pid_alive", return_value=False):
            sessions = current_state.agent_sessions()
        self.assertEqual((sessions["running"], sessions["abandoned"]), ([], 1))

    def test_an_approved_request_being_run_is_acting(self):
        self.handoff(handoffs.RUNNING, started_at=ago(1))
        agent = current_state.agent(pending_approvals=[])
        self.assertEqual(agent["state"], "ACTING")
        self.assertIn("doing what you approved", agent["step"])

    def test_the_provider_makes_a_waiting_request_a_card_and_counts_it_once(self):
        record = self.handoff(handoffs.AWAITING)
        policy.request(record["approval"], handoffs.action_for("browser.pursue", record["request_sha256"]),
                       reason="r", consequence=record["consequence"], reversible=False)
        out = mc.gather(fresh=True)
        card = [m for m in out["missions"] if m["id"] == "handoff:handoff-aaaaaaaaaaaa"][0]
        self.assertEqual(card["status"], "NEEDS YOU")
        self.assertIn("approve or deny", card["needs"][0]["said"])
        # The approval is claimed by its card, so it is not counted a second time as a
        # bare approval (the repo's own tasks may add needs of their own).
        self.assertEqual(out["header"]["needs_you_parts"]["approvals"], 0)
        self.assertEqual(card["needs_count"], 1)
        self.assertFalse(any(n["kind"] == "approval" for n in out["needs_you"]))
        self.assertEqual(out["header"]["state"], "NEEDS YOU")

    def test_what_became_of_it_is_on_the_ribbon(self):
        self.handoff(handoffs.DONE, finished_at=ago(2), outcome="done")
        out = mc.gather(fresh=True)
        said = [line["said"] for line in out["ribbon"] if line["receipt"]["kind"] == "handoff"]
        self.assertTrue(any(s.startswith("Did what you approved") for s in said), said)
        self.assertEqual(mc.receipt("handoff", "handoff-aaaaaaaaaaaa")["record"]["state"], handoffs.DONE)

    def test_a_running_session_is_not_narrated_as_a_failure(self):
        self.session()
        out = mc.gather(fresh=True)
        self.assertFalse(any("Couldn't finish" in line["said"] for line in out["ribbon"]))
        self.assertTrue(any(m["type"] == "agent_session" for m in out["missions"]))


class BrowserGoalsOnTheHomeScreen(Isolated):
    NOW = dt.datetime.now(dt.timezone.utc)

    def test_a_captcha_stop_is_named_exactly(self):
        card = mission_browser.card(self.captcha(), self.NOW)
        self.assertEqual(card["status"], "NEEDS YOU")
        self.assertTrue(card["needs"][0]["said"].startswith(
            "Stopped at a CAPTCHA on library.example.org: waiting for you"), card["needs"][0]["said"])

    def test_a_crashed_run_is_stopped_and_says_so(self):
        card = mission_browser.card(self.mission(beat_minutes_ago=60), self.NOW)
        self.assertEqual(card["status"], "STOPPED")
        self.assertIn("stopped moving", card["stuck"])

    def test_an_old_finished_goal_is_history(self):
        record = self.mission(bm.DONE, beat_minutes_ago=60 * 30)
        self.assertIsNone(mission_browser.card(record, self.NOW))

    def test_the_screen_shows_it_in_cards_eyes_and_needs_and_the_job_hunt_does_not_claim_it(self):
        self.mission()
        out = mc.gather(fresh=True)
        card = [m for m in out["missions"] if m["type"] == "browser_goal"][0]
        self.assertEqual((card["status"], card["in_browser"]), ("RUNNING", True))
        self.assertTrue(out["eyes"]["active"])
        self.assertEqual((out["eyes"]["site"], out["eyes"]["purpose"]), ("library.example.org", GOAL))
        self.assertFalse(any(m["in_browser"] for m in out["missions"] if m["type"] == "job_hunt"))

    def test_a_stopped_goal_is_in_needs_you(self):
        self.captcha()
        out = mc.gather(fresh=True)
        self.assertTrue(any("CAPTCHA" in str(n["said"]) for n in out["needs_you"]), out["needs_you"])

    def test_the_receipt_leaves_out_his_answers(self):
        record = self.captcha()
        shown = mc.receipt("browser_mission", record["id"])["record"]
        self.assertNotIn("inputs", shown)
        self.assertIn("CAPTCHA", shown["_explained"]["stop"])


class UsageIsWhatIsKnown(Isolated):
    def test_nothing_recorded_is_unknown_not_zero(self):
        said = current_state.usage()
        self.assertEqual((said["window_used"], said["weekly"]), ("unknown", "unknown"))
        self.assertIsNone(said["claude"]["last_limit_hit"])
        self.assertIn("no limit", said["claude"]["note"])

    def test_the_last_limit_hit_and_its_reset_are_read_from_the_record(self):
        path = reasoner._rest_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"until": "2026-09-16T15:00:00Z", "noted_at": "2026-09-16T12:41:02Z",
                                    "said": "You've hit your session limit · resets 3pm (UTC)"}), encoding="utf-8")
        now = dt.datetime(2026, 9, 16, 13, 0, tzinfo=dt.timezone.utc)
        claude = current_state.usage(now)["claude"]
        self.assertEqual((claude["last_limit_hit"], claude["resets_at"], claude["resting_now"]),
                         ("2026-09-16T12:41:02Z", "2026-09-16T15:00:00Z", True))
        later = current_state.usage(now + dt.timedelta(hours=3))["claude"]
        self.assertFalse(later["resting_now"])
        self.assertEqual(later["last_limit_hit"], "2026-09-16T12:41:02Z", "the last hit stays known after reset")


if __name__ == "__main__":
    unittest.main()
