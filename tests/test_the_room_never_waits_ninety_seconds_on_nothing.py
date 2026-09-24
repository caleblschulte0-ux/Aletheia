"""With the frontier hidden, a question must fail fast or answer from a store.

Measured 2026-09-24 with the Claude binary off the PATH: "which jobs did
you apply to today" took 92 s and "how much memory do you have free" took
120 s of silence, and the profile put all of it in one place - a ChatGPT
browser attempt that failed in 0.2 s and then spent 90 s in
`context.close()` waiting for Chrome. Two rules fall out:

- a browser session's close is BOUNDED; past it the browser is killed;
- a browser-reasoner failure is REMEMBERED for a while, like Claude's
  session limit, so the next question does not pay the round trip again.

And three of the battery's questions had answers in her own stores all
along: whether she is sending mail, which jobs went out today, and how
much memory her machine has free.
"""
from __future__ import annotations

import datetime as dt
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from aletheia import browse, browser_reasoner, quick


class ABrowserCloseIsBounded(unittest.TestCase):
    def test_a_close_that_hangs_is_cut_and_the_browser_killed(self):
        session = browse._Session.__new__(browse._Session)
        session.profile = Path(tempfile.gettempdir()) / "thea-close-test"
        gate = threading.Event()

        class Hanging:
            def close(self):
                gate.wait(30)

        session.context = Hanging()
        killed = []

        def kill(profile):
            # Killing Chrome is what makes a real close return.
            killed.append(profile)
            gate.set()
            return True

        with mock.patch.object(browse, "CLOSE_TIMEOUT_S", 0.3), \
                mock.patch.object(browse, "_close_orphans", kill):
            started = time.monotonic()
            session._close_bounded()
            took = time.monotonic() - started
        self.assertLess(took, 5.0, "the close must not wait for Chrome")
        self.assertEqual(killed, [session.profile])

    def test_a_close_that_returns_is_left_alone_and_its_error_is_raised(self):
        session = browse._Session.__new__(browse._Session)
        session.profile = Path("x")

        class Fine:
            def close(self):
                return None

        class Broken:
            def close(self):
                raise RuntimeError("Target page, context or browser has been closed")

        session.context = Fine()
        with mock.patch.object(browse, "_close_orphans", lambda profile: self.fail("nothing to kill")):
            session._close_bounded()
        session.context = Broken()
        with mock.patch.object(browse, "_close_orphans", lambda profile: self.fail("nothing to kill")):
            with self.assertRaises(RuntimeError):
                session._close_bounded()


