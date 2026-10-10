"""His mission, rehearsed whole against the real tool catalog.

2026-10-09 and 2026-10-10 each fixed one reason a Project Reboot task would
not move, and each fix was found by waiting a day for his PC to run it. This
runs a mission shaped like his - the same tasks, the same kinds of step -
through the real composer, the real gates and the real catalog, with only the
tools' effects and the model stubbed, and holds every task to one rule: it
finishes, or it waits for something only he can give (money, a send, a sign-up
he has not switched on). It never waits for his yes to LOOK at something, for
an argument an earlier step already found, or on a path or a source of its own.
"""
from __future__ import annotations

import re
import tempfile
from unittest import mock

from aletheia import agent_session, program_compose, program_run, tools
from aletheia import programs as pg
from aletheia import work_states as ws
from tests.test_programs import NOW, Sandbox

EVENT = "Sioux Falls Fall Job Fair - Thursday 2026-10-15 at 18:00, free, Sioux Falls Convention Center"


def _task(key, title, does, uses=(), needs=(), detail=""):
    return {"key": key, "workstream": "w1", "title": title, "detail": detail, "does": list(does),
            "uses": list(uses), "needs": list(needs)}


def reboot_draft() -> dict:
    """Shaped like the draft his PC made of Project Reboot (titles from its receipts)."""
    return {
        "title": "Project Reboot", "objective": "A new job, and the life around it",
        "horizon": "until December 31, 2026",
        "questions": [{"ask": "What kind of work do you want next?", "why": "decides the search"}],
        "outcomes": [{"key": "o1", "text": "An accepted offer", "measure": "an offer accepted by 2026-12-31"}],
        "workstreams": [{"key": "w1", "title": "Get a new job", "why": "he asked", "outcomes": ["o1"]}],
        "tasks": [
            _task("t1", "Check the confidentiality of the setup", ["confirm which calendar holds are written to"],
                  ["calendar.propose"]),
            _task("t2", "Search for upcoming job fairs, hiring events, networking events and info sessions",
                  ["search event listings and local sources"], ["web_task"]),
            _task("t3", "Pencil the fitting events onto his calendar as tentative holds", ["add tentative holds"],
                  ["calendar.hold"], ["t2"]),
            _task("t4", "Save Caleb's answers as job-hunt preferences",
                  ["write his answers down as job-hunt preferences"], ["file_write"]),
            _task("t5", "Write the move criteria from Caleb's answers",
                  ["write the move criteria from his answers"], ["compose"]),
            _task("t6", "Compare a shortlist of warm red-state cities",
                  ["compare warm red-state cities on cost of living, taxes, housing and jobs"], [], ["t5"]),
            _task("t7", "Find free relocation or newcomer events in the shortlisted cities",
                  ["search for free newcomer events in the shortlisted cities"], ["web_task"], ["t6"]),
        ],
        "activities": [
            {"key": "a1", "workstream": "w1", "title": "Weekly sweep for new job-search events",
             "does": ["search for newly listed events"], "uses": ["web_task"],
             "cadence": {"every": "week", "at": "07:30"}, "watch": True},
            {"key": "a2", "workstream": "w1", "title": "Watch shortlisted cities for roles and cost changes",
             "does": ["look for new matching postings in shortlisted cities"], "uses": ["web_task"],
             "cadence": {"every": "week", "at": "08:00"}, "watch": True},
        ],
        "decisions": [],
    }


def think(system, text, *, context=None, validator=None, **_):
    """The model: drafts the mission, and fills an argument only from what is in front of it."""
    if system is not program_compose.ARGS_SYSTEM:
        value = reboot_draft()
        return validator(value) if validator else value
    seen = " ".join(str(x) for x in (context or {}).get("found_by_earlier_steps") or [])
    got = {}
    for key in (context or {}).get("arguments_needed") or {}:
        if key == "start":
            when = re.search(r"\d{4}-\d{2}-\d{2} at \d{2}:\d{2}", seen)
            if when:
                got[key] = when.group(0).replace(" at ", "T")
        elif key == "title":
            name = re.search(r"([A-Z][\w ]+Job Fair)", seen)
            if name:
                got[key] = name.group(1)
        elif key in ("text", "what"):
            if "What Caleb has told" in seen:
                got[key] = "His preferences, from what he told the mission."
        elif key in ("question", "query", "topic"):
            got[key] = str((context or {}).get("task", {}).get("title") or text)
    value = {"args": got}
    return validator(value) if validator else value


