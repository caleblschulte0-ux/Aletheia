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

from aletheia import agent_session, program_compose, program_run, research, tools
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

    def test_the_steps_view_says_when_a_parked_task_may_run_and_what_holds_it(self):
        # His PC, 2026-10-11: t3 sat RETRY_LATER 26 hours past its retry and the relay could not say why.
        self._run_everything()
        record = pg.load(self.pid)
        t3 = dict(next(t for t in record["tasks"] if t["key"] == "t3"))
        pg.hold(record, t3, {"kind": "user_decision", "question": "what should I use for start and title?"},
                reason="what should I use for start and title?", purpose="args", now=NOW,
                extra={"step": 0, "missing": ["start", "title"]})
        pg.update(self.pid, lambda r: next(t for t in r["tasks"] if t["key"] == "t3").update(
            state=ws.RETRY_LATER, not_before="2026-10-11T20:09:20Z", waits=t3.get("waits")))
        said = pg.spoken_steps("Project Reboot")
        self.assertIn("not before 2026-10-11T20:09:20Z", said)
        self.assertIn("open waits args:start,title", said)


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
        # The model's own title, so the dated line the search read is not there to fill it first.
        with mock.patch.object(program_run, "THINK", made_up), mock.patch.object(program_run, "_dated_hold",
                                                                                 lambda *a, **k: {}):
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
        fail = (lambda r: next(t for t in r["tasks"] if t["key"] == "t7").update(
            state=ws.FAILED, reason="research failed 3 times"))
        pg.update(self.pid, fail)
        # Planned again once; its look may still try the pages it reads now once, and then no more.
        self.assertNotIn(("t7", "recomposed"), [(r["task"], r["was"]) for r in program_run.requeue_reclassified(now=NOW)])
        pg.update(self.pid, fail)
        self.assertNotIn("t7", [r["task"] for r in program_run.requeue_reclassified(now=NOW)])


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


class WhatHisPcDidAfterTheTwelfthFix(HisMissionRunsWithoutHim):
    """His PC, 2026-10-11 04:02Z: the weekly sweep found "605 Connections" and said it had no way to
    hold it (composed as a look alone); the comparison failed three times; a watch read pages about
    the film "Once" and stood as done."""

    def _sweep(self):
        return next(t for t in pg.load(self.pid)["tasks"] if t.get("from_activity") == "a1")

    def test_a_finished_sweep_composed_as_a_look_alone_goes_on_to_hold(self):
        key = self._sweep()["key"]

        def as_his_pc_left_it(record):
            t = next(x for x in record["tasks"] if x["key"] == key)
            t.update(does=["search for newly listed events", "hold fitting ones on the calendar"],
                     uses=["browser.pursue", "calendar_hold"], state=ws.DONE, cursor=1,
                     plan={"steps": [{"tool": "research", "for": "search for newly listed events",
                                      "by": "reader", "args": {"question": "events"}}], "requires": [], "gaps": []},
                     results=[{"at": "2026-09-16T15:00:00Z", "step": 0, "tool": "research", "outcome": "ok",
                               "said": EVENT}])
        pg.update(self.pid, as_his_pc_left_it)
        released = program_run.requeue_reclassified(now=NOW)
        self.assertIn((key, "done"), [(r["task"], r["was"]) for r in released])
        t = self._sweep()
        self.assertEqual((t["state"], t["cursor"]), (ws.READY, 1))
        self.assertEqual([s["tool"] for s in t["plan"]["steps"]], ["research", "calendar_hold"])
        self.assertEqual([r["task"] for r in program_run.requeue_reclassified(now=NOW)
                          if r["task"] == key and r.get("why", "").startswith("steps")], [])

    def test_the_sources_as_the_subject_is_still_nothing(self):
        self.assertTrue(program_run.NOTHING_FOUND.search(
            "The supplied sources can't answer this. They're about the film 'Once'."))

    def test_a_look_that_failed_for_want_of_pages_tries_once_more(self):
        def as_his_pc_left_it(record):
            t6 = next(t for t in record["tasks"] if t["key"] == "t6")
            t6.update(state=ws.FAILED, cursor=0, attempts=3, needs=[],
                      plan={"steps": [{"tool": "research", "for": "compare", "by": "reader", "args": {}}],
                            "requires": [], "gaps": []},
                      reason="research failed 3 times: I can't give you a sourced shortlist")
        pg.update(self.pid, as_his_pc_left_it)
        self.assertIn(("t6", "sources"), [(r["task"], r["was"]) for r in program_run.requeue_reclassified(now=NOW)])
        pg.update(self.pid, as_his_pc_left_it)
        self.assertNotIn("t6", [r["task"] for r in program_run.requeue_reclassified(now=NOW)])

    def test_the_steps_view_says_how_it_looked_first(self):
        self.assertTrue(pg._found_line("No figures here. More words. I couldn't read www.numbeo.com.")
                        .startswith("I couldn't read www.numbeo.com."))