class AFailedBrowserAttemptIsRemembered(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        env = mock.patch.dict(os.environ, {"ALETHEIA_PRIVATE_STATE": tmp.name,
                                           browser_reasoner.ALLOW_ENV: "1"})
        env.start(); self.addCleanup(env.stop)

    def test_after_a_failure_the_next_ask_is_refused_at_once_without_a_browser(self):
        self.assertEqual(browser_reasoner.resting_until(), "")
        opened = []

        class Session:
            def __enter__(self):
                opened.append(1)
                raise RuntimeError("no chrome here")

            def __exit__(self, *a):
                return False

        with mock.patch.object(browse, "available", return_value=(True, "")), \
                mock.patch.object(browser_reasoner, "_subscription_session", Session):
            with self.assertRaises(browser_reasoner.BrowserReasonerUnavailable):
                browser_reasoner.infer_json("sys", "hi", timeout_s=5.0)
            self.assertEqual(opened, [1])
            self.assertTrue(browser_reasoner.resting_until())
            started = time.monotonic()
            with self.assertRaises(browser_reasoner.BrowserReasonerUnavailable) as caught:
                browser_reasoner.infer_json("sys", "hi again", timeout_s=5.0)
            self.assertLess(time.monotonic() - started, 1.0)
            self.assertEqual(opened, [1], "no second browser for the same failure")
            self.assertIn("a moment ago", str(caught.exception))

    def test_the_rest_ends(self):
        browser_reasoner.rest(why="x", seconds=-1)
        self.assertEqual(browser_reasoner.resting_until(), "")


class ThreeAnswersSheHadAllAlong(unittest.TestCase):
    def test_whether_she_is_sending_mail_is_read_from_the_hold(self):
        with mock.patch("aletheia.mail.outward_hold", return_value={"on": True, "quote": "q", "since": "", "command": ""}), \
                mock.patch("aletheia.mail.drafts_ledger", return_value=[{"superseded_by": ""}, {"superseded_by": ""}]):
            said = quick.answer("are you sending emails")
        self.assertTrue(said.startswith("No."), said)
        self.assertIn("on hold", said)
        self.assertIn("2 drafts held", said)
        with mock.patch("aletheia.mail.outward_hold", return_value={"on": False, "quote": "", "since": "", "command": ""}), \
                mock.patch("aletheia.mail.drafts_ledger", return_value=[]):
            self.assertTrue(quick.answer("can you send email yet").startswith("Yes"))

    def test_which_jobs_went_out_today_is_read_from_her_records(self):
        from aletheia import localtime
        tz = localtime.operator_tz()
        now = dt.datetime.now(tz)
        stamp = lambda d: d.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")  # noqa: E731
        rows = [{"state": "SUBMITTED", "company": "Acme", "job_title": "Account Executive", "submitted_at": stamp(now)},
                {"state": "SUBMITTED", "company": "Okta", "job_title": "Customer Success Manager — Okta",
                 "submitted_at": stamp(now)},
                {"state": "SUBMITTED", "company": "Zeta", "job_title": "Partner Manager",
                 "submitted_at": stamp(now - dt.timedelta(days=1))}]
        with mock.patch("aletheia.apply_run.all_runs", lambda state=None: [r for r in rows if state in (None, r["state"])]):
            today = quick.answer("which jobs did you apply to today")
            yesterday = quick.answer("which jobs did you apply to yesterday")
        self.assertIn("2 applications went out today: Account Executive at Acme and Customer Success Manager — Okta", today)
        self.assertNotIn("Okta at Okta", today, "a title that already names the employer is not read twice")
        # "yesterday" is already answered by an older reader that names the
        # employer; either reader is honest, and neither goes to a model.
        self.assertIn("Zeta", yesterday)
        self.assertIn("yesterday", yesterday)
        with mock.patch("aletheia.apply_run.all_runs", lambda state=None: []):
            self.assertEqual(quick.answer("who did you apply to today"), "Nothing went out today.")

    def test_free_memory_is_a_number_and_which_model_fits(self):
        class VM:
            available = 4.6e9
            total = 17.0e9
        with mock.patch("psutil.virtual_memory", return_value=VM()), \
                mock.patch("aletheia.reasoner.local_role_that_fits", return_value=("small", "only 4.6 GB free")):
            said = quick.answer("how much memory do you have free")
        self.assertIn("4.6 GB free of 17", said)
        self.assertIn("smaller model fits", said)


class WhatHeAskedIsAStoreSheCanReadBack(unittest.TestCase):
    """"What did I ask you yesterday" had no store to read: his sentences were
    nowhere, only her replies. Every spoken turn journals his words now,
    and the fast lane reads them back by day, with no model."""

    def setUp(self):
        from aletheia import converse, journal
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        env = mock.patch.dict(os.environ, {"ALETHEIA_PRIVATE_STATE": str(root / "private")})
        env.start(); self.addCleanup(env.stop)
        for module, attr, value in ((journal, "JOURNAL_PATH", root / "journal.jsonl"),
                                    (converse, "THREAD_PATH", root / "thread.json")):
            p = mock.patch.object(module, attr, value)
            p.start(); self.addCleanup(p.stop)

    def test_a_spoken_turn_journals_his_words_under_their_own_subject(self):
        from aletheia import converse, journal
        converse.remember_exchange("remind me at 3 to call the dentist", "I'll remind you today at 3 pm.")
        rows = [e for e in journal.entries() if e.get("subject") == converse.ASKED_SUBJECT]
        self.assertEqual([r["text"] for r in rows], ["remind me at 3 to call the dentist"])
        self.assertEqual(rows[0]["actor"], "operator")
        # not "her doing", not one of his notes
        from aletheia import recollection
        self.assertEqual([r for r in recollection.day(hours=1) if "dentist" in str(r.get("what"))], [])
        self.assertEqual([n for n in quick._notes() if "dentist" in str(n.get("text"))], [])

    def test_what_did_i_ask_you_today_and_yesterday_read_from_it(self):
        from aletheia import converse, journal, localtime
        tz = localtime.operator_tz()
        now = dt.datetime.now(tz)
        converse.remember_exchange("what's on my calendar tomorrow", "Nothing tomorrow.")
        converse.remember_exchange("add milk to the shopping list", "Added.")
        import json
        yesterday = (now - dt.timedelta(days=1)).astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        with journal.JOURNAL_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": yesterday, "kind": "note", "actor": "operator",
                                "subject": converse.ASKED_SUBJECT, "text": "book the dentist"}) + "\n")
        today = quick.answer("what did I ask you today")
        self.assertTrue(today.startswith("Today you asked me:"), today)
        self.assertIn("calendar tomorrow", today)
        self.assertIn("shopping list", today)
        self.assertNotIn("dentist", today)
        before = quick.answer("what did I ask you yesterday")
        self.assertTrue(before.startswith("Yesterday you asked me:"), before)
        self.assertIn("dentist", before)

    def test_nothing_written_down_is_said_as_such(self):
        self.assertEqual(quick.answer("what did I tell you yesterday"), "Nothing from you yesterday that I wrote down.")