class HisMissionRunsWithoutHim(Sandbox):

    def setUp(self):
        super().setUp()
        self.catalog = tools.catalog()
        self.ran: list[tuple[str, dict]] = []
        work = tempfile.TemporaryDirectory()
        self.addCleanup(work.cleanup)
        for patcher in (
            mock.patch.object(program_run, "CATALOG", self.catalog),
            mock.patch.object(program_run, "THINK", think),
            mock.patch.dict("os.environ", {"ALETHEIA_WORKSPACE": work.name}),
            mock.patch.object(agent_session, "execute", self._execute),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        record = pg.propose("Project Reboot: help me change my life", via="operator-voice", now=NOW)
        program_run.do_shape(record["id"], now=NOW)
        pg.answer(record["id"], "Business development, no cold calling, $95K or more", via="operator-voice",
                  now=NOW)
        program_run.do_shape(record["id"], now=NOW)
        self.pid = pg.confirm(record["id"], words="yes confirm it", via="operator-voice", now=NOW)["id"]
        for key in ("a1", "a2"):
            pg.activity_due(self.pid, key, now=NOW)

    def _execute(self, tool, args, **_):
        self.ran.append((tool.name, dict(args)))
        if tool.read_only and tool.open_world:
            return "ok", {"text": EVENT}
        return "ok", {"text": f"{tool.name} done"}

    def _run_everything(self):
        for minute in range(0, 60, 5):
            when = NOW + __import__("datetime").timedelta(minutes=minute)
            program_run.requeue_reclassified(now=when)
            for task in pg.load(self.pid)["tasks"]:
                if task["state"] in (ws.READY, ws.RETRY_LATER):
                    program_run.run_task(self.pid, task["key"], now=when)

    def test_every_task_finishes_or_waits_only_for_what_is_his(self):
        self._run_everything()
        never = re.compile(r"what should I use|approval to (?:search|look|find|check|watch|compare|read)|"
                           r"OutsideWorkspace|ComposeError|spend money|did not work", re.I)
        stuck = [(t["title"], t["state"], t.get("reason"))
                 for t in pg.load(self.pid)["tasks"]
                 if t["state"] != ws.DONE and never.search(str(t.get("reason") or ""))]
        self.assertEqual(stuck, [])
        unfinished = [(t["title"], t["state"], t.get("reason")) for t in pg.load(self.pid)["tasks"]
                      if t["state"] != ws.DONE]
        self.assertEqual(unfinished, [])

    def test_the_holds_take_the_event_the_search_found(self):
        self._run_everything()
        holds = [a for name, a in self.ran if name == "calendar.hold"]
        self.assertTrue(holds, self.ran)
        self.assertEqual((holds[0]["start"], holds[0]["title"]), ("2026-10-15T18:00", "Sioux Falls Fall Job Fair"))

    def test_writing_from_his_answers_reads_his_answers(self):
        self._run_everything()
        composed = [a for name, a in self.ran if name == "compose"]
        self.assertTrue(composed, self.ran)
        self.assertTrue(any(s.endswith("-his-answers.md") for s in composed[0]["sources"]), composed[0])
        written = [a for name, a in self.ran if name == "file_write"]
        self.assertTrue(written and written[0]["path"].startswith("missions/"), written)

    def test_nothing_reached_anybody(self):
        self._run_everything()
        outward = [name for name, _a in self.ran if self.catalog[name].consequence == "outward"]
        self.assertEqual(outward, [])

    def test_tasks_parked_the_way_his_pc_left_them_move_on_the_next_beat(self):
        """His PC, 2026-10-10 15:03Z, after the third fix went live: still four stuck."""
        self._run_everything()
        bad = "C:\\Users\\caleb\\Documents\\Aletheia\\preferences.md"

        def park(record):
            by = {t["title"]: t for t in record["tasks"]}
            watch = by["Watch shortlisted cities for roles and cost changes"]
            watch.update(state=ws.BLOCKED_USER, cursor=0, results=[],
                         plan={"steps": [{"tool": "web_task", "for": "look for new matching postings in "
                                          "shortlisted cities", "by": "named", "score": None}],
                               "requires": [], "gaps": []})
            save = by["Save Caleb's answers as job-hunt preferences"]
            save.update(state=ws.FAILED, cursor=0, attempts=3, results=[],
                        plan={"steps": [{"tool": "file_write", "for": "", "by": "named", "score": None,
                                         "args": {"path": bad, "text": "his answers"}}],
                              "requires": [], "gaps": []},
                        reason="file_write failed 3 times: the tool failed (OutsideWorkspace)")
            crit = by["Write the move criteria from Caleb's answers"]
            crit.update(state=ws.FAILED, cursor=0, attempts=3, results=[],
                        plan={"steps": [{"tool": "compose", "for": "", "by": "named", "score": None,
                                         "args": {"path": "missions/criteria.md", "what": "the move criteria",
                                                  "sources": ["answers.md"]}}],
                              "requires": [], "gaps": []},
                        reason="compose failed 3 times: the tool failed (ComposeError)")
            for t in (watch, save, crit):
                t["updated_at"] = pg.stamp(NOW)
            return record
        pg.update(self.pid, park)
        record = pg.load(self.pid)
        watch = next(t for t in record["tasks"] if t["title"].startswith("Watch shortlisted"))
        pg.hold(record, watch, {"kind": "user_decision", "question": "may I look?"}, reason="needs Caleb's "
                "approval to look for new matching postings in shortlisted cities", purpose="handoff", now=NOW)
        pg.update(self.pid, lambda r: [t.update(watch) for t in r["tasks"] if t["key"] == watch["key"]])
        self.ran.clear()
        self._run_everything()
        left = [(t["title"], t["state"], t.get("reason")) for t in pg.load(self.pid)["tasks"]
                if t["state"] != ws.DONE]
        self.assertEqual(left, [])
        written = [a["path"] for name, a in self.ran if name == "file_write"]
        self.assertTrue(written and written[0].startswith("missions/"), written)
        watch = next(t for t in pg.load(self.pid)["tasks"] if t["title"].startswith("Watch shortlisted"))
        self.assertTrue(all(self.catalog[s["tool"]].read_only for s in watch["plan"]["steps"]), watch["plan"])

    def test_the_steps_view_shows_shapes_and_never_values(self):
        self._run_everything()
        pg.update(self.pid, lambda r: r["tasks"][0].update(
            state=ws.BLOCKED_USER, cursor=0, plan={"steps": [{"tool": "file_write", "args": {"path": "x.md",
                                                                                "text": "555-0100"}}]}))
        said = pg.spoken_steps("Project Reboot")
        self.assertIn("[file_write]", said)
        self.assertIn("args path,text", said)
        self.assertNotIn("555-0100", said)
