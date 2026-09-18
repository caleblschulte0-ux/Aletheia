"""'Work on my projects.' even with every frontier model out (continuity C3b).

The door (phrasings), the router (charter steps to local repair, a packet or the
cloud builder), the runners (reads run, world steps are handed off), red CI on a
charter branch as work, one piece of work in two stores as one item, the session
loop that does not stop while anything is executable, and the words he hears.
Every live check, checkout, model and network read is stubbed.
"""
import datetime as dt
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import (charter_ci, intercom, investigation as inv, policy, project_work, tools, voice,
                      work_engine as we, work_requirements as wr, work_runners as runners, work_states as ws)

NOW = dt.datetime(2026, 9, 17, 12, 0, tzinfo=dt.timezone.utc)
BARKLY = {"slug": "barkly", "title": "Barkly", "state": "open",
          "project": {"repo": "money_machine", "base_branch": "claude/barkly-x", "path": "barkly", "risk": "low"},
          "steps": [{"n": 1, "text": "Get Barkly CI green on the project branch: its 'Production dependency audit' "
                                     "step fails on every push", "state": "todo"},
                    {"n": 2, "text": "Turn on GitHub Pages for Money_Machine (Settings, Pages)", "state": "todo",
                     "owner": "caleb"},
                    {"n": 3, "text": "Fix the useBarkly.goTo() dev-flag mismatch noted in barkly/docs/APP.md "
                                     "(pass devRef.current to areaUnlocked)", "state": "todo"}]}
FLEET = {"owner": "caleb", "repos": {"money_machine": {"github": "Money_Machine", "default_branch": "main"},
                                     "shorts_pipeline": {"github": "Shorts-pipeline", "default_branch": "main"}}}