class WhyTheHuntIsNotMovingIsReadOffItsSwitches(unittest.TestCase):
    """"Why can't you apply to jobs right now" (offline: "I couldn't look
    into that just now") is a question about her own switches, in order:
    his stop, his pause, the grant, who can think, the browser."""

    def _ask(self, **state):
        patches = [
            mock.patch("aletheia.policy.halted", return_value=state.get("halt")),
            mock.patch("aletheia.apply_forever.paused", return_value=state.get("paused")),
            mock.patch("aletheia.standing.jobs_status", return_value={"granted": state.get("granted", True)}),
            mock.patch("aletheia.apply_forever._another_mind", return_value=state.get("mind", (True, "codex"))),
            mock.patch("aletheia.reasoner.resting_until", return_value=state.get("resting")),
            mock.patch("aletheia.browse.available", return_value=state.get("browser", (True, ""))),
            mock.patch("aletheia.campaign.running", return_value=state.get("running")),
            mock.patch("aletheia.current_state.job_hunt_words", return_value="3 sent today."),
        ]
        for p in patches:
            p.start(); self.addCleanup(p.stop)
        return quick.answer("why can't you apply to jobs right now")

    def test_his_stop_comes_first(self):
        said = self._ask(halt={"reason": "you said stop everything"}, paused={"reason": "x"})
        self.assertTrue(said.startswith("Because you stopped everything"), said)
        self.assertIn("resume", said)

    def test_then_his_pause(self):
        said = self._ask(paused={"reason": "hold on a sec"})
        self.assertIn("stop applying", said)
        self.assertIn("start applying", said)

    def test_then_the_things_that_hold_it_up_each_named(self):
        said = self._ask(granted=False, mind=(False, "Codex is not on this PC; my own model needs 6 GB free"),
                         resting=dt.datetime.now(dt.timezone.utc), browser=(False, "playwright is not installed"))
        self.assertTrue(said.startswith("The hunt is held up:"), said)
        self.assertIn("standing grant", said)
        self.assertIn("nobody can judge a job", said)
        self.assertIn("browser is not ready", said)
        self.assertIn("3 sent today", said)

    def test_nothing_stopping_it_says_so_with_the_days_numbers(self):
        said = self._ask()
        self.assertTrue(said.startswith("Nothing is stopping it"), said)
        self.assertIn("3 sent today", said)
        running = self._ask(running={"started_at": "2026-09-24T15:02:00Z", "pid": 1})
        self.assertIn("a batch is running right now", running)

    def test_the_phrasings_he_uses_reach_it(self):
        for s in ("why aren't you applying", "why is the job hunt stuck", "is the job hunt still running",
                  "why aren't applications going out today"):
            self.assertEqual((quick.match(s) or ("",))[0], "hunt_why", s)


