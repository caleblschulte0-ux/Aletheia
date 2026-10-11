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
            dict(_task("t5", "Write the move criteria from Caleb's answers",
                       ["write the move criteria from his answers", "ask him to confirm the list"], ["compose"]),
                 then_wait={"for": "reply", "who": "Caleb"}),
            _task("t6", "Compare a shortlist of warm red-state cities",
                  ["compare warm red-state cities on cost of living, taxes, housing and jobs"], [], ["t5"]),
            _task("t7", "Find free relocation or newcomer events in the shortlisted cities",
                  ["search for free newcomer events in the shortlisted cities"], ["web_task"], ["t6"]),
            _task("t8", "Prepare application packets for matching roles",
                  ["find matching postings", "prepare packets", "ask approval before sending"],
                  ["apply_prepare", "apply_campaign"], ["t4"]),
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
        elif key == "role" and "Business development" in seen:
            got[key] = "Business development"
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
        # The one thing left is his: preparing applications keeps its own gate, after the look ran.
        unfinished = [(t["title"], t["state"], t.get("reason")) for t in pg.load(self.pid)["tasks"]
                      if t["state"] != ws.DONE]
        self.assertEqual([u[0] for u in unfinished], ["Prepare application packets for matching roles"])
        self.assertIn("needs Caleb's approval", unfinished[0][2])
        self.assertIn("research", [name for name, _a in self.ran])

    def test_his_okay_of_her_own_work_is_a_choice_not_a_gate(self):
        self._run_everything()
        record = pg.load(self.pid)
        by = {t["key"]: t for t in record["tasks"]}
        self.assertEqual((by["t5"]["state"], by["t6"]["state"], by["t7"]["state"]), (ws.DONE,) * 3)
        confirm = next(d for d in record["decisions"] if d["key"] == "confirm-t5")
        self.assertEqual((confirm["state"], confirm["options"]), ("open", ["Looks right", "Change it"]))

    def test_nothing_dated_found_means_look_again_not_ask_him(self):
        with mock.patch.object(self, "_execute", lambda tool, args, **_: (
                self.ran.append((tool.name, dict(args))) or ("ok", {"text": "Lots of job fairs happen in the area."}))), \
                mock.patch.object(agent_session, "execute", lambda tool, args, **kw: self._execute(tool, args)):
            self._run_everything()
        t3 = next(t for t in pg.load(self.pid)["tasks"] if t["key"] == "t3")
        self.assertEqual(t3["state"], ws.RETRY_LATER)
        self.assertIn("nothing found yet has a date", t3["reason"])
        self.assertNotIn("calendar.hold", [name for name, _a in self.ran])

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
                if t["state"] != ws.DONE and not t["title"].startswith("Prepare application packets")]
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

    def test_a_task_already_parked_on_his_okay_finishes_on_the_next_beat(self):
        """His PC, 2026-10-10 16:51Z: "waiting for Caleb about Write the move criteria"."""
        self._run_everything()

        def unpick(record):
            record["decisions"] = [d for d in record.get("decisions") or [] if d["key"] != "confirm-t5"]
            t5 = next(t for t in record["tasks"] if t["key"] == "t5")
            t5.update(state=ws.READY)
        pg.update(self.pid, unpick)
        record = pg.load(self.pid)
        t5 = next(t for t in record["tasks"] if t["key"] == "t5")
        pg.hold(record, t5, {"kind": "event", "event_kind": "mission.reply", "subject_prefix": "x",
                             "describe": "a reply from Caleb is recorded"},
                reason="waiting for Caleb about Write the move criteria from Caleb's answers", purpose="then",
                now=NOW)
        pg.update(self.pid, lambda r: [t.update(t5) for t in r["tasks"] if t["key"] == "t5"])
        self.assertEqual(self.task_state("t5"), ws.BLOCKED_EXTERNAL)
        released = program_run.requeue_reclassified(now=NOW)
        self.assertIn(("t5", "then"), [(r["task"], r["was"]) for r in released])
        self.assertEqual(self.task_state("t5"), ws.DONE)
        self.assertTrue(any(d["key"] == "confirm-t5" and d["state"] == "open"
                            for d in pg.load(self.pid)["decisions"]))

    def task_state(self, key):
        return next(t for t in pg.load(self.pid)["tasks"] if t["key"] == key)["state"]

    def test_a_when_question_already_asked_is_taken_back_once(self):
        """His PC, 2026-10-10 17:56Z: t3 still asked "start and title" after the fifth fix."""
        with mock.patch.object(agent_session, "execute", lambda tool, args, **kw: (
                self.ran.append((tool.name, dict(args))) or ("ok", {"text": "Lots of job fairs happen here."}))):
            self._run_everything()
            record = pg.load(self.pid)
            t3 = next(t for t in record["tasks"] if t["key"] == "t3")
            t3.update(state=ws.READY, not_before=None, args_retried=True)
            pg.hold(record, t3, {"kind": "user_decision", "question": "what should I use for start and title?"},
                    reason="what should I use for start and title?", purpose="args", now=NOW,
                    extra={"step": 0, "missing": ["start", "title"]})
            pg.update(self.pid, lambda r: [t.update(t3) for t in r["tasks"] if t["key"] == "t3"])
            released = program_run.requeue_reclassified(now=NOW)
            self.assertIn(("t3", "args"), [(r["task"], r["was"]) for r in released])
            program_run.run_task(self.pid, "t3", now=NOW)
            self.assertEqual(self.task_state("t3"), ws.RETRY_LATER)
            self.assertEqual(program_run.requeue_reclassified(now=NOW), [])       # once

    def test_salary_maths_is_not_spending_and_a_task_refused_for_it_runs(self):
        """His PC, 2026-10-10 17:56Z: "compute adjusted pay equivalent: it commits money"."""
        from aletheia import webtask
        self.assertFalse(webtask.would_spend("compute adjusted pay equivalent"))
        self.assertTrue(webtask.would_spend("pay for the event"))
        self._run_everything()

        def refuse(record):
            t6 = next(t for t in record["tasks"] if t["key"] == "t6")
            t6.update(state=ws.FAILED, cursor=0, results=[],
                      does=["pick a shortlist that fits the criteria", "compute adjusted pay equivalent"],
                      uses=["web_task", "compose"],
                      # As his PC stored it: the refusal that failed it is still on the plan.
                      plan={"steps": [{"tool": "research", "for": "pick a shortlist", "by": "matched",
                                       "score": 3}], "requires": [],
                            "gaps": [{"need": "compute adjusted pay equivalent", "outcome": "refuse_policy",
                                      "why": "it commits money, and only Caleb spends money", "next": ""}]},
                      reason="compute adjusted pay equivalent: it commits money, and only Caleb spends money")
        pg.update(self.pid, refuse)
        released = program_run.requeue_reclassified(now=NOW)
        self.assertIn("t6", [r["task"] for r in released])
        self._run_everything()
        self.assertEqual(self.task_state("t6"), ws.DONE)

    def test_the_steps_view_shows_what_a_finished_task_found_for_the_ones_waiting(self):
        self._run_everything()
        pg.update(self.pid, lambda r: next(t for t in r["tasks"] if t["key"] == "t3").update(state=ws.BLOCKED_USER))
        said = pg.spoken_steps("Project Reboot")
        self.assertIn("t2 |", said)
        self.assertIn("found: " + EVENT[:40], said)


