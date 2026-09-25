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
            mock.patch("aletheia.apply_run.all_runs", return_value=state.get("waiting", [
                {"id": "run-1", "state": "AWAITING_YOU", "engine": "form"}])),
            mock.patch("aletheia.apply_run.waits_for_his_ok", return_value=""),
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
        self.assertIn("1 filled application waits for your tap", said)
        self.assertIn("standing grant", said)
        self.assertIn("nobody can judge a job", said)
        self.assertIn("browser is not ready", said)
        self.assertIn("3 sent today", said)

    def test_the_grant_is_named_only_when_something_waits_on_it(self):
        # "Filled applications wait for your tap" with nothing filled is a
        # sentence about nothing; with no other switch on, it steps aside.
        self.assertIsNone(self._ask(granted=False, waiting=[]))

    def test_a_running_batch_is_the_answer_and_nothing_stopping_it_is_not_hers(self):
        running = self._ask(running={"started_at": "2026-09-24T15:02:00Z", "pid": 1})
        self.assertIn("a batch is running right now", running)
        self.assertIn("3 sent today", running)
        # No switch of hers explains it and nothing runs: the investigator's
        # question (test_grounded_status_without_a_model), not a quick one.
        self.assertIsNone(self._ask())

    def test_the_phrasings_he_uses_reach_it(self):
        for s in ("why aren't you applying", "why is the job hunt stuck",
                  "why aren't applications going out today"):
            self.assertEqual((quick.match(s) or ("",))[0], "hunt_why", s)
        # "Is the job hunt still running" has its own reader (the process,
        # not the clock) and must not be swallowed by the why.
        self.assertNotEqual((quick.match("is the job hunt still running") or ("",))[0], "hunt_why")


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
            self.assertEqual(quick.answer("yes"), "Nothing is waiting for a yes or no right now.")
            # "ok" is filler and left alone (test_filler_and_nudges).
            self.assertIsNone(quick.answer("ok"))
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


