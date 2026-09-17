"""One blocked item never blocks another, blocked work is durable, and it wakes.

Continuity brief II.2, II.3, II.6 and rules 2, 3 and 7. Every live check is
stubbed: the aggregation is under test, not this laptop's network (CLAUDE.md).
"""
import datetime as dt
import importlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import (reasoning_gateway, stateio, work_engine as we, work_gaps,
                      work_requirements as wr, work_states as ws)

NOW = dt.datetime(2026, 9, 16, 15, 0, tzinfo=dt.timezone.utc)


class Isolated(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patcher = mock.patch.dict(os.environ, {"ALETHEIA_PRIVATE_STATE": self.tmp.name})
        patcher.start()
        self.addCleanup(patcher.stop)
        wr.forget()
        self.addCleanup(wr.forget)
        halt = mock.patch.object(we, "_halted", return_value=None)
        halt.start()
        self.addCleanup(halt.stop)
        self.journal = mock.patch.object(we, "_journal")
        self.journal.start()
        self.addCleanup(self.journal.stop)


def world(**ok):
    """A fake world check: requirement -> (ok, why[, not_before])."""
    def fake(req, *, now=None, probe=False, persist=False, fresh=False):
        spec = ok.get(req, (True, f"{req} fine"))
        nb = spec[2] if len(spec) > 2 else None
        return wr._result(req, spec[0], spec[1], live=True, now=NOW,
                          wake=f"when {req} is back", not_before=nb)
    return mock.patch.object(wr, "world", side_effect=fake)


def source(*items):
    return {"fake": lambda now: [dict(i) for i in items]}


class ThePickerNeverLetsOneItemBlockAnother(Isolated):
    def test_a_model_blocked_item_is_checkpointed_and_the_next_one_runs(self):
        a = we.item("x:a", "fake", "needs Claude", ws.READY, requires=["frontier_reasoning"], priority=1)
        b = we.item("x:b", "fake", "local work", ws.READY, requires=["local_reasoning"], priority=2)
        until = NOW + dt.timedelta(hours=2)
        with world(frontier_reasoning=(False, "Claude is resting", until)):
            picked = we.pick([a, b], NOW)
        self.assertEqual([i["id"] for i in picked["executable"]], ["x:b"])
        blocked = picked["blocked"][0]
        self.assertEqual(blocked["state"], ws.BLOCKED_MODEL)
        self.assertIn("Claude is resting", blocked["reason"])
        self.assertTrue(blocked["next"])                      # rule 3
        self.assertEqual(blocked["not_before"], we._stamp(until))
        self.assertEqual(ws.problems(blocked), [])

    def test_a_broken_item_does_not_stop_the_rest(self):
        a = we.item("x:a", "fake", "fine", ws.READY)
        with mock.patch.object(we, "assess", side_effect=[RuntimeError("boom"), {"verdict": "run", "woke": False}]):
            picked = we.pick([we.item("x:0", "fake", "broken", ws.READY, priority=1), a], NOW)
        self.assertEqual([i["id"] for i in picked["executable"]], ["x:a"])
        self.assertEqual(picked["blocked"][0]["state"], ws.RETRY_LATER)

    def test_a_person_blocked_item_waits_whatever_the_models_say(self):
        a = we.item("x:a", "fake", "his step", ws.BLOCKED_USER, reason="his", next="when he replies")
        with world():
            picked = we.pick([a], NOW)
        self.assertEqual(picked["executable"], [])
        self.assertEqual(picked["blocked"][0]["state"], ws.BLOCKED_USER)

    def test_retry_later_waits_for_its_not_before(self):
        later = we.item("x:a", "fake", "retry", ws.RETRY_LATER, reason="flaky", next="retry",
                        not_before=we._stamp(NOW + dt.timedelta(minutes=5)))
        with world():
            self.assertEqual(we.pick([later], NOW)["executable"], [])
            woke = we.pick([later], NOW + dt.timedelta(minutes=6))
        self.assertEqual([i["id"] for i in woke["executable"]], ["x:a"])
        self.assertEqual(woke["woke"], [{"id": "x:a", "was": ws.RETRY_LATER}])

    def test_halted_runs_nothing(self):
        a = we.item("x:a", "fake", "anything", ws.READY)
        with world(), mock.patch.object(we, "_halted", return_value={"reason": "operator"}):
            picked = we.pick([a], NOW)
        self.assertEqual(picked["executable"], [])
        self.assertIn("halted", picked["blocked"][0]["reason"])

    def test_payment_is_never_satisfied(self):
        a = we.item("x:a", "fake", "buy it", ws.READY, requires=["payment"])
        with world():
            picked = we.pick([a], NOW)
        self.assertEqual(picked["blocked"][0]["state"], ws.BLOCKED_USER)
        self.assertIn("only Caleb spends money", picked["blocked"][0]["reason"])

    def test_an_approval_counts_only_when_the_record_says_approved(self):
        a = we.item("x:a", "fake", "press", ws.BLOCKED_USER, requires=["user_approval"], reason="r", next="n",
                    evidence={"approval": "ap-1"})
        for state, runs in (("PENDING", False), ("APPROVED", True)):
            with self.subTest(state=state), world(), \
                    mock.patch.object(wr, "_approval_state", return_value=state):
                self.assertEqual(bool(we.pick([a], NOW)["executable"]), runs)

    def test_work_reserved_for_a_frontier_worker_needs_a_stronger_model(self):
        a = we.item("task:t", "tasks", "big build", ws.READY, requires=["frontier_reasoning"], stronger=True)
        with world(frontier_reasoning=(False, "the frontier models are switched off")):
            picked = we.pick([a], NOW)
        self.assertEqual(picked["blocked"][0]["state"], ws.NEEDS_STRONGER_MODEL)


class BlockedWorkIsDurableAndWakes(Isolated):
    def test_a_checkpoint_survives_a_restart_and_wakes_when_the_reset_passes(self):
        a = we.item("x:a", "fake", "needs Claude", ws.READY, requires=["frontier_reasoning"], native_state="todo")
        until = NOW + dt.timedelta(hours=1)
        with world(frontier_reasoning=(False, "Claude is resting", until)):
            first = we.reconcile(NOW, sources=source(a))
        self.assertEqual(first["checkpointed"], ["x:a"])
        on_disk = json.loads(we.store_path().read_text(encoding="utf-8"))["items"]["x:a"]
        self.assertEqual(on_disk["state"], ws.BLOCKED_MODEL)

        # "restart": a fresh module reads the same file
        fresh = importlib.reload(we)
        self.enterContext(mock.patch.object(fresh, "_halted", return_value=None))
        self.enterContext(mock.patch.object(fresh, "_journal"))
        items, _ = fresh.gather(NOW, sources=source(a))
        self.assertEqual(items[0]["state"], ws.BLOCKED_MODEL)
        self.assertEqual(items[0]["not_before"], we._stamp(until))

        with world(frontier_reasoning=(False, "Claude is resting", until)):
            again = fresh.reconcile(NOW + dt.timedelta(minutes=1), sources=source(a))
        self.assertEqual(again["checkpointed"], [], "an unchanged checkpoint is not rewritten")
        with world():
            woke = fresh.reconcile(until + dt.timedelta(minutes=1), sources=source(a))
        self.assertEqual(woke["woke"], [{"id": "x:a", "was": ws.BLOCKED_MODEL}])
        self.assertNotIn("x:a", fresh.load_store()["items"], "a woken foreign item drops its overlay")

    def test_an_overlay_written_against_an_older_native_state_is_not_believed(self):
        store = {"items": {"x:a": {"id": "x:a", "source": "fake", "state": ws.BLOCKED_MODEL, "reason": "old",
                                   "next": "n", "native_state": "todo"}}}
        we.save_store(store)
        moved = we.item("x:a", "fake", "t", ws.RUNNING, native_state="doing")
        items, _ = we.gather(NOW, sources=source(moved))
        self.assertEqual(items[0]["state"], ws.RUNNING)

    def test_native_items_are_filed_once_and_run_by_their_runner(self):
        first = we.add("do the thing", kind="probe", key="k", now=NOW)
        again = we.add("do the thing", kind="probe", key="k", now=NOW)
        self.assertEqual(first["id"], again["id"])
        ran = []
        with world(), mock.patch.dict(we.RUNNERS, {"probe": lambda it, now: ran.append(it["id"]) or
                                                   {"state": ws.DONE, "next": "done"}}), \
                mock.patch("aletheia.work_gaps.file_from_demand", return_value=[]):
            result = we.reconcile(NOW, sources={"work": we.source_native})
        self.assertEqual(ran, [first["id"]])
        self.assertEqual(we.load_store()["items"][first["id"]]["state"], ws.DONE)
        self.assertEqual(result["ran"][0]["state"], ws.DONE)

    def test_a_failing_runner_becomes_retry_later_not_a_crash(self):
        item = we.add("fragile", kind="probe", key="f", now=NOW)
        with world(), mock.patch.dict(we.RUNNERS, {"probe": mock.Mock(side_effect=OSError("disk"))}), \
                mock.patch("aletheia.work_gaps.file_from_demand", return_value=[]):
            we.reconcile(NOW, sources={"work": we.source_native})
        held = we.load_store()["items"][item["id"]]
        self.assertEqual(held["state"], ws.RETRY_LATER)
        self.assertTrue(held["not_before"])

    def test_a_source_that_cannot_be_read_is_a_note_not_an_empty_world(self):
        def broken(now):
            raise OSError("gone")
        items, notes = we.gather(NOW, sources={"broken": broken, **source(we.item("x:a", "fake", "t", ws.READY))})
        self.assertEqual(len(items), 1)
        self.assertIn("broken could not be read", notes[0])


class RequirementChecks(Isolated):
    def test_frontier_off_is_unavailable_and_says_so(self):
        with mock.patch.dict(os.environ, {reasoning_gateway.FRONTIER_OFF_ENV: "1"}):
            result = wr.world("frontier_reasoning", now=NOW, fresh=True)
        self.assertFalse(result["ok"])
        self.assertEqual(result["blocked_state"], ws.BLOCKED_MODEL)

    def test_a_resting_claude_names_the_reset_as_the_wake(self):
        from aletheia import reasoner
        until = NOW + dt.timedelta(hours=3)
        with mock.patch.object(reasoner, "cli_path", return_value="claude"), \
                mock.patch.object(reasoner, "resting_until", return_value=until), \
                mock.patch.object(reasoner, "codex_path", return_value=None), \
                mock.patch.object(reasoner, "codex_resting", return_value=None):
            result = wr.world("frontier_reasoning", now=NOW, fresh=True)
        self.assertFalse(result["ok"])
        self.assertEqual(result["not_before"], we._stamp(until))
        self.assertIn("resets", result["wake"])

    def test_codex_carries_frontier_when_claude_rests(self):
        from aletheia import reasoner
        with mock.patch.object(reasoner, "cli_path", return_value="claude"), \
                mock.patch.object(reasoner, "resting_until", return_value=NOW), \
                mock.patch.object(reasoner, "codex_path", return_value="codex"), \
                mock.patch.object(reasoner, "codex_resting", return_value=None):
            self.assertTrue(wr.world("frontier_reasoning", now=NOW, fresh=True)["ok"])

    def test_local_needs_enabled_reachable_and_room(self):
        from aletheia import local_model_pool, model_pool_config
        cases = [((False, True, True), False), ((True, False, True), False),
                 ((True, True, False), False), ((True, True, True), True)]
        for (enabled, reach, fits), expected in cases:
            with self.subTest(enabled=enabled, reach=reach, fits=fits), \
                    mock.patch.object(model_pool_config, "enabled", return_value=enabled), \
                    mock.patch.object(local_model_pool, "reachable", return_value=reach), \
                    mock.patch.object(local_model_pool, "room_for_role",
                                      return_value={"fits": fits, "why": "no room", "model": "m"}):
                wr.forget()
                self.assertEqual(wr.world("local_reasoning", now=NOW)["ok"], expected)

    def test_reasoning_is_satisfied_by_either_mind(self):
        with world(local_reasoning=(False, "off"), frontier_reasoning=(True, "claude")):
            pass
        with mock.patch.object(wr, "WORLD", {**wr.WORLD,
                                             "local_reasoning": lambda n, p: (False, "off", True, "w", None),
                                             "frontier_reasoning": lambda n, p: (True, "claude", False, "", None)}):
            self.assertTrue(wr.world("reasoning", now=NOW)["ok"])
        wr.forget()
        with mock.patch.object(wr, "WORLD", {**wr.WORLD,
                                             "local_reasoning": lambda n, p: (False, "off", True, "w", None),
                                             "frontier_reasoning": lambda n, p: (False, "out", False, "w", None)}):
            result = wr.world("reasoning", now=NOW)
        self.assertFalse(result["ok"])
        self.assertEqual(result["blocked_state"], ws.BLOCKED_MODEL)

    def test_an_expensive_check_is_not_made_without_probe_and_says_unverified(self):
        from aletheia import browse
        with mock.patch.object(browse, "available", return_value=(True, "installed")), \
                mock.patch.object(browse, "reachable", side_effect=AssertionError("launched a browser")):
            result = wr.world("browser", now=NOW)
        self.assertTrue(result["unverified"])

    def test_a_live_browser_result_is_cached_across_a_restart(self):
        from aletheia import browse
        with mock.patch.object(browse, "available", return_value=(True, "installed")), \
                mock.patch.object(browse, "reachable", return_value=(False, "ERR_CONNECTION_RESET")):
            live = wr.world("browser", now=NOW, probe=True, persist=True)
        self.assertFalse(live["ok"])
        self.assertEqual(live["blocked_state"], ws.RETRY_LATER)
        self.assertTrue(live["not_before"])
        wr.forget()
        with mock.patch.object(browse, "available", return_value=(True, "installed")), \
                mock.patch.object(browse, "reachable", side_effect=AssertionError("probed again")):
            cached = wr.world("browser", now=NOW + dt.timedelta(minutes=5))
        self.assertFalse(cached["ok"])
        self.assertTrue(cached["cached"])

    def test_an_unreachable_network_is_retry_later(self):
        with mock.patch.object(wr.socket, "create_connection", side_effect=OSError("down")):
            result = wr.world("network", now=NOW)
        self.assertEqual(result["blocked_state"], ws.RETRY_LATER)

    def test_item_requirements_need_evidence(self):
        self.assertFalse(wr.check("login", {}, now=NOW)["ok"])
        self.assertTrue(wr.check("login", {"evidence": {"signed_in": True}}, now=NOW)["ok"])
        self.assertEqual(wr.check("external_reply", {}, now=NOW)["blocked_state"], ws.BLOCKED_EXTERNAL)
        self.assertEqual(wr.check("telepathy", {}, now=NOW)["ok"], False)


class GapsBecomeNextActions(Isolated):
    REGISTRY = {"capabilities": [
        {"id": "calendar.read", "status": "AVAILABLE", "description": "read events on his calendar schedule"},
        {"id": "message.send", "status": "EXPERIMENTAL", "description": "send a text message"},
        {"id": "room.scene", "status": "NEEDS_CONFIGURATION", "description": "set the lights"},
        {"id": "browser.pursue", "status": "AVAILABLE", "description": "drive a browser toward a goal"},
        {"id": "script.run", "status": "AVAILABLE", "description": "run a sandboxed program"},
        {"id": "fax.send", "status": "NOT_BUILT", "description": "send a fax"},
    ]}

    def classify(self, step, **kw):
        return work_gaps.classify(step, registry=self.REGISTRY, **kw)

    def test_each_outcome(self):
        cases = [
            ("buy me a new monitor", {}, "refuse_policy"),
            ("approve your own request and resume yourself", {}, "refuse_policy"),
            ("check my calendar schedule events tomorrow", {"capability": "calendar.read"}, "other_tool"),
            ("turn the lights on", {"capability": "room.scene"}, "install_configure"),
            ("text Dana", {"capability": "message.send"}, "small_capability"),
            ("wait for the landlord to reply", {}, "wait_external"),
            ("which apartment do you prefer", {}, "ask_caleb"),
            ("renew the registration on the county website", {}, "browser_path"),
            ("convert these receipts into a csv", {}, "local_workaround"),
            ("send a fax to the clinic", {"capability": "fax.send"}, "small_capability"),
            ("add oauth authentication to the phone bridge", {"capability": "phone.bridge"}, "large_capability"),
        ]
        for step, kw, outcome in cases:
            with self.subTest(step=step):
                verdict = self.classify(step, **kw)
                self.assertEqual(verdict["outcome"], outcome, verdict)
                self.assertEqual(verdict["state"], ws.GAP_STATE[outcome])
                self.assertTrue(verdict["next"])

    def test_the_money_check_fails_closed(self):
        from aletheia import webtask
        with mock.patch.object(webtask, "would_spend", side_effect=RuntimeError("gone")):
            self.assertEqual(self.classify("text Dana")["outcome"], "refuse_policy")

    def test_a_gap_is_recorded_durably_once_and_acts_through_existing_gates(self):
        from aletheia import gaps, notifications
        with mock.patch.object(work_gaps, "_registry", return_value=self.REGISTRY):
            item = work_gaps.record("send a fax to the clinic", capability="fax.send", now=NOW)
            again = work_gaps.record("send a fax to the clinic", capability="fax.send", now=NOW)
        self.assertEqual(item["id"], again["id"])
        self.assertEqual(item["state"], ws.READY)
        with mock.patch.object(gaps, "materialize", return_value=[{"id": "build-fax-send"}]) as filed:
            outcome = work_gaps.act(item, now=NOW)
        filed.assert_called_once_with(["fax.send"], worker="local-repair")
        self.assertEqual(outcome["state"], ws.DONE)
        self.assertIn("build-fax-send", outcome["next"])

        ask = we.item("work:q", "work", "q", ws.READY, kind="gap",
                      payload=self.classify("which apartment do you prefer"))
        with mock.patch.object(notifications, "publish") as told:
            outcome = work_gaps.act(ask, now=NOW)
        self.assertEqual(outcome["state"], ws.BLOCKED_USER)
        self.assertEqual(told.call_args.kwargs["dedupe_key"], "work-gap:work:q")

    def test_a_policy_refusal_is_filed_failed_with_the_rule(self):
        with mock.patch.object(work_gaps, "_registry", return_value=self.REGISTRY):
            item = work_gaps.record("order me a pizza", now=NOW)
        self.assertEqual(item["state"], ws.FAILED)
        self.assertIn("money", item["reason"])

    def test_demand_gaps_are_filed_and_attempt_walls_are_not(self):
        from aletheia import demand
        rows = [{"capability": "fax.send", "reasons": {"GAP": 2}, "in_his_words": ["fax the clinic"]},
                {"capability": "application.submit", "reasons": {"NEEDS_YOU": 191}, "in_his_words": ["x"]},
                {"capability": "calendar.read", "reasons": {"GAP": 1}, "in_his_words": ["y"]}]
        with mock.patch.object(demand, "ranked", return_value=rows):
            preview = work_gaps.preview_from_demand(registry=self.REGISTRY)
        self.assertEqual([p["capability"] for p in preview], ["fax.send"])


class TheInventoryAndItsReaders(Isolated):
    def test_the_inventory_writes_nothing(self):
        a = we.item("x:a", "fake", "needs Claude", ws.READY, requires=["frontier_reasoning"])
        with world(frontier_reasoning=(False, "out")), \
                mock.patch.object(wr, "availability", return_value={}), \
                mock.patch.object(we, "_gaps_preview", return_value=[]):
            inv = we.inventory(NOW, sources=source(a))
        self.assertFalse(we.store_path().exists())
        self.assertEqual(inv["blocked_total"], 1)
        self.assertIn("render", dir(we))
        self.assertIn("BLOCKED_MODEL", we.render(inv))

    def test_the_mission_screen_shows_blocked_items_with_reason_and_wake(self):
        from aletheia import mission_work
        summary = {"readable": True, "as_of": "t", "halted": False, "counts": {"BLOCKED_MODEL": 1},
                   "executable_total": 0, "executable_now": [], "blocked_total": 1,
                   "blocked": [{"id": "x:a", "title": "build it", "state": ws.BLOCKED_MODEL,
                                "reason": "Claude is resting", "next": "when Claude's limit resets",
                                "not_before": "2026-09-16T17:00:00Z"}], "said": "I have 0 ..."}
        part = mission_work.build({"summary": summary}, {})
        card = part["missions"][0]
        self.assertEqual(card["status"], "WAITING")
        self.assertIn("Claude is resting", card["blockers"][0]["said"])
        self.assertEqual(card["next"], "when Claude's limit resets")
        self.assertEqual(part["details"]["work:inventory"]["blocked"][0]["not_before"], "2026-09-16T17:00:00Z")

    def test_the_provider_is_registered(self):
        from aletheia import mission_control
        self.assertIn("work", mission_control.registry())

    def test_current_state_carries_the_work_section(self):
        from aletheia import current_state
        with mock.patch.object(we, "summary", return_value={"readable": True, "counts": {}}):
            self.assertEqual(current_state.work(NOW), {"readable": True, "counts": {}})

    def test_the_beat_runs_the_engine_inside_its_guard(self):
        from aletheia import runtime
        with mock.patch.object(we, "reconcile", return_value={"checkpointed": ["x"], "woke": [], "ran": []}) as rec:
            out = runtime._reconcile_work()
        self.assertEqual(rec.call_args.kwargs["probe"], False)
        self.assertEqual(out[0]["checkpointed"], ["x"])


class TheSourcesMapTheirStores(Isolated):
    def test_tasks(self):
        from aletheia import tasks
        rows = [{"id": "a", "status": "QUEUED", "description": "a", "assigned_worker": "claude"},
                {"id": "b", "status": "WAITING_OPERATOR", "description": "b", "result": "his call"},
                {"id": "c", "status": "QUEUED", "description": "c", "dependencies": ["b"]},
                {"id": "d", "status": "COMPLETED", "description": "d"}]
        with mock.patch.object(tasks, "all_tasks", return_value=rows):
            got = {i["id"]: i for i in we.source_tasks(NOW)}
        self.assertEqual(got["task:a"]["requires"], ["frontier_reasoning"])
        self.assertTrue(got["task:a"]["stronger"])
        self.assertEqual(got["task:b"]["state"], ws.BLOCKED_USER)
        self.assertEqual(got["task:c"]["state"], ws.BLOCKED_EXTERNAL)
        self.assertEqual(got["task:d"]["state"], ws.DONE)
        for it in got.values():
            self.assertEqual(ws.problems(it), [], it)

    def test_charter_steps(self):
        from aletheia import plans
        plan = {"slug": "p", "title": "P", "state": "open", "project": {"repo": "r"}, "steps": [
            {"n": 1, "text": "hers", "state": "todo"},
            {"n": 2, "text": "his", "state": "todo", "owner": "caleb"},
            {"n": 3, "text": "later", "state": "todo", "needs": [2]}]}
        with mock.patch.object(plans, "all_plans", return_value=[plan]):
            got = {i["id"]: i for i in we.source_charters(NOW)}
        self.assertEqual(got["plan:p#1"]["state"], ws.READY)
        self.assertIn("frontier_reasoning", got["plan:p#1"]["requires"])
        self.assertEqual(got["plan:p#2"]["state"], ws.BLOCKED_USER)
        self.assertEqual(got["plan:p#3"]["state"], ws.BLOCKED_EXTERNAL)

    def test_browser_missions_at_a_sign_in_wall_are_blocked_login(self):
        from aletheia import browser_mission as bm
        rows = [{"id": "bm-1", "state": bm.NEEDS_YOU, "goal": "g", "boundary": {"kind": "NEEDS_SIGN_IN",
                                                                               "say": "it wants an account"}},
                {"id": "bm-2", "state": bm.SUBMITTED_UNCONFIRMED, "goal": "g2"}]
        with mock.patch.object(bm, "all_missions", return_value=rows), \
                mock.patch.object(bm, "stale", return_value=False):
            got = {i["id"]: i for i in we.source_browser_missions(NOW)}
        self.assertEqual(got["browser:bm-1"]["state"], ws.BLOCKED_LOGIN)
        self.assertEqual(got["browser:bm-2"]["state"], ws.BLOCKED_EXTERNAL)


if __name__ == "__main__":
    unittest.main()