HOURS = ("Off limits for events: weekdays 8:00am-5:00pm Central (his workday), except that 1:00-2:30pm "
         "Central on weekdays is kept free for job interviews. Events go on weekday evenings after 5:30pm "
         "Central and on weekends; virtual events are fine at those times too.")


class HisHoursAndHisCalendar(HisMissionRunsWithoutHim):
    """His PC, 2026-10-10 19:10Z: a hold "for the tour Friday, October 6 at 10 am" (a Friday three
    years gone, titled from an example), free windows on Monday morning at the office, and a
    sign-up step refused as spending for saying "stop at payment"."""

    def setUp(self):
        super().setUp()
        pg.update(self.pid, lambda r: r["asks"].append({"at": "2026-09-16T15:00:00Z", "kind": "more",
                                                         "words": HOURS, "via": "operator-voice"}))

    def _with_event(self, text):
        def run(tool, args, **_):
            self.ran.append((tool.name, dict(args)))
            return ("ok", {"text": text}) if tool.read_only and tool.open_world else ("ok", {"text": "done"})
        return mock.patch.object(agent_session, "execute", run)

    def test_his_hours_are_read_from_his_words(self):
        import datetime as dt
        self.assertEqual(program_run.his_hours(pg.load(self.pid)), dt.time(17, 30))
        self.assertIsNone(program_run.his_hours({"questions": [], "asks": [{"kind": "more", "words": "no cold calls"}]}))
        # Both ways of holding are held to it: the tool and the command his PC's step used.
        self.assertTrue(all(program_run._writes_holds(self.catalog[n]) for n in ("calendar.hold", "calendar_hold")))
        self.assertFalse(program_run._writes_holds(self.catalog["calendar_propose"]))

    def test_an_evening_event_is_held(self):
        self._run_everything()
        holds = [a for name, a in self.ran if name == "calendar.hold"]
        self.assertEqual([h["title"] for h in holds], ["Sioux Falls Fall Job Fair"])

    def test_an_event_in_his_working_day_is_never_held(self):
        with self._with_event("Sioux Falls Fall Job Fair - Thursday 2026-10-15 at 10:00, free"):
            self._run_everything()
        self.assertNotIn("calendar.hold", [name for name, _a in self.ran])
        t3 = next(t for t in pg.load(self.pid)["tasks"] if t["key"] == "t3")
        self.assertEqual(t3["state"], ws.RETRY_LATER)
        self.assertIn("working day", t3["reason"])

    def test_a_time_that_has_passed_is_never_held(self):
        with self._with_event("Sioux Falls Fall Job Fair - Friday 2023-10-06 at 18:00, free"):
            self._run_everything()
        self.assertNotIn("calendar.hold", [name for name, _a in self.ran])
        self.assertIn("already passed", next(t for t in pg.load(self.pid)["tasks"] if t["key"] == "t3")["reason"])

    def test_a_title_naming_nothing_found_is_never_held(self):
        def made_up(system, text, *, context=None, validator=None, **kw):
            value = think(system, text, context=context, validator=None, **kw)
            if system is program_compose.ARGS_SYSTEM and "title" in value.get("args", {}):
                value["args"]["title"] = "Hold Friday at 10 for the tour"
            return validator(value) if validator else value
        with mock.patch.object(program_run, "THINK", made_up):
            self._run_everything()
        self.assertNotIn("calendar.hold", [name for name, _a in self.ran])
        self.assertIn("names nothing", next(t for t in pg.load(self.pid)["tasks"] if t["key"] == "t3")["reason"])

    def test_a_wrong_hold_already_made_is_taken_back_and_done_again(self):
        from aletheia import calendar, calendar_reasoning, localtime
        import datetime as dt
        self._run_everything()
        bad = {"title": "Hold Friday at 10 for the tour", "start": "2023-10-06T10:00"}
        start = dt.datetime.fromisoformat(bad["start"]).replace(tzinfo=localtime.operator_tz())
        made = calendar_reasoning.hold(bad["title"], start.isoformat(), (start + dt.timedelta(hours=1)).isoformat())
        event_id = made["event"]["id"]

        def as_his_pc_left_it(record):
            t3 = next(t for t in record["tasks"] if t["key"] == "t3")
            t3["plan"]["steps"][0]["args"] = dict(bad)
            t3["results"] = [{"at": "2026-09-16T15:00:00Z", "step": 0, "tool": "calendar_hold", "outcome": "ok",
                              "said": "Pencilled in Hold Friday at 10 for the tour"}]
            t3.update(state=ws.DONE, cursor=1)
        pg.update(self.pid, as_his_pc_left_it)
        released = program_run.requeue_reclassified(now=NOW)
        self.assertIn(("t3", "done"), [(r["task"], r["was"]) for r in released])
        self.assertEqual(calendar.load(event_id)["status"], "CANCELLED")
        self.assertEqual(self.task_state("t3"), ws.READY)
        self.assertEqual(program_run.requeue_reclassified(now=NOW), [])       # once
        self.ran.clear()
        self._run_everything()
        self.assertEqual(self.task_state("t3"), ws.DONE)
        self.assertEqual([a["title"] for name, a in self.ran if name == "calendar.hold"],
                         ["Sioux Falls Fall Job Fair"])

    def test_a_free_time_read_that_counted_his_working_day_reads_again(self):
        self._run_everything()

        def free_read(record):
            t1 = next(t for t in record["tasks"] if t["key"] == "t1")
            t1.update(state=ws.DONE, cursor=1, plan={"steps": [
                {"tool": "calendar_find_free", "for": "find free windows", "args": {"when": "this week"}}],
                "requires": [], "gaps": []})
        pg.update(self.pid, free_read)
        released = program_run.requeue_reclassified(now=NOW)
        self.assertIn(("t1", "done"), [(r["task"], r["was"]) for r in released])
        self.ran.clear()
        program_run.run_task(self.pid, "t1", now=NOW)
        reads = [a for name, a in self.ran if name == "calendar_find_free"]
        self.assertEqual(reads[0].get("part"), "weekends and after 17:30")
        self.assertEqual(program_run.requeue_reclassified(now=NOW), [])

    def test_a_sign_up_refused_for_its_own_stop_at_payment_rule_runs(self):
        from aletheia import webtask
        self.assertFalse(webtask.would_spend("stop at payment or unknown required fields"))
        self._run_everything()

        def refuse(record):
            t6 = next(t for t in record["tasks"] if t["key"] == "t6")
            t6.update(state=ws.FAILED, cursor=0, results=[],
                      does=["compare the shortlisted places", "stop at payment or unknown required fields"],
                      uses=["web_task"],
                      plan={"steps": [{"tool": "research", "for": "compare the shortlisted places", "by": "named",
                                       "score": None}], "requires": [],
                            "gaps": [{"need": "stop at payment or unknown required fields",
                                      "outcome": "refuse_policy", "next": "",
                                      "why": "it commits money, and only Caleb spends money"}]},
                      reason="stop at payment or unknown required fields: it commits money, and only Caleb "
                             "spends money")
        pg.update(self.pid, refuse)
        self.assertIn("t6", [r["task"] for r in program_run.requeue_reclassified(now=NOW)])
        self._run_everything()
        self.assertEqual(self.task_state("t6"), ws.DONE)