class WhatHisPcDidAfterTheThirteenthFix(HisMissionRunsWithoutHim):
    """His PC, 2026-10-11 05:31Z: the sweep went on to hold and asked him "what should I use for start
    and title?"; the comparison stayed failed without trying the pages it reads now; and the watch
    over the shortlist looked twice before there was any shortlist."""

    DOES = ["pick a shortlist that fits the criteria", "write a ranked summary with sources"]

    def _sweep(self):
        return next(t for t in pg.load(self.pid)["tasks"] if t.get("from_activity") == "a1")

    def test_a_sweep_whose_look_found_nothing_dated_looks_again_rather_than_asking_him(self):
        key = self._sweep()["key"]

        def as_his_pc_left_it(record):
            t = next(x for x in record["tasks"] if x["key"] == key)
            t.update(does=["search for newly listed events", "hold fitting ones on the calendar"],
                     uses=["browser.pursue", "calendar_hold"], state=ws.READY, cursor=1, needs=[], relooked=research.REVISION,
                     plan={"steps": [{"tool": "research", "for": "search for newly listed events",
                                      "by": "reader", "args": {"question": "events"}},
                                     {"tool": "calendar_hold", "for": "hold fitting ones on the calendar",
                                      "by": "named", "args": {}}], "requires": [], "gaps": []},
                     results=[{"at": "2026-09-16T15:00:00Z", "step": 0, "tool": "research", "outcome": "ok",
                               "said": "605 Connections, a group for young professionals in town"}])
        pg.update(self.pid, as_his_pc_left_it)
        with mock.patch.object(program_compose, "model_args", lambda *a, **k: {}):
            out = program_run.run_task(self.pid, key, now=NOW)
        self.assertEqual(out["state"], ws.RETRY_LATER)
        self.assertNotIn("what should I use", str(self._sweep().get("reason") or ""))
        self.assertNotIn("calendar_hold", [n for n, _a in self.ran])

    def test_a_comparison_planned_again_once_still_tries_the_pages_it_reads_now(self):
        def as_his_pc_left_it(record):
            t6 = next(t for t in record["tasks"] if t["key"] == "t6")
            t6.update(state=ws.FAILED, cursor=0, attempts=3, needs=[], recomposed=True,
                      plan={"steps": [{"tool": "research", "for": "compare", "by": "reader", "args": {}}],
                            "requires": [], "gaps": []},
                      reason="research failed 3 times: I can't give you a sourced shortlist")
        pg.update(self.pid, as_his_pc_left_it)
        self.assertIn(("t6", "sources"), [(r["task"], r["was"]) for r in program_run.requeue_reclassified(now=NOW)])

    def _with_watch(self, t6_state):
        def change(record):
            t6 = next(t for t in record["tasks"] if t["key"] == "t6")
            t6.update(state=t6_state, does=list(self.DOES))
            record["tasks"].append(pg._task_from(
                {"key": "a9-2026101100", "title": "Watch shortlisted places for roles and cost changes",
                 "does": ["look for new matching postings in shortlisted places"], "uses": ["web_task"]},
                NOW, activity="a9"))
        pg.update(self.pid, change)

    def test_a_watch_over_the_shortlist_waits_for_the_shortlist(self):
        self._with_watch(ws.FAILED)
        out = program_run.run_task(self.pid, "a9-2026101100", now=NOW)
        self.assertEqual(out["state"], ws.BLOCKED_EXTERNAL)
        self.assertNotIn("research", [n for n, _a in self.ran])
        record = pg.load(self.pid)
        watch = next(t for t in record["tasks"] if t["key"] == "a9-2026101100")
        # A failed shortlist is already his to see; the watch only waits, it does not ask him.
        self.assertEqual(pg.blocked_by_needs(record, watch)[0], ws.BLOCKED_EXTERNAL)

    def test_once_the_shortlist_is_made_the_watch_looks(self):
        self._with_watch(ws.DONE)
        record = pg.load(self.pid)
        watch = next(t for t in record["tasks"] if t["key"] == "a9-2026101100")
        self.assertEqual(pg.unmet_needs(record, watch), [])

    def test_a_sweep_that_names_nothing_a_task_makes_waits_on_nothing(self):
        self._with_watch(ws.FAILED)
        record = pg.load(self.pid)
        self.assertEqual(pg.implied_needs(record, self._sweep()), [])


class WhatHisPcDidAfterTheFourteenthFix(HisMissionRunsWithoutHim):
    """His PC, 2026-10-11 07:04Z: the sweep still asked him "what should I use for start and title?"
    from before the fix; the watch over the shortlist waited but read as READY."""

    def test_the_sweeps_old_when_question_is_taken_back(self):
        record = pg.load(self.pid)
        sweep = dict(next(t for t in record["tasks"] if t.get("from_activity") == "a1"))
        sweep.update(does=["search for newly listed events", "hold fitting ones on the calendar"],
                     uses=["browser.pursue", "calendar_hold"], cursor=1, needs=[], relooked=research.REVISION, run=None,
                     plan={"steps": [{"tool": "research", "for": "search for newly listed events",
                                      "by": "reader", "args": {"question": "events"}},
                                     {"tool": "calendar_hold", "for": "hold fitting ones on the calendar",
                                      "by": "named", "args": {}}], "requires": [], "gaps": []},
                     results=[{"at": "2026-09-16T15:00:00Z", "step": 0, "tool": "research", "outcome": "ok",
                               "said": "605 Connections, a group for young professionals in town"}])
        question = 'For "Weekly sweep for new job-search events", what should I use for start and title?'
        pg.hold(record, sweep, {"kind": "user_decision", "question": question}, reason=question, purpose="args",
                now=NOW, extra={"step": 1, "missing": ["start", "title"]})
        pg.update(self.pid, lambda r: [t.update(sweep) for t in r["tasks"] if t["key"] == sweep["key"]])
        self.assertIn(sweep["key"], [r["task"] for r in program_run.requeue_reclassified(now=NOW)])
        with mock.patch.object(program_compose, "model_args", lambda *a, **k: {}):
            out = program_run.run_task(self.pid, sweep["key"], now=NOW)
        self.assertEqual(out["state"], ws.RETRY_LATER)

    def test_the_steps_view_says_what_a_watch_waits_on(self):
        def change(record):
            t6 = next(t for t in record["tasks"] if t["key"] == "t6")
            t6.update(state=ws.FAILED, does=["pick a shortlist that fits the criteria"])
            record["tasks"].append(pg._task_from(
                {"key": "a9-2026101100", "title": "Watch shortlisted places for roles and cost changes",
                 "does": ["look for new matching postings in shortlisted places"], "uses": ["web_task"]},
                NOW, activity="a9"))
        pg.update(self.pid, change)
        line = next(x for x in pg.spoken_steps("Project Reboot").splitlines() if x.startswith("a9-2026101100 |"))
        self.assertIn("| waits on t6 |", line)


