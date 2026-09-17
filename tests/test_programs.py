"""Long missions: general structure from his words, carried by the work engine, waiting as a state.

Continuity brief IV.11-14, rules 2, 3, 7, 8. Every model is scripted, every tool
is a fake behind a real descriptor shape, the clock is fake, and replies and
events are written into the real stores by hand. Nothing here launches a
browser, reaches a network or asks a real model.
"""
import datetime as dt
import os
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import (communications, events, handoffs, intercom, policy, program_compose, program_run,
                      program_shaping, programs as pg, reasoner, scheduler, tools, waits, work_engine as we,
                      work_requirements as wr, work_states as ws)

NOW = dt.datetime(2026, 9, 16, 15, 0, tzinfo=dt.timezone.utc)
SENT: list = []
READS: list = []


def _look_up(args, **_):
    READS.append(dict(args))
    return {"text": f"found three sources about {args['question'][:40]}"}


def _send(args, **_):
    SENT.append(dict(args))
    return {"text": f"sent to {args['to']}"}


def _hold_slot(args, **_):
    return {"text": f"held {args['when']} for {args['what']}"}


def fake_catalog() -> dict:
    return {t.name: t for t in (
        tools.declare("look.up", description="Research a question on the web and answer it from real sources",
                      input_schema={"properties": {"question": {"type": "string"}}, "required": ["question"]},
                      handler=_look_up, capability="test.research"),
        tools.declare("send.message", description="Send a message to a person on his behalf (text or email)",
                      input_schema={"properties": {"to": {"type": "string"}, "body": {"type": "string"}},
                                    "required": ["to", "body"]},
                      handler=_send, capability="test.message", risk=intercom.TIER_WORLD, writes=("outbox",),
                      open_world=True, approval="operator_once"),
        tools.declare("calendar.hold", description="Put an event on the calendar at a time",
                      input_schema={"properties": {"when": {"type": "string"}, "what": {"type": "string"}},
                                    "required": ["when", "what"]},
                      handler=_hold_slot, capability="test.calendar", risk=intercom.TIER_ROUTINE,
                      writes=("calendar",), approval="operator_once"),
        tools.declare("switch.thing", description="Send a message to everyone and delete the calendar",
                      input_schema={"properties": {}}, handler=lambda a: {}, capability="test.switch",
                      risk=intercom.TIER_ROUTINE, writes=("x",), destructive=True),
    )}


def draft(**over) -> dict:
    """What a model might return for a broad objective. Keys are the MODEL's words, never code's."""
    value = {
        "title": "Two-month change", "objective": "Look at two places to move and what work there is",
        "horizon": "two months",
        "questions": [{"ask": "Which two places are you considering?", "why": "decides what to research"},
                      {"ask": "When must you have moved by?", "why": "makes the outcome measurable"}],
        "outcomes": [{"key": "o1", "text": "A place chosen", "measure": "Caleb names one place"},
                     {"key": "o2", "text": "A visit arranged", "measure": "a visit is on the calendar"}],
        "workstreams": [{"key": "w1", "title": "Compare the places", "why": "he asked", "outcomes": ["o1"]},
                        {"key": "w2", "title": "Arrange a visit", "why": "to see one", "outcomes": ["o2"]}],
        "tasks": [
            {"key": "t1", "workstream": "w1", "title": "Research the two places", "detail": "costs and neighbourhoods",
             "does": ["research the places"], "uses": ["look.up"], "needs": []},
            {"key": "t2", "workstream": "w2", "title": "Contact the lister", "detail": "ask whether it is free",
             "does": ["send a message to the lister"], "uses": [], "needs": [],
             "then_wait": {"for": "reply", "who": "lister@example.com", "follow_up_days": 3, "timeout_days": 7,
                           "timeout_means": "the listing is probably gone"}},
            {"key": "t3", "workstream": "w2", "title": "Wait for the visit day", "detail": "",
             "does": [], "uses": ["look.up"], "needs": ["t2"], "then_wait": {"for": "date", "in_days": 5}},
        ],
        "activities": [{"key": "a1", "workstream": "w1", "title": "Check new listings", "does": ["research new listings"],
                        "uses": ["look.up"], "cadence": {"every": "day", "at": "07:30"}, "watch": True}],
        "decisions": [{"key": "d1", "workstream": "w1", "question": "Which place?", "options": ["North", "South"],
                       "after": ["t1"]}],
    }
    value.update(over)
    return value