class TwoQuestionsAboutHerselfNeedNoThinking(unittest.TestCase):
    def test_who_are_you_is_one_breath_with_no_ids(self):
        from aletheia import speech
        said = quick.answer("who are you")
        self.assertTrue(said.startswith("I'm Thea"), said)
        self.assertEqual(speech.strip_ids(said), said)
        self.assertEqual(quick.match("what's your name")[0], "who_are_you")

    def test_what_works_offline_is_said_from_what_is_true(self):
        with mock.patch("aletheia.reasoner.local_role_that_fits", return_value=(None, "only 3 GB of memory is free")):
            said = quick.answer("what can you do offline")
        self.assertIn("tasks, reminders and lists", said)
        self.assertIn("What waits for a model", said)
        self.assertIn("only 3 GB of memory is free", said)
        for s in ("what still works without the internet", "can you work without claude"):
            self.assertEqual(quick.match(s)[0], "offline_can", s)

    def test_how_long_has_the_core_been_running_is_her_uptime(self):
        self.assertEqual(quick.match("how long has the core been running")[0], "uptime")
        with mock.patch("aletheia.liveness.uptime_seconds", return_value=3700.0), \
                mock.patch("aletheia.liveness.spoken_duration", return_value="an hour"):
            self.assertEqual(quick.answer("how long has the core been running"), "Up an hour.")


class TheThirdBatteryFallThroughs(unittest.TestCase):
    """Twenty everyday sentences with every model rung off (2026-09-24)."""

    def test_two_near_misses_no_longer_answer_a_different_question(self):
        # a calendar question went to the FILE finder; an application went to the fleet
        self.assertEqual(quick.match("do i have anything tomorrow")[0], "free")
        found = quick.match("what's the status of the human interest one")
        self.assertEqual(found[0], "status_of")
        with mock.patch("aletheia.quick._opportunity", return_value="Account Manager — Human Interest: sent.") as opp:
            self.assertEqual(quick.answer("what's the status of the human interest one"),
                             "Account Manager — Human Interest: sent.")
            self.assertEqual(opp.call_args.args[0], "human interest")

    def test_a_part_of_the_day_is_her_journal_filtered_by_the_hour(self):
        rows = [{"at": "Thu 09:12", "what": "read your email"}, {"at": "Thu 14:40", "what": "sent an application"}]
        with mock.patch("aletheia.quick._on_day", return_value=rows):
            morning = quick.answer("what did you do this morning")
            afternoon = quick.answer("what did you do this afternoon")
            night = quick.answer("what did you do tonight")
        self.assertIn("read your email", morning)
        self.assertNotIn("sent an application", morning)
        self.assertIn("sent an application", afternoon)
        self.assertEqual(night, "Nothing tonight.")

    def test_did_i_get_an_interview_reads_the_records(self):
        self.assertEqual(quick.match("did i get an interview")[0], "outcomes")
        with mock.patch("aletheia.apply_run.all_runs", return_value=[]):
            self.assertEqual(quick.answer("did i get an interview"), "No interviews on record.")

    def test_the_next_interview_comes_from_her_calendar(self):
        soon = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=26)).strftime("%Y-%m-%dT%H:%M:%SZ")
        events = [{"title": "Interview: Acme", "start": soon, "end": soon, "status": "CONFIRMED"}]
        with mock.patch("aletheia.calendar.all_events", return_value=events):
            said = quick.answer("what time is my interview")
        self.assertTrue(said.startswith("Your interview with Acme is"), said)
        with mock.patch("aletheia.calendar.all_events", return_value=[]):
            self.assertTrue(quick.answer("when is my next interview").startswith("No interview on your calendar"))

    def test_the_plan_for_today_and_whether_she_is_stuck_are_her_stores(self):
        with mock.patch("aletheia.quick._agenda", return_value="Nothing on your calendar today."), \
                mock.patch("aletheia.quick._tasks", return_value="Nothing open on your task list."), \
                mock.patch("aletheia.quick._job_hunt", return_value="3 applications sent today."):
            said = quick.answer("what's the plan for today")
        self.assertIn("Nothing on your calendar today.", said)
        self.assertIn("3 applications sent today.", said)
        with mock.patch("aletheia.work_engine.inventory", return_value={"items": [], "executable_total": 2}), \
                mock.patch("aletheia.needs_you.items", return_value=[]):
            self.assertEqual(quick.answer("are you stuck"), "No, nothing is stuck. 2 things in my queue.")
        with mock.patch("aletheia.work_engine.inventory", return_value={"items": [{"state": "BLOCKED_EXTERNAL"}], "executable_total": 0}), \
                mock.patch("aletheia.needs_you.items", return_value=[{"what": "x"}]):
            said = quick.answer("are you stuck")
        self.assertTrue(said.startswith("Not stuck, but"), said)
        self.assertIn("1 thing wait", said)
        self.assertIn("1 piece of work is blocked", said)


