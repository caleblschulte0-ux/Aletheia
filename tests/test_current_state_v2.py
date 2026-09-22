"""`current_state` v2: the single root of situational awareness.

The brief (docs/JARVIS_BRIEF.md §2) names what the snapshot omitted — the
job hunt, her own state, the browser, the code — and the standard for all
of it: every count derived from a store, never guessed; an unreadable
store says so. These hold the derivation against records written into the
suite's own private state, and hold the fast lane's four answers against
the same records with no model anywhere.
"""
from __future__ import annotations

import datetime as dt
import json
import unittest
from unittest import mock

from aletheia import apply_run, campaign, current_state, quick, stateio

UTC = dt.timezone.utc
NOW = dt.datetime(2026, 9, 15, 20, 30, tzinfo=UTC)         # 3:30 pm in Chicago


def stamp(hours_ago: float) -> str:
    return (NOW - dt.timedelta(hours=hours_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


def fresh(minutes_ago: float) -> str:
    """Against the REAL clock, for the fast lane, which reads the real
    clock: a frozen date next to a moving fixture fails on the day the
    calendar passes it (CLAUDE.md).

    And never across midnight. "140 minutes ago" is yesterday between
    midnight and 02:20, and the readers count TODAY - in his zone and in
    UTC - so this failed at 01:35 Central on 2026-09-22 with nothing
    changed but the hour. The offset is held inside the current day of
    both zones; the ordering of a fixture's stamps survives, only the gaps
    shrink near midnight.
    """
    from aletheia import localtime
    now = dt.datetime.now(UTC)
    cap = None
    for tz in (UTC, localtime.operator_tz()):
        local = now.astimezone(tz)
        since_midnight = (local - local.replace(hour=0, minute=0, second=0, microsecond=0)).total_seconds() / 60
        cap = since_midnight if cap is None else min(cap, since_midnight)
    room = max(0.0, (cap or 0.0) - 1.0)
    if minutes_ago > room:
        minutes_ago = room * (minutes_ago / max(minutes_ago, 240.0))
    return (now - dt.timedelta(minutes=minutes_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


def record(run_id: str, state: str, *, hours_ago: float = 1.0, **fields) -> dict:
    value = {"id": run_id, "state": state, "url": f"https://jobs.lever.co/{run_id}/apply",
             "company": fields.pop("company", run_id.title()),
             "job_title": fields.pop("job_title", "Operations Analyst"),
             "staged_at": stamp(hours_ago), "filled": [], "not_filled": [],
             "skipped": [], "steps": [], "approval": "", "resume": ""}
    value.update(fields)
    stateio.write_json_atomic(apply_run.staged_dir() / f"{run_id}.json", value)
    return value


class Records(unittest.TestCase):
    """Every test writes its own records into the suite's throwaway private
    state and clears the derived cache, so nothing leaks between them."""

    def setUp(self):
        self.addCleanup(self._clear)
        self._clear()
        current_state.forget_cache()

    @staticmethod
    def _clear():
        directory = apply_run.staged_dir()
        if directory.is_dir():
            for path in directory.glob("*.json"):
                path.unlink()
        try:
            campaign.LOCK_PATH.unlink()
        except OSError:
            pass
        current_state.forget_cache()


class TheJobHuntIsCounted(Records):
    def test_every_count_is_a_count_of_records(self):
        record("palantir", "FAILED", hours_ago=2,
               failure="the Submit button would not take a click - a CAPTCHA challenge was in front of it")
        record("stripe", "SUBMITTED", hours_ago=3, submitted_at=stamp(2.5))
        record("figma", "AWAITING_YOU", hours_ago=1)
        record("brex", "NEEDS_YOU", hours_ago=1,
               questions=[{"label": "Preferred shift", "required": True}])
        record("old-one", "SUBMITTED", hours_ago=40, submitted_at=stamp(39))   # yesterday
        record("dupe", "CLOSED", hours_ago=1, closed_because="same job already went")
        record("unfit", "CLOSED", hours_ago=1, closed_because="not realistic for him")
        with mock.patch.object(current_state, "thinking",
                               return_value={"claude": {"resting_until": None},
                                             "codex": {"resting_until": None},
                                             "local": {"allowed": False, "why": "off"},
                                             "anyone": True}):
            hunt = current_state.job_hunt(NOW)
        self.assertTrue(hunt["readable"])
        self.assertEqual(hunt["today"], {"discovered": 6, "qualified": 5, "attempted": 4,
                                         "ready": 1, "sent": 1, "blocked": 1, "replies": 0})
        self.assertEqual(hunt["now"]["ready"], 1)
        self.assertEqual(hunt["now"]["needs_you"], 1)
        self.assertEqual(hunt["now"]["records"], 7)
        self.assertEqual([b["company"] for b in hunt["blockers"]], ["Palantir"])
        self.assertIn("CAPTCHA", hunt["blockers"][0]["reason"])
        self.assertEqual(hunt["waiting_on_him"][0]["company"], "Brex")
        self.assertEqual(hunt["waiting_on_him"][0]["questions"], ["Preferred shift"])
        self.assertFalse(hunt["running"])
        self.assertFalse(hunt["blocked"])

    def test_a_reply_today_is_counted_from_the_outcome_history(self):
        record("gong", "SUBMITTED", hours_ago=30, submitted_at=stamp(29),
               outcome="interview",
               outcomes=[{"outcome": "interview", "note": "Tuesday", "at": stamp(1)}])
        hunt = current_state.job_hunt(NOW)
        self.assertEqual(hunt["today"]["replies"], 1)
        self.assertEqual(hunt["replies"][0]["outcome"], "interview")

    def test_an_unreadable_store_says_so_instead_of_counting_zero(self):
        with mock.patch.object(apply_run, "all_runs", side_effect=OSError("disk")):
            hunt = current_state.job_hunt(NOW)
        self.assertFalse(hunt["readable"])
        self.assertNotIn("today", hunt)
        self.assertIn("could not be read", hunt["note"])
        self.assertIn("could not be read", current_state.job_hunt_words(hunt))

    def test_the_campaign_lock_is_read_without_killing_anything(self):
        stateio.write_json_atomic(campaign.LOCK_PATH,
                                  {"kind": "retry", "pid": 424242, "limit": 60,
                                   "started_at": stamp(0.5)})
        with mock.patch("aletheia.proc.pid_alive", return_value=True) as alive, \
             mock.patch("aletheia.proc.kill_tree") as kill:
            hunt = current_state.job_hunt(NOW)
        self.assertTrue(hunt["running"])
        self.assertEqual(hunt["campaign"]["kind"], "retry")
        alive.assert_called()
        kill.assert_not_called()

    def test_a_dead_pid_is_not_a_running_campaign(self):
        stateio.write_json_atomic(campaign.LOCK_PATH,
                                  {"kind": "apply", "pid": 1, "started_at": stamp(0.5)})
        with mock.patch("aletheia.proc.pid_alive", return_value=False):
            self.assertFalse(current_state.job_hunt(NOW)["running"])

    def test_nobody_able_to_think_is_blocked(self):
        with mock.patch.object(current_state, "thinking",
                               return_value={"claude": {"resting_until": "2026-09-16T00:00:00Z"},
                                             "codex": {"resting_until": "2026-09-16T00:00:00Z",
                                                       "why": "limit"},
                                             "local": {"allowed": False,
                                                       "why": "only 2 GB is free"},
                                             "anyone": False}):
            hunt = current_state.job_hunt(NOW)
            block = current_state.agent(NOW, hunt=hunt,
                                        browsing={"active": False, "stage": "idle"})
        self.assertTrue(hunt["blocked"])
        self.assertEqual(block["state"], "BLOCKED")
        self.assertIn("nobody can think", block["step"])
        self.assertIn("2 GB", block["step"])


class TheBrowserIsDerived(Records):
    def test_idle_when_nothing_is_working(self):
        record("stripe", "SUBMITTED", hours_ago=3, submitted_at=stamp(2.5))
        seen = current_state.browser(NOW)
        self.assertFalse(seen["active"])
        self.assertEqual(seen["stage"], "idle")
        self.assertEqual(seen["last"]["site"], "jobs.lever.co")

    def test_pressing_submit_is_the_browser_acting(self):
        record("carta", "SUBMITTING", hours_ago=0.1, submit_pid=777, pressed_at=stamp(0.05),
               job_title="Account Executive")
        with mock.patch("aletheia.proc.pid_alive", return_value=True):
            seen = current_state.browser(NOW)
            block = current_state.agent(NOW, browsing=seen,
                                        hunt={"readable": True, "waiting_on_him": []})
        self.assertTrue(seen["active"])
        self.assertEqual(seen["site"], "jobs.lever.co")
        self.assertEqual(seen["stage"], "pressing submit")
        self.assertIn("Account Executive", seen["purpose"])
        self.assertEqual(block["state"], "ACTING")
        self.assertIn("jobs.lever.co", block["step"])

    def test_a_fresh_campaign_with_no_form_yet_is_looking(self):
        stateio.write_json_atomic(campaign.LOCK_PATH,
                                  {"kind": "apply", "pid": 5, "count": 8,
                                   "started_at": stamp(0.2)})
        with mock.patch("aletheia.proc.pid_alive", return_value=True):
            hunt = current_state.job_hunt(NOW)
            seen = current_state.browser(NOW, hunt=hunt)
            block = current_state.agent(NOW, hunt=hunt, browsing=seen)
        self.assertEqual(seen["stage"], "looking for openings")
        self.assertEqual(block["state"], "LOOKING")

    def test_a_campaign_that_staged_a_form_is_acting_at_that_site(self):
        stateio.write_json_atomic(campaign.LOCK_PATH,
                                  {"kind": "apply", "pid": 5, "started_at": stamp(0.5)})
        record("figma", "AWAITING_YOU", hours_ago=0.2)
        with mock.patch("aletheia.proc.pid_alive", return_value=True):
            hunt = current_state.job_hunt(NOW)
            seen = current_state.browser(NOW, hunt=hunt)
        self.assertEqual(seen["site"], "jobs.lever.co")
        self.assertEqual(seen["stage"], "form filled, waiting for confirmation")


class TheAgentStateHasAnOrder(Records):
    def test_halted_beats_everything(self):
        with mock.patch("aletheia.policy.halted", return_value={"reason": "stop", "halted_at": "x"}):
            block = current_state.agent(NOW, hunt={"readable": True}, browsing={"active": True})
        self.assertEqual(block["state"], "HALTED")
        self.assertEqual(block["step"], "stop")
        # Case-insensitive: she says "I'm halted" in the first person now,
        # because it is her answering a question about herself. The rule is
        # that the word HALTED reaches him, and that the sentence says
        # nothing runs until he resumes her.
        said = current_state.agent_words(block)
        self.assertIn("halted", said.lower())
        self.assertIn("resume", said.lower())

    def test_needs_you_names_what_is_waiting(self):
        block = current_state.agent(
            NOW, hunt={"readable": True, "waiting_on_him": [{"id": "a"}, {"id": "b"}]},
            browsing={"active": False}, pending_approvals=[{"id": "p", "created_at": "t"}])
        self.assertEqual(block["state"], "NEEDS YOU")
        self.assertIn("1 approval and 2 applications", block["step"])

    def test_idle_when_nothing_at_all(self):
        block = current_state.agent(NOW, hunt={"readable": True, "waiting_on_him": []},
                                    browsing={"active": False})
        self.assertEqual(block["state"], "IDLE")
        # The rule is that IDLE says nothing is happening — not the exact
        # sentence, which was "Nothing in flight right now": a phrase off a
        # control tower, not something a person says about their day.
        said = current_state.agent_words(block)
        self.assertTrue(said.lower().startswith("nothing"), said)

    def test_every_state_is_in_the_vocabulary(self):
        for state in ("HALTED", "ACTING", "LOOKING", "THINKING", "BLOCKED", "NEEDS YOU",
                      "WAITING", "LISTENING", "IDLE"):
            self.assertIn(state, current_state.AGENT_STATES)


class TheCodeBlock(unittest.TestCase):
    def test_it_says_which_code_and_whether_she_is_behind_it(self):
        with mock.patch("aletheia.running.version",
                        return_value={"branch": "live", "commit": "abc123", "subject": "s",
                                      "behind": "", "running_old_code": True,
                                      "newest_code": "core.py", "started_at": "t"}), \
             mock.patch.object(current_state, "_dirty",
                               return_value={"known": True, "dirty": True, "count": 1,
                                             "files": ["aletheia/core.py"]}):
            block = current_state.code()
        self.assertEqual(block["branch"], "live")
        self.assertTrue(block["dirty"])
        self.assertTrue(block["running_old_code"])
        self.assertTrue(block["readable"])

    def test_outside_git_it_does_not_guess(self):
        with mock.patch("aletheia.running.version", return_value={}), \
             mock.patch.object(current_state, "_dirty",
                               return_value={"known": False, "dirty": None, "files": []}):
            block = current_state.code()
        self.assertIsNone(block["dirty"])
        self.assertFalse(block["readable"])


class TheSnapshotCarriesTheSections(Records):
    def test_version_two_has_the_four_sections(self):
        snap = current_state.snapshot(now=NOW)
        self.assertEqual(snap["version"], 2)
        for key in ("agent", "job_hunt", "browser", "code"):
            self.assertIn(key, snap)
        self.assertIn(snap["agent"]["state"], current_state.AGENT_STATES)

    def test_the_status_route_carries_them(self):
        from aletheia import core
        payload = core.status_payload()
        for key in ("agent", "job_hunt", "browser", "code"):
            self.assertIn(key, payload)
        json.dumps(payload)          # the API serialises it


class TheFastLaneAnswersTheFourQuestions(Records):
    """No model anywhere: every sentence is counted from the records."""

    def setUp(self):
        super().setUp()
        record("palantir", "FAILED", staged_at=fresh(3),
               failure="the Submit button would not take a click - a CAPTCHA challenge was in front of it")
        record("stripe", "SUBMITTED", staged_at=fresh(4), submitted_at=fresh(2))
        record("brex", "NEEDS_YOU", staged_at=fresh(1),
               questions=[{"label": "Preferred shift", "required": True}])
        self.minds = mock.patch.object(
            current_state, "thinking",
            return_value={"claude": {"resting_until": None}, "codex": {"resting_until": None},
                          "local": {"allowed": False, "why": "off"}, "anyone": True})
        self.minds.start()
        self.addCleanup(self.minds.stop)
        current_state.forget_cache()

    def test_how_did_the_applications_go_today(self):
        for sentence in ("how did the applications go today", "how did the job hunt go",
                         "how's the job hunt going"):
            with self.subTest(sentence=sentence):
                said = quick.answer(sentence)
                self.assertIsNotNone(said, sentence)
                self.assertIn("3 openings found", said)
                self.assertIn("1 sent", said)
                self.assertIn("1 blocked", said)
                self.assertIn("Palantir", said)
                self.assertIn("CAPTCHA", said)

    def test_how_many_is_answered_with_the_count_not_the_report(self):
        """"How many" wants a number. It used to get the whole day's report,
        with the number somewhere in the middle of it."""
        said = quick.answer("how many jobs did you apply to today")
        self.assertIsNotNone(said)
        self.assertTrue(said.startswith("1 application sent today"), said)
        self.assertNotIn("openings found", said)

    def test_what_went_wrong_today(self):
        said = quick.answer("what went wrong today")
        self.assertIsNotNone(said)
        self.assertIn("Palantir", said)
        self.assertIn("CAPTCHA", said)

    def test_what_do_you_need_from_me(self):
        empty = {"halted": False, "waiting_on_you": [], "notifications": []}
        with mock.patch("aletheia.presence.snapshot", lambda: empty):
            said = quick.answer("what do you need from me")
        self.assertIsNotNone(said)
        self.assertIn("Brex", said)
        self.assertIn("Preferred shift", said)

    def test_what_are_you_doing_right_now(self):
        self.assertEqual(quick.match("what are you doing right now")[0], "doing")
        with mock.patch.object(current_state, "sections",
                               return_value={"agent": {"state": "ACTING", "mission": "job hunt",
                                                       "step": "pressing submit at jobs.lever.co",
                                                       "since": None}}):
            said = quick.answer("what are you doing right now")
        self.assertIn("pressing submit at jobs.lever.co", said)

    def test_nothing_went_wrong_is_said_as_a_fact_about_the_stores(self):
        self._clear()
        current_state.forget_cache()
        with mock.patch("aletheia.recollection.trouble", return_value=[]):
            said = quick.answer("what went wrong today")
        self.assertIn("Nothing went wrong", said)
        self.assertIn("no alerts", said)


if __name__ == "__main__":
    unittest.main()


class WhatSheReadsOutIsSayable(unittest.TestCase):
    """Heard on a talk run, 2026-09-16: "what went wrong today" read out a whole
    SmartRecruiters URL, a reason cut to "so it is not an", a ValueError, and an
    HTTP method and path; "what do you need from me" joined two question labels
    with commas into one unparseable sentence."""

    def test_a_record_with_no_employer_is_named_by_its_site(self):
        from aletheia import current_state
        self.assertEqual(current_state.said_name("", "https://jobs.smartrecruiters.com/oneclick-ui/x/1"),
                         "an opening on smartrecruiters.com")
        self.assertEqual(current_state.said_name("Palantir", "https://x"), "Palantir")

    def test_a_long_reason_ends_where_a_clause_ends(self):
        from aletheia import current_state
        said = current_state.said_clause("nothing on this page asks for his name, email or phone, "
                                         "so it is not an application form at all", 80)
        self.assertEqual(said, "nothing on this page asks for his name, email or phone")

    def test_codes_class_names_and_paths_are_not_read_out(self):
        from aletheia import current_state
        said = current_state.said_clause("subsystem failing: ValueError: pulse is unreadable", 90)
        self.assertNotIn("ValueError", said)
        said = current_state.said_clause("a local process attempted POST /api/voice/followup/ack "
                                         "without the secret", 90)
        self.assertNotIn("/api/", said)
        self.assertNotIn("https://", current_state.said_clause("see https://example.com/x now", 90))

    def test_repeated_notices_are_said_once_with_a_count(self):
        from aletheia import needs_you, presence, quick
        # `_job_hunt_needs` is gone: the job hunt is one source of the ONE
        # needs-you list now, not a second sentence bolted on here.
        notices = [{"title": "Applications ready to approve"}, {"title": "Applications ready to approve"},
                   {"title": "Application sent"}]
        with mock.patch.object(presence, "snapshot",
                               return_value={"waiting_on_you": [], "notifications": notices}), \
                mock.patch.object(needs_you, "items", return_value=[]):
            said = quick._waiting()
        self.assertEqual(said.count("Applications ready to approve"), 1)
        self.assertIn("2 times", said)