class WhatHisPcDidAfterTheSeventhFix(HisHoursAndHisCalendar):
    """His PC, 2026-10-10 20:37Z, after the seventh fix: the comparison DONE on pages about grammar,
    the sign-up still refused, the holds asking him for a start and title once free windows were
    read, and the newcomer-events task reading his free time with a stretch it cannot read."""

    def test_a_sign_up_refused_as_spending_runs_though_its_step_has_no_address_yet(self):
        self._run_everything()

        def refuse(record):
            t6 = next(t for t in record["tasks"] if t["key"] == "t6")
            t6.update(state=ws.FAILED, cursor=0, results=[], uses=["event.register"],
                      does=["register for free events", "stop at payment or unknown required fields",
                            "count sign-ups against the weekly limit"],
                      plan={"steps": [{"tool": "event.register", "for": "register for free events", "by": "named",
                                       "score": None}], "requires": [],
                            "gaps": [{"need": "stop at payment or unknown required fields",
                                      "outcome": "refuse_policy", "next": "",
                                      "why": "it commits money, and only Caleb spends money"}]},
                      reason="stop at payment or unknown required fields: it commits money, and only Caleb "
                             "spends money")
        pg.update(self.pid, refuse)
        self.assertIn("t6", [r["task"] for r in program_run.requeue_reclassified(now=NOW)])
        t6 = next(t for t in pg.load(self.pid)["tasks"] if t["key"] == "t6")
        self.assertEqual((t6["state"], t6["plan"]["gaps"]), (ws.READY, []))

    def test_free_windows_are_not_an_event_so_it_looks_again_instead_of_asking(self):
        with self._with_event("Free: Saturday 3:30 pm to 10 pm and Sunday 9 am to 10 pm."):
            self._run_everything()
        t3 = next(t for t in pg.load(self.pid)["tasks"] if t["key"] == "t3")
        self.assertEqual(t3["state"], ws.RETRY_LATER, t3.get("reason"))
        self.assertNotIn("what should I use", str(t3.get("reason")))

    def test_a_when_question_asked_again_after_its_one_retry_is_taken_back(self):
        self._run_everything()
        record = pg.load(self.pid)
        t3 = dict(next(t for t in record["tasks"] if t["key"] == "t3"))
        pg.hold(record, t3, {"kind": "user_decision", "question": "what should I use for start and title?"},
                reason="what should I use for start and title?", purpose="args", now=NOW,
                extra={"step": 0, "missing": ["start", "title"]})
        t3.update(dated_retried=True, cursor=0, run=None)
        pg.update(self.pid, lambda r: [t.update(t3) for t in r["tasks"] if t["key"] == "t3"])
        self.assertIn("t3", [r["task"] for r in program_run.requeue_reclassified(now=NOW)])

    def test_a_stretch_the_calendar_cannot_read_becomes_the_default_one(self):
        self.assertFalse(program_run._readable_window("the next 30 days"))
        self.assertTrue(program_run._readable_window("next week"))
        self._run_everything()

        def free_read(record):
            t1 = next(t for t in record["tasks"] if t["key"] == "t1")
            t1.update(state=ws.READY, cursor=0, results=[], plan={"steps": [
                {"tool": "calendar_find_free", "for": "find free windows",
                 "args": {"when": "the next 30 days", "part": "weekends and after 17:30"}}],
                "requires": [], "gaps": []})
        pg.update(self.pid, free_read)
        self.ran.clear()
        program_run.run_task(self.pid, "t1", now=NOW)
        reads = [a for name, a in self.ran if name == "calendar_find_free"]
        self.assertEqual(reads[0]["when"], program_compose.DEFAULT_WINDOW)

    def test_a_look_that_found_nothing_is_not_done_and_a_done_one_is_done_again(self):
        empty = ("I can't give you a city comparison from these sources. The four pages supplied are about "
                 "spelling and punctuation. I won't invent figures. That is from 4 sources.")
        with self._with_event(empty):
            self._run_everything()
        t2 = next(t for t in pg.load(self.pid)["tasks"] if t["key"] == "t2")
        self.assertNotEqual(t2["state"], ws.DONE)
        self.assertEqual(t2["results"][-1]["outcome"], "empty")

        def as_his_pc_left_it(record):
            by = {t["key"]: t for t in record["tasks"]}
            by["t2"].update(state=ws.DONE, cursor=len(by["t2"]["plan"]["steps"]), attempts=0)
            by["t2"]["results"] = [dict(by["t2"]["results"][-1], outcome="ok")]
            by["t3"].update(state=ws.DONE, cursor=1)
        pg.update(self.pid, as_his_pc_left_it)
        released = program_run.requeue_reclassified(now=NOW)
        self.assertIn(("t2", "done"), [(r["task"], r["was"]) for r in released])
        self.assertEqual((self.task_state("t2"), self.task_state("t3")), (ws.READY, ws.READY))
        self._run_everything()
        self.assertEqual((self.task_state("t2"), self.task_state("t3")), (ws.DONE, ws.DONE))

    def test_free_events_are_searched_for_and_the_holds_and_sign_ups_stay(self):
        plan = program_compose.compose({
            "title": "Find free relocation and newcomer events for the shortlisted places",
            "does": ["search for free relocation and newcomer events", "hold fitting ones on the calendar",
                     "register for free ones with his approval"],
            "uses": ["web_task", "calendar_hold", "event.register"]}, self.catalog)
        self.assertEqual([s["tool"] for s in plan["steps"]], ["research", "calendar_hold", "event.register"])

    def test_the_steps_view_says_which_holds_were_taken_back(self):
        from aletheia import calendar_reasoning, localtime
        import datetime as dt
        start = dt.datetime(2023, 10, 6, 10, tzinfo=localtime.operator_tz())
        made = calendar_reasoning.hold("Hold Friday at 10 for the tour", start.isoformat(),
                                       (start + dt.timedelta(hours=1)).isoformat())
        calendar_reasoning.release_hold(made["event"]["id"], why="taken back: that time had already passed")
        said = pg.spoken_steps("Project Reboot")
        self.assertIn("hold taken back | Hold Friday at 10 for the tour", said)
        self.assertIn("CANCELLED", said)