class TheEighthBatteryFallThroughs(unittest.TestCase):
    """Seven everyday sentences that a store settles went to a model
    (2026-09-24, every rung off): his interview window ("I don't have your
    interview window on record" - it was 1 to 2:30 PM Central the whole
    time), whether a repo ran today, "what did I say about the rent", the
    drafts count, "what questions do you need me to answer", "the next
    thing on my calendar" and "what did you fix today"."""

    def test_the_sentences_land_on_their_stores(self):
        for s, name in (("what questions do you need me to answer", "to_answer"),
                        ("what do you need answers to", "to_answer"),
                        ("what's the next thing on my calendar", "next_meeting"),
                        ("what did I say about the rent", "recall"),
                        ("what did you fix today", "changed_today"),
                        ("did you fix anything today", "changed_today"),
                        ("how many emails are in the drafts folder", "drafts"),
                        ("how many drafts do you have", "drafts"),
                        ("what's my interview window", "interview_window"),
                        ("when can I do interviews", "interview_window"),
                        ("did the shorts pipeline run today", "ran_today")):
            self.assertEqual((quick.match(s) or ("",))[0], name, s)
        self.assertEqual(quick.match("what did I say about the rent")[1], "rent")
        self.assertEqual(quick.match("did the shorts pipeline run today")[1], "shorts")

    def test_his_interview_window_is_her_own_switch(self):
        window = {"start": "13:00", "end": "14:30", "timezone": "America/Chicago"}
        with mock.patch("aletheia.interviews.status", return_value={"on": True, "window": window, "quote": "", "command": "x"}):
            said = quick.answer("what's my interview window")
        self.assertTrue(said.startswith("1 PM to 2:30 PM Central, on weekdays."), said)
        self.assertIn("I book inside that", said)
        with mock.patch("aletheia.interviews.status", return_value={"on": False, "window": window, "quote": "", "command": "x"}):
            said = quick.answer("what's my interview window")
        self.assertIn("switched off", said)

    def test_did_a_repo_run_today_is_the_pulses_own_times(self):
        import datetime as dt
        import json
        from aletheia import pulse
        from aletheia import localtime
        # Stamps at 9 and 10 this morning ON HIS CLOCK, written as UTC the way
        # the pulse writes them: "today" is his day wherever the test runs.
        tz = localtime.operator_tz()
        morning = dt.datetime.now(tz).replace(hour=9, minute=49, second=38, microsecond=0)
        stamp = lambda h: morning.replace(hour=h).astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")  # noqa: E731
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            (d / "latest.json").write_text(json.dumps({"repos": {
                "shorts_pipeline": {"github": "Shorts-pipeline", "health": "red", "workflows": {
                    "daily.yml": {"conclusion": "failure", "updated_at": stamp(9)},
                    "third.yml": {"conclusion": "success", "updated_at": stamp(10)},
                    "retro.yml": {"conclusion": "success", "updated_at": "2026-09-20T04:55:44Z"}}},
                "barkly": {"github": "Barkly", "health": "green", "workflows": {
                    "ci.yml": {"conclusion": "success", "updated_at": "2026-09-20T04:55:44Z"}}}}}), encoding="utf-8")
            with mock.patch.object(pulse, "PULSE_DIR", d):
                said = quick.answer("did the shorts pipeline run today")
                self.assertTrue(said.startswith("Yes. Shorts-pipeline today: third green at"), said)
                self.assertIn("daily red at", said)
                self.assertNotIn("retro", said)
                said = quick.answer("did barkly run today")
                self.assertTrue(said.startswith("Not today. The last run of Barkly was ci, green,"), said)
                # A name the pulse does not know is a model's question, never a guess.
                self.assertIsNone(quick.answer("did the trader run today"))
            with mock.patch.object(pulse, "PULSE_DIR", d / "nowhere"):
                self.assertTrue(quick.answer("did the shorts pipeline run today").startswith("No fleet reading yet"))

    def test_the_ninth_battery_three_near_misses(self):
        import datetime as dt
        from aletheia import localtime, voice
        # "what's the Barkly status" is the pulse's row, like "how's the trader".
        for s in ("what's the barkly status", "barkly status", "what is the status of barkly"):
            self.assertEqual(quick.status_of(s), ("repo", "barkly"), s)
        # "what day is it tomorrow" is arithmetic, not a model.
        tomorrow = dt.datetime.now(localtime.operator_tz()) + dt.timedelta(days=1)
        said = quick.answer("what day is it tomorrow")
        self.assertTrue(said.startswith(f"Tomorrow is {tomorrow.strftime('%A')} the"), said)
        self.assertEqual(quick.match("what's tomorrow")[0], "date")
        self.assertFalse(quick.answer("what day is it").startswith("Tomorrow"))
        # "read me my notes" is the notes reader, not a file search for "my".
        out = voice.interpret("thea read me my notes")
        self.assertNotEqual((out.get("command") or {}).get("kind"), "file_find", out)
        self.assertEqual(quick.match("read me my notes")[0], "notes_list")
        out = voice.interpret("thea read me the positioning notes")
        self.assertEqual((out.get("command") or {}).get("kind"), "file_find")

    def test_the_whole_replay_at_the_true_bottom_rung(self):
        """135 sentences replayed with the Claude CLI actually hidden
        (patched, not a PATH strip): four fell through that a store settles."""
        for s, name in (("what did we talk about earlier", "asked_on"),
                        ("what have we discussed today", "asked_on"),
                        ("what's the wifi password", "recall"),
                        ("how many jobs are left to apply to", "jobs_left"),
                        ("what's left to apply for", "jobs_left")):
            self.assertEqual((quick.match(s) or ("",))[0], name, s)
        self.assertEqual(quick.match("what did we talk about earlier")[1], "earlier")
        self.assertEqual(quick.match("what's the wifi password")[1], "wifi")
        with mock.patch("aletheia.current_state.job_hunt_words", return_value="Today: 4 found, 2 sent."):
            said = quick.answer("how many jobs are left to apply to")
        self.assertTrue(said.startswith("There's no queue to work down"), said)
        self.assertIn("2 sent", said)
        with mock.patch("aletheia.liveness.uptime_seconds", return_value=None):
            # No heartbeat on record: the fast lane declines rather than invents (test_liveness).
            self.assertIsNone(quick.answer("how long has the core been running"))

    def test_the_tenth_battery_orders_at_the_bottom_rung(self):
        """Twenty-seven orders with every rung off (2026-09-24). Five had no
        rule and went to nobody: a thing to do on "my list", the announcements
        switch, a hold on his calendar, a file with text he already has - and
        "am I free Friday evening" was answered about office hours."""
        import datetime as dt
        from aletheia import intercom, voice

        def kind(s):
            return voice.interpret(f"thea {s}").get("command") or {}
        self.assertEqual(kind("add call the dentist to my list")["kind"], "task_new")
        self.assertEqual(kind("add call the dentist to my list")["description"], "call the dentist")
        self.assertEqual(kind("add milk to my list")["kind"], "shopping_add")
        self.assertEqual(kind("add call the dentist to my shopping list")["kind"], "shopping_add")
        self.assertEqual(kind("turn announcements off"), {"kind": "announce_set", "on": False})
        self.assertEqual(kind("turn announcements on"), {"kind": "announce_set", "on": True})
        self.assertEqual(kind("stop announcing things")["on"], False)
        held = kind("put dinner with Sam on my calendar friday at 7")
        self.assertEqual(held["kind"], "calendar_hold")
        self.assertEqual(held["title"], "dinner with Sam")
        start = dt.datetime.fromisoformat(held["start"])
        self.assertEqual((start.strftime("%A"), start.hour), ("Friday", 19), held)
        self.assertEqual(dt.datetime.fromisoformat(kind("hold friday at 10 for the tour")["start"]).hour, 10)
        self.assertEqual(dt.datetime.fromisoformat(kind("add the dentist to my calendar tomorrow afternoon")["start"]).hour, 14)
        self.assertEqual(kind("put dinner on my calendar")["kind"], "intent", "no day and no time is the planner's")
        self.assertEqual(kind("write a file called notes.md with hello"),
                         {"kind": "file_write", "path": "notes.md", "text": "hello"})
        self.assertEqual(kind("write a file called todo with buy milk")["path"], "todo.txt")
        # The evening is looked at as the evening.
        seen = {}

        def slots(day, **kw):
            seen.update(kw)
            return []
        with mock.patch("aletheia.calendar.free_slots", side_effect=slots), \
                mock.patch("aletheia.calendar.all_events", return_value=[{"start": "2026-09-01T09:00:00"}]):
            said = intercom.free_time_answer({"kind": "free_time", "day": "2026-09-25", "part": "evening"})
        self.assertEqual((seen["work_start"].hour, seen["work_end"].hour), (17, 22))
        self.assertNotIn("working hours", said)

    def test_undo_that_is_his_word_over_her_own_ledger(self):
        """"Undo that" went to nobody at the bottom rung (2026-09-24). It is a
        kind now: his word, forbidden to every planner, over the newest
        reversible act of her own; a decision of his and an outward act are
        refused by name inside autonomy.undo."""
        import os
        from aletheia import agenda, autonomy, intercom, tasks, voice
        self.assertIn("undo", intercom.PLANNER_FORBIDDEN)
        self.assertIn("undo", agenda.FORBIDDEN_KINDS)
        for s in ("undo that", "take that back", "undo the last thing you did", "undo"):
            self.assertEqual(voice.interpret(f"thea {s}")["command"], {"kind": "undo"}, s)
        self.assertEqual(voice.interpret("thea undo the task you added")["command"], {"kind": "undo", "which": "task"})
        self.assertNotEqual((voice.interpret("thea undo the study change").get("command") or {}).get("kind"), "undo",
                            "a study verdict keeps its own verb")
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.dict(os.environ, {"ALETHEIA_PRIVATE_STATE": tmp}), \
                mock.patch.object(tasks, "TASKS_DIR", Path(tmp) / "tasks"), \
                mock.patch("aletheia.journal.append"):
            self.assertTrue(intercom.execute_command({"kind": "undo"}, {}, quote="undo that")
                            .startswith("Nothing to undo"))
            tasks.create("t-plumber", "call the plumber", goal="voice")
            autonomy.record(tool="task_new", args={"id": "t-plumber"}, consequence="reversible_local",
                            said="added a task: call the plumber",
                            undo={"how": autonomy.TASK_CANCEL, "task": "t-plumber"})
            autonomy.record(tool="email_draft", args={}, consequence="outward", said="drafted a note to Sam")
            said = intercom.execute_command({"kind": "undo", "which": "email"}, {}, quote="undo the email")
            self.assertTrue(said.startswith("I have nothing of my own to take back that matches email"), said)
            said = intercom.execute_command({"kind": "undo"}, {}, quote="undo that")
            self.assertTrue(said.startswith("Undone: cancelled the task I added"), said)
            self.assertEqual(tasks.load("t-plumber")["status"], "CANCELLED")
            self.assertTrue(intercom.execute_command({"kind": "undo"}, {}, quote="undo that")
                            .startswith("Nothing to undo"))

    def test_the_eleventh_battery(self):
        """"Undo that" after his own "add a task" said nothing to undo (the
        ledger holds only what she did unasked); a weekday agenda, the
        notification count and "what time is my interview window" went to
        nobody; and his note read back as "operator: ..." among her acts."""
        import datetime as dt
        import os
        from aletheia import intercom, localtime, recollection, tasks
        for s, name in (("what's on my calendar monday", "agenda"), ("what do I have on friday", "agenda"),
                        ("how many notifications do I have", "notify_count"),
                        ("any new notifications", "notify_count"),
                        ("what time is my interview window", "interview_window")):
            self.assertEqual((quick.match(s) or ("",))[0], name, s)
        now = dt.datetime.now(localtime.operator_tz())
        monday = now.date() + dt.timedelta(days=(0 - now.weekday()) % 7)
        with mock.patch("aletheia.calendar.all_events", return_value=[
                {"title": "Dentist", "start": f"{monday.isoformat()}T14:00:00", "status": "CONFIRMED"}]), \
                mock.patch("aletheia.calendar.parse_time", side_effect=lambda s: dt.datetime.fromisoformat(s).replace(tzinfo=localtime.operator_tz())):
            said = quick.answer("what's on my calendar monday")
        self.assertIn("Dentist at 2 pm", said, said)
        with mock.patch("aletheia.notifications.all_notifications", return_value=[]):
            self.assertEqual(quick.answer("how many notifications do I have"), "No unread notifications.")
        row = recollection._row({"ts": "2026-09-24T20:00:00Z", "kind": "note", "actor": "operator-local-core",
                                 "subject": "operator", "text": "my landlord's name is Dana"})
        self.assertEqual(row["what"], "Noted: my landlord's name is Dana")
        self.assertIn("core:note", recollection.SAID_NOT_DID)
        # Undo his own last ask: the task he just added is cancelled.
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.dict(os.environ, {"ALETHEIA_PRIVATE_STATE": tmp}), \
                mock.patch.object(tasks, "TASKS_DIR", Path(tmp) / "tasks"), \
                mock.patch("aletheia.journal.append"), \
                mock.patch("aletheia.converse.recent", return_value=[
                    {"he_asked": "add a task to call the plumber", "she_said": "Added a task: call the plumber."}]):
            tasks.create("call-the-plumber", "call the plumber", goal="voice")
            said = intercom.execute_command({"kind": "undo"}, {}, quote="undo that")
            self.assertEqual(said, "Undone: cancelled the task call the plumber.")
            self.assertEqual(tasks.load("call-the-plumber")["status"], "CANCELLED")
        with mock.patch("aletheia.converse.recent", return_value=[{"he_asked": "what time is it"}]), \
                mock.patch("aletheia.autonomy.recent", return_value=[]):
            self.assertTrue(intercom.execute_command({"kind": "undo"}, {}, quote="undo that").startswith("Nothing to undo"))

    def test_the_twelfth_battery_follow_ups(self):
        """"And Friday?", "what about next week", "read them", "make that 4",
        "cancel it": six follow-up turns went to nobody at the bottom rung
        (2026-09-24). The previous sentence is rebuilt and asked again."""
        import datetime as dt
        from aletheia import intercom, localtime, voice

        def after(prev):
            return mock.patch("aletheia.converse.recent", return_value=[{"he_asked": prev, "she_answered": "x"}])
        with after("what's on my calendar tomorrow"), mock.patch("aletheia.calendar.all_events", return_value=[]):
            self.assertEqual(quick.answer("and friday"), "Nothing on your calendar Friday.")
            self.assertEqual(quick.answer("what about next week"), "Nothing on your calendar next week.")
        with after("is the trader running"), \
                mock.patch("aletheia.current_state.repo_words", side_effect=lambda n: f"{n} is healthy." if "shorts" in n else None), \
                mock.patch.object(quick, "_no_pulse", return_value=False):
            self.assertEqual(quick.answer("and the shorts pipeline"), "shorts is healthy.")
        with after("how many tasks do I have"), mock.patch("aletheia.tasks.all_tasks", return_value=[]):
            said = quick.answer("read them")
            self.assertIsNotNone(said)
            self.assertIn("task", said.lower())
        with after("what time is it"):
            self.assertIsNone(quick.answer("and friday"), "nothing to rebuild from a question with no day")
            self.assertIsNone(quick.answer("read them"))
        # "Make that 4" moves the reminder he just set; "cancel it" takes it back.
        with after("remind me at 3 to call the dentist"):
            moved = voice.interpret("thea make that 4")["command"]
            self.assertEqual((moved["kind"], moved["text"], moved["replaces"]),
                             ("remind_at", "call the dentist", "call the dentist"))
            self.assertEqual(dt.datetime.fromisoformat(moved["at"]).astimezone(localtime.operator_tz()).hour, 16)
            with mock.patch("aletheia.policy.all_approvals", return_value=[]):
                self.assertEqual(voice.interpret("thea cancel it")["command"], {"kind": "undo"})
        with after("what time is it"), mock.patch("aletheia.policy.all_approvals", return_value=[]):
            self.assertIsNone(voice.interpret("thea cancel it")["command"])
            self.assertEqual(voice.interpret("thea make that 4")["command"]["kind"], "intent")
        self.assertIn("replaces", intercom.KIND_ARGS["remind_at"][1])
        # "Cancel it" after "make that 4" still finds the reminder, not the move.
        with mock.patch("aletheia.converse.recent", return_value=[
                {"he_asked": "remind me at 3 to call the dentist"}, {"he_asked": "make that 4"}]), \
                mock.patch("aletheia.policy.all_approvals", return_value=[]):
            self.assertEqual(voice.interpret("thea cancel it")["command"], {"kind": "undo"})
        # A task's state line reads as a sentence with the task's own words.
        from aletheia import recollection
        with mock.patch("aletheia.tasks.load", return_value={"description": "renew the car insurance"}):
            row = recollection._row({"ts": "2026-09-24T20:00:00Z", "kind": "task", "actor": "aletheia-tasks",
                                     "subject": "task:renew-the-car-insurance",
                                     "text": "QUEUED -> COMPLETED — marked done: spoken to the wall: thea mark the first one done"})
        self.assertEqual(row["what"], "Marked done: renew the car insurance")

    def test_the_thirteenth_battery_the_job_hunt_and_the_mail(self):
        """Job-hunt, mail and interview questions at the bottom rung
        (2026-09-24): the newest application, who is waiting on a reply
        from him, the mail hold, what she is drafting, the interview switch,
        "what happened with the job hunt overnight", openings this week."""
        import datetime as dt
        from aletheia import conversations, localtime
        for s, name in (("what's the newest application", "newest_application"),
                        ("which one did you apply to last", "newest_application"),
                        ("what should I follow up on", "follow_ups"),
                        ("who do I need to write back to", "follow_ups"),
                        ("is the mail hold still on", "sending"),
                        ("are you holding my emails", "sending"),
                        ("what are you drafting", "drafts"),
                        ("what's the interview switch set to", "interview_window"),
                        ("are you booking interviews", "interview_window"),
                        ("what happened with the job hunt overnight", "overnight"),
                        ("what did the job hunt do while I was asleep", "overnight"),
                        ("how many jobs did you find this week", "found")):
            self.assertEqual((quick.match(s) or ("",))[0], name, s)
        self.assertEqual(quick.match("how many jobs did you find this week")[1], "this week")
        self.assertEqual(quick.match("how many jobs did you find today")[1], "")
        rec = {"id": "apply-9", "state": "SUBMITTED", "company": "Vanta", "job_title": "CSM",
               "submitted_at": "2026-09-24T06:00:00Z", "staged_at": "2026-09-24T05:00:00Z"}
        old = {"id": "apply-1", "state": "AWAITING_YOU", "company": "Ramp", "job_title": "AE",
               "staged_at": "2026-09-20T05:00:00Z"}
        with mock.patch("aletheia.apply_run.all_runs", return_value=[old, rec]), \
                mock.patch("aletheia.apply_run.describe", side_effect=lambda r: f"{r['job_title']} at {r['company']}"):
            said = quick.answer("what's the newest application")
        self.assertTrue(said.startswith("The newest is CSM at Vanta: sent"), said)
        with mock.patch("aletheia.apply_run.all_runs", return_value=[]):
            self.assertEqual(quick.answer("what's the newest application"), "No applications on record yet.")
        with mock.patch("aletheia.conversations.all_threads", side_effect=lambda state=None: (
                [{"id": "conv-1", "to": "dana@example.com", "name": "Dana"}] if state == conversations.REPLIED else [])), \
                mock.patch("aletheia.conversations._name", return_value="Dana"):
            said = quick.answer("who do I need to write back to")
        self.assertEqual(said, "1 reply waiting on you: Dana.")
        with mock.patch("aletheia.conversations.all_threads", return_value=[]):
            self.assertTrue(quick.answer("what should I follow up on").startswith("Nobody is waiting"))
        stamp = dt.datetime.now(dt.timezone.utc)
        rows = [{"ts": (stamp - dt.timedelta(days=d)).strftime("%Y-%m-%dT%H:%M:%SZ"), "kind": "note",
                 "actor": "aletheia-campaign", "subject": "jobs",
                 "text": f"I found {100 + d} openings today, {10 + d} of them realistic"} for d in (0, 1, 2)]
        with mock.patch("aletheia.journal.entries", return_value=list(reversed(rows))):
            said = quick.answer("how many jobs did you find this week")
        self.assertTrue(said.startswith("303 openings found this week over 3 days, 33 worth applying to."), said)
        # The mail verbs he says in the other word order.
        from aletheia import voice
        self.assertEqual(voice.interpret("thea read me the email from Stripe")["command"],
                         {"kind": "email_read", "which": "Stripe"})
        self.assertEqual(voice.interpret("thea draft a reply to Stripe saying thanks for the call")["command"],
                         {"kind": "email_draft", "to": "Stripe", "body": "thanks for the call"})
        self.assertEqual(voice.interpret("thea reply to Dana saying see you at 6")["command"]["kind"], "email_draft")
        self.assertNotEqual((voice.interpret("thea read me the last email").get("command") or {}).get("which"), "last")

    def test_the_fourteenth_battery_her_machine(self):
        """Her own machine at the bottom rung (2026-09-24): "20 percent of 45
        dollars", "how much memory are you using", "what's using the CPU",
        "what timers do I have", "shut down the computer", and the eyes'
        NotGranted read out with its class name."""
        from aletheia import act, eyes, intercom, voice
        self.assertEqual(quick.answer("what's 20 percent of 45 dollars"), "$9.")
        self.assertEqual(quick.answer("what's 15 percent of 80"), "12.")
        for s, name in (("how much memory are you using", "memory_free"),
                        ("what's using the cpu", "cpu"), ("why is my pc so slow", "cpu"), ("what's the cpu at", "cpu")):
            self.assertEqual((quick.match(s) or ("",))[0], name, s)
        self.assertIn((quick.match("how much ram is in use") or ("",))[0], ("memory_free", "machine"))
        said = quick.answer("what's using the cpu")
        self.assertTrue(said.startswith(("The processor is at", "I can't read this machine's processor")), said)
        self.assertNotIn("System Idle Process", said)
        self.assertEqual((voice.interpret("thea what timers do I have").get("command") or {}).get("kind"), "reminders")
        for s in ("shut down the computer", "lock the pc", "restart the computer", "turn off my laptop"):
            out = voice.interpret(f"thea {s}")
            self.assertIsNone(out["command"], s)
            self.assertIn("yours at the keyboard", out["say"])
        self.assertEqual(voice.interpret("thea restart yourself")["command"]["kind"], "restart")
        with mock.patch("aletheia.eyes.answer", side_effect=eyes.NotGranted("looking at the actual picture of your screen is switched off")), \
                mock.patch("aletheia.perception.window_named", return_value=None, create=True):
            with self.assertRaises(act.Refused) as ctx:
                intercom.execute_command({"kind": "screen_ask", "question": "what's on my screen"}, {}, quote="t")
        self.assertNotIn("NotGranted", str(ctx.exception))

    def test_the_fifteenth_battery_the_rundown(self):
        """Casual asks at the bottom rung (2026-09-24): "are we good" looked
        up a repo called "we"; "summarize today", "how was your day", "what
        should I do next" and "how many applications are waiting" went to
        nobody."""
        for s, name in (("are we good", "status"), ("is everything ok", "status"), ("summarize today", "status"),
                        ("how was your day", "status"), ("what should I do next", "focus"),
                        ("how many applications are waiting", "applications_waiting"),
                        ("how many are waiting on me", "applications_waiting")):
            self.assertEqual((quick.match(s) or ("",))[0], name, s)
        rows = [{"id": "a1", "state": "AWAITING_YOU"}, {"id": "a2", "state": "AWAITING_YOU"}, {"id": "a3", "state": "AWAITING_YOU"}]
        with mock.patch("aletheia.apply_run.all_runs", side_effect=lambda state=None: rows if state == "AWAITING_YOU" else []), \
                mock.patch("aletheia.campaign.open_questions", return_value=[{"label": "Shift?", "jobs": ["a1", "a2"]}]):
            said = quick.answer("how many applications are waiting")
        self.assertEqual(said, "3 applications waiting: 2 on 1 question only you can answer, 1 on the next beat.")
        with mock.patch("aletheia.apply_run.all_runs", return_value=[]):
            self.assertTrue(quick.answer("how many applications are waiting").startswith("None waiting"))

    def test_the_sixteenth_battery_the_drafts_ledger(self):
        """His 2026-09-24 ruling: she tracks the drafts and keeps them in
        order. At the bottom rung "read me the draft to Stripe" went to
        nobody, "is the mail hold on" answered "No." while it was on, and
        "lift the mail hold" went to nobody (it is his, at the keyboard)."""
        from aletheia import voice
        drafts = [{"id": "mail-2", "to": "jobs@stripe.com", "to_name": "Stripe", "subject": "Thanks for the call",
                   "body": "Thanks for the call today. I enjoyed it.", "created": "2026-09-24T20:00:00Z", "held": True},
                  {"id": "mail-1", "to": "dana@example.com", "to_name": "Dana", "subject": "Dinner",
                   "body": "See you at six.", "created": "2026-09-24T18:00:00Z", "held": True}]
        with mock.patch("aletheia.mail.held_drafts", return_value=drafts):
            said = quick.answer("read me the draft to Stripe")
            self.assertTrue(said.startswith("To Stripe, drafted"), said)
            self.assertIn("'Thanks for the call': Thanks for the call today.", said)
            self.assertIn("See you at six", quick.answer("what did you draft for Dana"))
            self.assertEqual(quick.answer("what's in the draft to Nobody"), "I have no draft to Nobody.")
        for s in ("who have you drafted to today", "what did you draft today"):
            self.assertEqual(quick.match(s)[0], "drafts", s)
        on = {"on": True, "quote": "q", "since": "", "command": "python -m aletheia.mail hold off"}
        off = {"on": False, "quote": "", "since": "", "command": "python -m aletheia.mail hold off"}
        with mock.patch("aletheia.mail.outward_hold", return_value=on), mock.patch("aletheia.mail.drafts_ledger", return_value=[]):
            self.assertTrue(quick.answer("is the mail hold on").startswith("Yes."))
            self.assertTrue(quick.answer("are you holding my emails").startswith("Yes."))
            self.assertTrue(quick.answer("is the mail hold off").startswith("No, it's still on."))
            self.assertTrue(quick.answer("are you sending emails").startswith("No."))
        with mock.patch("aletheia.mail.outward_hold", return_value=off), mock.patch("aletheia.mail.drafts_ledger", return_value=[]):
            self.assertTrue(quick.answer("is the mail hold on").startswith("No, the hold is lifted"))
            self.assertTrue(quick.answer("is the mail hold lifted").startswith("Yes, the hold is lifted"))
            self.assertTrue(quick.answer("are you sending emails").startswith("Yes,"))
        with mock.patch("aletheia.mail.outward_hold", return_value=on):
            out = voice.interpret("thea lift the mail hold")
        self.assertIsNone(out["command"])
        self.assertIn("yours, at the keyboard", out["say"])
        self.assertIn("mail hold off", out["say"])

    def test_the_seventeenth_battery_four_orders_from_the_whole_replay(self):
        """247 sentences replayed at the floor: "cancel the passport task"
        (no verb), "move the dentist to 4" (a named reminder), "make me a
        word document called notes with the text hello", and "open youtube"
        (compiled for approval as a browser task)."""
        import datetime as dt
        from aletheia import localtime, open_it, voice
        with mock.patch("aletheia.intercom._one_task", return_value=({"id": "renew-passport", "description": "renew the passport"}, "")):
            self.assertEqual(voice.interpret("thea cancel the passport task")["command"],
                             {"kind": "task_status", "id": "renew-passport", "state": "CANCELLED", "note": "cancelled by voice"})
        with mock.patch("aletheia.intercom._one_task", return_value=(None, "You have no task about the passport.")):
            out = voice.interpret("thea cancel the passport task")
            self.assertIsNone(out["command"])
            self.assertIn("no task", out["say"])
        with mock.patch("aletheia.intercom._one_reminder", return_value=({"id": "r1", "command": {"text": "call the dentist"}}, "")):
            moved = voice.interpret("thea move the dentist to 4")["command"]
        self.assertEqual((moved["kind"], moved["text"], moved["replaces"]), ("remind_at", "call the dentist", "call the dentist"))
        self.assertEqual(dt.datetime.fromisoformat(moved["at"]).astimezone(localtime.operator_tz()).hour, 16)
        made = voice.interpret("thea make me a word document called notes with the text hello there")["command"]
        self.assertEqual(made, {"kind": "doc_make", "path": "notes.docx", "content": ["hello there"]})
        self.assertEqual(voice.interpret("thea open youtube")["command"], {"kind": "open_page", "which": "youtube"})
        self.assertEqual(voice.interpret("thea open the thea page")["command"], {"kind": "open_page", "which": "the thea page"})
        self.assertEqual(open_it.page_for("youtube")[1], "YouTube")
        self.assertEqual(open_it.page_for("the Thea page")[0], "http://127.0.0.1:8777/")
        self.assertNotEqual((voice.interpret("thea open my resume").get("command") or {}).get("kind"), "open_page",
                            "a word not in the table is never guessed into an address")
        self.assertEqual(voice.interpret("thea open thea")["command"]["kind"], "open", "her own switch keeps its word")
        # The rules never open a door, a window or his resume "in the browser".
        from aletheia import rule_planner
        for s in ("open the door", "open the window", "open my resume", "open the notes file"):
            self.assertIsNone(rule_planner.match(s), s)
        self.assertEqual(rule_planner.match("open hacker news")[0], "web_task")

    def test_what_did_i_say_about_is_his_note(self):
        with mock.patch.object(quick, "_notes", return_value=[
                {"ts": "2026-09-24T20:00:00Z", "text": "the rent is due on the first"}]), \
                mock.patch("aletheia.memory.everything", return_value={}):
            said = quick.answer("what did I say about the rent") or ""
        self.assertIn("rent is due on the first", said)


if __name__ == "__main__":
    unittest.main()