class WhatHisPcDidAfterTheFifteenthFix(HisMissionRunsWithoutHim):
    """His PC, 2026-10-11 08:45Z: the sweep looked again for "a date" while its look had read
    dated items; the comparison failed again before it read pages the new way."""

    def _sweep_at_hold(self, said):
        key = next(t for t in pg.load(self.pid)["tasks"] if t.get("from_activity") == "a1")["key"]

        def change(record):
            t = next(x for x in record["tasks"] if x["key"] == key)
            t.update(does=["search for newly listed events", "hold fitting ones on the calendar"],
                     uses=["browser.pursue", "calendar_hold"], state=ws.READY, cursor=1, needs=[], relooked=research.REVISION,
                     plan={"steps": [{"tool": "research", "for": "search for newly listed events",
                                      "by": "reader", "args": {"question": "events"}},
                                     {"tool": "calendar_hold", "for": "hold fitting ones on the calendar",
                                      "by": "named", "args": {}}], "requires": [], "gaps": []},
                     results=[{"at": "2026-09-16T15:00:00Z", "step": 0, "tool": "research", "outcome": "ok",
                               "said": said}])
        pg.update(self.pid, change)
        return key

    def test_a_dated_evening_line_its_own_look_read_becomes_the_hold_with_no_model(self):
        key = self._sweep_at_hold("Two groups meet. Dated: 605 Connections: Networking After Hours, "
                                  "Thursday, Sep 17, 6:00 pm; YPN Lunch, Friday, Sep 18, 12:00 pm.")
        with mock.patch.object(program_compose, "model_args", side_effect=AssertionError("no model")):
            program_run.run_task(self.pid, key, now=NOW)
        holds = [a for n, a in self.ran if n == "calendar_hold"]
        self.assertEqual([a["title"] for a in holds], ["605 Connections: Networking After Hours"])
        self.assertTrue(holds[0]["start"].startswith("2026-09-17T18:00"))

    def test_a_date_with_no_time_is_not_a_hold(self):
        key = self._sweep_at_hold("Dated: Coffee Connect, Saturday September 19.")
        with mock.patch.object(program_compose, "model_args", lambda *a, **k: {}):
            out = program_run.run_task(self.pid, key, now=NOW)
        self.assertEqual(out["state"], ws.RETRY_LATER)
        self.assertNotIn("calendar_hold", [n for n, _a in self.ran])

    def test_a_look_that_failed_on_the_old_reading_tries_once_on_the_new(self):
        def failed(record):
            t6 = next(t for t in record["tasks"] if t["key"] == "t6")
            t6.update(state=ws.FAILED, cursor=0, attempts=3, needs=[], sources_retried=True, recomposed=True,
                      plan={"steps": [{"tool": "research", "for": "compare", "by": "reader", "args": {}}],
                            "requires": [], "gaps": []},
                      reason="research failed 3 times: I can't deliver the full comparison")
        pg.update(self.pid, failed)
        self.assertIn(("t6", "sources"), [(r["task"], r["was"]) for r in program_run.requeue_reclassified(now=NOW)])
        pg.update(self.pid, failed)
        self.assertNotIn("t6", [r["task"] for r in program_run.requeue_reclassified(now=NOW)])


class WhatHisPcDidAfterTheSixteenthFix(HisMissionRunsWithoutHim):
    """His PC, 2026-10-11 10:25Z: the comparison's look read two national pages and a tax table and
    no place's own page - its question, stored from the task's detail, never said which places; and
    the sweep's look predated the dated lines, so it would have waited a week to read them."""

    def test_a_look_is_asked_with_its_tasks_title(self):
        seen = []

        def as_his_pc_left_it(record):
            t6 = next(t for t in record["tasks"] if t["key"] == "t6")
            t6.update(title="Compare a shortlist of warm red-state places", state=ws.READY, cursor=0, needs=[],
                      plan={"steps": [{"tool": "research", "for": "pick a shortlist", "by": "reader",
                                       "args": {"question": "pick a shortlist that fits the criteria"}}],
                            "requires": [], "gaps": []})
        pg.update(self.pid, as_his_pc_left_it)
        with mock.patch.object(agent_session, "execute",
                               lambda tool, args, **k: (seen.append(dict(args)) or ("ok", {"text": EVENT}))):
            program_run.run_task(self.pid, "t6", now=NOW)
        self.assertEqual(seen[0]["question"],
                         "Compare a shortlist of warm red-state places: pick a shortlist that fits the criteria")

    def test_a_sweep_whose_look_predates_the_dated_lines_looks_again_now_once(self):
        key = next(t for t in pg.load(self.pid)["tasks"] if t.get("from_activity") == "a1")["key"]

        def change(record):
            t = next(x for x in record["tasks"] if x["key"] == key)
            t.update(does=["search for newly listed events", "hold fitting ones on the calendar"],
                     uses=["browser.pursue", "calendar_hold"], state=ws.READY, cursor=1, needs=[],
                     plan={"steps": [{"tool": "research", "for": "search for newly listed events",
                                      "by": "reader", "args": {"question": "events"}},
                                     {"tool": "calendar_hold", "for": "hold fitting ones on the calendar",
                                      "by": "named", "args": {}}], "requires": [], "gaps": []},
                     results=[{"at": "2026-09-16T15:00:00Z", "step": 0, "tool": "research", "outcome": "ok",
                               "said": "605 Connections, a group for young professionals in town"}])
        pg.update(self.pid, change)
        with mock.patch.object(program_compose, "model_args", lambda *a, **k: {}):
            out = program_run.run_task(self.pid, key, now=NOW)
        self.assertEqual(out["state"], ws.READY)
        t = next(x for x in pg.load(self.pid)["tasks"] if x["key"] == key)
        self.assertEqual((t["cursor"], t["relooked"]), (0, research.REVISION))


