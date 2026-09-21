"""The job hunt as one mission type: the provider mission control plugs in.

Jobs are the current test case, not the architecture (operator, 2026-09-16).
These hold what only applications have - the pipeline stage a record lands
in, "why this one?", "why didn't this send?", whether the apply loop is
alive - and what the provider hands the generic screen: one mission card,
its needs, its liveness signal, its ribbon lines and its screenshots.
"""
from __future__ import annotations

import datetime as dt
import json
import unittest

from aletheia import mission_control as mc, mission_jobs as jobs

UTC = dt.timezone.utc
NOW = dt.datetime(2026, 9, 16, 15, 0, tzinfo=UTC)


def ago(minutes: float) -> str:
    return (NOW - dt.timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M:%SZ")


def rec(run_id, state, **fields):
    value = {"id": run_id, "state": state, "url": f"https://jobs.lever.co/{run_id}/apply",
             "company": run_id.title(), "job_title": "Operations Analyst", "staged_at": ago(60)}
    value.update(fields)
    return value


def ctx(**over):
    value = {"now": NOW, "entries": [], "halted": False, "browser": {}, "say_time": lambda w: w.strftime("%H:%M"),
             "today_floor": ago(600)}
    value.update(over)
    return value


class TheApplyLoopIsJudgedFromWhatItLeaves(unittest.TestCase):
    def test_a_running_batch_is_alive(self):
        out = jobs.apply_loop({"running": True, "started_at": ago(12)}, [], NOW)
        self.assertIs(out["alive"], True)
        self.assertIn("12 minutes", out["said"])

    def test_a_three_hour_lock_is_the_stale_lock(self):
        out = jobs.apply_loop({"running": True, "started_at": ago(200)}, [], NOW)
        self.assertTrue(out["stale"])
        self.assertIsNone(out["alive"])

    def test_a_recent_journal_line_is_alive(self):
        out = jobs.apply_loop(None, [{"ts": ago(4), "subject": "apply:forever"}], NOW)
        self.assertIs(out["alive"], True)

    def test_resting_or_halted_is_expected_quiet_not_death(self):
        entries = [{"ts": ago(400), "subject": "apply:forever"}]
        self.assertIsNone(jobs.apply_loop(None, entries, NOW, resting=True)["alive"])
        self.assertIsNone(jobs.apply_loop(None, entries, NOW, halted=True)["alive"])

    def test_never_seen_is_not_alive(self):
        out = jobs.apply_loop(None, [{"ts": ago(1), "subject": "core"}], NOW)
        self.assertIs(out["alive"], False)
        self.assertIn("no sign", out["said"])


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
                self.assertEqual(jobs.stage_of(record, **facts), stage)

    def test_a_live_grant_moves_a_filled_form_to_applying(self):
        self.assertEqual(jobs.stage_of(rec("x", "AWAITING_YOU"), approval_state="PENDING", grant_live=True),
                         "APPLYING")

    def test_counts_cards_and_off_ramps(self):
        records = [rec("s1", "SUBMITTED", submitted_at=ago(30)), rec("s2", "SUBMITTED", submitted_at=ago(3000)),
                   rec("n1", "NEEDS_YOU", questions=[{"label": "Preferred shift"}]),
                   rec("f1", "FAILED", failure="ApplyError: she could not find the button that submits this form"),
                   rec("c1", "CLOSED", closed_because="not realistic: 7+ years"),
                   {"not": "a record"}]
        out = jobs.pipeline(records, today_floor=ago(600), discovery_today={"discovered": 312, "qualified": 40})
        stages = {s["stage"]: s for s in out["stages"]}
        self.assertEqual([s["stage"] for s in out["stages"]], list(jobs.STAGES))
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
        out = jobs.pipeline([], discovery_today=None)
        discovered = out["stages"][0]
        self.assertIsNone(discovered["count"])
        self.assertIn("no discovery", discovered["source"])

    def test_cards_are_newest_first_and_capped(self):
        records = [rec(f"s{i}", "SUBMITTED", submitted_at=ago(i)) for i in range(20)]
        sent = [s for s in jobs.pipeline(records, per_stage=5)["stages"] if s["stage"] == "SENT"][0]
        self.assertEqual(sent["count"], 20)
        self.assertEqual([c["id"] for c in sent["cards"]], ["s0", "s1", "s2", "s3", "s4"])


class TheCardAnswersBothQuestions(unittest.TestCase):
    def test_why_this_one_prefers_job_values_reasons(self):
        record = rec("v", "SUBMITTED", why_she_liked_it=["it pays $95,000", "it is in Sioux Falls"],
                     why_not=["it asks for 3 years"], value=71, queue="outlier",
                     fit={"why": "the model's view", "by": "model:codex"})
        why = jobs.why_this_one(record)
        self.assertEqual(why["source"], "job_value")
        self.assertIn("it pays $95,000", why["said"])
        self.assertIn("against it", why["said"])
        self.assertEqual(why["queue"], "outlier")

    def test_why_this_one_falls_back_to_the_fit_without_naming_the_model(self):
        why = jobs.why_this_one(rec("f", "SUBMITTED", fit={"why": "operations role he fits", "by": "model:codex"}))
        self.assertEqual(why["said"], "operations role he fits")
        self.assertNotIn("codex", json.dumps(why))

    def test_an_unscored_record_says_nothing_rather_than_inventing(self):
        self.assertIsNone(jobs.why_this_one(rec("u", "FAILED")))

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
                stage = jobs.stage_of(record, **facts)
                said = jobs.why_not_sent(record, stage=stage, **facts)
                self.assertIn(words, said)
                self.assertNotRegex(said, r"^[A-Z][A-Za-z]+Error:")

    def test_a_sent_application_has_no_blocker(self):
        self.assertEqual(jobs.why_not_sent(rec("s", "SUBMITTED"), stage="SENT"), "")


class TheRecordsBecomeRibbonLines(unittest.TestCase):
    def test_each_line_is_a_sentence_with_its_receipt(self):
        records = [rec("s1", "SUBMITTED", submitted_at=ago(10)),
                   rec("f1", "FAILED", staged_at=ago(15), failure="there is no application form on this page"),
                   rec("n1", "NEEDS_YOU", staged_at=ago(20), questions=[{"label": "Preferred shift"}])]
        out = jobs.activity(records)
        said = {i["receipt"]["id"]: i for i in out}
        self.assertEqual(said["s1"]["said"], "Sent Operations Analyst at S1.")
        self.assertEqual(said["s1"]["tone"], "good")
        self.assertTrue(said["f1"]["said"].startswith("Couldn't send Operations Analyst at F1: There is no"))
        self.assertEqual(said["n1"]["tone"], "needs")
        self.assertTrue(all(i["receipt"]["kind"] == "application" for i in out))

    def test_merged_into_the_generic_ribbon_the_apply_lines_give_way(self):
        entries = [{"ts": ago(35), "kind": "action", "subject": "apply", "text": "closed apply-1234abcd"},
                   {"ts": ago(20), "kind": "alert", "subject": "apply:forever", "text": "a batch could not start"}]
        out = mc.ribbon(journal_entries=entries, extra=jobs.activity([rec("s1", "SUBMITTED", submitted_at=ago(10))]),
                        skip_subjects=jobs.PROVIDER.journal_subjects, labels=jobs.PROVIDER.subject_labels)
        self.assertEqual([i["said"] for i in out], ["Sent Operations Analyst at S1.", "A batch could not start"])
        self.assertEqual(out[1]["what"], "Job hunt")


class ScreenshotsAreOnlyWhatIsRecorded(unittest.TestCase):
    def test_the_current_application_first_then_the_last_then_the_newest(self):
        records = {"a1": rec("a1", "FAILED"), "a0": rec("a0", "SUBMITTED")}
        browser = {"active": True, "application": "a1", "last": {"application": "a0", "at": ago(5)}}
        out = jobs.screenshots(browser, records_by_id=records, shots={"a1", "a0"})
        self.assertEqual([s["id"] for s in out], ["a1", "a0"])
        self.assertEqual(out[0]["src"], "/api/mission/screenshot?id=a1")
        out = jobs.screenshots(browser, records_by_id=records, shots={"a0"})
        self.assertEqual(out[0]["of"], "the last application she worked")
        self.assertEqual(jobs.screenshots(browser, records_by_id=records, shots=set()), [])
        records["old"] = rec("old", "SUBMITTED", submitted_at=ago(900))
        out = jobs.screenshots(browser, records_by_id=records, shots={"old"})
        self.assertEqual(out[0]["of"], "the latest screenshot on record")
        self.assertEqual(mc.eyes(browser, screenshots=out)["screenshot"]["id"], "old")


class TheProviderHandsTheScreenOneMission(unittest.TestCase):
    def mission(self, part):
        self.assertEqual(len(part["missions"]), 1)
        card = part["missions"][0]
        self.assertEqual(card["type"], "job_hunt")
        self.assertTrue(card["detail"])
        self.assertIn(card["id"], part["details"])
        return card

    def test_a_running_batch_is_a_running_mission_with_what_follows(self):
        hunt = {"readable": True, "running": True, "campaign": {"running": True, "started_at": ago(3), "count": 8}}
        part = jobs.build({"hunt": hunt, "records": [rec("s1", "SUBMITTED", submitted_at=ago(2))]},
                          ctx(browser={"active": True, "purpose": "sending the application for X",
                                       "stage": "pressing submit", "site": "jobs.lever.co"}))
        card = self.mission(part)
        self.assertEqual(card["status"], "RUNNING")
        self.assertTrue(card["in_browser"])
        self.assertIn("pressing submit at jobs.lever.co", card["step"])
        self.assertIn("batch of 8", card["next"])
        self.assertIn("another within 5 minutes", card["next"])
        self.assertEqual(card["stuck"], "")
        self.assertTrue(part["signals"][0]["ok"])

    def test_a_refill_is_not_called_a_batch(self):
        hunt = {"running": True, "campaign": {"running": True, "started_at": ago(3), "kind": "retry", "limit": 60}}
        card = self.mission(jobs.build({"hunt": hunt, "records": []}, ctx()))
        self.assertIn("re-reading up to 60 waiting applications", card["next"])

    def test_waiting_applications_are_needs_counted_once_with_their_approvals_claimed(self):
        records = [rec(f"n{i}", "NEEDS_YOU", questions=[{"label": "Preferred shift"}]) for i in range(11)]
        records.append(rec("w1", "AWAITING_YOU", approval="ap-w1"))
        part = jobs.build({"hunt": {"readable": True}, "records": records,
                           "facts": {"w1": {"approval_state": "PENDING"}}}, ctx())
        card = self.mission(part)
        self.assertEqual(card["status"], "NEEDS YOU")
        self.assertEqual(card["needs_count"], 12)
        self.assertEqual(len(card["needs"]), jobs.NEEDS_LISTED)
        self.assertIn("Preferred shift", card["needs"][0]["said"] + card["needs"][-1]["said"])
        self.assertEqual(part["claims"], ["ap-w1"])
        # the loop left no mark, which is what stops these moving without him
        self.assertIn("no sign of the apply loop", card["stuck"])

    def test_nobody_can_think_is_a_blocker_that_names_when_claude_is_back(self):
        hunt = {"readable": True, "blocked": True,
                "thinking": {"claude": {"resting_until": "2026-09-16T21:40:00Z"},
                             "local": {"why": "is switched off"}}}
        card = self.mission(jobs.build({"hunt": hunt, "records": [rec("s1", "SUBMITTED", submitted_at=ago(90))]},
                                       ctx()))
        self.assertEqual(card["status"], "BLOCKED")
        # The RULE: it says WHEN it picks up. The brand went (his brief:
        # no model names in normal use); the time is the fact.
        self.assertIn("21:40", card["next"])
        self.assertNotIn("Claude", card["next"])
        self.assertIn("nobody can think", card["stuck"])

    def test_a_loop_that_died_today_is_a_banner_and_a_blocker(self):
        entries = [{"ts": ago(300), "subject": "apply:forever", "text": "started"}]
        part = jobs.build({"hunt": {"readable": True}, "records": [rec("s1", "SUBMITTED", submitted_at=ago(310))]},
                          ctx(entries=entries))
        card = self.mission(part)
        self.assertEqual(card["status"], "STOPPED")
        self.assertIn("5 hours", card["stuck"])
        self.assertIn("5 hours", card["next"])
        self.assertIn("job hunt looks stopped", part["signals"][0]["banner"])

    def test_a_loop_stopped_days_ago_is_said_on_the_card_but_is_not_news(self):
        entries = [{"ts": ago(3 * 1440), "subject": "apply:forever", "text": "started"}]
        part = jobs.build({"hunt": {"readable": True}, "records": [rec("s1", "SUBMITTED", submitted_at=ago(3 * 1440))]},
                          ctx(entries=entries))
        self.assertEqual(self.mission(part)["status"], "STOPPED")
        self.assertNotIn("banner", part["signals"][0])

    def test_a_hunt_untouched_for_weeks_is_not_a_mission(self):
        part = jobs.build({"hunt": {"readable": True}, "records": [rec("s1", "SUBMITTED", submitted_at=ago(30 * 1440),
                                                                     staged_at=ago(30 * 1440))]}, ctx())
        self.assertEqual(part["missions"], [])
        self.assertEqual(part["signals"], [])
        self.assertEqual(len(part["activity"]), 1)   # history still reads on the ribbon

    def test_halted_stops_the_mission_without_calling_the_loop_dead(self):
        entries = [{"ts": ago(300), "subject": "apply:forever", "text": "started"}]
        part = jobs.build({"hunt": {"readable": True}, "records": [rec("s1", "SUBMITTED", submitted_at=ago(10))]},
                          ctx(entries=entries, halted=True))
        card = self.mission(part)
        self.assertEqual(card["status"], "STOPPED")
        self.assertIn("halted", card["stuck"])
        self.assertNotIn("banner", part["signals"][0])

    def test_it_is_registered(self):
        self.assertIs(mc.registry()["job_hunt"], jobs.PROVIDER)
        self.assertIn("application", jobs.PROVIDER.receipt_kinds)


if __name__ == "__main__":
    unittest.main()
