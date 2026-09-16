"""Mission control: one screen, ten seconds, after hours away (brief milestone 5).

The screen is GENERIC: the state word, the mission cards, what needs him,
the ribbon and eyes derive from agent state, missions / plans / tasks,
approvals, the browser and the journal - never from one goal's records. A
mission type with more to show plugs in through the provider registry.

The builders are pure, so these hold the DERIVATION. The endpoint tests hold
the other half: the routes sit behind the Core's existing gate exactly like
every other read. The job hunt provider has its own file, test_mission_jobs.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

from aletheia import access, apply_run, core, journal, mission_control as mc, stateio

UTC = dt.timezone.utc
NOW = dt.datetime(2026, 9, 16, 15, 0, tzinfo=UTC)


def ago(minutes: float) -> str:
    return (NOW - dt.timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M:%SZ")


CORE_OK = {"heartbeat_age_s": 40.0, "alive": True}


def card(**over):
    value = {"id": "plan:x", "type": "plan", "title": "Barkly", "status": "OPEN", "next": "Her next step (1): fix CI"}
    value.update(over)
    return mc.mission_card(**value)


class TheHeaderSaysWhatSheIsDoing(unittest.TestCase):
    def test_every_state_word_is_the_briefs(self):
        from aletheia.current_state import AGENT_STATES
        for state in AGENT_STATES:
            with self.subTest(state=state):
                out = mc.header({"state": state, "step": "x"}, now=NOW, core=CORE_OK)
                self.assertEqual(out["state"], state)
                self.assertTrue(out["doing"].endswith("."))
                self.assertTrue(out["next"])

    def test_an_unknown_word_is_never_shown(self):
        self.assertEqual(mc.header({"state": "DANCING"}, now=NOW, core=CORE_OK)["state"], "IDLE")

    def test_acting_says_the_step_and_the_next_of_the_mission_in_the_browser(self):
        missions = [card(id="task:a", status="RUNNING", next="Finish it."),
                    card(id="research", type="research", title="Research", status="RUNNING", in_browser=True,
                         next="Read the next source, then write it up.")]
        out = mc.header({"state": "ACTING", "step": "reading a page at example.org"}, now=NOW, core=CORE_OK,
                        missions=missions)
        self.assertEqual(out["doing"], "Working: reading a page at example.org.")
        self.assertEqual(out["next"], "Read the next source, then write it up.")
        self.assertFalse(out["stale"])
        self.assertEqual(out["banner"], "")

    def test_idle_with_a_running_mission_says_between_steps(self):
        out = mc.header({"state": "IDLE"}, now=NOW, core=CORE_OK,
                        missions=[card(title="Nightly research", status="RUNNING", step="between rounds",
                                       next="Start round 3 within the hour.")])
        self.assertEqual(out["doing"], "Between steps: Nightly research is running (between rounds).")
        self.assertEqual(out["next"], "Nightly research: Start round 3 within the hour.")

    def test_quiet_with_nothing_moving_says_nothing_is_scheduled(self):
        out = mc.header({"state": "IDLE"}, now=NOW, core=CORE_OK, missions=[card(status="DONE", next="")])
        self.assertEqual(out["next"], "Nothing is scheduled.")

    def test_a_dead_heartbeat_is_stale_whatever_the_state_says(self):
        out = mc.header({"state": "ACTING", "step": "filling a form"}, now=NOW,
                        core={"heartbeat_age_s": 3600.0, "alive": False})
        self.assertTrue(out["stale"])
        self.assertIn("1 hour old", out["banner"])
        self.assertFalse(out["signals"][0]["ok"])

    def test_no_heartbeat_at_all_is_stale_too(self):
        out = mc.header({"state": "IDLE"}, now=NOW, core={"heartbeat_age_s": None, "alive": False})
        self.assertTrue(out["stale"])
        self.assertIn("missing", out["banner"])

    def test_a_provider_signal_banners_only_while_the_core_is_fine(self):
        signal = {"what": "research loop", "ok": False, "said": "quiet for 5 hours",
                  "banner": "Research looks stopped: quiet for 5 hours."}
        out = mc.header({"state": "IDLE"}, now=NOW, core=CORE_OK, signals=[signal])
        self.assertEqual(out["banner"], "Research looks stopped: quiet for 5 hours.")
        self.assertFalse(out["stale"])
        self.assertNotIn("banner", out["signals"][1])
        out = mc.header({"state": "IDLE"}, now=NOW, core={"heartbeat_age_s": 900.0, "alive": False}, signals=[signal])
        self.assertIn("heartbeat", out["banner"])

    def test_halted_says_nothing_happens_until_resume(self):
        out = mc.header({"state": "HALTED", "step": "operator pressed HALT"}, now=NOW, core=CORE_OK,
                        missions=[card(needs=[{"said": "x", "blocking": True}])], approvals=2)
        self.assertIn("operator pressed HALT", out["doing"])
        self.assertEqual(out["state"], "HALTED")
        self.assertEqual(out["next"], "Nothing, until you resume her.")

    def test_blocked_names_the_stuck_missions_next(self):
        missions = [card(status="BLOCKED", blockers=[{"said": "nobody can think"}],
                         next="Picks up when Claude is back at 21:40.")]
        out = mc.header({"state": "BLOCKED", "step": "nobody can think"}, now=NOW, core=CORE_OK, missions=missions)
        self.assertEqual(out["next"], "Picks up when Claude is back at 21:40.")

    def test_needs_you_names_the_first_and_counts_every_need_once(self):
        missions = [card(id="job-hunt", type="job_hunt", title="Job hunt", status="NEEDS YOU",
                         needs=[{"said": "Analyst at Brex: questions only you can answer", "blocking": True}],
                         needs_count=31),
                    card(id="task:setup", type="task", title="Operator setup", status="NEEDS YOU",
                         needs=[{"said": "create the ChatGPT project", "blocking": True}]),
                    card(id="plan:barkly", status="OPEN",
                         needs=[{"said": "step 2 is yours", "blocking": False}])]
        out = mc.header({"state": "NEEDS YOU", "step": "whatever the agent said"}, now=NOW, core=CORE_OK,
                        missions=missions, approvals=2)
        self.assertEqual(out["needs_you"], 34)
        self.assertEqual(out["needs_you_parts"], {"approvals": 2, "missions": 32})
        self.assertEqual(out["next"], "Job hunt: Analyst at Brex: questions only you can answer (and 33 more).")
        self.assertEqual(out["doing"], "Waiting on you: 2 approvals and 31 things for Job hunt and 1 thing for "
                                       "Operator setup.")

    def test_a_blocking_need_turns_quiet_into_needs_you(self):
        for quiet in ("IDLE", "WAITING", "LISTENING"):
            with self.subTest(state=quiet):
                out = mc.header({"state": quiet}, now=NOW, core=CORE_OK,
                                missions=[card(needs=[{"said": "say yes", "blocking": True}])])
                self.assertEqual(out["state"], "NEEDS YOU")
        out = mc.header({"state": "IDLE"}, now=NOW, core=CORE_OK,
                        missions=[card(needs=[{"said": "step 2 is yours", "blocking": False}])])
        self.assertEqual(out["state"], "IDLE")

    def test_today_says_what_was_done_and_what_failed(self):
        items = [{"at": ago(10), "tone": "good"}, {"at": ago(20), "tone": "alert"}, {"at": ago(30), "tone": "good"},
                 {"at": ago(5000), "tone": "alert"}]
        today = mc.today_tally(items, ago(600))
        self.assertEqual(today, {"done": 2, "problems": 1})
        out = mc.header({"state": "IDLE"}, now=NOW, core=CORE_OK, today=today)
        self.assertEqual(out["today"]["said"], "Today: 2 things done, 1 problem.")


class EveryMissionIsOneCardShape(unittest.TestCase):
    KEYS = {"id", "type", "title", "goal", "status", "step", "next", "blockers", "stuck", "needs",
            "needs_count", "progress", "counts", "receipts", "updated", "detail", "in_browser", "source"}

    def test_why_stuck_comes_from_recorded_blockers(self):
        self.assertEqual(mc.why_stuck("BLOCKED", [{"said": "the build machine is offline."}], []),
                         "Stuck because the build machine is offline.")
        self.assertEqual(mc.why_stuck("BLOCKED", [], []), "Marked blocked, but no blocker was recorded.")
        self.assertEqual(mc.why_stuck("NEEDS YOU", [], [{"said": "choose a bundle id", "blocking": True}]),
                         "Waiting on you: choose a bundle id.")
        self.assertEqual(mc.why_stuck("RUNNING", [], []), "")
        many = [{"said": f"b{i}"} for i in range(5)]
        self.assertEqual(mc.why_stuck("BLOCKED", many, []), "Stuck because b0; b1; b2; and 2 more.")

    def test_an_unknown_status_is_never_shown(self):
        self.assertEqual(card(status="VIBING")["status"], "OPEN")
        self.assertEqual(set(card()), self.KEYS)

    def test_a_charter_with_her_step_and_his(self):
        plan = {"slug": "barkly", "title": "Barkly", "goal": "Barkly on real iPhones", "state": "open",
                "created": ago(9000), "project": {"repo": "money_machine"},
                "steps": [{"n": 1, "text": "Get CI green", "state": "todo", "owner": "thea"},
                          {"n": 2, "text": "Turn on Pages", "state": "todo", "owner": "caleb"},
                          {"n": 3, "text": "Ship", "state": "todo", "owner": "thea", "needs": [2]}]}
        out = mc.plan_mission(plan)
        self.assertEqual(set(out), self.KEYS)
        self.assertEqual((out["id"], out["type"], out["status"]), ("plan:barkly", "charter", "OPEN"))
        self.assertEqual(out["next"], "Her next step (1): Get CI green")
        self.assertEqual(out["needs"][0]["said"], "step 2 is yours: Turn on Pages")
        self.assertFalse(out["needs"][0]["blocking"])     # she still has work: not stuck on him
        self.assertEqual(out["needs_count"], 0)
        self.assertEqual(out["progress"], {"done": 0, "total": 3, "unit": "steps"})
        self.assertEqual(out["receipts"][0], {"kind": "plan", "id": "barkly", "label": "plan"})

    def test_a_plan_only_he_can_move_needs_him_and_a_blocked_step_is_why(self):
        plan = {"slug": "p", "title": "P", "goal": "g", "state": "open", "created": ago(10),
                "steps": [{"n": 1, "text": "Fix it", "state": "blocked", "owner": "thea"},
                          {"n": 2, "text": "Choose", "state": "todo", "owner": "caleb"}]}
        out = mc.plan_mission(plan)
        self.assertEqual(out["type"], "plan")
        self.assertEqual(out["status"], "NEEDS YOU")
        self.assertEqual(out["needs_count"], 1)
        self.assertIn("Stuck because step 1 is blocked: Fix it", out["stuck"])
        plan["steps"][1]["state"] = "done"
        out = mc.plan_mission(plan)
        self.assertEqual(out["status"], "BLOCKED")

    def test_tasks_filed_under_a_plan_are_its_blockers_and_needs(self):
        plan = {"slug": "wall", "title": "Wall", "goal": "g", "state": "open", "created": ago(10),
                "steps": [{"n": 1, "text": "A", "state": "doing"}]}
        tasks = [{"id": "wall-s1", "goal": "wall", "status": "FAILED_RETRYABLE", "error": "Pages 404",
                  "updated_at": ago(5)},
                 {"id": "wall-s2", "goal": "wall", "status": "WAITING_OPERATOR", "description": "add the token"}]
        out = mc.plan_mission(plan, tasks)
        self.assertEqual(out["status"], "RUNNING")
        self.assertEqual(out["step"], "A")
        self.assertIn("task wall-s1: Pages 404", out["stuck"])
        self.assertEqual(out["needs_count"], 1)

    def test_proposed_waits_for_his_yes_and_finished_plans_are_not_missions(self):
        plan = {"slug": "p", "title": "P", "goal": "g", "state": "proposed", "created": ago(10), "steps": []}
        self.assertEqual(mc.plan_mission(plan)["status"], "PROPOSED")
        for state in ("done", "dropped"):
            self.assertIsNone(mc.plan_mission(dict(plan, state=state)))

    def test_a_standalone_task(self):
        index = {"dep": {"id": "dep", "status": "QUEUED"}}
        out = mc.task_mission({"id": "t", "description": "Verify the campaign", "status": "QUEUED",
                               "dependencies": ["dep"], "updated_at": ago(3)}, index)
        self.assertEqual(out["status"], "WAITING")
        self.assertEqual(out["stuck"], "Stuck because waiting on dep.")
        out = mc.task_mission({"id": "s", "description": "Operator: create the project", "status": "WAITING_OPERATOR",
                               "result": "the ChatGPT project is the last step"})
        self.assertEqual((out["status"], out["needs_count"]), ("NEEDS YOU", 1))
        self.assertIsNone(mc.task_mission({"id": "d", "description": "x", "status": "COMPLETED"}))

    def test_a_budgeted_mission_running_expired_and_old(self):
        record = {"id": "m-1", "kind": "fix_projects", "goal": "Fix the repos", "state": "RUNNING",
                  "created_at": ago(30), "expires": ago(-60), "max_actions": 12, "actions_used": 4,
                  "log": [{"at": ago(2), "entry": "opened a PR on schwab-trader", "spent": 1}]}
        out = mc.budget_mission(record, NOW)
        self.assertEqual((out["status"], out["title"]), ("RUNNING", "Fix projects"))
        self.assertEqual(out["step"], "opened a PR on schwab-trader")
        self.assertIn("8 more", out["next"])
        self.assertEqual(out["receipts"][0]["kind"], "mission")
        # past its deadline but not yet recorded: judged by the clock, not by writing
        out = mc.budget_mission(dict(record, expires=ago(1)), NOW)
        self.assertEqual(out["status"], "STOPPED")
        self.assertIn("its time ran out", out["stuck"])
        ended = dict(record, state="STOPPED", ended_at=ago(90), ended_because="stopped by operator-local")
        self.assertEqual(mc.budget_mission(ended, NOW)["status"], "STOPPED")
        self.assertIsNone(mc.budget_mission(dict(ended, ended_at=ago(3 * 1440)), NOW))

    def test_generic_missions_attach_tasks_to_their_plan_and_order_by_attention(self):
        plans = [{"slug": "wall", "title": "Wall", "goal": "g", "state": "open", "created": ago(10),
                  "steps": [{"n": 1, "text": "A", "state": "todo"}]}]
        tasks = [{"id": "wall-s4", "goal": "wall", "status": "QUEUED", "description": "x"},
                 {"id": "loose", "status": "BLOCKED", "description": "y", "error": "no key"},
                 {"id": "setup", "status": "WAITING_OPERATOR", "description": "z"}]
        out = mc.order_missions(mc.generic_missions(mission_record=None, plans=plans, tasks=tasks, now=NOW))
        self.assertEqual([m["id"] for m in out], ["task:setup", "task:loose", "plan:wall"])
        needs = mc.needs_list(out, [{"id": "ap-1", "label": "Remember the landlord"}])
        self.assertEqual([(n["kind"], n["id"]) for n in needs], [("approval", "ap-1"), ("mission", "task:setup")])


class TheRibbonIsSentencesWithReceipts(unittest.TestCase):
    def test_newest_first_noise_dropped_every_line_has_a_receipt(self):
        entries = [
            {"ts": ago(50), "kind": "action", "subject": "task:wall-s3", "text": "QUEUED -> COMPLETED"},
            {"ts": ago(40), "kind": "action", "subject": "formfill", "text": "read 120 fields on https://x"},
            {"ts": ago(35), "kind": "action", "subject": "research", "text": "wrote the brief on heat pumps"},
            {"ts": ago(30), "kind": "event", "subject": "access", "text": "tok-1 GET /api/status"},
            {"ts": ago(20), "kind": "alert", "subject": "core", "text": "sync could not push"},
        ]
        sessions = [{"id": "agent-abc", "saved_at": ago(5), "outcome": "answered",
                     "question": "what are you doing?", "model": "ollama:qwen3-vl:4b",
                     "sources": [{"tool": "state.now", "provenance": "TRUSTED_LOCAL_STATE"}]}]
        extra = [{"at": ago(10), "tone": "good", "what": "Research", "said": "Finished the heat pump brief.",
                  "receipt": {"kind": "research", "id": "r-1"}},
                 {"at": ago(11), "tone": "good", "said": "a line with no receipt is dropped"}]
        out = mc.ribbon(journal_entries=entries, sessions=sessions, extra=extra)
        said = [i["said"] for i in out]
        self.assertEqual(said, ["Answered “what are you doing?” after looking at state.now.",
                                "Finished the heat pump brief.", "Sync could not push",
                                "Wrote the brief on heat pumps", "QUEUED -> COMPLETED"])
        self.assertEqual(out[2]["tone"], "alert")
        self.assertEqual(out[4]["what"], "Tasks")
        self.assertTrue(all(i["receipt"]["kind"] for i in out))
        # provenance is receipt material, never the sentence
        self.assertFalse(any("qwen" in s for s in said))

    def test_a_provider_can_take_over_its_subjects_but_never_their_alerts(self):
        entries = [{"ts": ago(5), "kind": "action", "subject": "research", "text": "fetched a page"},
                   {"ts": ago(4), "kind": "alert", "subject": "research", "text": "the source refused"}]
        out = mc.ribbon(journal_entries=entries, skip_subjects={"research"}, labels={"research": "Research"})
        self.assertEqual([(i["what"], i["said"]) for i in out], [("Research", "The source refused")])

    def test_journal_receipt_ids_are_stable(self):
        entry = {"ts": ago(1), "subject": "core", "text": "local Core up"}
        self.assertEqual(mc.journal_id(entry), mc.journal_id(dict(entry)))
        self.assertTrue(mc.journal_id(entry).startswith("j-"))


class EyesShowOnlyWhatIsRecorded(unittest.TestCase):
    def test_the_browser_and_the_first_candidate(self):
        browser = {"active": True, "site": "example.org", "purpose": "reading a source", "stage": "reading",
                   "last": {"site": "a.org", "what": "a page", "state": "done", "at": ago(5)}}
        shots = [{"id": "x", "of": "the page she is on", "title": "t", "src": "/api/mission/screenshot?id=x"},
                 {"id": "y", "src": "/api/mission/screenshot?id=y"}]
        out = mc.eyes(browser, screenshots=shots)
        self.assertEqual((out["site"], out["screenshot"]["id"], out["last"]["title"]), ("example.org", "x", "a page"))
        self.assertIsNone(mc.eyes({}, screenshots=[])["screenshot"])


def fake_provider(**over):
    def read(ctx):
        return {"n": 2, "notes": ["one store was half-read"]}

    def build(reading, ctx):
        return {"missions": [mc.mission_card(id="research-1", type="research", title="Heat pumps",
                                             status="RUNNING", next="Write it up.", detail=True)],
                "claims": ["ap-claimed"],
                "signals": [{"what": "research loop", "ok": True, "said": f"{reading['n']} rounds"}],
                "activity": [{"at": ctx["now"].strftime("%Y-%m-%dT%H:%M:%SZ"), "tone": "good", "what": "Research",
                              "said": "Read two sources.", "receipt": {"kind": "research", "id": "research-1"}}],
                "screenshots": [], "details": {"research-1": {"type": "research", "sources": 2}}}

    value = dict(type="research", label="Research", read=read, build=build,
                 receipt_kinds=("research",), receipt=lambda kind, ident: {"kind": kind, "id": ident, "record": {}})
    value.update(over)
    return mc.Provider(**value)


class IsolatedStores(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        env = mock.patch.dict(os.environ, {"ALETHEIA_PRIVATE_STATE": str(root / "private")})
        env.start()
        self.addCleanup(env.stop)
        p = mock.patch.object(journal, "JOURNAL_PATH", root / "journal.jsonl")
        p.start()
        self.addCleanup(p.stop)
        # approvals bind their directory at import: without this a test's
        # pending approval leaks into every later test in the run
        from aletheia import policy
        p = mock.patch.object(policy, "APPROVALS_DIR", root / "approvals")
        p.start()
        self.addCleanup(p.stop)
        mc.forget_cache()
        self.addCleanup(mc.forget_cache)
        from aletheia import current_state
        current_state.forget_cache()
        self.addCleanup(current_state.forget_cache)


class TheRegistryPlugsTypesIn(IsolatedStores):
    def test_the_registry_is_explicit_and_holds_the_job_hunt(self):
        # Explicit and small: the job hunt is one type, beside the general
        # ones every goal uses (any browser goal, any request she handed him).
        registered = mc.registry()
        self.assertEqual(list(registered), ["job_hunt", "browser_goal", "agent_request"])
        for provider in registered.values():
            self.assertTrue(callable(provider.read) and callable(provider.build))

    def test_a_new_type_adds_a_provider_not_a_screen(self):
        out = mc.gather(fresh=True, providers={"research": fake_provider()})
        mission = [m for m in out["missions"] if m["id"] == "research-1"][0]
        self.assertEqual((mission["type"], mission["status"]), ("research", "RUNNING"))
        self.assertEqual(out["details"]["research-1"], {"type": "research", "sources": 2})
        self.assertIn({"what": "research loop", "ok": True, "said": "2 rounds"}, out["header"]["signals"])
        self.assertEqual(out["ribbon"][0]["said"], "Read two sources.")
        self.assertIn("one store was half-read", out["notes"])
        self.assertEqual(out["providers"], [{"type": "research", "label": "Research"}])
        self.assertEqual(mc.receipt("research", "research-1", providers={"research": fake_provider()})["id"],
                         "research-1")
        self.assertIsNone(mc.receipt("research", "research-1", providers={}))

    def test_a_provider_that_breaks_does_not_blank_the_screen(self):
        def explode(*_a):
            raise RuntimeError("boom")
        out = mc.gather(fresh=True, providers={"a": fake_provider(type="a", build=explode),
                                               "b": fake_provider(type="b", label="Other", read=explode)})
        self.assertIn("header", out)
        self.assertTrue(any("could not be read (RuntimeError)" in n for n in out["notes"]))
        self.assertFalse(any(m["id"] == "research-1" for m in out["missions"]))

    def test_claimed_approvals_are_not_counted_twice(self):
        from aletheia import policy
        policy.request("ap-claimed", "x", "y", "claimed by the provider", True)
        policy.request("ap-free", "x", "y", "Remember the landlord", True)
        out = mc.gather(fresh=True, providers={"research": fake_provider()})
        self.assertEqual([n["id"] for n in out["needs_you"] if n["kind"] == "approval"], ["ap-free"])
        self.assertEqual(out["header"]["needs_you_parts"]["approvals"], 1)


class TheRoutesSitBehindTheSameGate(IsolatedStores):
    """Loopback reads openly, like /api/status; a remote caller needs a real
    token, like /api/status. Nothing new is reachable that was not before."""

    def setUp(self):
        super().setUp()
        access.clear_failures()
        self.addCleanup(access.clear_failures)
        self.server = core.make_server(port=0)
        self.port = self.server.server_address[1]
        self.addCleanup(self.server.server_close)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.shutdown)
        # one record with a screenshot the page may show
        home = apply_run.staged_dir()
        home.mkdir(parents=True, exist_ok=True)
        self.png = home / "apply-0000beef.png"
        self.png.write_bytes(b"\x89PNG\r\n\x1a\nfake")
        stateio.write_json_atomic(home / "apply-0000beef.json", {
            "id": "apply-0000beef", "state": "FAILED", "url": "https://jobs.lever.co/x/apply",
            "company": "Beef Co", "job_title": "Analyst", "staged_at": stateio.utcnow(),
            "failure": "ApplyError: she could not find the button", "screenshot": str(self.png)})

    def fetch(self, path, token=None, remote=False):
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        request = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", headers=headers)
        patch = mock.patch.object(core.access, "is_loopback", side_effect=lambda a: False) if remote \
            else mock.patch.object(core.access, "is_loopback", wraps=core.access.is_loopback)
        with patch:
            try:
                with urllib.request.urlopen(request, timeout=30) as response:
                    return response.status, response.headers.get("Content-Type"), response.read()
            except urllib.error.HTTPError as exc:
                return exc.code, exc.headers.get("Content-Type"), exc.read()

    def test_loopback_reads_the_mission_screen(self):
        status, _ctype, body = self.fetch("/api/mission")
        self.assertEqual(status, 200)
        value = json.loads(body)
        for part in ("header", "missions", "needs_you", "ribbon", "eyes", "details", "providers"):
            self.assertIn(part, value)
        from aletheia.current_state import AGENT_STATES
        self.assertIn(value["header"]["state"], AGENT_STATES)
        hunt = [m for m in value["missions"] if m["type"] == "job_hunt"][0]
        self.assertTrue(hunt["detail"])
        pipe = value["details"][hunt["id"]]["pipeline"]
        stopped = [s for s in pipe["off_ramps"] if s["stage"] == "STOPPED"][0]
        self.assertEqual(stopped["cards"][0]["why_not_sent"], "She could not find the button.")
        self.assertTrue(stopped["cards"][0]["screenshot"])
        self.assertEqual(value["eyes"]["screenshot"]["id"], "apply-0000beef")

    def test_remote_without_a_token_is_refused_on_every_route(self):
        for path in ("/api/mission", "/api/mission/receipt?kind=application&id=apply-0000beef",
                     "/api/mission/receipt?kind=plan&id=barkly",
                     "/api/mission/screenshot?id=apply-0000beef"):
            with self.subTest(path=path):
                status, _ctype, body = self.fetch(path, remote=True)
                self.assertEqual(status, 401)
                self.assertEqual(json.loads(body), {"error": "unauthorized"})

    def test_a_read_token_reads_them(self):
        token, _ = access.mint("iPhone", scope="read")
        status, _ctype, body = self.fetch("/api/mission", token=token, remote=True)
        self.assertEqual(status, 200)
        self.assertIn("header", json.loads(body))

    def test_the_receipt_and_the_screenshot(self):
        status, _ctype, body = self.fetch("/api/mission/receipt?kind=application&id=apply-0000beef")
        self.assertEqual(status, 200)
        receipt = json.loads(body)
        self.assertEqual(receipt["record"]["company"], "Beef Co")
        self.assertEqual(receipt["record"]["_explained"]["stage"], "STOPPED")
        status, ctype, body = self.fetch("/api/mission/screenshot?id=apply-0000beef")
        self.assertEqual(status, 200)
        self.assertEqual(ctype, "image/png")
        self.assertTrue(body.startswith(b"\x89PNG"))

    def test_generic_receipts(self):
        from aletheia import tasks
        with mock.patch.object(tasks, "TASKS_DIR", Path(self.tmp.name) / "tasks"):
            tasks.TASKS_DIR.mkdir()
            stateio.write_json_atomic(tasks.TASKS_DIR / "call-the-plumber.json",
                                      {"id": "call-the-plumber", "description": "call the plumber",
                                       "status": "QUEUED", "created_at": ago(1), "updated_at": ago(1), "attempts": 0})
            status, _ctype, body = self.fetch("/api/mission/receipt?kind=task&id=call-the-plumber")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["record"]["description"], "call the plumber")

    def test_nothing_outside_the_records_is_served(self):
        for path in ("/api/mission/receipt?kind=application&id=../../secrets",
                     "/api/mission/receipt?kind=session&id=..%2Fx",
                     "/api/mission/receipt?kind=plan&id=..%2F..%2Fconfig%2Ffleet",
                     "/api/mission/receipt?kind=task&id=..%5Cx",
                     "/api/mission/receipt?kind=mission&id=m-nope",
                     "/api/mission/receipt?kind=shell&id=x",
                     "/api/mission/screenshot?id=nope"):
            with self.subTest(path=path):
                self.assertEqual(self.fetch(path)[0], 404)
        # a record pointing its screenshot outside the applications directory
        outside = Path(self.tmp.name) / "elsewhere.png"
        outside.write_bytes(b"\x89PNG")
        record = apply_run.load_run("apply-0000beef")
        record["screenshot"] = str(outside)
        stateio.write_json_atomic(apply_run.staged_dir() / "apply-0000beef.json", record)
        self.assertEqual(self.fetch("/api/mission/screenshot?id=apply-0000beef")[0], 404)

    def test_the_routes_only_read(self):
        request = urllib.request.Request(f"http://127.0.0.1:{self.port}/api/mission", data=b"{}",
                                         headers={"Content-Type": "application/json",
                                                  "X-Aletheia-Local": access.local_secret()},
                                         method="POST")
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(request, timeout=10)
        self.assertEqual(ctx.exception.code, 404)


if __name__ == "__main__":
    unittest.main()