class WhatHisPcDidAfterTheSeventeenthFix(HisMissionRunsWithoutHim):
    """His PC, 2026-10-11 12:12Z: the comparison's look passed and the write-up after it failed with
    ComposeError - it had only his answers to write from, never what the look read - and the sweep's
    look carried dated lines that were cut off at 300 characters before the hold could read them."""

    LONG = ("I read bestplaces.net, numbeo.com. " + "Young professionals meet across town most weeks. " * 8
            + "Dated: 605 Connections: Networking After Hours, Thursday, Sep 17, 6:00 pm.")

    def test_dated_lines_at_the_end_of_a_long_answer_reach_the_hold(self):
        self.assertGreater(self.LONG.index("Dated:"), 300)
        key = next(t for t in pg.load(self.pid)["tasks"] if t.get("from_activity") == "a1")["key"]

        def change(record):
            t = next(x for x in record["tasks"] if x["key"] == key)
            t.update(does=["search for newly listed events", "hold fitting ones on the calendar"],
                     uses=["browser.pursue", "calendar_hold"], state=ws.READY, cursor=0, needs=[],
                     relooked=research.REVISION,
                     plan={"steps": [{"tool": "research", "for": "search for newly listed events",
                                      "by": "reader", "args": {"question": "events"}},
                                     {"tool": "calendar_hold", "for": "hold fitting ones on the calendar",
                                      "by": "named", "args": {}}], "requires": [], "gaps": []})
        pg.update(self.pid, change)

        def execute(tool, args, **_):
            self.ran.append((tool.name, dict(args)))
            return ("ok", self.LONG) if tool.name == "research" else ("ok", {"text": "held"})
        with mock.patch.object(agent_session, "execute", execute), \
                mock.patch.object(program_compose, "model_args", lambda *a, **k: {}):
            program_run.run_task(self.pid, key, now=NOW)
        holds = [a for n, a in self.ran if n == "calendar_hold"]
        self.assertEqual([a["title"] for a in holds], ["605 Connections: Networking After Hours"])

    def test_a_write_up_is_handed_what_the_look_before_it_read(self):
        def change(record):
            t6 = next(t for t in record["tasks"] if t["key"] == "t6")
            t6.update(title="Compare warm red-state places", state=ws.READY, cursor=1, needs=[],
                      plan={"steps": [{"tool": "research", "for": "compare", "by": "reader",
                                       "args": {"question": "compare"}},
                                      {"tool": "compose", "for": "write the ranked summary", "by": "named",
                                       "args": {"path": "missions/ranked.md", "what": "rank them",
                                                "sources": ["the research above"]}}],
                            "requires": [], "gaps": []},
                      results=[{"at": "2026-09-16T15:00:00Z", "step": 0, "tool": "research", "outcome": "ok",
                                "said": "Tampa: cost of living index 102; Austin: 119.",
                                "revision": research.REVISION}])
        pg.update(self.pid, change)
        program_run.run_task(self.pid, "t6", now=NOW)
        wrote = [a for n, a in self.ran if n == "compose"]
        self.assertTrue(wrote[0]["sources"][0].endswith("-t6-found.md"))
        from aletheia import workspace
        self.assertIn("Austin: 119", workspace.resolve(wrote[0]["sources"][0]).read_text(encoding="utf-8"))
        self.assertIn("the research above", wrote[0]["sources"])

    def test_the_steps_view_keeps_what_a_passed_look_read(self):
        def change(record):
            t6 = next(t for t in record["tasks"] if t["key"] == "t6")
            t6.update(title="Compare warm red-state places", state=ws.RETRY_LATER, cursor=1, needs=[],
                      reason="compose error: the tool failed (ComposeError)",
                      plan={"steps": [{"tool": "research", "for": "compare", "by": "reader",
                                       "args": {"question": "Compare warm red-state places: compare"}},
                                      {"tool": "compose", "for": "write", "by": "named", "args": {}}],
                            "requires": [], "gaps": []},
                      results=[{"at": "2026-09-16T15:00:00Z", "step": 0, "tool": "research", "outcome": "ok",
                                "said": "Tampa: cost of living index 102; Austin: 119."}])
        pg.update(self.pid, change)
        with mock.patch.object(research, "last_look",
                               lambda q: {"at": "2026-10-11T12:00Z", "shown": [], "unread": []}), \
                mock.patch.object(research, "look_words", lambda look: "shown: bestplaces.net (2400 of 9000)"):
            said = pg.spoken_steps()
        self.assertIn("t6 | last look at 2026-10-11T12:00Z | shown: bestplaces.net", said)
        self.assertIn("t6 | found so far: Tampa: cost of living index 102; Austin: 119.", said)

    def test_a_write_up_that_failed_for_want_of_a_source_tries_once_with_the_found_file(self):
        def failed(record):
            t6 = next(t for t in record["tasks"] if t["key"] == "t6")
            t6.update(state=ws.FAILED, cursor=1, attempts=3, needs=[], source_retried=True,
                      plan={"steps": [{"tool": "research", "for": "compare", "by": "reader", "args": {}},
                                      {"tool": "compose", "for": "write", "by": "named", "args": {}}],
                            "requires": [], "gaps": []},
                      results=[{"at": "2026-09-16T15:00:00Z", "step": 0, "tool": "research", "outcome": "ok",
                                "said": "Tampa: 102."}],
                      reason="compose failed 3 times: the tool failed (ComposeError)")
        pg.update(self.pid, failed)
        self.assertIn("t6", [r["task"] for r in program_run.requeue_reclassified(now=NOW)])
        t6 = next(t for t in pg.load(self.pid)["tasks"] if t["key"] == "t6")
        self.assertEqual(t6["written_from"], program_run.WRITES_FROM)
        pg.update(self.pid, failed)
        pg.update(self.pid, lambda r: next(t for t in r["tasks"] if t["key"] == "t6").update(
            written_from=program_run.WRITES_FROM))
        self.assertNotIn("t6", [r["task"] for r in program_run.requeue_reclassified(now=NOW)])