class TheFourthBatteryFallThroughs(unittest.TestCase):
    """Fifteen more sentences with every model rung off (2026-09-24)."""

    def test_the_name_before_the_noun_is_still_an_email_and_draft_is_too(self):
        from aletheia import voice
        out = voice.interpret("thea send Dana an email saying I'm running late")
        self.assertEqual(out["command"]["kind"], "email_draft")
        self.assertEqual(out["command"]["to"], "Dana", "his capitals are put back")
        self.assertEqual(out["command"]["body"], "I'm running late")
        out = voice.interpret("thea draft an email to Dana saying I'm running late")
        self.assertEqual(out["command"]["kind"], "email_draft")
        self.assertEqual(out["command"]["to"], "Dana")
        # a reminder that mentions email is still a reminder
        out = voice.interpret("thea remind me to email bob at 3")
        self.assertNotEqual(out["command"]["kind"], "email_draft")

    def test_tomorrow_morning_is_a_time(self):
        from aletheia import voice
        out = voice.interpret("thea remind me tomorrow morning to email Dana")
        self.assertEqual(out["command"]["kind"], "remind_at")
        self.assertIn("T09:00", out["command"]["at"])
        self.assertEqual(out["command"]["text"], "email Dana")
        out = voice.interpret("thea remind me tomorrow evening to call mom")
        self.assertIn("T19:00", out["command"]["at"])

    def test_what_needs_me_right_now_and_the_first_thing_waiting(self):
        for s in ("what needs me right now", "what's the first thing waiting on me", "anything need me"):
            self.assertEqual(quick.match(s)[0], "waiting", s)

    def test_how_long_until_my_interview_says_the_distance(self):
        soon = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=50)).strftime("%Y-%m-%dT%H:%M:%SZ")
        with mock.patch("aletheia.calendar.all_events",
                        return_value=[{"title": "Interview: Acme", "start": soon, "end": soon, "status": "CONFIRMED"}]):
            said = quick.answer("how long until my interview")
        self.assertIn("in 2 days", said)

    def test_a_bare_no_with_nothing_pending_is_answered_and_with_something_pending_is_left_alone(self):
        with mock.patch("aletheia.policy.all_approvals", return_value=[]), \
                mock.patch("aletheia.needs_you.items", return_value=[]):
            self.assertEqual(quick.answer("no"), "Nothing is waiting for a yes or no right now.")
            self.assertEqual(quick.answer("ok"), "Nothing is waiting for a yes or no right now.")
        with mock.patch("aletheia.policy.all_approvals", return_value=[{"id": "a", "state": "PENDING"}]):
            self.assertIsNone(quick.answer("no"))

    def test_how_many_things_on_my_task_list_and_what_did_i_tell_you_to_remember(self):
        self.assertEqual(quick.match("how many things are on my task list")[0], "tasks")
        self.assertEqual(quick.match("what did i tell you to remember")[0], "notes_list")