class ALookComposedUnderOldRules(HisMissionRunsWithoutHim):
    def test_a_failed_look_the_composer_would_no_longer_choose_is_planned_again_once(self):
        """His PC, 2026-10-10 22:34Z: "calendar.find_free failed 3 times" on a search for free events."""
        self._run_everything()

        def stuck(record):
            t7 = next(t for t in record["tasks"] if t["key"] == "t7")
            t7.update(state=ws.FAILED, cursor=0, attempts=3, results=[],
                      plan={"steps": [{"tool": "calendar.find_free", "for": t7["does"][0], "by": "reader",
                                       "args": {"when": "the next 30 days"}}], "requires": [], "gaps": []},
                      reason="calendar.find_free failed 3 times: the tool failed (ValueError)")
        pg.update(self.pid, stuck)
        released = program_run.requeue_reclassified(now=NOW)
        self.assertIn(("t7", "recomposed"), [(r["task"], r["was"]) for r in released])
        t7 = next(t for t in pg.load(self.pid)["tasks"] if t["key"] == "t7")
        self.assertEqual(t7["state"], ws.READY)
        self.assertNotIn("calendar.find_free", [s["tool"] for s in t7["plan"]["steps"]])
        pg.update(self.pid, lambda r: next(t for t in r["tasks"] if t["key"] == "t7").update(
            state=ws.FAILED, reason="research failed 3 times"))
        self.assertNotIn("t7", [r["task"] for r in program_run.requeue_reclassified(now=NOW)])  # once


