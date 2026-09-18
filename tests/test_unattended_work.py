"""What she does without asking: the budget, the kill switch, the ledger, the undo.

His continuity brief, Part III item 10, gives her reversible local work without
an approval. Everything here is the price of that:

- a BUDGET, so a loop cannot churn (the failure mode "reversible" invites);
- the KILL SWITCH checked before EVERY action rather than once per session,
  because a session outlives the moment he says stop;
- a LEDGER with an undo, so "I did it without asking" is always followed by
  "and here is how to take it back";
- a refusal to undo anything that was HIS - a decision, an approval, or
  anything that reached the world.
"""
from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import agent_session as s
from aletheia import autonomy, tools


class Ledgered(unittest.TestCase):
    """Each test gets its own ledger: a budget test that counted another
    test's rows would pass or fail on the order they ran in."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="c4b-ledger-")
        self.addCleanup(self.tmp.cleanup)
        patch = mock.patch.object(autonomy, "ledger_dir", lambda: Path(self.tmp.name))
        patch.start()
        self.addCleanup(patch.stop)
        # `tasks` binds a REPO-anchored path at import time, so a test that
        # forgets this writes a task into his repository. One did, while this
        # file was being written.
        from aletheia import tasks
        here = mock.patch.object(tasks, "TASKS_DIR", Path(self.tmp.name) / "tasks")
        here.start()
        self.addCleanup(here.stop)
        # The workspace is chosen by environment, and its whole promise is that
        # she cannot write outside it.
        env = mock.patch.dict("os.environ", {"ALETHEIA_WORKSPACE": str(Path(self.tmp.name) / "work")})
        env.start()
        self.addCleanup(env.stop)
        # AND THE APPROVALS. A test here drives the live question route, which
        # files a real pending approval; left in the suite's shared store it
        # made `test_current_state_v2` say NEEDS YOU where it expected IDLE and
        # `test_quick` answer a different question - two failures in modules
        # that have nothing to do with this one, and only in some orders.
        from aletheia import policy
        approvals = mock.patch.object(policy, "APPROVALS_DIR", Path(self.tmp.name) / "approvals")
        approvals.start()
        self.addCleanup(approvals.stop)
        self.catalog = tools.catalog()


class TheBudgetStopsALoop(Ledgered):
    def test_a_session_runs_out_and_the_rest_waits_for_him(self):
        tool = self.catalog["note"]
        for _ in range(autonomy.SESSION_LIMIT):
            autonomy.record(tool="note", args={"text": "x"}, consequence=tool.consequence,
                            session="agent-1", said="noted")
        ok, why = autonomy.allow(tool, session="agent-1", halted=lambda: False)
        self.assertFalse(ok)
        self.assertIn("this session", why)
        # ANOTHER session still works: the session cap is about looping, not
        # about a day's worth of work.
        ok, _why = autonomy.allow(tool, session="agent-2", halted=lambda: False)
        self.assertTrue(ok)

    def test_a_day_runs_out_for_every_session(self):
        tool = self.catalog["note"]
        for n in range(autonomy.DAY_LIMIT):
            autonomy.record(tool="note", args={"text": "x"}, consequence=tool.consequence,
                            session=f"agent-{n}", said="noted")
        ok, why = autonomy.allow(tool, session="agent-new", halted=lambda: False)
        self.assertFalse(ok)
        self.assertIn("today", why)

    def test_past_the_budget_the_broker_hands_off_rather_than_running(self):
        for _ in range(autonomy.SESSION_LIMIT):
            autonomy.record(tool="note", args={"text": "x"}, consequence=tools.VISIBLE_TO_HIM,
                            session="agent-full", said="noted")
        broker = s.Broker(self.catalog, audience="all", halted=lambda: False, session="agent-full")
        decision = broker.check(s.ToolRequest("note", {"text": "one more"}))
        self.assertEqual(decision.verdict, s.HANDOFF)
        self.assertIn("reversible", decision.reason)

    def test_an_outward_tool_is_never_a_budget_question(self):
        ok, why = autonomy.allow(self.catalog["thread_send"], session="agent-1", halted=lambda: False)
        self.assertFalse(ok)
        self.assertIn("consequence", why)


class TheKillSwitchIsCheckedBeforeEachAction(Ledgered):
    def test_halted_refuses_before_the_budget_is_even_read(self):
        with mock.patch.object(autonomy, "counts", side_effect=AssertionError("must not be reached")):
            ok, why = autonomy.allow(self.catalog["note"], session="agent-1", halted=lambda: True)
        self.assertFalse(ok)
        self.assertIn("halted", why)

    def test_an_unreadable_switch_counts_as_halted(self):
        def boom():
            raise OSError("the halt file is unreadable")
        ok, why = autonomy.allow(self.catalog["note"], session="agent-1", halted=boom)
        self.assertFalse(ok)
        self.assertIn("halted", why)

    def test_the_switch_thrown_MID_SESSION_stops_the_next_action(self):
        """The whole point of checking per action: two reversible steps, and he
        says stop between them."""
        switch = {"on": False}
        broker = s.Broker(self.catalog, audience="all", halted=lambda: switch["on"],
                          session="agent-mid")
        self.assertEqual(broker.check(s.ToolRequest("note", {"text": "first"})).verdict, s.RUN)
        switch["on"] = True
        self.assertEqual(broker.check(s.ToolRequest("note", {"text": "second"})).verdict, s.REFUSED)


class EveryUnattendedActionSaysHowToUndoIt(Ledgered):
    def test_the_plan_names_the_thing_it_made(self):
        cases = [
            ("task_new", {"id": "t-99", "description": "call back"}, autonomy.TASK_CANCEL, "task", "t-99"),
            ("remember", {"domain": "people", "key": "landlord", "value": "Dana"},
             autonomy.MEMORY_FORGET, "key", "landlord"),
            ("file_write", {"path": "notes/x.md", "text": "hi"}, autonomy.FILE_VERSION,
             "path", "notes/x.md"),
        ]
        for name, args, how, field, value in cases:
            with self.subTest(tool=name):
                plan = autonomy.undo_plan(self.catalog[name], args, None)
                self.assertEqual(plan["how"], how)
                self.assertEqual(plan[field], value)

    def test_where_there_is_no_undo_it_says_so_rather_than_saying_nothing(self):
        plan = autonomy.undo_plan(self.catalog["note"], {"text": "x"}, None)
        self.assertEqual(plan["how"], autonomy.NONE)
        self.assertIn("append-only", plan["why"])

    def test_every_tool_that_can_run_unattended_has_a_plan(self):
        for name, tool in self.catalog.items():
            if not tools.runs_unattended(tool) or tool.read_only:
                continue
            with self.subTest(tool=name):
                args = {k: "x" for k in tool.input_schema.get("required") or []}
                plan = autonomy.undo_plan(tool, args, None)
                self.assertIn(plan["how"], autonomy.HOWS, name)
                if plan["how"] == autonomy.NONE:
                    self.assertTrue(plan.get("why"), f"{name} has no undo and does not say why")


class SheUndoesHerOwnAndOnlyHerOwn(Ledgered):
    def test_a_task_she_added_is_cancelled(self):
        from aletheia import tasks
        tasks.create("t-undo-1", "a task she added by herself")
        entry = autonomy.record(tool="task_new", args={"id": "t-undo-1", "description": "x"},
                                consequence=tools.REVERSIBLE_LOCAL, session="agent-1",
                                said="added a task", undo={"how": autonomy.TASK_CANCEL, "task": "t-undo-1"})
        out = autonomy.undo(entry["id"])
        self.assertTrue(out["undone"])
        self.assertEqual(tasks.load("t-undo-1")["status"], "CANCELLED")
        self.assertIn("cancelled", out["said"])

    def test_undoing_twice_is_not_an_error_and_not_a_second_undo(self):
        from aletheia import tasks
        tasks.create("t-undo-2", "another")
        entry = autonomy.record(tool="task_new", args={"id": "t-undo-2"},
                                consequence=tools.REVERSIBLE_LOCAL, session="agent-1", said="added",
                                undo={"how": autonomy.TASK_CANCEL, "task": "t-undo-2"})
        autonomy.undo(entry["id"])
        again = autonomy.undo(entry["id"])
        self.assertFalse(again["undone"])
        self.assertIn("already", again["said"])

    def test_she_does_not_undo_something_outward(self):
        entry = autonomy.record(tool="thread_send", args={}, consequence=tools.OUTWARD,
                                session="agent-1", said="sent it", undo={"how": autonomy.NONE})
        with self.assertRaises(autonomy.UndoRefused) as caught:
            autonomy.undo(entry["id"])
        self.assertIn("reached the world", str(caught.exception))

    def test_she_does_not_undo_HIS_decision(self):
        entry = autonomy.record(tool="study_decide", args={}, consequence=tools.REVERSIBLE_LOCAL,
                                session="agent-1", said="he accepted the hypothesis",
                                undo={"how": autonomy.TASK_CANCEL, "task": "t-x"})
        day, row = autonomy.load(entry["id"])
        row["decided_by"] = "caleb"
        autonomy._write_day(day, [row])
        with self.assertRaises(autonomy.UndoRefused) as caught:
            autonomy.undo(entry["id"])
        self.assertIn("your decision", str(caught.exception))

    def test_an_id_she_never_wrote_is_not_undoable(self):
        with self.assertRaises(KeyError):
            autonomy.undo("un-somebody-elses")

    def test_a_file_she_wrote_is_taken_back(self):
        from aletheia import workspace
        workspace.write("c4b/undo-me.md", "the first version", why="test")
        workspace.write("c4b/undo-me.md", "what she wrote without asking", why="test")
        entry = autonomy.record(tool="file_write", args={"path": "c4b/undo-me.md"},
                                consequence=tools.REVERSIBLE_LOCAL, session="agent-1",
                                said="wrote it", undo={"how": autonomy.FILE_VERSION,
                                                       "path": "c4b/undo-me.md"})
        out = autonomy.undo(entry["id"])
        self.assertTrue(out["undone"])
        self.assertEqual(workspace.read("c4b/undo-me.md")["text"], "the first version")

    def test_a_branch_she_prepared_is_thrown_away(self):
        with tempfile.TemporaryDirectory(prefix="c4b-repo-") as folder:
            root = Path(folder)
            (root / "a.txt").write_text("x", encoding="utf-8")
            # `investigation.git` refuses `init` by design, so the fixture
            # builds the repository with plain git and the UNDO uses hers.
            run = ["git", "-C", str(root)]
            subprocess.run(run + ["init", "-b", "main"], check=True, capture_output=True)
            subprocess.run(run + ["add", "-A"], check=True, capture_output=True)
            subprocess.run(run + ["-c", "user.email=t@t", "-c", "user.name=t",
                                  "commit", "-m", "first"], check=True, capture_output=True)
            subprocess.run(run + ["switch", "-c", "thea-repair/x"], check=True, capture_output=True)
            entry = autonomy.record(tool="local_repair.branch", args={"branch": "thea-repair/x"},
                                    consequence=tools.REVERSIBLE_LOCAL, session="work-1",
                                    said="prepared a repair on a branch; nothing was pushed",
                                    undo=autonomy.branch_undo(path=str(root), branch="thea-repair/x"))
            out = autonomy.undo(entry["id"])
        self.assertTrue(out["undone"])
        self.assertIn("threw away", out["said"])


class WhatSheSaysAboutIt(Ledgered):
    def test_the_wording_says_reversible_and_local(self):
        autonomy.record(tool="task_new", args={"id": "t1"}, consequence=tools.REVERSIBLE_LOCAL,
                        session="agent-1", said="added a task to call the landlord back",
                        undo={"how": autonomy.TASK_CANCEL, "task": "t1"})
        said = autonomy.spoken()
        self.assertIn("reversible", said)
        self.assertIn("this machine", said)
        self.assertIn("nothing was sent", said)
        self.assertIn("call the landlord back", said)

    def test_it_is_sayable_out_loud(self):
        """No identifier, no state code, no markdown: it is read in a room.

        The first version put `say undo un-3af32fc6a8a4 and I will take it
        back` in the sentence, which is not something a person can say back."""
        from aletheia import speech
        autonomy.record(tool="note", args={"text": "x"}, consequence=tools.VISIBLE_TO_HIM,
                        session="agent-1", said="noted what he said about the tour")
        autonomy.record(tool="task_new", args={"id": "t1"}, consequence=tools.REVERSIBLE_LOCAL,
                        session="agent-1", said="added a task to call the landlord back",
                        undo={"how": autonomy.TASK_CANCEL, "task": "t1"})
        said = autonomy.spoken()
        self.assertEqual(said, speech.spoken_prose(said).strip() or said)
        self.assertNotIn("un-", said)
        for jargon in ("reversible_local", "REVERSIBLE", "consequence=", "{"):
            self.assertNotIn(jargon, said)
        self.assertIn("which one to undo", said)

    def test_a_long_list_is_cut_and_the_count_still_matches(self):
        for n in range(7):
            autonomy.record(tool="note", args={"text": "x"}, consequence=tools.VISIBLE_TO_HIM,
                            session="agent-1", said=f"noted thing {n}")
        said = autonomy.spoken()
        self.assertIn("7 things", said)
        self.assertIn("and 4 more", said)

    def test_an_empty_ledger_proves_the_ledger(self):
        said = autonomy.spoken()
        self.assertIn("Nothing in the last", said)
        self.assertIn("waiting for your yes", said)

    def test_the_summary_carries_the_undo_command(self):
        entry = autonomy.record(tool="task_new", args={"id": "t1"}, consequence=tools.REVERSIBLE_LOCAL,
                                session="agent-1", said="added a task",
                                undo={"how": autonomy.TASK_CANCEL, "task": "t1"})
        block = autonomy.summary()
        self.assertTrue(block["readable"])
        self.assertEqual(block["actions"][0]["id"], entry["id"])
        self.assertIn(f"aletheia.autonomy undo {entry['id']}", block["actions"][0]["undo"])
        self.assertEqual(block["budget"]["day_limit"], autonomy.DAY_LIMIT)

    def test_something_with_no_undo_says_why_rather_than_offering_one(self):
        autonomy.record(tool="note", args={"text": "x"}, consequence=tools.VISIBLE_TO_HIM,
                        session="agent-1", said="noted it",
                        undo={"how": autonomy.NONE, "why": "my journal is append-only"})
        row = autonomy.summary()["actions"][0]
        self.assertEqual(row["undo"], "")
        self.assertIn("append-only", row["why_not_undoable"])


class TheWorkSessionSaysWhatItDidWithoutAsking(Ledgered):
    def test_the_report_names_it_and_offers_the_undo(self):
        from aletheia import project_work
        entry = autonomy.record(tool="local_repair.branch", args={"branch": "thea-repair/x"},
                                consequence=tools.REVERSIBLE_LOCAL, session="work-1",
                                said="prepared a verified repair on the branch thea-repair/x, in a "
                                     "throwaway copy of barkly; nothing was pushed",
                                undo=autonomy.branch_undo(path="/tmp/x", branch="thea-repair/x"))
        record = {"receipts": [{"title": "fix the goTo mismatch", "kind": "repaired",
                                "evidence": {"unattended": [entry["id"]]}}]}
        said = project_work.unattended_words(record)
        self.assertIn("without asking", said)
        self.assertIn("reversible", said)
        self.assertIn("this machine", said)
        self.assertIn("thea-repair/x", said)

    def test_a_session_that_did_nothing_unattended_says_nothing(self):
        from aletheia import project_work
        self.assertEqual(project_work.unattended_words({"receipts": [{"title": "x", "evidence": {}}]}), "")


class TheSurfacesShowIt(Ledgered):
    def test_current_state_carries_the_section(self):
        from aletheia import current_state
        autonomy.record(tool="task_new", args={"id": "t1"}, consequence=tools.REVERSIBLE_LOCAL,
                        session="agent-1", said="added a task",
                        undo={"how": autonomy.TASK_CANCEL, "task": "t1"})
        block = current_state.unattended()
        self.assertTrue(block["readable"])
        self.assertEqual(block["count"], 1)
        self.assertIn("reversible", block["said"])

    def test_mission_control_carries_it_too(self):
        from aletheia import current_state, mission_control
        autonomy.record(tool="task_new", args={"id": "t1"}, consequence=tools.REVERSIBLE_LOCAL,
                        session="agent-1", said="added a task",
                        undo={"how": autonomy.TASK_CANCEL, "task": "t1"})
        current_state.forget_cache()
        mission_control.forget_cache()
        value = mission_control.gather(fresh=True, providers={})
        self.assertIn("unattended", value)
        self.assertTrue(value["unattended"]["readable"])
        self.assertEqual(value["unattended"]["actions"][0]["tool"], "task_new")

    def test_the_tool_a_session_reads_it_with(self):
        from aletheia import state_tools
        autonomy.record(tool="note", args={"text": "x"}, consequence=tools.VISIBLE_TO_HIM,
                        session="agent-1", said="noted it")
        out = state_tools.unattended_query({"hours": 24})
        self.assertTrue(out["readable"])
        self.assertEqual(len(out["actions"]), 1)

    def test_an_empty_store_still_proves_the_store(self):
        from aletheia import state_tools
        out = state_tools.unattended_query({"hours": 24})
        self.assertTrue(out["readable"])
        self.assertEqual(out["actions"], [])
        self.assertIn("I do keep this record", out["note"])

    def test_what_did_you_do_without_asking_me_reaches_a_session(self):
        from aletheia import investigate
        for said in ("what did you do without asking me",
                     "did you change anything without telling me",
                     "what have you done on your own today",
                     "what did you do unattended"):
            with self.subTest(said=said):
                self.assertTrue(investigate.wants_session(said), said)
        # and an ordinary question about the world still does not
        self.assertFalse(investigate.wants_session("why is the sky blue"))


class NothingHereCanWidenItself(unittest.TestCase):
    """The rules that are not allowed to have an exception, checked against the
    SOURCE rather than against behaviour: a behaviour test passes for a module
    that grew a flag nobody noticed."""

    def code(self):
        """The module's CODE, with the docstrings taken out - a rule about what
        it may reach must not be tripped by a sentence describing the rule."""
        import ast
        from pathlib import Path as P
        import aletheia.autonomy as module
        tree = ast.parse(P(module.__file__).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                body = node.body
                if (body and isinstance(body[0], ast.Expr)
                        and isinstance(body[0].value, ast.Constant)
                        and isinstance(body[0].value.value, str)):
                    body[0].value.value = ""
        return ast.unparse(tree)

    def test_it_never_touches_authority_or_grants(self):
        text = self.code()
        for forbidden in ("import authority", "authority.", "policy.resume", "policy.halt(",
                          "front_door", "delegable", "satisfy("):
            self.assertNotIn(forbidden, text, f"autonomy.py must not reach {forbidden}")

    def test_it_never_decides_an_approval(self):
        text = self.code()
        for forbidden in ("policy.decide", "APPROVED", "handoffs.run_approved"):
            self.assertNotIn(forbidden, text)

    def test_the_caps_are_constants_and_not_read_from_anywhere(self):
        """A budget an environment variable can raise is not a budget."""
        text = self.code()
        self.assertIn("SESSION_LIMIT = ", text)
        self.assertIn("DAY_LIMIT = ", text)
        self.assertNotIn("os.environ", text)

    def test_spending_is_never_a_question_for_this_module(self):
        """It cannot allow a spending action, and it has no word for money."""
        from aletheia import tools
        catalog = tools.catalog()
        for kind in ("web_task", "subscription_cancel", "web_task_retry"):
            with self.subTest(kind=kind):
                ok, _why = autonomy.allow(catalog[kind], session="x", halted=lambda: False)
                self.assertFalse(ok)


class AQuestionIsNeverAnInstruction(Ledgered):
    """The live route for a QUESTION about her work turns unattended work off.

    It is the one place where "reversible" is not the whole argument: he asked
    what happened, not for something to happen, and a session that answers a
    question by adding a task has answered a different question - the failure
    he cannot detect."""

    def test_the_question_route_hands_off_what_it_would_otherwise_run(self):
        from aletheia import investigate

        def think(system, text):
            if "HANDOFF" in text or "OBSERVATION" in text:
                return {"answer": "Nothing has been written down about it."}, "fake:model"
            return {"tool": "note", "args": {"text": "he asked about the tour"}}, "fake:model"

        record = investigate.propose("why hasn't the landlord replied yet", think=think,
                                     report=lambda _line: None)
        self.assertIsNotNone(record)
        self.assertEqual(autonomy.recent(), [])

    def test_and_the_ordinary_session_still_runs_it(self):
        def think(system, text):
            if "OBSERVATION" in text:
                return {"answer": "noted"}, "fake:model"
            return {"tool": "note", "args": {"text": "he asked about the tour"}}, "fake:model"
        result = s.AgentSession("note that he asked about the tour", think=think, record=False,
                                audience="local", max_steps=2).run()
        self.assertEqual(result.receipts[0]["verdict"], s.RUN)
        self.assertEqual(len(autonomy.recent()), 1)


class TheSessionWritesItDown(Ledgered):
    def test_a_session_that_notes_something_leaves_a_ledger_line(self):
        def think(system, text):
            if "OBSERVATION" in text or "noted" in text:
                return {"answer": "I noted it. I can take that back if you want."}, "fake:model"
            return {"tool": "note", "args": {"text": "he mentioned the tour on Friday"}}, "fake:model"
        session = s.AgentSession("note that I mentioned the tour", think=think, record=False,
                                 audience="local", max_steps=2)
        result = session.run()
        self.assertEqual(result.receipts[0]["verdict"], s.RUN)
        self.assertEqual(len(result.unattended), 1)
        self.assertTrue(result.unattended[0]["recorded"])
        rows = autonomy.recent(session=session.result.id)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["tool"], "note")
        self.assertIn("did without asking", s.render(result))


if __name__ == "__main__":
    unittest.main()