class WhatHisPcDidAfterTheEighteenthFix(HisMissionRunsWithoutHim):
    """His PC, 2026-10-11 14:09Z: the comparison's write-up ran on a look that kept 300 characters a
    page and refused ("CANNOT WRITE ... partial cost-of-living data"); the sweep's re-look had run
    while answers were still cut at 300 characters, so its dated lines never arrived."""

    def _write_up_after(self, result):
        def change(record):
            t6 = next(t for t in record["tasks"] if t["key"] == "t6")
            t6.update(title="Compare warm red-state places", state=ws.READY, cursor=1, needs=[],
                      plan={"steps": [{"tool": "research", "for": "compare", "by": "reader",
                                       "args": {"question": "compare"}},
                                      {"tool": "compose", "for": "write the ranked summary", "by": "named",
                                       "args": {"path": "missions/ranked.md", "what": "rank them"}}],
                            "requires": [], "gaps": []},
                      results=[dict({"at": "2026-09-16T15:00:00Z", "step": 0, "tool": "research", "outcome": "ok",
                                     "said": "Tampa: partial figures."}, **result)])
        pg.update(self.pid, change)

    def test_a_write_up_on_an_old_reading_looks_again_first_once(self):
        self._write_up_after({})
        out = program_run.run_task(self.pid, "t6", now=NOW)
        self.assertEqual(out["state"], ws.READY)
        t6 = next(t for t in pg.load(self.pid)["tasks"] if t["key"] == "t6")
        self.assertEqual((t6["cursor"], t6["relooked"]), (0, research.REVISION))
        self.assertNotIn("compose", [n for n, _a in self.ran])

    def test_a_write_up_on_the_current_reading_writes(self):
        self._write_up_after({"revision": research.REVISION})
        program_run.run_task(self.pid, "t6", now=NOW)
        self.assertIn("compose", [n for n, _a in self.ran])

    def test_a_look_that_runs_now_is_marked_with_the_current_reading(self):
        self._write_up_after({})
        pg.update(self.pid, lambda r: next(t for t in r["tasks"] if t["key"] == "t6").update(cursor=0))
        program_run.run_task(self.pid, "t6", now=NOW)
        t6 = next(t for t in pg.load(self.pid)["tasks"] if t["key"] == "t6")
        looks = [r for r in t6["results"] if r["tool"] == "research"]
        self.assertEqual(looks[-1]["revision"], research.REVISION)
        self.assertIn("compose", [n for n, _a in self.ran])


class WhatHisPcDidAfterTheNineteenthFix(HisMissionRunsWithoutHim):
    """His PC, 2026-10-11 14:09Z: the watch for openings in the shortlisted places searched the open
    web and read a sports app, a download page and two dictionary entries. The boards' own listings
    had a tool all along, described only as "The 'jobs' command"."""

    def test_a_look_for_openings_goes_to_the_boards_not_the_open_web(self):
        for need in ("search job postings in each shortlisted place", "Watch job postings in the shortlisted cities"):
            tool, _top = program_compose.best_tool(need, self.catalog)
            self.assertEqual(tool.name, "jobs", need)

    def test_checking_something_in_the_world_does_not_read_his_email(self):
        """His PC, 2026-10-11: "check rents in each city" went to the tool that reads one unread
        email, three points for the word "read" that "check" stands for."""
        for need in ("check rents in each city", "check the cost of living"):
            tool, _top = program_compose.best_tool(need, self.catalog)
            self.assertEqual(tool.name, "research", need)
        tool, _top = program_compose.best_tool("check my email", self.catalog)
        self.assertTrue(tool.name.startswith("email_"))


class HowTheMissionIsGoingIsAboutTheMission(HisMissionRunsWithoutHim):
    """Talked to her, 2026-10-11: "how is the move plan going" answered "No fleet reading yet" -
    the subject is no repository, and the mission he started was right there."""

    def test_a_status_question_naming_the_mission_is_answered_from_it(self):
        from aletheia import quick
        pg.add_words(self.pid, "also start planning a move somewhere warm", via="operator-voice", now=NOW)
        for asked in ("how is the move plan going", "how's the reboot going"):
            said = quick.answer(asked)
            self.assertIsNotNone(said, asked)
            self.assertIn("Project Reboot", said, asked)
            self.assertNotIn("fleet", said.lower(), asked)

    def test_a_subject_naming_no_mission_is_not_answered_with_one(self):
        from aletheia import quick
        self.assertIsNone(quick._mission_named("the trader"))

    def test_what_a_named_mission_waits_on_reaches_its_own_store(self):
        from aletheia import voice
        pg.add_words(self.pid, "also start planning a move somewhere warm", via="operator-voice", now=NOW)
        for asked in ("what's the move plan waiting on", "what's next on the move plan"):
            got = voice._interpret(asked)
            self.assertEqual(got["command"], {"kind": "missions", "about": "waiting", "which": self.pid}, asked)
        self.assertNotEqual((voice._interpret("what's the trader waiting on") or {}).get("command", {}).get("kind"),
                            "missions")

    def test_what_she_found_for_a_named_mission_is_its_steps(self):
        from aletheia import voice
        pg.add_words(self.pid, "also start planning a move somewhere warm", via="operator-voice", now=NOW)
        for asked in ("what have you found for the move plan", "what have you done on the reboot so far",
                      "what did you find out about the move"):
            got = voice._interpret(asked)
            self.assertEqual(got["command"], {"kind": "missions", "about": "steps", "which": self.pid}, asked)
        self.assertNotEqual((voice._interpret("what have you found about the trader") or {}).get("command", {})
                            .get("kind"), "missions")


class WhatHisPcDidAfterTheTwentiethFix(HisMissionRunsWithoutHim):
    """His PC, 2026-10-11 16:08Z: the ranked comparison's write-up has no look of its own - its
    sources are the look of the task it needs - so the stale-look check found nothing, and it wrote
    from 300-character pages again and refused again."""

    def _needs_an_old_look(self, **t6_more):
        def change(record):
            tasks = {t["key"]: t for t in record["tasks"]}
            tasks["t6"].update(state=ws.DONE, cursor=1, needs=[],
                               plan={"steps": [{"tool": "research", "for": "compare", "by": "reader",
                                                "args": {"question": "compare"}}], "requires": [], "gaps": []},
                               results=[{"at": "2026-09-16T15:00:00Z", "step": 0, "tool": "research",
                                         "outcome": "ok", "said": "Tampa: partial figures."}], **t6_more)
            tasks["t7"].update(title="Write the ranked comparison", state=ws.READY, cursor=0, needs=["t6"],
                               plan={"steps": [{"tool": "compose", "for": "write the ranked comparison",
                                                "by": "named", "args": {"path": "missions/ranked.md",
                                                                        "what": "rank them"}}],
                                     "requires": [], "gaps": []})
        pg.update(self.pid, change)

    def test_the_task_it_writes_from_looks_again_first_once(self):
        self._needs_an_old_look()
        out = program_run.run_task(self.pid, "t7", now=NOW)
        self.assertEqual(out["state"], ws.BLOCKED_EXTERNAL)
        tasks = {t["key"]: t for t in pg.load(self.pid)["tasks"]}
        self.assertEqual((tasks["t6"]["state"], tasks["t6"]["cursor"], tasks["t6"]["relooked"]),
                         (ws.READY, 0, research.REVISION))
        self.assertNotIn("compose", [n for n, _a in self.ran])

    def test_a_task_that_already_looked_again_is_written_from(self):
        self._needs_an_old_look(relooked=research.REVISION)
        program_run.run_task(self.pid, "t7", now=NOW)
        self.assertIn("compose", [n for n, _a in self.ran])