class WhatHisPcDidAfterTheNinthFix(HisHoursAndHisCalendar):
    """His PC, 2026-10-10 23:51Z: the comparison said its nothing in other words and stood as done,
    and the weekly event sweep went FAILED for good after three bad searches in one evening."""

    def _sweep_key(self):
        return next(t["key"] for t in pg.load(self.pid)["tasks"] if t.get("from_activity") == "a1")

    def test_a_recurring_sweep_looks_again_tomorrow_instead_of_failing(self):
        key = self._sweep_key()
        empty = "I can't give you any events from these sources. All five pages are about something else."
        with self._with_event(empty):
            for n in range(program_run.MAX_ATTEMPTS):
                pg.update(self.pid, lambda r: next(t for t in r["tasks"] if t["key"] == key).update(
                    state=ws.READY, not_before=None))
                program_run.run_task(self.pid, key, now=NOW)
        sweep = next(t for t in pg.load(self.pid)["tasks"] if t["key"] == key)
        self.assertEqual(sweep["state"], ws.RETRY_LATER)
        self.assertEqual(sweep["attempts"], 0)
        self.assertEqual(sweep["next"], "look again tomorrow")

    def test_a_sweep_with_a_newer_one_after_it_may_fail(self):
        import datetime as dt
        key = self._sweep_key()
        pg.activity_due(self.pid, "a1", now=NOW + dt.timedelta(days=7))
        record = pg.load(self.pid)
        sweep = next(t for t in record["tasks"] if t["key"] == key)
        self.assertFalse(program_run._looks_again_tomorrow(record, sweep))

    def test_a_sweep_his_pc_left_failed_is_released_once(self):
        key = self._sweep_key()
        program_run.run_task(self.pid, key, now=NOW)  # composed, as his had been

        def as_his_pc_left_it(record):
            next(t for t in record["tasks"] if t["key"] == key).update(
                state=ws.FAILED, attempts=3, cursor=0, run=None,
                reason="research failed 3 times: I can't give you any events from these sources.")
        pg.update(self.pid, as_his_pc_left_it)
        released = program_run.requeue_reclassified(now=NOW)
        self.assertIn((key, "recurring"), [(r["task"], r["was"]) for r in released])
        self.assertEqual(self.task_state(key), ws.READY)
        pg.update(self.pid, as_his_pc_left_it)
        self.assertNotIn(key, [r["task"] for r in program_run.requeue_reclassified(now=NOW)])  # once

    def test_nothing_said_in_other_words_is_still_nothing(self):
        for said in ("I can't answer this from the sources provided. All five extracts are about spelling.",
                     "I can’t give you a sourced comparison from what I was handed."):
            self.assertTrue(program_run.NOTHING_FOUND.search(said), said)
        self.assertFalse(program_run.NOTHING_FOUND.search("Three free events: a mixer on Oct 15 at the library."))

    def test_a_look_done_again_that_came_back_empty_again_is_done_again(self):
        import datetime as dt
        empty = "I can't give you a sourced comparison from what I was handed."

        def as_his_pc_left_it(record):
            t2 = next(t for t in record["tasks"] if t["key"] == "t2")
            t2.update(state=ws.DONE, cursor=len(t2["plan"]["steps"]), attempts=0, empty_rechecked=True,
                      history=[{"at": "2026-09-16T15:00:00Z", "did": "opened again: its look found nothing to answer with"}],
                      results=[{"at": "2026-09-16T15:30:00Z", "step": len(t2["plan"]["steps"]) - 1,
                                "tool": t2["plan"]["steps"][-1]["tool"], "outcome": "ok", "said": empty}])
        self._run_everything()
        pg.update(self.pid, as_his_pc_left_it)
        released = program_run.requeue_reclassified(now=NOW + dt.timedelta(hours=1))
        self.assertIn(("t2", "done"), [(r["task"], r["was"]) for r in released])
        # And not again for the same empty answer.
        pg.update(self.pid, lambda r: next(t for t in r["tasks"] if t["key"] == "t2").update(
            state=ws.DONE, cursor=len(next(t for t in r["tasks"] if t["key"] == "t2")["plan"]["steps"])))
        self.assertNotIn("t2", [r["task"] for r in program_run.requeue_reclassified(now=NOW + dt.timedelta(hours=2))])