class TheFifthBatteryFallThroughs(unittest.TestCase):
    """What she changed, learned and wrote today, and what is on his desktop:
    journal and disk reads that went to a model (2026-09-24)."""

    def _entries(self, rows):
        import datetime as dt
        stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        return [{"ts": stamp, **r} for r in rows]

    def test_what_changed_today_is_her_code_updates_and_her_files(self):
        rows = self._entries([
            {"kind": "event", "actor": "operator-local-core", "subject": "core:sync",
             "text": "code updated (3 file(s), now at 6023566a0c) — restarting to run it"},
            {"kind": "action", "actor": "aletheia-pursuit", "subject": "opportunity",
             "text": "write — wrote positioning-notes.md in the workspace"}])
        with mock.patch("aletheia.journal.entries", return_value=rows):
            said = quick.answer("what did you change today")
        self.assertIn("updated my own code 1 time today", said)
        self.assertIn("positioning-notes.md", said)
        with mock.patch("aletheia.journal.entries", return_value=[]):
            self.assertTrue(quick.answer("what did you change today").startswith("Nothing changed today"))

    def test_what_she_learned_today_is_his_facts_in_words(self):
        rows = self._entries([
            {"kind": "note", "actor": "aletheia-profile", "subject": "profile",
             "text": "his answer to 'What % of travel are you open to?' is on file"},
            {"kind": "note", "actor": "aletheia", "subject": "identity", "text": 'set identity.home_city = "Hartford, SD" (inferred)'},
            {"kind": "note", "actor": "operator", "subject": "operator", "text": "note that Dana called"}])
        with mock.patch("aletheia.journal.entries", return_value=rows):
            said = quick.answer("what did you learn today")
        self.assertTrue(said.startswith("Today I learned 2 things:"), said)
        self.assertIn("your answer to 'What % of travel are you open to?'", said)
        self.assertIn('home city = "Hartford, SD"', said)
        self.assertNotIn("Dana called", said, "his own note is not something she learned")

    def test_the_last_thing_she_wrote_is_read_back_from_the_workspace(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "notes.md").write_text("# Notes\nHello there.", encoding="utf-8")
            rows = self._entries([{"kind": "action", "actor": "aletheia-pursuit", "subject": "opportunity",
                                   "text": "write — wrote notes.md in the workspace"}])
            with mock.patch("aletheia.journal.entries", return_value=rows), \
                    mock.patch("aletheia.workspace.root", return_value=root):
                said = quick.answer("read me the last thing you wrote")
            self.assertIn("notes.md", said)
            self.assertIn("Hello there", said)
            with mock.patch("aletheia.journal.entries", return_value=[]), \
                    mock.patch("aletheia.workspace.root", return_value=root / "empty"):
                self.assertEqual(quick.answer("what did you write today"), "I haven't written anything in my workspace yet.")

    def test_what_is_on_my_desktop_is_the_newest_names_never_the_disk(self):
        with tempfile.TemporaryDirectory() as tmp:
            desk = Path(tmp) / "Desktop"
            desk.mkdir()
            for name in ("a.txt", "b.pdf"):
                (desk / name).write_text("x", encoding="utf-8")
            with mock.patch("aletheia.files.places", return_value=[("Desktop", desk)]):
                said = quick.answer("what's on my desktop")
            self.assertIn("2 things on your desktop", said)
            self.assertIn("a.txt", said)
            with mock.patch("aletheia.files.places", return_value=[]):
                self.assertIn("can't see a downloads folder", quick.answer("what files are on my downloads"))


if __name__ == "__main__":
    unittest.main()