class Isolated(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        for patcher in (
            mock.patch.dict(os.environ, {"ALETHEIA_PRIVATE_STATE": self.tmp.name, "ALETHEIA_REHEARSAL": "1",
                                         "ALETHEIA_REPAIR_WORKTREES": str(root / "wt")}),
            mock.patch.object(policy, "APPROVALS_DIR", root / "approvals"),
            mock.patch.object(policy, "HALT_PATH", root / "halt.json"),
            mock.patch.object(we, "_journal"), mock.patch.object(runners, "_journal"),
            mock.patch.object(project_work, "_journal"),
            mock.patch.object(we, "_halted", return_value=None),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        wr.forget()
        self.addCleanup(wr.forget)

    def frontier(self, ok: bool):
        return mock.patch.object(runners, "_frontier_ok", return_value=ok)


def plan_item(n: int, **over) -> dict:
    step = BARKLY["steps"][n - 1]
    base = we.item(f"plan:barkly#{n}", "plans", f"Barkly: {step['text']}", ws.READY, requires=["reasoning", "network"],
                   native_state="todo", owner="thea", payload={"slug": "barkly", "n": n, "text": step["text"],
                                                                "charter": True})
    base.update(over)
    return base


class HeSaysIt(unittest.TestCase):
    def test_the_ways_he_says_it_reach_the_command(self):
        for said in ("work on my projects", "Work on my projects.", "keep working on my stuff",
                     "what can you get done right now", "thea, can you work on my projects for a while",
                     "get some work done on my projects", "keep working on my projects"):
            self.assertEqual(voice.interpret(said)["command"]["kind"], "work_projects", said)
        self.assertEqual(voice.interpret("work on my projects for half an hour")["command"]["minutes"], 30)

    def test_questions_and_drops_are_not_orders_to_work(self):
        self.assertEqual(voice.interpret("how are my projects")["command"]["kind"], "projects")
        self.assertEqual(voice.interpret("stop working on barkly")["command"]["kind"], "project_drop")
        self.assertNotEqual((voice.interpret("keep going")["command"] or {}).get("kind"), "work_projects")
        self.assertEqual(voice.interpret("what did you get done on my projects")["command"]["kind"], "work_report")

    def test_the_grammar_tiers_and_the_reader(self):
        self.assertIn("work_projects", intercom.ROUTINE_KINDS)
        self.assertIn("work_report", intercom.READ_ONLY_KINDS)
        self.assertIn("work_projects", intercom.LOCAL_KINDS)
        self.assertTrue(tools.get("work.receipts").read_only)
        from aletheia import investigate
        self.assertTrue(investigate.wants_session("what did you get done"))

    def test_the_intercom_starts_a_session_and_speaks_its_opening(self):
        with mock.patch.object(project_work, "start", return_value={"said": "On it.", "started": True}) as start:
            said = intercom.execute_command({"kind": "work_projects", "minutes": 10}, {}, quote="work on my projects")
        self.assertEqual(said, "On it.")
        self.assertEqual(start.call_args.kwargs["minutes"], 10.0)


class TheWordsOfTheWorkDecideTheRoute(Isolated):
    def test_step_kinds_from_his_real_charter_steps(self):
        kinds = {text: runners.step_kind(text)["kind"] for text in (
            BARKLY["steps"][0]["text"], BARKLY["steps"][2]["text"],
            "Write a one-page status of the five-film slate in handoff/STATUS.md: which films are delivered",
            "Make the watchdog say which of the two likely causes a stall is (no trigger runs, or runs that fail)",
            "Point a ChatGPT scheduled task at state/pulse/briefing.md with the exchange/README.md contract",
            "Migrate the login flow to OAuth",
            "Shorts-pipeline daily.yml + third.yml red since 2026-08-14: nobody authors the day's packages")}
        self.assertEqual(list(kinds.values()), ["failure", "change", "doc", "change", "his", "escalate", "failure"])

    def test_a_charter_step_goes_to_the_builder_when_the_frontier_is_up_and_stays_local_when_it_is_out(self):
        self.assertEqual(runners.route(plan_item(3), frontier=True)["route"], "builder")
        self.assertEqual(runners.route(plan_item(3), frontier=False)["route"], "change")
        self.assertEqual(runners.route(plan_item(1), frontier=False)["route"], "failure")

    def test_a_packet_waits_for_a_stronger_model_and_is_consumed_when_one_is_back(self):
        it = plan_item(3, state=ws.NEEDS_STRONGER_MODEL, evidence={"packet": "packet-x"})
        self.assertEqual(runners.route(it, frontier=False)["route"], "wait_stronger")
        self.assertEqual(runners.route(it, frontier=True)["route"], "frontier_packet")

    def test_a_task_for_a_frontier_worker_is_theirs_when_they_are_up_and_investigated_when_not(self):
        it = we.item("task:t", "tasks", "Refactor the scheduler", ws.READY,
                     payload={"task": "t", "description": "Refactor the scheduler", "worker": "claude"})
        self.assertEqual(runners.route(it, frontier=True)["route"], "frontier_worker")
        self.assertEqual(runners.route(it, frontier=False, investigate=True)["route"], "escalate")

    def test_heavy_work_waits_for_a_session_and_costs_the_beat_nothing(self):
        with self.frontier(False):
            out = runners.run(plan_item(3), NOW)
        self.assertTrue(out["noop"])
        self.assertIn("work session", out["next"])


class TheRunners(Isolated):
    def test_something_only_he_can_do_is_asked_once_and_waits_on_him(self):
        it = we.item("plan:w#4", "plans", "Wall: Point a ChatGPT scheduled task at the briefing", ws.READY,
                     payload={"slug": "w", "n": 4, "text": "Point a ChatGPT scheduled task at the briefing"})
        with self.frontier(False), mock.patch("aletheia.notifications.publish") as publish:
            out = runners.run(it, NOW)
        self.assertEqual(out["state"], ws.BLOCKED_USER)
        self.assertIn("scheduled task", out["reason"])
        self.assertEqual(publish.call_args.kwargs["dedupe_key"], "work-ask:plan:w#4")

    def test_a_stale_verify_task_for_an_available_capability_is_closed_as_bookkeeping(self):
        from aletheia import capabilities, tasks
        it = we.item("task:verify-x", "tasks", "Verify or repair capability app.x", ws.READY,
                     payload={"task": "verify-x", "description": "Verify or repair capability app.x", "worker": "claude"})
        with self.frontier(False), \
                mock.patch.object(capabilities, "get", return_value={"id": "app.x", "status": "AVAILABLE",
                                                                    "verification": "live 2026-09-10"}), \
                mock.patch.object(tasks, "set_status") as set_status:
            out = runners.run(it, NOW)                    # light: no session needed
        self.assertEqual(out["state"], ws.DONE)
        self.assertEqual(set_status.call_args.args[:2], ("verify-x", "COMPLETED"))

    def test_an_experimental_capability_runs_its_tests_and_hands_the_live_proof_to_him(self):
        from aletheia import capabilities, project_checkout, tasks
        it = we.item("task:verify-m", "tasks", "Verify or repair capability message.send", ws.READY,
                     payload={"task": "verify-m", "description": "Verify or repair capability message.send"})
        entry = {"id": "message.send", "status": "EXPERIMENTAL", "module": "aletheia.messages",
                 "notes": "What moves it: one supervised live send to a number he chooses."}
        with self.frontier(False), runners.session_scope({"id": "s"}), \
                mock.patch.object(capabilities, "get", return_value=entry), \
                mock.patch.object(project_checkout, "clone_local", return_value={"path": self.tmp.name, "scratch": ""}), \
                mock.patch.object(project_checkout, "discard"), \
                mock.patch.object(inv, "run_tests", return_value={"passed": True, "failing": [], "seconds": 4.0,
                                                                   "command": "python -m unittest tests.test_messages"}), \
                mock.patch.object(tasks, "set_status") as set_status:
            out = runners.run(it, NOW)
        self.assertEqual(out["state"], ws.BLOCKED_USER)
        self.assertIn("supervised live send", out["reason"])
        self.assertEqual(set_status.call_args.args[1], "WAITING_OPERATOR")

    def compose_catalog(self):
        read = tools.declare("look.it.up", description="Look up the status summary of something and report it",
                             input_schema={"properties": {"question": {"type": "string"}}, "required": ["question"]},
                             handler=lambda a, **_: {"text": "all fine"}, capability="test.read")
        world = tools.declare("post.it", description="Post a status summary publicly for everyone",
                              input_schema={"properties": {"text": {"type": "string"}}, "required": ["text"]},
                              handler=lambda a, **_: {"text": "posted"}, capability="test.post",
                              risk=intercom.TIER_WORLD, writes=("web",), open_world=True, approval="operator_once")
        return {t.name: t for t in (read, world)}

    def test_compose_runs_a_read_and_hands_a_world_step_to_him(self):
        from aletheia import agent_session, handoffs, program_compose, tasks
        it = we.item("task:q", "tasks", "Look up the status summary", ws.READY,
                     payload={"task": "q", "description": "Look up the status summary"})
        cat = self.compose_catalog()
        with self.frontier(False), mock.patch.object(tools, "catalog", return_value=cat), \
                mock.patch.object(agent_session.Broker, "_capability", return_value=None), \
                mock.patch.object(program_compose, "compose",
                                  return_value={"steps": [{"tool": "look.it.up", "for": "x"}], "gaps": [], "requires": []}), \
                mock.patch.object(tasks, "set_status") as set_status:
            out = runners.run(it, NOW)
        self.assertEqual(out["state"], ws.DONE)
        self.assertEqual(set_status.call_args.args[1], "COMPLETED")
        with self.frontier(False), mock.patch.object(tools, "catalog", return_value=cat), \
                mock.patch.object(agent_session.Broker, "_capability", return_value=None), \
                mock.patch.object(program_compose, "compose",
                                  return_value={"steps": [{"tool": "post.it", "for": "x"}], "gaps": [], "requires": []}), \
                mock.patch.object(handoffs, "file", return_value={"id": "handoff-1"}) as filed:
            out = runners.run(it, NOW)
        self.assertEqual(out["state"], ws.BLOCKED_USER)
        self.assertEqual(out["evidence"]["approval"], "handoff-1")
        self.assertEqual(filed.call_args.kwargs["tool"].name, "post.it")

    def fake_view(self, **over):
        view = {"path": self.tmp.name, "scratch": "", "subdir": "barkly", "base_sha": "a" * 40, "branch": "claude/barkly-x",
                "repo": "caleb/Money_Machine", "files": 3, "python_tests": [], "package_json": ["barkly/package.json"],
                "skipped": 0}
        view.update(over)
        return view

    def test_red_ci_that_her_tests_cannot_run_becomes_a_packet_with_the_ci_evidence(self):
        from aletheia import local_repair, plans, project_checkout
        ci = {"slug": "barkly", "repo": "caleb/Money_Machine", "branch": "claude/barkly-x", "subdir": "barkly",
              "workflow": "Barkly CI", "workflow_path": ".github/workflows/barkly-ci.yml", "run_id": 7,
              "head_sha": "b" * 40, "url": "https://example/run/7",
              "failed": [{"job": "Typecheck and tests", "steps": ["Production dependency audit"]}]}
        it = we.link([plan_item(1), we.item("ci:barkly@wf", "charter_ci", "Barkly: CI is red", ws.READY,
                                            native_state="run:7", payload={**ci, "same_as": "plan:barkly#1"})])
        self.assertEqual(len(it), 1)
        it = it[0]
        workflow = "jobs:\n  t:\n    steps:\n      - name: Production dependency audit\n        run: npm audit --omit=dev\n"
        with self.frontier(False), runners.session_scope({"id": "s"}), \
                mock.patch.object(plans, "load", return_value=BARKLY), \
                mock.patch.object(local_repair, "charter_target", return_value={"repo": "caleb/Money_Machine",
                                                                                "base_ref": "claude/barkly-x",
                                                                                "subdir": "barkly", "charter": "barkly"}), \
                mock.patch.object(project_checkout, "checkout", return_value=self.fake_view()), \
                mock.patch.object(project_checkout, "discard"), \
                mock.patch.object(project_checkout, "raw_file", return_value=workflow), \
                mock.patch.object(runners, "_hypothesis", return_value={"answered": True, "provider": "ollama:qwen3:8b",
                                                                         "cause": "a vulnerable dependency", "files": [],
                                                                         "decision_needed": "", "next_steps": []}), \
                mock.patch.object(local_repair, "run") as local_run:
            out = runners.run(it, NOW)
        local_run.assert_not_called()                       # Node checks: never a local attempt
        self.assertEqual(out["state"], ws.NEEDS_STRONGER_MODEL)
        packet = inv.load_packet(out["evidence"]["packet"])
        self.assertEqual(packet["failure"]["command"], "run: npm audit --omit=dev")
        self.assertEqual(packet["ci"]["run_id"], 7)
        self.assertTrue(packet["on_branch"])
        # It used to say "its checks run under Node ... which the local repair
        # tier does not run"; the tier runs Node now (C5a), so the rule this
        # assertion protects is the one that survives: a project with NO tests
        # she can run to prove a fix does not get a local attempt, and the
        # packet says why in a sentence.
        self.assertIn("no tests the local repair tier can run", packet["evidence_summary"])
        self.assertIn("unverified", packet["evidence_summary"])
        queued = inv.waiting_for_frontier("caleb/Money_Machine")
        self.assertEqual([q["packet_id"] for q in queued], [packet["id"]])
        written = we.record_outcome(it, out, NOW)
        self.assertEqual(set(written), {"plan:barkly#1", "ci:barkly@wf"})    # every copy is settled

    def test_a_failure_her_tests_can_run_goes_to_the_local_repair_tier_on_a_branch(self):
        from aletheia import local_repair, plans, project_checkout
        with self.frontier(False), runners.session_scope({"id": "s"}), \
                mock.patch.object(plans, "load", return_value=BARKLY), \
                mock.patch.object(local_repair, "charter_target", return_value={"repo": "caleb/Money_Machine",
                                                                                "base_ref": "claude/barkly-x",
                                                                                "subdir": "barkly", "charter": "barkly"}), \
                mock.patch.object(runners, "_ci_for", return_value=None), \
                mock.patch.object(project_checkout, "checkout",
                                  return_value=self.fake_view(python_tests=["barkly/test_x.py"], package_json=[])), \
                mock.patch.object(project_checkout, "discard"), \
                mock.patch.object(local_repair, "run", return_value={"status": "BRANCH_READY", "branch": "thea-repair/x",
                                                                      "id": "repair-1"}) as local_run:
            out = runners.run(plan_item(1), NOW)
        self.assertEqual(local_run.call_args.kwargs["publish_base_sha"], "a" * 40)
        self.assertFalse(local_run.call_args.kwargs["open_pr"])            # a rehearsal opens no PR
        self.assertEqual(out["state"], ws.BLOCKED_USER)
        self.assertIn("thea-repair/x", out["reason"])

    def test_the_frontier_path_starts_from_the_packet(self):
        from aletheia import reasoning_gateway
        packet = inv.write_packet({"id": "packet-abc", "repo": "caleb/Money_Machine", "task_id": "t",
                                   "evidence_summary": "CI red at bbbb: Production dependency audit fails",
                                   "failure": {"output_tail": "npm audit: 3 high"}, "classification": {"kind": "x"}})
        it = plan_item(1, state=ws.NEEDS_STRONGER_MODEL, evidence={"packet": packet["id"]})
        seen = {}

        def think(system, text, *, context=None, policy=None, **kw):
            seen.update(context=context, policy=policy)
            return reasoning_gateway.GatewayResult({"diagnosis": "upgrade the one vulnerable package",
                                                    "plan": ["bump it"], "files": [], "bounded": True},
                                                   "claude", "critical")
        with self.frontier(True), runners.session_scope({"id": "s"}), \
                mock.patch.object(reasoning_gateway, "reason_json", side_effect=think):
            out = runners.run(it, NOW)
        self.assertEqual(seen["policy"], "critical")
        self.assertIn("Production dependency audit", seen["context"]["untrusted_packet"])
        self.assertEqual(out["state"], ws.BLOCKED_USER)
        self.assertEqual(inv.load_packet("packet-abc")["frontier_read"]["provider"], "claude")


class RedCIOnACharterBranch(Isolated):
    def test_the_latest_red_run_per_workflow_with_its_failed_steps(self):
        def get(path):
            if "/jobs" in path:
                return {"jobs": [{"name": "Typecheck and tests", "conclusion": "failure",
                                  "steps": [{"name": "Production dependency audit", "conclusion": "failure"}]},
                                 {"name": "Layout", "conclusion": "success", "steps": []}]}
            return {"workflow_runs": [
                {"id": 3, "name": "Barkly CI", "path": "ci.yml", "status": "completed", "conclusion": "failure",
                 "head_sha": "c" * 40},
                {"id": 2, "name": "Barkly CI", "path": "ci.yml", "status": "completed", "conclusion": "success"},
                {"id": 1, "name": "Build", "path": "build.yml", "status": "completed", "conclusion": "success"}]}
        runs = charter_ci.failing_runs("caleb/Money_Machine", "claude/barkly-x", get=get)
        self.assertEqual([(r["run_id"], r["failed"][0]["steps"]) for r in runs], [(3, ["Production dependency audit"])])

    def test_a_red_run_is_an_item_linked_to_the_step_about_ci(self):
        from aletheia import plans
        cache = {"observed_at": "2026-09-17T11:59:00Z", "failures": [
            {"slug": "barkly", "title": "Barkly", "repo": "caleb/Money_Machine", "branch": "claude/barkly-x",
             "subdir": "barkly", "workflow": "Barkly CI", "workflow_path": ".github/workflows/barkly-ci.yml",
             "run_id": 9, "head_sha": "d" * 40, "failed": [{"job": "t", "steps": ["Production dependency audit"]}]}]}
        charter_ci.cache_path().parent.mkdir(parents=True, exist_ok=True)
        charter_ci.cache_path().write_text(json.dumps(cache), encoding="utf-8")
        with mock.patch.object(plans, "load", return_value=BARKLY):
            items = charter_ci.source(NOW)
        self.assertEqual(items[0]["state"], ws.READY)
        self.assertEqual(items[0]["native_state"], "run:9")
        self.assertEqual(items[0]["payload"]["same_as"], "plan:barkly#1")


class OnePieceOfWorkIsOneItem(unittest.TestCase):
    def test_a_task_filed_for_a_plan_step_is_that_step(self):
        task = we.item("task:light-up-the-wall-s4", "tasks", "Point a ChatGPT scheduled task", ws.READY,
                       native_state="QUEUED", payload={"task": "light-up-the-wall-s4", "goal": "light-up-the-wall",
                                                       "description": "Point a ChatGPT scheduled task"})
        step = we.item("plan:light-up-the-wall#4", "plans", "Light up the wall: Point a ChatGPT scheduled task",
                       ws.READY, native_state="todo",
                       payload={"slug": "light-up-the-wall", "n": 4, "text": "Point a ChatGPT scheduled task"})
        other = we.item("task:other", "tasks", "Something else", ws.READY, payload={"task": "other"})
        linked = we.link([task, step, other])
        self.assertEqual([i["id"] for i in linked], ["plan:light-up-the-wall#4", "task:other"])
        self.assertEqual(linked[0]["aliases"][0]["id"], "task:light-up-the-wall-s4")

    def test_the_merged_item_takes_the_furthest_state(self):
        a = we.item("plan:p#1", "plans", "P: do it", ws.READY, payload={"slug": "p", "n": 1, "text": "do it"})
        b = we.item("task:p-s1", "tasks", "do it", ws.BLOCKED_USER, reason="his", next="when he does",
                    payload={"task": "p-s1", "goal": "p", "description": "do it"})
        merged = we.link([a, b])[0]
        self.assertEqual(merged["state"], ws.BLOCKED_USER)

    def test_a_conversation_for_a_mission_task_is_that_task(self):
        conv = we.item("conversation:conv-1", "conversations", "conversation with x", ws.BLOCKED_EXTERNAL,
                       reason="waiting", next="reply", payload={"same_as": "program:m#t2"})
        task = we.item("program:m#t2", "programs", "M: contact", ws.BLOCKED_EXTERNAL, reason="waiting", next="reply")
        self.assertEqual([i["id"] for i in we.link([conv, task])], ["program:m#t2"])


def fake_source(items):
    return {"fake": lambda now: [dict(i) for i in items]}


class TheSessionDoesNotStopWhileWorkIsExecutable(Isolated):
    def items(self):
        return [we.item(f"task:t{n}", "tasks", f"Thing {n}", ws.READY, native_state="QUEUED",
                        payload={"task": f"t{n}", "description": f"Look up thing {n}"}) for n in range(1, 5)] + [
            we.item("task:his", "tasks", "Sign the lease", ws.BLOCKED_USER, reason="his to sign", next="when he signs",
                    native_state="WAITING_OPERATOR", payload={"task": "his"})]

    def test_it_carries_every_executable_item_then_reports_without_saying_it_cannot_work(self):
        store = {"items": self.items(), "done": set()}

        def source(now):
            return [dict(i, state=ws.DONE) if i["id"] in store["done"] else dict(i) for i in store["items"]]

        def runner(it, now, mode):
            store["done"].add(it["id"])
            return {"state": ws.DONE, "kind": "completed", "did": f"did {it['title']}"}
        minds = {"frontier": {"ok": False, "why": "switched off"}, "local": {"ok": True, "why": "qwen"}}
        with mock.patch.dict(we.SOURCES, {"fake": source}, clear=True), \
                mock.patch.dict(we.SOURCE_RUNNERS, {"tasks": lambda it, now: {}}, clear=True), \
                mock.patch.object(project_work, "_frontier", return_value=minds), \
                mock.patch.object(runners, "_frontier_ok", return_value=False), \
                mock.patch.object(charter_ci, "refresh"), \
                mock.patch("aletheia.notifications.publish"):
            # the session runs on the real clock: a fixed NOW here would be a deadline already past
            began = project_work.start(via="test", words="work on my projects", inline=True, runner=runner)
        record = project_work.load(began["session"]["id"])
        self.assertIn("I can take 4 things right now", began["said"])
        self.assertIn("Claude and Codex are out", began["said"])
        self.assertEqual(len(record["receipts"]), 4)
        self.assertEqual(record["stopped"]["why"], "nothing_left")
        self.assertEqual(record["stopped"]["executable_left"], [])          # proof: nothing runnable was left
        self.assertIn("I finished 4", record["report"])
        self.assertIn("on you", record["report"])
        for words in (began["said"], record["report"]):
            self.assertNotRegex(words.lower(), r"can'?t work|cannot work|unable to work|nothing i can do")

    def test_opening_words_never_say_it_cannot_work_while_anything_is_executable(self):
        base = {"can_now": [{"id": "a", "title": "Barkly: fix it", "mode": "run", "route": "change"}],
                "waiting": [{"id": "w", "title": "x", "state": ws.NEEDS_STRONGER_MODEL}], "left_to_others": []}
        for frontier in (True, False):
            for local in (True, False):
                said = project_work.opening_words({**base, "frontier": {"ok": frontier}, "local": {"ok": local}})
                self.assertTrue(said.startswith("On it."), said)
                self.assertNotRegex(said.lower(), r"can'?t work|cannot work|nothing (?:for me|i can)")

    def test_with_nothing_executable_it_says_what_would_move_the_work(self):
        said = project_work.opening_words({"can_now": [], "left_to_others": [], "frontier": {"ok": False},
                                           "local": {"ok": True},
                                           "waiting": [{"id": "w", "title": "x", "state": ws.BLOCKED_USER}]})
        self.assertIn("waiting", said)
        self.assertIn("on you", said)

    def test_the_report_names_what_was_queued_for_a_stronger_model_and_why(self):
        record = {"started_at": "2026-09-17T12:00:00Z", "finished_at": "2026-09-17T12:24:00Z",
                  "receipts": [{"id": "plan:barkly#1", "title": "Barkly: Get Barkly CI green on the project branch",
                                "kind": "investigated", "state": ws.NEEDS_STRONGER_MODEL,
                                "reason": "its checks run under Node (package.json), which the local repair tier does not run",
                                "did": "investigated it"},
                               {"id": "plan:o#1", "title": "Open Range: Write a one-page status", "kind": "drafted",
                                "state": ws.BLOCKED_USER, "did": "drafted handoff/STATUS.md on local branch thea-work/x"}],
                  "stopped": {"why": "nothing_left"},
                  "after": {"waiting": [{"id": "plan:barkly#2", "title": "Barkly: Turn on GitHub Pages",
                                         "state": ws.BLOCKED_USER}], "can_now": []}}
        said = project_work.report_words(record)
        self.assertIn("I worked on your projects for 24 minutes.", said)
        self.assertIn("I finished 1: write a one-page status in Open Range", said)
        self.assertIn("a draft of", said)
        self.assertIn("queued it for Claude or Codex with the evidence", said)
        self.assertIn("because its checks run under Node", said)
        self.assertIn("What I need from you: turn on GitHub Pages in Barkly", said)
        self.assertNotIn("_", said.replace("handoff/STATUS.md", "").replace("thea-work/x", ""))

    def test_work_a_stronger_model_read_is_not_said_as_handed_to_him_and_every_item_is_counted(self):
        receipts = [{"id": f"plan:p#{n}", "title": f"P: step number {n}", "kind": "frontier",
                     "state": ws.BLOCKED_USER, "did": "handed"} for n in range(1, 6)]
        said = project_work.report_words({"started_at": "2026-09-17T12:00:00Z", "finished_at": "2026-09-17T12:02:00Z",
                                          "rehearsal": True, "receipts": receipts, "stopped": {"why": "nothing_left"},
                                          "after": {"waiting": [dict(r, title=r["title"]) for r in receipts],
                                                    "can_now": []}})
        self.assertIn("Claude or Codex read the evidence I'd gathered for 5", said)
        self.assertIn("and 1 more", said)
        self.assertNotIn("handed 5 to you", said)
        self.assertNotIn("What I need from you", said)

    def test_a_halt_stops_the_loop(self):
        calls = []
        items = self.items()
        with mock.patch.dict(we.SOURCES, {"fake": lambda now: [dict(i) for i in items]}, clear=True), \
                mock.patch.dict(we.SOURCE_RUNNERS, {"tasks": lambda it, now: {}}, clear=True), \
                mock.patch.object(project_work, "_frontier", return_value={"frontier": {"ok": False, "why": ""},
                                                                           "local": {"ok": True, "why": ""}}), \
                mock.patch.object(runners, "_frontier_ok", return_value=False), \
                mock.patch.object(charter_ci, "refresh"), mock.patch("aletheia.notifications.publish"), \
                mock.patch.object(policy, "halted", side_effect=[None, None, {"reason": "stop"}, {"reason": "stop"},
                                                                  {"reason": "stop"}, {"reason": "stop"}]):
            began = project_work.start(via="test", inline=True,
                                       runner=lambda it, now, mode: calls.append(it["id"]) or {"state": ws.DONE,
                                                                                                "kind": "completed"})
        record = project_work.load(began["session"]["id"])
        self.assertEqual(record["stopped"]["why"], "halted")
        self.assertEqual(len(calls), 1)

    def test_the_beat_skips_a_noop_without_spending_a_slot(self):
        a = we.item("task:a", "tasks", "a", ws.READY, native_state="QUEUED")
        b = we.item("task:b", "tasks", "b", ws.READY, native_state="QUEUED")
        seen = []

        def runner(it, now):
            seen.append(it["id"])
            return {"noop": True} if it["id"] == "task:a" else {"state": ws.BLOCKED_USER, "reason": "his", "next": "x"}
        with mock.patch.dict(we.SOURCE_RUNNERS, {"tasks": runner}, clear=True), \
                mock.patch("aletheia.waits.reconcile", return_value=[]), \
                mock.patch("aletheia.work_gaps.file_from_demand", return_value=[]):
            out = we.reconcile(NOW, probe=False, max_runs=1,
                               sources={"tasks": lambda now: [dict(a), dict(b)]})
        self.assertEqual(seen, ["task:a", "task:b"])
        self.assertEqual([r["id"] for r in out["ran"]], ["task:b"])
        self.assertEqual(we.load_store()["items"]["task:b"]["state"], ws.BLOCKED_USER)


class TheScreenShowsTheSession(Isolated):
    def test_a_card_with_running_done_and_waiting_and_ribbon_sentences(self):
        from aletheia import mission_work
        session = {"id": "work-1", "state": "RUNNING", "started_at": "2026-09-17T12:00:00Z", "rehearsal": True,
                   "running": {"title": "Barkly: Fix the useBarkly.goTo() mismatch", "since": "2026-09-17T12:05:00Z"},
                   "done": [{"id": "plan:o#1", "title": "Open Range: status", "kind": "drafted", "state": ws.BLOCKED_USER,
                             "did": "drafted handoff/STATUS.md on local branch thea-work/x", "at": "2026-09-17T12:04:00Z"}],
                   "waiting": [{"id": "plan:b#2", "title": "Barkly: Turn on Pages", "state": ws.BLOCKED_USER,
                                "reason": "this step is Caleb's", "next": "when he replies done"}]}
        built = mission_work.build({"summary": {"readable": False}, "session": {"readable": True, "session": session}},
                                   {"now": NOW})
        card = built["missions"][0]
        self.assertEqual((card["id"], card["status"]), ("work:session", "RUNNING"))
        self.assertIn("Fix the useBarkly", card["step"])
        self.assertTrue(any("Turn on Pages" in n["said"] for n in card["needs"]))
        said = [line["said"] for line in built["activity"]]
        self.assertIn("Drafted handoff/STATUS.md on local branch thea-work/x.", said)
        self.assertTrue(any(s.startswith("Working on Barkly") for s in said))


class APullRequestIsNotABranch(unittest.TestCase):
    """Measured live on 2026-09-18 (acceptance A, plan:open-range-promo#1).

    She drafted the file, opened a real pull request on Money_Machine under his
    code-work grant, and told the room "a draft of handoff/STATUS.md is on a
    branch for you to read". The one thing that left the machine was the one
    thing the sentence hid.
    """

    def test_a_published_draft_says_pull_request_and_a_local_one_says_branch(self):
        published = {"kind": "drafted", "title": "Open Range demo films: Write a status",
                     "evidence": {"file": "handoff/STATUS.md", "branch": "thea-work/x",
                                  "pr_url": "https://github.com/x/y/pull/11"}}
        local = {"kind": "drafted", "title": "Open Range demo films: Write a status",
                 "evidence": {"file": "handoff/STATUS.md", "branch": "thea-work/x"}}
        said = project_work._finished_words(published)
        self.assertIn("pull request", said)
        self.assertNotIn("github.com", said)
        self.assertIn("on a branch", project_work._finished_words(local))

    def test_a_published_repair_says_so_too(self):
        said = project_work._finished_words(
            {"kind": "repaired", "title": "Barkly: CI", "evidence": {"pr_url": "https://github.com/x/y/pull/12"}})
        self.assertIn("pull request", said)


class TheEvidenceContainsTheThingItIsAbout(unittest.TestCase):
    """Measured live on 2026-09-18 (acceptance A, plan:barkly#3).

    The packet that went to the stronger model carried an import block and an
    interface from a 2,200-line hook, and neither of the two lines the work
    item names. A packet whose evidence does not contain the thing it is
    about makes the frontier model rediscover what she already had.
    """

    def test_the_lines_that_show_the_behaviour_travel_not_the_import_block(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        lines = ["import { areaUnlocked } from '../game/progression';"]
        lines += [f"  // filler {n}" for n in range(60)]
        lines += ["  const canGo = (area: string) => areaUnlocked(area, xp, devRef.current);"]
        lines += [f"  // more filler {n}" for n in range(400)]
        lines += ["  const goTo = (loc: LocationId) => { if (!canGo(loc)) return; };"]
        (root / "useBarkly.ts").write_text("\n".join(lines), encoding="utf-8")

        found = runners.locate(root, "Fix the useBarkly.goTo() dev-flag mismatch "
                                     "(pass devRef.current to areaUnlocked)")
        text = "\n".join(slice_["text"] for slice_ in found["code"])
        self.assertIn("useBarkly.ts", found["files"])
        self.assertIn("const canGo", text)
        self.assertIn("const goTo", text)

    def test_an_import_only_line_ranks_below_the_definition(self):
        # weights: 3 exact, 2 exact-but-import, 1 loose
        self.assertEqual(runners.best_lines({0: 2, 500: 3}), [500, 0])

    def test_two_lines_from_one_neighbourhood_are_one_piece_of_evidence(self):
        self.assertEqual(runners.best_lines({10: 3, 12: 3, 90: 3}), [10, 90])


if __name__ == "__main__":
    unittest.main()
