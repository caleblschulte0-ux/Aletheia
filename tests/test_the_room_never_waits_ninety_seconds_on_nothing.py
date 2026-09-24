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
                {"state": "SUBMITTED", "company": "Zeta", "job_title": "Partner Manager",
                 "submitted_at": stamp(now - dt.timedelta(days=1))}]
        with mock.patch("aletheia.apply_run.all_runs", lambda state=None: [r for r in rows if state in (None, r["state"])]):
            today = quick.answer("which jobs did you apply to today")
            yesterday = quick.answer("which jobs did you apply to yesterday")
        self.assertIn("1 application went out today: Account Executive at Acme", today)
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


if __name__ == "__main__":
    unittest.main()