class WhatHisPcDidAfterTheTenthFix(HisMissionRunsWithoutHim):
    """His PC, 2026-10-11 01:17Z: the city comparison was planned again as the website tool and
    waited for his yes on "pick a shortlist that fits the criteria" - a read."""

    DOES = ["pick a shortlist that fits the criteria", "compare cost of living, job market, taxes, housing",
            "compute adjusted pay equivalent", "write a ranked summary with sources"]

    def test_a_comparison_that_names_the_website_tool_is_a_look_and_a_write(self):
        plan = program_compose.compose({"title": "Compare a shortlist of warm red-state places", "does": self.DOES,
                                        "uses": ["web_task", "compose"]}, self.catalog)
        self.assertEqual([s["tool"] for s in plan["steps"]], ["research", "compose"])

    def test_a_doing_tool_a_doing_need_is_for_stays(self):
        plan = program_compose.compose({"title": "Find free newcomer events and sign up",
                                        "does": ["search for free newcomer events", "sign up for the newsletter"],
                                        "uses": ["web_task"]}, self.catalog)
        self.assertIn("web_task", [s["tool"] for s in plan["steps"]])

    def test_the_comparison_his_pc_parked_on_his_yes_runs_as_a_look(self):
        def as_his_pc_left_it(record):
            t6 = next(t for t in record["tasks"] if t["key"] == "t6")
            t6.update(does=list(self.DOES), uses=["web_task", "compose"], state=ws.READY, cursor=0, attempts=0,
                      needs=[], recomposed=True,
                      plan={"steps": [{"tool": "web_task", "for": self.DOES[0], "by": "named", "args": {}},
                                      {"tool": "compose", "for": "", "by": "named", "args": {}}],
                            "requires": [], "gaps": []})
        pg.update(self.pid, as_his_pc_left_it)
        program_run.run_task(self.pid, "t6", now=NOW)
        self.assertEqual(self.task_state("t6"), ws.BLOCKED_USER)
        released = program_run.requeue_reclassified(now=NOW)
        self.assertIn("t6", [r["task"] for r in released])
        t6 = next(t for t in pg.load(self.pid)["tasks"] if t["key"] == "t6")
        self.assertEqual(t6["state"], ws.READY)
        self.assertEqual(t6["plan"]["steps"][0]["tool"], "research")

    def task_state(self, key):
        return next(t for t in pg.load(self.pid)["tasks"] if t["key"] == key)["state"]