class HeCanPauseHisMission(HisMissionRunsWithoutHim):
    """Talked to her, 2026-10-11: "pause the move plan" went to the planner. `programs.set_state`
    had been written with no way to say it."""

    def setUp(self):
        super().setUp()
        pg.add_words(self.pid, "also start planning a move somewhere warm", via="operator-voice", now=NOW)

    def test_the_sentences_reach_the_mission(self):
        from aletheia import voice
        for asked, state in (("pause the move plan", "pause"), ("put the move plan on hold", "pause"),
                             ("resume my mission", "resume"), ("drop the reboot", "drop"),
                             ("stop working on the move plan", "pause")):
            got = voice._interpret(asked)
            self.assertEqual(got["command"], {"kind": "mission_state", "state": state, "which": self.pid}, asked)

    def test_other_things_that_pause_are_not_the_mission(self):
        from aletheia import voice
        for asked in ("pause the music", "stop applying to jobs", "cancel that", "resume"):
            got = (voice._interpret(asked) or {}).get("command") or {}
            self.assertNotEqual(got.get("kind"), "mission_state", asked)

    def test_paused_is_paused_and_resumed_is_on(self):
        from aletheia import intercom
        said = intercom._mission_state({"state": "pause", "which": self.pid}, "pause the move plan")
        self.assertIn("Paused Project Reboot", said)
        self.assertEqual(pg.load(self.pid)["state"], pg.PAUSED)
        self.assertIn("already paused", intercom._mission_state({"state": "pause", "which": self.pid}, ""))
        self.assertIn("is paused", pg.spoken_status(self.pid))
        self.assertIn("back on", intercom._mission_state({"state": "resume", "which": self.pid}, ""))
        self.assertEqual(pg.load(self.pid)["state"], pg.ACTIVE)

    def test_it_is_never_a_plan_step(self):
        from aletheia import agenda, intercom
        self.assertIn("mission_state", intercom.PLANNER_FORBIDDEN)
        self.assertIn("mission_state", agenda.FORBIDDEN_KINDS)


class WhatHisPcDidAfterTheTwentyFirstFix(HisMissionRunsWithoutHim):
    """His PC, 2026-10-11 17:03Z: the weekly sweep sat on the found text from before looks read
    dates, parked a day at a time to "look again for something dated" on that same reading."""

    def _parked(self, **more):
        def change(record):
            t2 = next(t for t in record["tasks"] if t["key"] == "t2")
            t2.update(state=ws.RETRY_LATER, cursor=1, needs=[], next="look again for something dated",
                      not_before="2099-01-01T00:00:00Z",
                      plan={"steps": [{"tool": "research", "for": "look", "by": "reader", "args": {}},
                                      {"tool": "calendar_hold", "for": "hold", "by": "named", "args": {}}],
                            "requires": [], "gaps": []},
                      results=[{"at": "2026-09-16T15:00:00Z", "step": 0, "tool": "research", "outcome": "ok",
                                "said": "A fair, sometime."}], **more)
        pg.update(self.pid, change)

    def test_a_parked_look_on_an_old_reading_looks_again_now_once(self):
        self._parked()
        self.assertIn("t2", [r["task"] for r in program_run.requeue_reclassified(now=NOW)])
        t2 = next(t for t in pg.load(self.pid)["tasks"] if t["key"] == "t2")
        self.assertEqual((t2["state"], t2["cursor"], t2["relooked"], t2["not_before"]),
                         (ws.READY, 0, research.REVISION, None))
        self.assertNotIn("t2", [r["task"] for r in program_run.requeue_reclassified(now=NOW)])

    def test_a_parked_look_on_the_current_reading_waits_its_day(self):
        self._parked(relooked=research.REVISION)
        self.assertNotIn("t2", [r["task"] for r in program_run.requeue_reclassified(now=NOW)])


