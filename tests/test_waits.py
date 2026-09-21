"""Waiting is a state, not a failure (continuity brief IV.14, rules 2, 3, 7).

A fake clock and fake events throughout: every wake is driven by what the
stores say and by `now`, never by this laptop's network or wall clock.
"""
import datetime as dt
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import communications, events, waits, work_requirements as wr, work_states as ws

NOW = dt.datetime(2026, 9, 16, 15, 0, tzinfo=dt.timezone.utc)


class Isolated(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        for patcher in (
            mock.patch.dict(os.environ, {"ALETHEIA_PRIVATE_STATE": self.tmp.name}),
            mock.patch.object(communications, "THREADS_DIR", root / "comms" / "threads"),
            mock.patch.object(communications, "MESSAGES_DIR", root / "comms" / "messages"),
            mock.patch.object(communications, "EXPECT_DIR", root / "comms" / "expectations"),
            mock.patch.object(events, "EVENTS_DIR", root / "events"),
            mock.patch.object(events, "WATCHERS_DIR", root / "watchers"),
            mock.patch.object(waits, "_journal"),
            mock.patch.dict(waits.HANDLERS, {}, clear=True),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.told = []
        waits.HANDLERS["test"] = "tests.test_waits:_record_handler"
        _SINK.clear()

    def at(self, **delta):
        return NOW + dt.timedelta(**delta)


_SINK: list = []


def _record_handler(record, event, now):
    _SINK.append((record["item"], event, record["state"]))
    return {"said": f"{event} handled"}


class AWaitIsDurableAndSaysWhy(Isolated):
    def test_a_wait_needs_a_reason_and_a_checkable_condition(self):
        with self.assertRaises(waits.WaitError):
            waits.wait_for("x", {"kind": "time_after", "at": "2026-09-17T09:00:00Z"}, reason="", now=NOW)
        with self.assertRaises(waits.WaitError):
            waits.wait_for("x", {"kind": "telepathy"}, reason="because", now=NOW)
        with self.assertRaises(waits.WaitError):
            waits.wait_for("x", {"kind": "requirement", "requirement": "payment"}, reason="r", now=NOW)
        with self.assertRaises(waits.WaitError):
            waits.wait_for("x", {"kind": "time_after", "at": "2026-09-17T09:00:00Z"}, reason="r",
                           timeout={"after_s": 60}, now=NOW)      # a timeout must say what it MEANS

    def test_it_survives_a_restart_and_is_idempotent(self):
        cond = {"kind": "time_after", "at": "2026-09-18T09:00:00Z"}
        one = waits.wait_for("mission:a/t1", cond, reason="the tour is on Friday", owner="test", now=NOW)
        again = waits.wait_for("mission:a/t1", cond, reason="the tour is on Friday", owner="test", now=NOW)
        self.assertEqual(one["id"], again["id"])
        # "restart": nothing in memory, the record is read back from disk
        reread = waits.load(one["id"])
        self.assertEqual(reread["state"], waits.WAITING)
        self.assertEqual(reread["work_state"], ws.BLOCKED_EXTERNAL)
        self.assertIn("2026-09-18", reread["next"])
        self.assertEqual(ws.problems({"state": reread["work_state"], "reason": reread["reason"],
                                      "next": reread["next"]}), [])

    def test_each_condition_kind_waits_in_the_right_work_state(self):
        self.assertEqual(waits.work_state_for({"kind": "user_decision", "question": "q"}), ws.BLOCKED_USER)
        self.assertEqual(waits.work_state_for({"kind": "model_available", "requirement": "reasoning"}),
                         ws.BLOCKED_MODEL)
        self.assertEqual(waits.work_state_for({"kind": "requirement", "requirement": "browser"}), ws.RETRY_LATER)
        self.assertEqual(waits.work_state_for({"kind": "any_of", "conditions": [
            {"kind": "reply_from", "thread_id": "t", "participant": "p"},
            {"kind": "user_decision", "question": "q"}]}), ws.BLOCKED_USER)


class WakesComeFromTheWorldAndTheClock(Isolated):
    def test_a_date_passing_wakes_only_that_wait(self):
        date = waits.wait_for("a", {"kind": "time_after", "at": "2026-09-18T09:00:00Z"}, reason="tour day",
                              owner="test", now=NOW)
        other = waits.wait_for("b", {"kind": "time_after", "at": "2026-09-25T09:00:00Z"}, reason="later",
                               owner="test", now=NOW)
        self.assertEqual(waits.reconcile(self.at(days=1)), [])
        moved = waits.reconcile(self.at(days=2, hours=1))
        self.assertEqual([t["item"] for t in moved], ["a"])
        self.assertEqual(waits.load(date["id"])["state"], waits.WOKEN)
        self.assertEqual(waits.load(other["id"])["state"], waits.WAITING)
        self.assertEqual(_SINK, [("a", "woke", waits.WOKEN)])

    def test_a_reply_from_the_person_wakes_it_and_nobody_else_does(self):
        communications.create_thread("listing-12", participants=["caleb", "landlord@example.com"],
                                     subject="the flat")
        communications.record_message("m1", thread_id="listing-12", direction="OUTBOUND", channel="email",
                                      participant="caleb", summary="is it available?",
                                      occurred_at="2026-09-16T15:00:00Z")
        w = waits.wait_for("contact-landlord", {"kind": "reply_from", "thread_id": "listing-12",
                                                "participant": "landlord@example.com", "after_message_id": "m1"},
                           reason="asked the landlord whether the flat is available", owner="test", now=NOW)
        self.assertEqual(waits.reconcile(self.at(hours=3)), [])
        communications.record_message("m2", thread_id="listing-12", direction="INBOUND", channel="email",
                                      participant="landlord@example.com", summary="yes, tours Friday",
                                      occurred_at="2026-09-17T10:00:00Z")
        moved = waits.reconcile(self.at(days=1))
        self.assertEqual(moved[0]["outcome"], "replied")
        self.assertEqual(waits.load(w["id"])["outcome"]["evidence"]["reply_message_id"], "m2")

    def test_an_event_wakes_a_wait_on_that_kind_and_subject(self):
        w = waits.wait_for("x", {"kind": "event", "event_kind": "listing.changed", "subject_prefix": "listing:12"},
                           reason="watching the listing", owner="test", now=NOW)
        waits.signal("listing.changed", "listing:99", "another listing", occurred_at="2026-09-16T16:00:00Z")
        self.assertEqual(waits.reconcile(self.at(hours=2)), [])
        waits.signal("listing.changed", "listing:12", "price dropped", occurred_at="2026-09-16T17:00:00Z")
        self.assertEqual(waits.reconcile(self.at(hours=3))[0]["wait"], w["id"])

    def test_a_decision_is_his_and_never_hers(self):
        w = waits.wait_for("pick-city", {"kind": "user_decision", "question": "Which city?",
                                         "options": ["A", "B"]}, reason="two cities researched",
                           owner="test", now=NOW)
        for her in ("aletheia-programs", "agent-session", "thea", ""):
            with self.assertRaises(PermissionError):
                waits.decide(w["id"], "A", words="A", via=her, now=NOW)
        self.assertEqual(waits.reconcile(self.at(hours=1)), [])
        waits.decide(w["id"], "B", words="let's do B", via="operator-voice", now=NOW)
        moved = waits.reconcile(self.at(hours=1))
        self.assertEqual(moved[0]["outcome"], "decided")

    def test_a_model_coming_back_wakes_a_model_wait(self):
        w = waits.wait_for("draft", {"kind": "model_available"}, reason="nobody can think", owner="test", now=NOW)
        down = wr._result("reasoning", False, "all out", live=True, now=NOW)
        up = wr._result("reasoning", True, "local answers", live=True, now=NOW)
        with mock.patch.object(wr, "world", return_value=down):
            self.assertEqual(waits.reconcile(NOW), [])
        with mock.patch.object(wr, "world", return_value=up):
            self.assertEqual(waits.reconcile(NOW)[0]["wait"], w["id"])

    def test_any_of_wakes_on_whichever_comes_first(self):
        w = waits.wait_for("x", {"kind": "any_of", "conditions": [
            {"kind": "event", "event_kind": "reply.arrived"},
            {"kind": "time_after", "at": "2026-09-20T00:00:00Z"}]}, reason="reply or Sunday", now=NOW)
        moved = waits.reconcile(self.at(days=4))
        self.assertEqual(moved[0]["outcome"], "time_passed")
        self.assertEqual(waits.load(w["id"])["outcome"]["evidence"]["by"], "time_after")

    def test_an_unreadable_condition_keeps_waiting_and_says_so(self):
        w = waits.wait_for("x", {"kind": "reply_from", "thread_id": "nope", "participant": "p"},
                           reason="r", now=NOW)
        self.assertEqual(waits.reconcile(NOW), [])
        self.assertFalse(waits.check(waits.load(w["id"]), NOW)["met"])


class FollowUpAndTimeoutAreNotFailure(Isolated):
    def test_a_nudge_comes_due_is_handed_to_the_owner_and_needs_approval_by_default(self):
        w = waits.wait_for("x", {"kind": "event", "event_kind": "reply.arrived"}, reason="asked a recruiter",
                           owner="test", follow_up={"after_s": 3 * 86400, "every_s": 2 * 86400, "max": 2},
                           now=NOW)
        self.assertEqual(waits.reconcile(self.at(days=2)), [])
        first = waits.reconcile(self.at(days=3, minutes=1))
        self.assertEqual(first[0]["to"], "FOLLOW_UP")
        self.assertTrue(first[0]["needs_approval"])
        self.assertEqual(waits.reconcile(self.at(days=4)), [])          # not again until every_s
        self.assertEqual(waits.reconcile(self.at(days=5, minutes=2))[0]["n"], 2)
        self.assertEqual(waits.reconcile(self.at(days=9)), [])          # max reached
        record = waits.load(w["id"])
        self.assertEqual(record["state"], waits.WAITING)                # a nudge never ends the wait
        self.assertEqual([e for (_i, e, _s) in _SINK], ["follow_up", "follow_up"])

    def test_a_nudge_with_no_owner_becomes_a_notification_not_a_message(self):
        waits.wait_for("x", {"kind": "event", "event_kind": "reply.arrived"}, reason="asked someone",
                       follow_up={"after_s": 60}, now=NOW)
        with mock.patch.object(waits, "_notify_follow_up") as told:
            moved = waits.reconcile(self.at(minutes=2))
        told.assert_called_once()
        self.assertEqual(moved[0]["handler"], None)

    def test_a_timeout_wakes_with_its_meaning_and_is_not_failed(self):
        w = waits.wait_for("x", {"kind": "event", "event_kind": "reply.arrived"}, reason="asked a landlord",
                           owner="test", timeout={"after_s": 5 * 86400, "means": "the listing is probably gone",
                                                  "then": "ask_caleb"}, now=NOW)
        moved = waits.reconcile(self.at(days=6))
        self.assertEqual(moved[0]["to"], waits.TIMED_OUT)
        record = waits.load(w["id"])
        self.assertEqual(record["outcome"]["why"], "the listing is probably gone")
        self.assertEqual(record["outcome"]["then"], "ask_caleb")
        self.assertNotIn("FAIL", record["state"])

    def test_a_handler_that_raises_never_stops_the_other_waits(self):
        waits.HANDLERS["broken"] = "tests.test_waits:_raising_handler"
        waits.wait_for("a", {"kind": "time_after", "at": "2026-09-16T16:00:00Z"}, reason="r", owner="broken", now=NOW)
        waits.wait_for("b", {"kind": "time_after", "at": "2026-09-16T16:00:00Z"}, reason="r", owner="test", now=NOW)
        moved = waits.reconcile(self.at(hours=2))
        self.assertEqual(sorted(t["item"] for t in moved), ["a", "b"])

    def test_cancel_stops_waiting(self):
        w = waits.wait_for("a", {"kind": "time_after", "at": "2026-09-20T00:00:00Z"}, reason="r", now=NOW)
        waits.cancel(w["id"], why="he dropped it", now=NOW)
        self.assertEqual(waits.waiting(), [])
        self.assertEqual(waits.reconcile(self.at(days=9)), [])

    def test_describe_says_when_it_may_next_move(self):
        w = waits.wait_for("a", {"kind": "event", "event_kind": "x"}, reason="r",
                           follow_up={"after_s": 3600}, timeout={"after_s": 7200, "means": "m"}, now=NOW)
        d = waits.describe(w)
        self.assertEqual(d["next_wake_at"], "2026-09-16T16:00:00Z")
        self.assertEqual(d["timeout"]["means"], "m")


class TheWorkEngineChecksWaitsOnTheBeat(Isolated):
    def setUp(self):
        super().setUp()
        from aletheia import work_engine as we
        self.we = we
        for patcher in (mock.patch.object(we, "_halted", return_value=None), mock.patch.object(we, "_journal")):
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_a_wait_is_an_unfinished_item_with_its_reason_and_it_wakes_in_reconcile(self):
        w = waits.wait_for("call-back", {"kind": "time_after", "at": "2026-09-17T09:00:00Z"},
                           reason="he said to try again tomorrow", now=NOW)
        only = {"waits": self.we.source_waits}
        inv = self.we.inventory(NOW, sources=only, with_availability=False, with_gaps=False)
        self.assertEqual(inv["blocked_total"], 1)
        row = inv["blocked"][0]
        self.assertEqual((row["state"], row["reason"]), (ws.BLOCKED_EXTERNAL, "he said to try again tomorrow"))
        self.assertEqual(row["not_before"], "2026-09-17T09:00:00Z")
        with mock.patch("aletheia.work_gaps.file_from_demand"):
            result = self.we.reconcile(self.at(days=1), sources=only, probe=False)
        self.assertEqual(result["waits"][0]["wait"], w["id"])
        self.assertEqual(self.we.inventory(self.at(days=1), sources=only, with_availability=False,
                                           with_gaps=False)["blocked_total"], 0)

    def test_a_wait_whose_owner_is_a_source_is_not_counted_twice(self):
        waits.wait_for("x", {"kind": "time_after", "at": "2026-09-17T09:00:00Z"}, reason="r", owner="tasks", now=NOW)
        self.assertEqual(self.we.source_waits(NOW), [])


def _raising_handler(record, event, now):
    raise RuntimeError("boom")


if __name__ == "__main__":
    unittest.main()