class WhatHisPcDidAfterTheEleventhFix(HisHoursAndHisCalendar):
    """His PC, 2026-10-11 02:41Z: the young professionals' October events were found; a weekend
    one may be held, a weekday lunch may not, and a finished weekly sweep vanished from the steps."""

    def test_a_saturday_event_is_held(self):
        with self._with_event("Community Job Fair - Saturday 2026-10-17 at 11:00, Sioux Falls"):
            self._run_everything()
        self.assertEqual([a["title"] for n, a in self.ran if n == "calendar.hold"], ["Community Job Fair"])

    def test_a_monday_lunch_is_not_held(self):
        # October 19 and 26, 2026 are Mondays: a lunch then is his working day.
        with self._with_event("Lunch Job Fair - Monday 2026-10-19 at 12:00, Sioux Falls"):
            self._run_everything()
        self.assertNotIn("calendar.hold", [n for n, _a in self.ran])

    def test_the_steps_view_shows_what_the_finished_sweep_found(self):
        self._run_everything()
        key = next(t["key"] for t in pg.load(self.pid)["tasks"] if t.get("from_activity") == "a1")
        self.assertEqual(self.task_state(key), ws.DONE)
        said = pg.spoken_steps("Project Reboot")
        self.assertIn(f"{key} | Weekly sweep for new job-search events | DONE | found:", said)

    def task_state(self, key):
        return next(t for t in pg.load(self.pid)["tasks"] if t["key"] == key)["state"]