class WhatHisPcDidAfterTheTwentySecondFix(HisHoursAndHisCalendar):
    """His PC, 2026-10-11 18:22Z, once holds were made at all: a free Saturday-morning walk (kept: he
    asked for his calendar filled with anything free in his hours), the newcomer-events task
    pencilled in its own name at a free slot tomorrow at 6:15 pm, and then asked him for a url."""

    WALK = "WWE South Dakota: Tails on the Trail - Saturday 2026-10-24 at 09:00, free"

    def test_anything_free_found_in_his_hours_is_held_whatever_it_is_about(self):
        with self._with_event(self.WALK):
            self._run_everything()
        self.assertEqual([a["title"] for name, a in self.ran if name == "calendar.hold"],
                         ["WWE South Dakota: Tails on the Trail"])

    def test_the_soonest_found_line_is_held(self):
        with self._with_event(self.WALK + "\n" + EVENT):
            self._run_everything()
        self.assertEqual([a["title"] for name, a in self.ran if name == "calendar.hold"],
                         ["Sioux Falls Fall Job Fair"])

    def test_a_hold_for_a_day_nothing_found_names_is_never_made(self):
        def other_day(system, text, *, context=None, validator=None, **kw):
            value = think(system, text, context=context, validator=None, **kw)
            if system is program_compose.ARGS_SYSTEM and "start" in (context or {}).get("arguments_needed", {}):
                value["args"].update(title="Sioux Falls Fall Job Fair", start="2026-10-17T18:15")
            return validator(value) if validator else value
        with mock.patch.object(program_run, "THINK", other_day), \
                mock.patch.object(program_run, "_dated_hold", lambda *a, **k: {}):
            self._run_everything()
        self.assertNotIn("calendar.hold", [name for name, _a in self.ran])
        self.assertIn("on that day", next(t for t in pg.load(self.pid)["tasks"] if t["key"] == "t3")["reason"])

    def test_a_hold_named_for_the_task_itself_is_never_made(self):
        def own_name(system, text, *, context=None, validator=None, **kw):
            value = think(system, text, context=context, validator=None, **kw)
            if system is program_compose.ARGS_SYSTEM and "title" in (context or {}).get("arguments_needed", {}):
                value["args"].update(title=(context or {}).get("task", {}).get("title"), start="2026-10-17T18:15")
            return validator(value) if validator else value
        # The page echoes the task's words, as a search for them does, so only its own name is wrong.
        echo = EVENT + "\nPencil the fitting events onto his calendar as tentative holds"
        with mock.patch.object(program_run, "THINK", own_name), self._with_event(echo), \
                mock.patch.object(program_run, "_dated_hold", lambda *a, **k: {}):
            self._run_everything()
        self.assertNotIn("calendar.hold", [name for name, _a in self.ran])
        self.assertIn("own name", next(t for t in pg.load(self.pid)["tasks"] if t["key"] == "t3")["reason"])

    def _made(self, title, start):
        from aletheia import calendar_reasoning, localtime
        import datetime as dt
        at = dt.datetime.fromisoformat(start).replace(tzinfo=localtime.operator_tz())
        return calendar_reasoning.hold(title, at.isoformat(), (at + dt.timedelta(hours=1)).isoformat())["event"]["id"]

    def test_a_wrong_hold_made_by_a_task_still_under_way_is_taken_back(self):
        from aletheia import calendar
        self._run_everything()
        bad = {"title": "Pencil the fitting events onto his calendar as tentative holds",
               "start": "2026-10-17T18:15"}
        event_id = self._made(bad["title"], bad["start"])

        def as_his_pc_left_it(record):
            t3 = next(t for t in record["tasks"] if t["key"] == "t3")
            t3["plan"]["steps"][0]["args"] = dict(bad)
            t3["results"] = [{"at": "2026-09-16T15:00:00Z", "step": 0, "tool": "calendar.hold", "outcome": "ok",
                              "said": "Pencilled in Pencil the fitting events onto his calendar"}]
            t3.update(state=ws.BLOCKED_USER, cursor=1, holds_rechecked=True)
        pg.update(self.pid, as_his_pc_left_it)
        released = program_run.requeue_reclassified(now=NOW)
        self.assertIn(("t3", "hold"), [(r["task"], r["was"]) for r in released])
        self.assertEqual(calendar.load(event_id)["status"], "CANCELLED")
        self.assertNotIn("t3", [r["task"] for r in program_run.requeue_reclassified(now=NOW)])     # once

    def test_a_right_hold_already_made_stays(self):
        from aletheia import calendar
        self._run_everything()
        good = {"title": "Sioux Falls Fall Job Fair", "start": "2026-10-15T18:00"}
        event_id = self._made(good["title"], good["start"])

        def made_it(record):
            t3 = next(t for t in record["tasks"] if t["key"] == "t3")
            t3["plan"]["steps"][0]["args"] = dict(good)
            t3["results"] = [{"at": "2026-09-16T15:00:00Z", "step": 0, "tool": "calendar.hold", "outcome": "ok",
                              "said": "Pencilled in Sioux Falls Fall Job Fair"}]
            t3.update(state=ws.BLOCKED_USER, cursor=1, holds_rechecked=True)
        pg.update(self.pid, made_it)
        self.assertNotIn("t3", [r["task"] for r in program_run.requeue_reclassified(now=NOW)])
        self.assertNotEqual(calendar.load(event_id)["status"], "CANCELLED")

    def test_a_sign_up_with_no_address_found_looks_again_instead_of_asking(self):
        self._run_everything()

        def sign_up(record):
            t6 = next(t for t in record["tasks"] if t["key"] == "t6")
            t6.update(state=ws.READY, cursor=0, results=[], uses=["event.register"],
                      does=["register for free events"],
                      plan={"steps": [{"tool": "event.register", "for": "register for free events", "by": "named",
                                       "score": None}], "requires": [], "gaps": []})
        pg.update(self.pid, sign_up)
        program_run.run_task(self.pid, "t6", now=NOW)
        t6 = next(t for t in pg.load(self.pid)["tasks"] if t["key"] == "t6")
        self.assertEqual(t6["state"], ws.RETRY_LATER, t6.get("reason"))
        self.assertNotIn("what should I use", str(t6.get("reason")))

    def test_an_address_asked_for_before_that_fix_is_asked_again_once_on_the_new_rule(self):
        # His PC, 2026-10-11 20:56Z: t12 still BLOCKED on "what should I use for url?" hours after
        # the fix that stops asking, because nothing requeued a question asked before it.
        self._run_everything()
        record = pg.load(self.pid)
        t6 = dict(next(t for t in record["tasks"] if t["key"] == "t6"))
        t6.update(cursor=0, run=None, results=[], uses=["event.register"], does=["register for free events"],
                  args_retried=True,
                  plan={"steps": [{"tool": "event.register", "for": "register for free events", "by": "named",
                                   "score": None}], "requires": [], "gaps": []})
        pg.hold(record, t6, {"kind": "user_decision", "question": "what should I use for url?"},
                reason="what should I use for url?", purpose="args", now=NOW,
                extra={"step": 0, "missing": ["url"]})
        pg.update(self.pid, lambda r: [t.update(t6) for t in r["tasks"] if t["key"] == "t6"])
        self.assertIn("t6", [r["task"] for r in program_run.requeue_reclassified(now=NOW)])
        program_run.run_task(self.pid, "t6", now=NOW)
        t6 = next(t for t in pg.load(self.pid)["tasks"] if t["key"] == "t6")
        self.assertEqual(t6["state"], ws.RETRY_LATER, t6.get("reason"))
        self.assertTrue(t6.get("where_retried"))
        # and once is once
        self.assertNotIn("t6", [r["task"] for r in program_run.requeue_reclassified(now=NOW)])

    def test_a_comparison_read_before_it_was_measured_against_his_town_is_done_once_more(self):
        # His PC, 2026-10-14: the move comparison still said "measured against New York, not Sioux
        # Falls" days after looks were measured against where he lives, because it stood as done.
        self._run_everything()
        record = pg.load(self.pid)
        look = next(t for t in record["tasks"] if t["state"] == ws.DONE and "warm red-state" in t["title"]
                    and any(s.get("tool") == "research" for s in t["plan"]["steps"]))
        i = next(n for n, s in enumerate(look["plan"]["steps"]) if s["tool"] == "research")

        def as_his_pc_left_it(r, revision):
            t = next(x for x in r["tasks"] if x["key"] == look["key"])
            t.update(state=ws.DONE, cursor=len(t["plan"]["steps"]))
            t.pop("baseline_rechecked", None)
            t["results"] = [{"at": "2026-09-16T15:00:00Z", "step": i, "tool": "research", "outcome": "ok",
                             "said": "Austin is 31% cheaper than New York.", "revision": revision}]
        # Read on the current reading: it stands.
        pg.update(self.pid, lambda r: as_his_pc_left_it(r, research.REVISION))
        self.assertNotIn(look["key"], [x["task"] for x in program_run.requeue_reclassified(now=NOW)])
        pg.update(self.pid, lambda r: as_his_pc_left_it(r, 4))
        released = [x for x in program_run.requeue_reclassified(now=NOW) if x["task"] == look["key"]]
        self.assertEqual([x["was"] for x in released], ["done"])
        self.assertIn("where he lives", released[0]["why"])
        self.assertEqual(self.task_state(look["key"]), ws.READY)
        pg.update(self.pid, lambda r: next(x for x in r["tasks"] if x["key"] == look["key"]).update(
            state=ws.DONE, cursor=len(look["plan"]["steps"])))
        self.assertNotIn(look["key"], [x["task"] for x in program_run.requeue_reclassified(now=NOW)])  # once


