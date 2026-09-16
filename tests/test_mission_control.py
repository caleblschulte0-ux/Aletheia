"""Mission control: one screen, ten seconds, after hours away (brief milestone 5).

The builders are pure, so these hold the DERIVATION: which state word, which
"next" sentence, which pipeline stage a record lands in, and what the card
says when it did not send. The endpoint tests hold the other half - the new
routes sit behind the Core's existing gate exactly like every other read.
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
LOOP_OK = {"alive": True, "stale": False, "said": "a batch is running"}


class TheHeaderSaysWhatSheIsDoing(unittest.TestCase):
    def test_every_state_word_is_the_briefs(self):
        from aletheia.current_state import AGENT_STATES
        for state in AGENT_STATES:
            with self.subTest(state=state):
                out = mc.header({"state": state, "step": "x"}, now=NOW, core=CORE_OK, loop=LOOP_OK)
                self.assertEqual(out["state"], state)
                self.assertTrue(out["doing"].endswith("."))
                self.assertTrue(out["next"])

    def test_an_unknown_word_is_never_shown(self):
        out = mc.header({"state": "DANCING"}, now=NOW, core=CORE_OK, loop=LOOP_OK)
        self.assertEqual(out["state"], "IDLE")

    def test_acting_says_the_step_and_what_follows_the_batch(self):
        out = mc.header({"state": "ACTING", "mission": "job hunt",
                         "step": "sending the application for Analyst at Figma - pressing submit"},
                        now=NOW, core=CORE_OK, loop=LOOP_OK,
                        hunt={"running": True, "campaign": {"count": 8}})
        self.assertEqual(out["doing"], "Working: sending the application for Analyst at Figma - pressing submit.")
        self.assertIn("batch of 8", out["next"])
        self.assertIn("another within 5 minutes", out["next"])
        self.assertFalse(out["stale"])
        self.assertEqual(out["banner"], "")

    def test_a_refill_is_not_called_a_batch(self):
        out = mc.header({"state": "ACTING", "step": "re-reading"}, now=NOW, core=CORE_OK, loop=LOOP_OK,
                        hunt={"running": True, "campaign": {"kind": "retry", "limit": 60}})
        self.assertIn("re-reading up to 60 waiting applications", out["next"])

    def test_a_dead_heartbeat_is_stale_whatever_the_state_says(self):
        out = mc.header({"state": "ACTING", "step": "filling a form"}, now=NOW,
                        core={"heartbeat_age_s": 3600.0, "alive": False}, loop=LOOP_OK)
        self.assertTrue(out["stale"])
        self.assertIn("1 hour old", out["banner"])
        self.assertFalse(out["signals"][0]["ok"])

    def test_no_heartbeat_at_all_is_stale_too(self):
        out = mc.header({"state": "IDLE"}, now=NOW, core={"heartbeat_age_s": None, "alive": False},
                        loop=LOOP_OK)
        self.assertTrue(out["stale"])
        self.assertIn("missing", out["banner"])

    def test_a_quiet_apply_loop_is_said_plainly(self):
        loop = mc.apply_loop(None, [{"ts": ago(300), "subject": "apply:forever", "text": "started"}], NOW)
        self.assertIs(loop["alive"], False)
        out = mc.header({"state": "IDLE"}, now=NOW, core=CORE_OK, loop=loop)
        self.assertIn("5 hours", out["next"])
        self.assertIn("job hunt looks stopped", out["banner"])
        self.assertFalse(out["stale"])      # the Core is fine; the hunt is not

    def test_halted_says_nothing_happens_until_resume(self):
        out = mc.header({"state": "HALTED", "step": "operator pressed HALT"}, now=NOW, core=CORE_OK,
                        loop={"alive": None, "said": "halted with everything else"})
        self.assertIn("operator pressed HALT", out["doing"])
        self.assertEqual(out["next"], "Nothing, until you resume her.")

    def test_blocked_names_when_claude_is_back(self):
        hunt = {"thinking": {"claude": {"resting_until": "2026-09-16T21:40:00Z"}}}
        out = mc.header({"state": "BLOCKED", "step": "nobody can think"}, now=NOW, core=CORE_OK,
                        loop={"alive": None}, hunt=hunt, say_time=lambda when: when.strftime("%H:%M"))
        self.assertIn("Claude is back at 21:40", out["next"])

    def test_needs_you_names_the_first_and_counts_the_rest_once(self):
        hunt = {"waiting_on_him": [{"company": "Brex", "why": "questions only you can answer"}]}
        out = mc.header({"state": "NEEDS YOU", "step": "1 application waiting on you"}, now=NOW,
                        core=CORE_OK, loop=LOOP_OK, hunt=hunt, pending_approvals=2,
                        applications_waiting=31)
        self.assertIn("Brex is waiting on you: questions only you can answer (and 30 more)", out["next"])
        self.assertEqual(out["doing"], "Waiting on you: 31 applications and 2 approvals waiting on you.")
        # an application's approval is not counted a second time
        self.assertEqual(out["needs_you"], 33)


class TheApplyLoopIsJudgedFromWhatItLeaves(unittest.TestCase):
    def test_a_running_batch_is_alive(self):
        out = mc.apply_loop({"running": True, "started_at": ago(12)}, [], NOW)
        self.assertIs(out["alive"], True)
        self.assertIn("12 minutes", out["said"])

    def test_a_three_hour_lock_is_the_stale_lock(self):
        out = mc.apply_loop({"running": True, "started_at": ago(200)}, [], NOW)
        self.assertTrue(out["stale"])
        self.assertIsNone(out["alive"])

    def test_a_recent_journal_line_is_alive(self):
        out = mc.apply_loop(None, [{"ts": ago(4), "subject": "apply:forever"}], NOW)
        self.assertIs(out["alive"], True)

    def test_resting_or_halted_is_expected_quiet_not_death(self):
        entries = [{"ts": ago(400), "subject": "apply:forever"}]
        self.assertIsNone(mc.apply_loop(None, entries, NOW, resting=True)["alive"])
        self.assertIsNone(mc.apply_loop(None, entries, NOW, halted=True)["alive"])

    def test_never_seen_is_not_alive(self):
        out = mc.apply_loop(None, [{"ts": ago(1), "subject": "core"}], NOW)
        self.assertIs(out["alive"], False)
        self.assertIn("no sign", out["said"])


def rec(run_id, state, **fields):
    value = {"id": run_id, "state": state, "url": f"https://jobs.lever.co/{run_id}/apply",
             "company": run_id.title(), "job_title": "Operations Analyst", "staged_at": ago(60)}
    value.update(fields)
    return value


class ThePipelineIsCountedFromTheRecords(unittest.TestCase):
    def test_each_state_lands_in_its_stage(self):
        cases = [
            (rec("a", "SUBMITTED"), {}, "SENT"),
            (rec("b", "SUBMITTED", outcome="replied"), {}, "REPLIED"),
            (rec("c", "SUBMITTED", outcome="rejected"), {}, "REPLIED"),
            (rec("d", "SUBMITTED", outcome="interview"), {}, "INTERVIEW"),
            (rec("e", "SUBMITTING"), {}, "APPLYING"),
            (rec("f", "NEEDS_YOU"), {}, "NEEDS YOU"),
            (rec("g", "NEEDS_ACCOUNT"), {}, "NEEDS YOU"),
            (rec("h", "AWAITING_YOU"), {"approval_state": "APPROVED"}, "APPLYING"),
            (rec("i", "AWAITING_YOU"), {"approval_state": "PENDING"}, "NEEDS YOU"),
            (rec("j", "AWAITING_YOU"), {"approval_state": "APPROVED", "his_ok": "part-time"}, "NEEDS YOU"),
            (rec("k", "FAILED"), {}, "STOPPED"),
            (rec("l", "REJECTED"), {}, "STOPPED"),
            (rec("m", "CLOSED"), {}, "SET ASIDE"),
        ]
        for record, facts, stage in cases:
            with self.subTest(record=record["id"]):
                self.assertEqual(mc.stage_of(record, **facts), stage)

    def test_a_live_grant_moves_a_filled_form_to_applying(self):
        self.assertEqual(mc.stage_of(rec("x", "AWAITING_YOU"), approval_state="PENDING", grant_live=True),
                         "APPLYING")

    def test_counts_cards_and_off_ramps(self):
        records = [rec("s1", "SUBMITTED", submitted_at=ago(30)), rec("s2", "SUBMITTED", submitted_at=ago(3000)),
                   rec("n1", "NEEDS_YOU", questions=[{"label": "Preferred shift"}]),
                   rec("f1", "FAILED", failure="ApplyError: she could not find the button that submits this form"),
                   rec("c1", "CLOSED", closed_because="not realistic: 7+ years"),
                   {"not": "a record"}]
        out = mc.pipeline(records, today_floor=ago(600), discovery_today={"discovered": 312, "qualified": 40})
        stages = {s["stage"]: s for s in out["stages"]}
        self.assertEqual([s["stage"] for s in out["stages"]], list(mc.STAGES))
        self.assertEqual(stages["SENT"]["count"], 2)
        self.assertEqual(stages["SENT"]["today"], 1)
        self.assertEqual(stages["NEEDS YOU"]["count"], 1)
        self.assertEqual(stages["DISCOVERED"]["count"], 312)
        self.assertEqual(stages["REVIEWED"]["count"], 40)
        self.assertEqual(stages["DISCOVERED"]["source"], "today's discovery summary")
        ramps = {s["stage"]: s for s in out["off_ramps"]}
        self.assertEqual(ramps["STOPPED"]["count"], 1)
        self.assertEqual(ramps["SET ASIDE"]["count"], 1)
        self.assertEqual(out["records"], 5)
        card = ramps["STOPPED"]["cards"][0]
        self.assertEqual(card["why_not_sent"], "She could not find the button that submits this form.")

    def test_no_discovery_today_is_unknown_not_zero(self):
        out = mc.pipeline([], discovery_today=None)
        discovered = out["stages"][0]
        self.assertIsNone(discovered["count"])
        self.assertIn("no discovery", discovered["source"])

    def test_cards_are_newest_first_and_capped(self):
        records = [rec(f"s{i}", "SUBMITTED", submitted_at=ago(i)) for i in range(20)]
        sent = [s for s in mc.pipeline(records, per_stage=5)["stages"] if s["stage"] == "SENT"][0]
        self.assertEqual(sent["count"], 20)
        self.assertEqual([c["id"] for c in sent["cards"]], ["s0", "s1", "s2", "s3", "s4"])


class TheCardAnswersBothQuestions(unittest.TestCase):
    def test_why_this_one_prefers_job_values_reasons(self):
        record = rec("v", "SUBMITTED", why_she_liked_it=["it pays $95,000", "it is in Sioux Falls"],
                     why_not=["it asks for 3 years"], value=71, queue="outlier",
                     fit={"why": "the model's view", "by": "model:codex"})
        why = mc.why_this_one(record)
        self.assertEqual(why["source"], "job_value")
        self.assertIn("it pays $95,000", why["said"])
        self.assertIn("against it", why["said"])
        self.assertEqual(why["queue"], "outlier")

    def test_why_this_one_falls_back_to_the_fit_without_naming_the_model(self):
        why = mc.why_this_one(rec("f", "SUBMITTED", fit={"why": "operations role he fits", "by": "model:codex"}))
        self.assertEqual(why["said"], "operations role he fits")
        self.assertNotIn("codex", json.dumps(why))

    def test_an_unscored_record_says_nothing_rather_than_inventing(self):
        self.assertIsNone(mc.why_this_one(rec("u", "FAILED")))

    def test_why_not_sent_in_plain_words(self):
        cases = [
            (rec("a", "FAILED", failure="TargetClosedError: BrowserType.launch_persistent_context: Target page, "
                                        "context or browser has been closed"), {},
             "the browser closed"),
            (rec("b", "NEEDS_YOU", questions=[{"label": "Please identify your race*"}]), {},
             "only you can answer: Please identify your race*"),
            (rec("c", "AWAITING_YOU"), {"his_ok": "part-time"}, "part-time work"),
            (rec("d", "AWAITING_YOU"), {"his_ok": "judged-locally"}, "her own model"),
            (rec("e", "AWAITING_YOU"), {"approval_state": "PENDING"}, "waits for your OK"),
            (rec("f", "AWAITING_YOU"), {"approval_state": "PENDING", "grant_live": True}, "standing grant sends it"),
            (rec("g", "REJECTED"), {}, "handed the form back"),
            (rec("h", "FAILED", click_evidence={"captcha": "hcaptcha"}), {}, "CAPTCHA"),
            (rec("i", "CLOSED", closed_because="the same job is already waiting"), {}, "Set aside: the same job"),
            (rec("j", "SUBMITTING"), {}, "never recorded"),
        ]
        for record, facts, words in cases:
            with self.subTest(record=record["id"]):
                stage = mc.stage_of(record, **facts)
                said = mc.why_not_sent(record, stage=stage, **facts)
                self.assertIn(words, said)
                self.assertNotRegex(said, r"^[A-Z][A-Za-z]+Error:")

    def test_a_sent_application_has_no_blocker(self):
        self.assertEqual(mc.why_not_sent(rec("s", "SUBMITTED"), stage="SENT"), "")


class TheRibbonIsSentencesWithReceipts(unittest.TestCase):
    def test_newest_first_noise_dropped_every_line_has_a_receipt(self):
        entries = [
            {"ts": ago(50), "kind": "action", "subject": "apply:forever", "actor": "aletheia-apply-forever",
             "text": "started another batch of 8"},
            {"ts": ago(40), "kind": "action", "subject": "formfill", "text": "read 120 fields on https://x"},
            {"ts": ago(35), "kind": "action", "subject": "apply", "text": "closed apply-1234abcd without applying"},
            {"ts": ago(30), "kind": "event", "subject": "access", "text": "tok-1 GET /api/status"},
            {"ts": ago(20), "kind": "alert", "subject": "apply:forever", "text": "a batch could not start"},
        ]
        records = [rec("s1", "SUBMITTED", submitted_at=ago(10)),
                   rec("f1", "FAILED", staged_at=ago(15), failure="there is no application form on this page")]
        sessions = [{"id": "agent-abc", "saved_at": ago(5), "outcome": "answered",
                     "question": "how did applications go today?", "model": "ollama:qwen3-vl:4b",
                     "sources": [{"tool": "applications.query", "provenance": "TRUSTED_LOCAL_STATE"}]}]
        out = mc.ribbon(journal_entries=entries, records=records, sessions=sessions)
        said = [i["said"] for i in out]
        self.assertEqual(said[0], "Answered “how did applications go today?” after looking at "
                                  "applications.query.")
        self.assertEqual(said[1], "Sent Operations Analyst at S1.")
        self.assertTrue(said[2].startswith("Couldn't send Operations Analyst at F1: There is no application form"))
        self.assertEqual(out[3]["tone"], "alert")
        self.assertFalse(any("120 fields" in s or "/api/status" in s or "closed apply-" in s for s in said))
        self.assertEqual(len(out), 5)
        for item in out:
            self.assertIn(item["receipt"]["kind"], ("journal", "application", "session"))
        # provenance is receipt material, never the sentence
        self.assertFalse(any("qwen" in s for s in said))

    def test_journal_receipt_ids_are_stable(self):
        entry = {"ts": ago(1), "subject": "core", "text": "local Core up"}
        self.assertEqual(mc.journal_id(entry), mc.journal_id(dict(entry)))
        self.assertTrue(mc.journal_id(entry).startswith("j-"))


class EyesShowOnlyWhatIsRecorded(unittest.TestCase):
    def test_the_current_applications_screenshot_first_then_the_last(self):
        records = {"a1": rec("a1", "FAILED"), "a0": rec("a0", "SUBMITTED")}
        browser = {"active": True, "site": "jobs.lever.co", "purpose": "finding openings",
                   "stage": "the form would not go", "application": "a1",
                   "last": {"application": "a0", "at": ago(5)}}
        out = mc.eyes(browser, records_by_id=records, has_screenshot=lambda r: True)
        self.assertEqual(out["screenshot"]["application"], "a1")
        self.assertEqual(out["screenshot"]["src"], "/api/mission/screenshot?id=a1")
        out = mc.eyes(browser, records_by_id=records, has_screenshot=lambda r: r["id"] == "a0")
        self.assertEqual(out["screenshot"]["of"], "the last application she worked")
        out = mc.eyes(browser, records_by_id=records, has_screenshot=lambda r: False)
        self.assertIsNone(out["screenshot"])
        # neither has one: the newest record that does, said as exactly that
        records["old"] = rec("old", "SUBMITTED", submitted_at=ago(900))
        out = mc.eyes(browser, records_by_id=records, has_screenshot=lambda r: r["id"] == "old")
        self.assertEqual(out["screenshot"]["of"], "the latest screenshot on record")
        self.assertEqual(out["site"], "jobs.lever.co")


class TheRoutesSitBehindTheSameGate(unittest.TestCase):
    """Loopback reads openly, like /api/status; a remote caller needs a real
    token, like /api/status. Nothing new is reachable that was not before."""

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
        access.clear_failures()
        self.addCleanup(access.clear_failures)
        mc.forget_cache()
        self.addCleanup(mc.forget_cache)
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
        status, ctype, body = self.fetch("/api/mission")
        self.assertEqual(status, 200)
        value = json.loads(body)
        for part in ("header", "pipeline", "discovery", "ribbon", "eyes"):
            self.assertIn(part, value)
        from aletheia.current_state import AGENT_STATES
        self.assertIn(value["header"]["state"], AGENT_STATES)
        stopped = [s for s in value["pipeline"]["off_ramps"] if s["stage"] == "STOPPED"][0]
        self.assertEqual(stopped["cards"][0]["why_not_sent"], "She could not find the button.")
        self.assertTrue(stopped["cards"][0]["screenshot"])

    def test_remote_without_a_token_is_refused_on_every_route(self):
        for path in ("/api/mission", "/api/mission/receipt?kind=application&id=apply-0000beef",
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

    def test_nothing_outside_the_records_is_served(self):
        for path in ("/api/mission/receipt?kind=application&id=../../secrets",
                     "/api/mission/receipt?kind=session&id=..%2Fx",
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