def scripted(value):
    def think(system, text, *, context=None, validator=None, **_):
        return validator(value) if validator else value
    think.provider = "scripted-frontier"
    return think


class Sandbox(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        SENT.clear()
        READS.clear()
        for patcher in (
            mock.patch.dict(os.environ, {"ALETHEIA_PRIVATE_STATE": self.tmp.name}),
            mock.patch.object(communications, "THREADS_DIR", root / "c" / "threads"),
            mock.patch.object(communications, "MESSAGES_DIR", root / "c" / "messages"),
            mock.patch.object(communications, "EXPECT_DIR", root / "c" / "expect"),
            mock.patch.object(events, "EVENTS_DIR", root / "events"),
            mock.patch.object(events, "WATCHERS_DIR", root / "watchers"),
            mock.patch.object(scheduler, "SCHEDULE_DIR", root / "schedules" / "definitions"),
            mock.patch.object(scheduler, "RECEIPT_DIR", root / "schedules" / "receipts"),
            mock.patch.object(policy, "APPROVALS_DIR", root / "approvals"),
            mock.patch.object(policy, "HALT_PATH", root / "halt.json"),
            mock.patch.object(program_run, "EXECUTION", "inline"),
            mock.patch.object(program_run, "CATALOG", fake_catalog()),
            mock.patch.object(program_run, "THINK", scripted(draft())),
            mock.patch.object(pg, "_journal"), mock.patch.object(waits, "_journal"),
            mock.patch.object(we, "_journal"), mock.patch.object(we, "_halted", return_value=None),
            mock.patch("aletheia.work_gaps.record"),
            mock.patch.object(pg, "_notify_draft"),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        wr.forget()
        self.addCleanup(wr.forget)

    def at(self, **delta):
        return NOW + dt.timedelta(**delta)

    def active(self) -> dict:
        record = pg.propose("over the next two months: look at two places and work there", via="operator-voice",
                            now=NOW)
        program_run.do_shape(record["id"], now=NOW)
        return pg.confirm(record["id"], words="yes confirm it", via="operator-voice", now=NOW)

    def task(self, pid, key):
        return next(t for t in pg.load(pid)["tasks"] if t["key"] == key)

    def items(self, now=NOW):
        return {i["id"]: i for i in program_run.source(now)}

    def approve_all(self):
        for row in handoffs.all_handoffs(handoffs.AWAITING):
            policy.decide(row["approval"], "APPROVED", via="operator-phone", because="he said yes")
        return handoffs.run_approved(catalog=program_run.CATALOG)


class TheMissionModelIsDurableAndInertUntilHisYes(Sandbox):
    def test_his_sentence_becomes_a_draft_that_asks_him_before_anything_runs(self):
        record = pg.propose("a completely different life six months from now", via="operator-voice", now=NOW)
        self.assertEqual(record["state"], pg.DRAFTING)
        shape_item = self.items()[f"program:{record['id']}#shape"]
        self.assertEqual((shape_item["state"], shape_item["requires"]), (ws.READY, ["reasoning"]))
        program_run.do_shape(record["id"], now=NOW)
        drafted = pg.load(record["id"])
        self.assertEqual(drafted["state"], pg.DRAFT)
        self.assertEqual([q["ask"] for q in drafted["questions"]][0], "Which two places are you considering?")
        self.assertEqual(drafted["tasks"], [])                       # a draft holds no live work
        rows = self.items()
        self.assertEqual(rows[f"program:{record['id']}#confirm"]["state"], ws.BLOCKED_USER)
        self.assertFalse(any("/t" in k for k in rows))

    def test_only_his_words_confirm_answer_or_decide(self):
        record = pg.propose("change things", via="operator-voice", now=NOW)
        program_run.do_shape(record["id"], now=NOW)
        for her in ("aletheia-programs", "agent-session", "thea", ""):
            with self.assertRaises(PermissionError):
                pg.confirm(record["id"], words="yes", via=her, now=NOW)
            with self.assertRaises(PermissionError):
                pg.add_words(record["id"], "North", via=her, now=NOW)
        self.assertEqual(pg.load(record["id"])["state"], pg.DRAFT)

    def test_answers_are_kept_and_trigger_a_redraft(self):
        record = pg.propose("change things", via="operator-voice", now=NOW)
        program_run.do_shape(record["id"], now=NOW)
        first = pg.add_words(record["id"], "North and South", via="operator-voice", now=NOW)
        self.assertEqual((first["became"], first["remaining"]), ("answer", 1))
        pg.add_words(record["id"], "by November", via="operator-voice", now=NOW)
        self.assertTrue(pg.load(record["id"])["needs_shape"])
        seen = {}

        def think(system, text, *, context=None, validator=None, **_):
            seen.update(context)
            return validator(draft())
        program_run.do_shape(record["id"], think=think, now=NOW)
        self.assertEqual([a["answer"] for a in seen["his_answers"]], ["North and South", "by November"])
        again = pg.load(record["id"])
        self.assertEqual([q.get("answer") for q in again["questions"]], ["North and South", "by November"])

    def test_confirm_makes_tasks_work_items_schedules_activities_and_holds_decisions(self):
        record = self.active()
        self.assertEqual(record["state"], pg.ACTIVE)
        rows = self.items()
        pid = record["id"]
        self.assertEqual(rows[pg.item_id(pid, "t1")]["state"], ws.READY)
        self.assertEqual(rows[pg.item_id(pid, "t3")]["state"], ws.BLOCKED_EXTERNAL)   # needs t2 first
        self.assertIn("Contact the lister", rows[pg.item_id(pid, "t3")]["reason"])
        spec = scheduler.load(pg.schedule_id(pid, "a1"))
        self.assertEqual((spec["kind"], spec["time"], spec["command"]["kind"]), ("daily", "07:30", "mission_activity"))
        self.assertEqual(record["decisions"][0]["state"], "pending")                  # opens after t1
        for row in rows.values():
            self.assertEqual(ws.problems({"state": row["state"], "reason": row["reason"], "next": row["next"],
                                          "not_before": row.get("not_before") or "x"}), [], row["id"])

    def test_it_survives_a_restart_and_a_task_whose_runner_vanished_resumes(self):
        record = self.active()
        pid = record["id"]
        program_run._claim_task(pid, "t1", NOW)
        self.assertEqual(self.items()[pg.item_id(pid, "t1")]["state"], ws.RUNNING)
        with mock.patch.object(program_run, "PROCESS_ID", "a-new-process"):   # the Core restarted
            again = self.items()[pg.item_id(pid, "t1")]
        self.assertEqual(again["state"], ws.READY)
        self.assertEqual(pg.load(pid)["title"], "Two-month change")

    def test_a_revision_is_drafted_and_waits_for_his_yes_keeping_started_work(self):
        record = self.active()
        pid = record["id"]
        program_run.run_task(pid, "t1", now=NOW)
        self.assertEqual(self.task(pid, "t1")["state"], ws.DONE)
        said = pg.add_words(pid, "also look at a third place", via="operator-voice", now=NOW)
        self.assertEqual(said["became"], "revision")
        revised = draft(tasks=[draft()["tasks"][0], {"key": "t9", "workstream": "w1", "title": "Research a third place",
                                                     "does": ["research it"], "uses": ["look.up"], "needs": []}])
        program_run.do_shape(pid, think=scripted(revised), now=NOW)
        self.assertIsNotNone(pg.load(pid)["pending_revision"])
        self.assertNotIn("t9", [t["key"] for t in pg.load(pid)["tasks"]])
        pg.confirm(pid, words="yes", via="operator-voice", now=NOW)
        keys = [t["key"] for t in pg.load(pid)["tasks"]]
        self.assertIn("t9", keys)
        self.assertEqual(self.task(pid, "t1")["state"], ws.DONE)              # started work kept


class ShapingIsGeneral(Sandbox):
    def test_the_validator_repairs_sloppy_output_and_drops_bad_references(self):
        sloppy = {"objective": "x", "outcomes": [{"text": "one thing"}, {"no": "text"}],
                  "workstreams": [{"title": "Stream", "outcomes": ["nope"]}],
                  "tasks": [{"title": "Do it", "workstream": "Stream", "needs": ["ghost"], "uses": ["not.a.tool"],
                             "then_wait": {"for": "telepathy"}}],
                  "activities": [{"title": "Every so often", "cadence": {"every": "fortnight"}}]}
        value = program_shaping.validate(sloppy, tool_names={"look.up"})
        self.assertEqual(value["outcomes"][0]["measure"], "Caleb says it is met")
        self.assertEqual(value["workstreams"][0]["outcomes"], ["o1"])
        task = value["tasks"][0]
        self.assertEqual((task["workstream"], task["needs"], task["uses"], task["then_wait"]),
                         (value["workstreams"][0]["key"], [], [], None))
        self.assertEqual(value["activities"], [])
        with self.assertRaises(program_shaping.ShapeError):
            program_shaping.validate({"title": "empty"})

    def test_it_asks_for_the_standard_class_and_says_when_her_own_model_drafted(self):
        from aletheia import reasoning_gateway
        result = reasoning_gateway.GatewayResult(draft(), "ollama:qwen3:8b", "standard", "fast", "qwen3:8b",
                                                 degraded="subscriptions unavailable: ReasonerUnavailable")
        with mock.patch.object(reasoning_gateway, "reason_json", return_value=result) as asked, \
                mock.patch.object(reasoning_gateway, "frontier_available", return_value=True), \
                mock.patch.object(program_run, "THINK", None):
            record = pg.propose("change things", via="operator-voice", now=NOW)
            program_run.do_shape(record["id"], now=NOW)
        self.assertEqual(asked.call_args.kwargs["policy"], "standard")
        drafted = pg.load(record["id"])["drafted_by"]
        self.assertTrue(drafted["local"])
        self.assertIn("subscriptions unavailable", drafted["degraded"])

    def test_with_no_frontier_it_drafts_in_small_staged_calls_that_a_local_model_can_finish(self):
        calls = []

        def think(system, text, *, context=None, validator=None, **_):
            calls.append(system)
            if system == program_shaping.SKELETON_SYSTEM:
                return validator({k: draft()[k] for k in ("title", "objective", "questions", "outcomes",
                                                           "workstreams")})
            stream = context["workstream"]["key"]
            tasks = [t for t in draft()["tasks"] if t["workstream"] == stream]
            keys = {x["key"] for x in tasks}
            return validator({"tasks": [dict(t, needs=[n for n in t["needs"] if n in keys]) for t in tasks],
                              "activities": [], "decisions": []})
        shaped = program_shaping.shape("change things", catalog=fake_catalog(), think=think, staged=True)
        self.assertEqual(calls, [program_shaping.SKELETON_SYSTEM] + [program_shaping.STREAM_SYSTEM] * 2)
        keys = [t["key"] for t in shaped["structure"]["tasks"]]
        self.assertEqual(keys, ["w1t1", "w2t2", "w2t3"])
        self.assertEqual(shaped["structure"]["tasks"][2]["needs"], ["w2t2"])
        self.assertTrue(shaped["staged"])

    def test_with_the_frontier_out_each_beat_writes_one_piece_and_an_outage_keeps_the_pieces(self):
        from aletheia import reasoning_gateway

        def answer(system, text, *, context=None, validator=None, **_):
            if system == program_shaping.SKELETON_SYSTEM:
                value = {k: draft()[k] for k in ("title", "objective", "questions", "outcomes", "workstreams")}
            else:
                key = context["workstream"]["key"]
                value = {"tasks": [dict(t, needs=[]) for t in draft()["tasks"] if t["workstream"] == key]}
            return reasoning_gateway.GatewayResult(validator(value), "ollama:qwen3:8b", "standard",
                                                   degraded="subscriptions unavailable: ReasonerUnavailable")
        outage = [False]

        def flaky(system, text, **kw):
            if outage[0]:
                raise reasoner.ReasonerUnavailable("the local model timed out")
            return answer(system, text, **kw)
        with mock.patch.object(reasoning_gateway, "reason_json", side_effect=flaky), \
                mock.patch.object(reasoning_gateway, "frontier_available", return_value=False), \
                mock.patch.object(program_run, "THINK", None):
            record = pg.propose("change things", via="operator-voice", now=NOW)
            pid = record["id"]
            self.assertEqual(program_run.do_shape(pid, now=NOW)["state"], "partial")       # skeleton
            outage[0] = True
            self.assertEqual(program_run.do_shape(pid, now=NOW)["state"], ws.BLOCKED_MODEL)
            kept = pg.load(pid)["shape"]["partial"]
            self.assertIsNotNone(kept["skeleton"])                                          # nothing lost
            outage[0] = False
            self.assertEqual(program_run.do_shape(pid, now=self.at(minutes=20))["state"], "partial")  # w1
            self.assertEqual(program_run.do_shape(pid, now=self.at(minutes=21))["state"], "drafted")  # w2
        drafted = pg.load(pid)
        self.assertEqual(drafted["state"], pg.DRAFT)
        self.assertTrue(drafted["drafted_by"]["local"])
        self.assertEqual(len(drafted["draft"]["tasks"]), 3)

    def test_a_compact_local_plan_becomes_full_tasks_with_waits_that_mean_something(self):
        value = program_shaping.expand_compact({"tasks": [
            {"title": "Ask the person about it", "waits_for": "reply", "who": "someone@example.test", "after": 0},
            {"title": "Go on the agreed day", "waits_for": "date", "who": "", "after": 1},
            {"title": "Pick one", "waits_for": "decision", "after": 7}]})
        first, second, third = value["tasks"]
        self.assertEqual(first["then_wait"]["who"], "someone@example.test")
        self.assertTrue(first["then_wait"]["follow_up_days"] and first["then_wait"]["timeout_means"])
        self.assertEqual(second["needs"], ["t1"])
        self.assertEqual((third["needs"], third["then_wait"]["question"]), ([], "Pick one"))

    def test_nobody_able_to_think_is_blocked_model_not_failure(self):
        from aletheia import reasoning_gateway
        with mock.patch.object(reasoning_gateway, "reason_json",
                               side_effect=reasoner.ReasonerUnavailable("all out")), \
                mock.patch.object(program_run, "THINK", None):
            record = pg.propose("change things", via="operator-voice", now=NOW)
            said = program_run.do_shape(record["id"], now=NOW)
        self.assertEqual(said["state"], ws.BLOCKED_MODEL)
        row = self.items()[f"program:{record['id']}#shape"]
        self.assertEqual(row["state"], ws.BLOCKED_MODEL)
        self.assertEqual(self.items(self.at(minutes=20))[f"program:{record['id']}#shape"]["state"], ws.READY)

    def test_the_menu_it_shows_a_model_comes_from_the_real_catalog_by_relevance(self):
        lines = program_compose.menu("research places and send a message", fake_catalog())
        self.assertTrue(lines[0].startswith(("look.up", "send.message")))
        self.assertFalse(any(l.startswith("switch.thing") for l in lines))


class NoCategoriesInCode(unittest.TestCase):
    """Brief IV.12: the structure is discovered, never predefined. The long-mission layer's code may
    not carry a list of life domains or any particular mission."""
    MODULES = ("programs.py", "program_run.py", "program_shaping.py", "program_compose.py", "program_tools.py",
               "mission_programs.py", "waits.py")
    DOMAIN = re.compile(r"\b(?:career|careers|housing|health|healthcare|finance|finances|financial|social|"
                        r"dating|relationship|relationships|fitness|job|jobs|employment|apartment|landlord|"
                        r"rent|realtor|recruiter|city|cities|reboot)\b", re.I)

    def test_no_module_of_the_layer_names_a_domain(self):
        import ast
        root = Path(pg.__file__).parent
        for name in self.MODULES:
            tree = ast.parse((root / name).read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and isinstance(node.value, str):
                    if node is getattr(tree.body[0], "value", None):
                        continue                    # the module docstring may quote his words
                    found = self.DOMAIN.search(node.value)
                    self.assertIsNone(found, f"{name}: string names a domain: {node.value[:80]!r}")

    def test_there_is_no_project_reboot_module(self):
        root = Path(pg.__file__).parent
        self.assertEqual(list(root.glob("*reboot*")), [])


class CompositionChoosesByCapability(Sandbox):
    def test_needs_become_steps_on_whatever_tool_matches(self):
        cat = fake_catalog()
        plan = program_compose.compose({"title": "x", "does": ["research the neighbourhoods",
                                                               "send a message to the owner",
                                                               "put the visit on the calendar"]}, cat)
        self.assertEqual([s["tool"] for s in plan["steps"]], ["look.up", "send.message", "calendar.hold"])
        self.assertIn("network", plan["requires"])
        self.assertEqual(plan["gaps"], [])

    def test_a_named_tool_is_used_and_an_excluded_one_never_is(self):
        cat = fake_catalog()
        plan = program_compose.compose({"title": "x", "uses": ["switch.thing", "look.up"], "does": []}, cat)
        self.assertEqual([s["tool"] for s in plan["steps"]], ["look.up"])

    def test_no_tool_is_a_classified_gap_and_money_is_refused(self):
        cat = fake_catalog()
        with mock.patch("aletheia.work_gaps._registry", return_value={"capabilities": []}):
            plan = program_compose.compose({"title": "x", "does": ["pay the deposit"]}, cat)
            other = program_compose.compose({"title": "x", "does": ["knit a scarf"]}, cat)
        self.assertEqual(plan["steps"], [])
        self.assertEqual(plan["gaps"][0]["outcome"], "refuse_policy")
        self.assertEqual(other["gaps"][0]["state"] in ws.WORK_STATES, True)

    def test_the_real_catalog_composes_without_any_domain_table(self):
        cat = tools.catalog()
        plan = program_compose.compose({"title": "x", "does": ["research the cost of living there",
                                                               "send a message to the person"]}, cat)
        self.assertEqual([s["tool"] for s in plan["steps"]], ["research", "message_send"])


class TasksRunThroughTheBrokerAndWait(Sandbox):
    def test_a_read_runs_now_and_the_task_is_done_with_its_result(self):
        pid = self.active()["id"]
        program_run.run_task(pid, "t1", now=NOW)
        task = self.task(pid, "t1")
        self.assertEqual(task["state"], ws.DONE)
        self.assertEqual(READS[0]["question"], "costs and neighbourhoods")
        self.assertIn("found three sources", pg.load(pid)["results"][-1]["text"])
        decision = pg.load(pid)["decisions"][0]
        self.assertEqual(decision["state"], "open")                   # its `after` task is done: his now
        self.assertEqual(waits.load(decision["wait"])["work_state"], ws.BLOCKED_USER)

    def test_reaching_a_person_is_handed_to_him_then_waits_for_the_reply_then_wakes(self):
        pid = self.active()["id"]
        said = program_run.run_task(pid, "t2", now=NOW)
        self.assertEqual(said["state"], ws.BLOCKED_USER)
        self.assertEqual(SENT, [])                                   # nothing reached anyone
        row = self.items()[pg.item_id(pid, "t2")]
        self.assertIn("needs Caleb's approval", row["reason"])
        self.assertEqual(self.approve_all()[0]["outcome"], handoffs.DONE)
        self.assertEqual(SENT[0]["to"], "lister@example.com")
        moved = waits.reconcile(self.at(minutes=1))
        self.assertEqual(moved[0]["outcome"], "done")
        self.assertEqual(self.task(pid, "t2")["state"], ws.READY)
        program_run.run_task(pid, "t2", now=self.at(minutes=2))
        task = self.task(pid, "t2")
        self.assertEqual(task["state"], ws.BLOCKED_EXTERNAL)
        held = pg.current_wait(task)
        self.assertEqual((held["condition"]["kind"], held["condition"]["participant"]),
                         ("reply_from", "lister@example.com"))
        # the reply arrives
        communications.record_message("in-1", thread_id=held["condition"]["thread_id"], direction="INBOUND",
                                      channel="email", participant="lister@example.com", summary="still free",
                                      occurred_at=waits.stamp(self.at(days=1)))
        waits.reconcile(self.at(days=1, minutes=5))
        self.assertEqual(self.task(pid, "t2")["state"], ws.DONE)
        self.assertEqual(self.items(self.at(days=1, minutes=5))[pg.item_id(pid, "t3")]["state"], ws.READY)

    def test_silence_follows_up_through_his_approval_and_a_timeout_asks_him_not_fails(self):
        pid = self.active()["id"]
        program_run.run_task(pid, "t2", now=NOW)
        self.approve_all()
        waits.reconcile(self.at(minutes=1))
        program_run.run_task(pid, "t2", now=self.at(minutes=2))
        waits.reconcile(self.at(days=3, minutes=5))                  # follow_up_days: 3
        nudge = self.task(pid, "t2-nudge1")
        self.assertEqual(nudge["state"], ws.READY)
        program_run.run_task(pid, "t2-nudge1", now=self.at(days=3, minutes=6))
        self.assertEqual(self.task(pid, "t2-nudge1")["state"], ws.BLOCKED_USER)   # the nudge asks him first
        self.assertEqual(len(SENT), 1)
        waits.reconcile(self.at(days=8))                              # timeout_days: 7
        task = self.task(pid, "t2")
        self.assertEqual(task["state"], ws.BLOCKED_USER)
        self.assertIn("the listing is probably gone", task["reason"])
        held = pg.current_wait(task)
        waits.decide(held["id"], "move on", words="move on", via="operator-voice", now=self.at(days=8))
        waits.reconcile(self.at(days=8, minutes=1))
        self.assertEqual(self.task(pid, "t2")["state"], ws.DONE)

    def test_a_date_wait_wakes_on_the_fake_clock_while_other_work_keeps_going(self):
        pid = self.active()["id"]
        record = pg.load(pid)
        t3 = self.task(pid, "t3")
        t3["needs"] = []
        with pg._LOCK:
            record["tasks"] = [t if t["key"] != "t3" else t3 for t in record["tasks"]]
            pg.save(record)
        program_run.run_task(pid, "t3", now=NOW)
        self.assertEqual(self.task(pid, "t3")["state"], ws.BLOCKED_EXTERNAL)
        self.assertEqual(self.items()[pg.item_id(pid, "t1")]["state"], ws.READY)    # rule 2
        self.assertEqual(waits.reconcile(self.at(days=4)), [])
        waits.reconcile(self.at(days=5, minutes=1))
        self.assertEqual(self.task(pid, "t3")["state"], ws.DONE)

    def test_money_is_refused_and_missing_arguments_ask_him(self):
        pid = self.active()["id"]
        record = pg.load(pid)
        record["tasks"].append(pg._task_from({"key": "tpay", "title": "Pay the deposit", "does": ["pay the deposit"],
                                              "uses": []}, NOW))
        record["tasks"].append(pg._task_from({"key": "tcal", "title": "Hold the visit", "does": ["put it on the calendar"],
                                              "uses": ["calendar.hold"]}, NOW))
        with pg._LOCK:
            pg.save(record)
        with mock.patch("aletheia.work_gaps._registry", return_value={"capabilities": []}):
            program_run.run_task(pid, "tpay", now=NOW)
        self.assertEqual(self.task(pid, "tpay")["state"], ws.FAILED)
        self.assertIn("money", self.task(pid, "tpay")["reason"])
        with mock.patch.object(program_compose, "model_args", side_effect=reasoner.ReasonerUnavailable("out")):
            program_run.run_task(pid, "tcal", now=NOW)
        self.assertEqual(self.task(pid, "tcal")["state"], ws.BLOCKED_MODEL)
        up = wr._result("reasoning", True, "back", live=True, now=NOW)
        with mock.patch.object(wr, "world", return_value=up):
            waits.reconcile(self.at(minutes=1))
        self.assertEqual(self.task(pid, "tcal")["state"], ws.READY)
        with mock.patch.object(program_compose, "model_args", return_value={}):
            program_run.run_task(pid, "tcal", now=self.at(minutes=2))
        task = self.task(pid, "tcal")
        self.assertEqual(task["state"], ws.BLOCKED_USER)
        self.assertIn("what should I use for when", task["reason"])


class TheWorkEngineCarriesIt(Sandbox):
    def sources(self):
        return {"programs": we.source_programs, "waits": we.source_waits}

    def test_reconcile_runs_ready_mission_tasks_and_keeps_waiting_ones_waiting(self):
        pid = self.active()["id"]
        with mock.patch("aletheia.work_gaps.file_from_demand"):
            first = we.reconcile(NOW, sources=self.sources(), probe=False, max_runs=5)
        ran = {r["id"] for r in first["ran"]}
        self.assertIn(pg.item_id(pid, "t1"), ran)
        self.assertIn(pg.item_id(pid, "t2"), ran)
        self.assertEqual(self.task(pid, "t1")["state"], ws.DONE)
        self.assertEqual(self.task(pid, "t2")["state"], ws.BLOCKED_USER)
        inv = we.inventory(NOW, sources=self.sources(), with_availability=False, with_gaps=False)
        blocked = {b["id"]: b for b in inv["blocked"]}
        self.assertIn(pg.item_id(pid, "t2"), blocked)
        self.assertIn(pg.item_id(pid, "decision-d1"), blocked)
        self.assertEqual(blocked[pg.item_id(pid, "t3")]["state"], ws.BLOCKED_EXTERNAL)

    def test_the_shape_item_is_run_by_the_engine_and_a_model_outage_does_not_stop_other_work(self):
        pid = self.active()["id"]
        other = pg.propose("another objective entirely", via="operator-voice", now=NOW)
        down = wr._result("reasoning", False, "nobody can think", live=True, now=NOW)

        def world(req, **_):
            return down if req in ("reasoning", "local_reasoning", "frontier_reasoning") else \
                wr._result(req, True, "ok", live=True, now=NOW)
        with mock.patch.object(wr, "world", side_effect=world), mock.patch("aletheia.work_gaps.file_from_demand"):
            result = we.reconcile(NOW, sources=self.sources(), probe=False, max_runs=5)
        self.assertIn(f"program:{other['id']}#shape", result["checkpointed"])
        self.assertEqual(self.task(pid, "t1")["state"], ws.DONE)             # rule 2
        self.assertEqual(pg.load(other["id"])["state"], pg.DRAFTING)

    def test_a_schedule_firing_starts_an_occurrence_and_a_watch_signals_change(self):
        pid = self.active()["id"]
        made = pg.activity_due(pid, "a1", now=NOW)
        self.assertEqual(made["made"], "a1-2026091615")
        self.assertIsNone(pg.activity_due(pid, "a1", now=NOW)["made"])     # idempotent per occurrence
        program_run.run_task(pid, "a1-2026091615", now=NOW)
        pg.activity_due(pid, "a1", now=self.at(days=1))
        with mock.patch.object(program_run, "_said", return_value="something new today"):
            program_run.run_task(pid, "a1-2026091715", now=self.at(days=1))
        kinds = [e["kind"] for e in events.list_events(limit=10)]
        self.assertIn("mission.changed", kinds)
        fleet = {"repos": {}}
        with mock.patch.object(intercom, "validate_kind_args", return_value=[]):
            said = intercom.execute_command({"kind": "mission_activity", "mission": pid, "activity": "a1"}, fleet,
                                            quote="schedule")
        self.assertIn("Check new listings", said)


class ItIsReadBack(Sandbox):
    def test_the_voice_door_the_intercom_and_the_reader_agree(self):
        from aletheia import voice
        fleet = {"repos": {}}
        cmd = voice.interpret("start a mission: over two months look at two places and work there")["command"]
        said = intercom.execute_command(cmd, fleet, quote="start a mission")
        self.assertIn("draft", said)
        pid = pg.find()["id"]
        self.assertIn("still drafting", intercom.execute_command({"kind": "missions"}, fleet))
        program_run.do_shape(pid, now=NOW)
        self.assertIn("Which two places", intercom.execute_command({"kind": "missions"}, fleet))
        said = intercom.execute_command(voice.interpret("add to my mission: North and South")["command"], fleet,
                                        quote="add to my mission: North and South")
        self.assertIn("1 more question", said)
        said = intercom.execute_command(voice.interpret("confirm my mission")["command"], fleet,
                                        quote="confirm my mission")
        self.assertIn("is on", said)
        program_run.run_task(pid, "t2", now=NOW)
        waiting = intercom.execute_command(voice.interpret("what are we waiting on")["command"], fleet)
        self.assertIn("needs Caleb's approval", waiting)

    def test_the_session_tools_and_the_provider_read_the_same_store(self):
        empty = tools.get("mission.status").handler({})
        self.assertTrue(empty["readable"])
        self.assertIn("READ AND EMPTY", empty["note"])
        pid = self.active()["id"]
        program_run.run_task(pid, "t1", now=NOW)
        program_run.run_task(pid, "t2", now=NOW)
        status = tools.get("mission.status").handler({"which": "two-month"})
        mission = status["missions"][0]
        self.assertEqual(mission["progress"], "1 of 3 tasks done")
        self.assertEqual(mission["decisions_for_caleb"][0]["question"], "Which place?")
        waiting = tools.get("mission.waiting").handler({})
        whys = [w["why"] for w in waiting["waiting"]]
        self.assertTrue(any("needs Caleb's approval" in w for w in whys))
        self.assertTrue(tools.get("mission.status").read_only)
        from aletheia import mission_programs
        reading = mission_programs.read({"now": NOW, "sections": {}})
        built = mission_programs.build(reading, {"now": NOW})
        card = built["missions"][0]
        self.assertEqual(card["status"], "NEEDS YOU")
        self.assertEqual(card["progress"], {"done": 1, "total": 3})
        detail = built["details"][card["id"]]
        self.assertEqual({w["key"] for w in detail["waiting"]} >= {"t2", "t3"}, True)
        self.assertTrue(any("Decide: Which place?" == n["said"] for n in card["needs"]))

    def test_investigate_routes_a_mission_question_to_a_session_with_the_tools(self):
        from aletheia import investigate
        self.assertTrue(investigate.wants_session("how is my big mission going"))
        self.assertEqual(investigate.looking_at("mission.waiting"), "what your missions are waiting on")
        visible = tools.for_model("local")["tools"]
        self.assertTrue({"mission.status", "mission.waiting"} <= {t["name"] for t in visible})


if __name__ == "__main__":
    unittest.main()