class WhatHisPcDidOnTheThirteenth(HisHoursAndHisCalendar):
    """His PC, 2026-10-13 23:49Z: the weekly sweep found new evenings, chose a time the trail walk
    already held, and was refused "it overlaps WWE South Dakota: Tails on the Trail" three times, so
    nothing it found that week reached his calendar."""

    TWO = ("Tails on the Trail - Thursday 2026-10-15 at 18:00, free, Sioux Falls\n"
           "Networking Night - Saturday 2026-10-17 at 11:00, free, Sioux Falls")

    def setUp(self):
        super().setUp()
        from pathlib import Path
        from aletheia import calendar
        # His calendar is read for real here, so each test gets its own.
        patcher = mock.patch.object(calendar, "CALENDAR_DIR", Path(self.tmp.name) / "calendar" / "events")
        patcher.start()
        self.addCleanup(patcher.stop)

    def _already_held(self):
        from aletheia import calendar_reasoning, localtime
        import datetime as dt
        start = dt.datetime(2026, 10, 15, 18, 0, tzinfo=localtime.operator_tz())
        made = calendar_reasoning.hold("WWE South Dakota: Tails on the Trail", start.isoformat(),
                                       (start + dt.timedelta(hours=1)).isoformat())
        self.assertTrue(made["created"], made)

    def test_what_is_already_on_his_calendar_is_skipped_for_the_next_thing_found(self):
        self._already_held()
        with self._with_event(self.TWO):
            self._run_everything()
        held = [a["title"] for n, a in self.ran if n == "calendar.hold"]
        self.assertTrue(held, self.ran)
        self.assertNotIn("Tails on the Trail", held)
        self.assertIn("Networking Night", held)
        stuck = [t["reason"] for t in pg.load(self.pid)["tasks"] if "overlaps" in str(t.get("reason") or "")]
        self.assertEqual(stuck, [])

    def test_a_clashing_time_already_chosen_is_chosen_again(self):
        self._already_held()
        with self._with_event(self.TWO):
            self._run_everything()
        record = pg.load(self.pid)
        t3 = next(t for t in record["tasks"] if t["key"] == "t3")
        tool = self.catalog["calendar.hold"]
        clash = {"start": "2026-10-15T18:00", "title": "Tails on the Trail"}
        self.assertIn("already on his calendar", program_run._wrong_hold(record, t3, tool, clash, NOW))
        # A hold already made is never wrong for clashing with itself or what it was checked against.
        self.assertNotIn("already on his calendar",
                         program_run._wrong_hold(record, t3, tool, clash, NOW, made_at=NOW))
        again = program_run._dated_hold(record, t3, tool, {}, NOW)
        self.assertEqual(again.get("title"), "Networking Night")

    def test_with_nothing_else_found_it_looks_again_rather_than_failing(self):
        self._already_held()
        with self._with_event("Tails on the Trail - Thursday 2026-10-15 at 18:00, free, Sioux Falls"):
            self._run_everything()
        self.assertNotIn("calendar.hold", [n for n, _a in self.ran])
        t3 = next(t for t in pg.load(self.pid)["tasks"] if t["key"] == "t3")
        self.assertEqual(t3["state"], ws.RETRY_LATER, t3.get("reason"))
        self.assertNotIn("failed", str(t3.get("reason")))

    def test_the_steps_view_names_every_open_decision_with_its_options(self):
        # "6 decisions for you" named four of them; he said "just ask here" (2026-10-14).
        self._run_everything()
        record = pg.load(self.pid)
        open_ = [d for d in record["decisions"] if d.get("state") == "open"]
        self.assertTrue(open_)
        said = pg.spoken_steps("Project Reboot")
        for d in open_:
            self.assertIn(f"decision {d['key']} | {d['question']} | options: " + " / ".join(d["options"]), said)
