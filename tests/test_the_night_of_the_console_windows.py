"""He woke to console windows opening and closing three and four at a time.

2026-09-13, overnight, with the job hunt running unattended. Four defects
stacked, and each of these tests holds one of them:

- The browser lock asked `tasklist` once a second whether the process
  holding Chrome was still alive. From a windowless process every call got
  its own console tab: Windows Terminal crashed twice and he had to restart
  the machine. Nothing may spawn a console without saying why.
- A batch ran longer than the campaign lock's three-hour staleness, so the
  loop started a second batch beside it, the first deleted the second's lock
  when it finished, and a third started. All of them queued on one browser.
- The submit process's time limit was EXACTLY the browser lock's wait, so a
  queued submit was killed the moment it would have got the browser, left at
  SUBMITTING for good, and its Chrome left holding the profile: the next
  launches died with TargetClosedError.
- A waiter that gave up opened the profile anyway, into that collision.
"""
from __future__ import annotations

import ast
import datetime as dt
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

from aletheia import apply_run, browse, campaign, proc, runtime, stateio
from aletheia.fleet import REPO_ROOT

import tests.test_apply_run as apply_base

SPAWNERS = ("run", "Popen", "call", "check_output", "check_call")


def _sleeper(*marks: str) -> subprocess.Popen:
    return subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)", *marks],
                            creationflags=proc.hidden_flags())


def _dead_pid() -> int:
    child = subprocess.Popen([sys.executable, "-c", "pass"],
                             creationflags=proc.hidden_flags())
    child.wait()
    return child.pid


def _gone(child: subprocess.Popen) -> None:
    try:
        child.kill()
        child.wait(timeout=10)
    except Exception:
        pass


class NothingOpensAConsoleWithoutSayingWhy(unittest.TestCase):
    def test_every_subprocess_she_starts_is_windowless_or_marked(self):
        offenders = []
        for path in sorted((REPO_ROOT / "aletheia").glob("*.py")):
            if path.name == "proc.py":
                continue
            source = path.read_text(encoding="utf-8")
            lines = source.splitlines()
            for node in ast.walk(ast.parse(source)):
                if not isinstance(node, ast.Call):
                    continue
                f = node.func
                if not (isinstance(f, ast.Attribute) and f.attr in SPAWNERS
                        and isinstance(f.value, ast.Name) and f.value.id == "subprocess"):
                    continue
                if any(k.arg == "creationflags" for k in node.keywords):
                    continue
                around = "\n".join(lines[max(0, node.lineno - 12):node.end_lineno])
                if "proc: visible-by-design" in around:
                    continue
                splats = [k.value.id for k in node.keywords
                          if k.arg is None and isinstance(k.value, ast.Name)]
                if any("NO_WINDOW" in s or f'{s}["creationflags"]' in around for s in splats):
                    continue
                offenders.append(f"{path.name}:{node.lineno}")
        self.assertEqual(offenders, [],
                         "each of these opens a console window from a windowless "
                         "process: pass creationflags=proc.hidden_flags(), or mark it "
                         "'# proc: visible-by-design' and say why")

    def test_asking_whether_a_process_lives_starts_no_process(self):
        dead = _dead_pid()
        with mock.patch.object(subprocess, "run", side_effect=AssertionError("spawned")), \
             mock.patch.object(subprocess, "Popen", side_effect=AssertionError("spawned")):
            self.assertTrue(proc.pid_alive(os.getpid()))
            self.assertFalse(proc.pid_alive(dead))


class APidIsOnlyOursIfItsCommandLineSaysSo(unittest.TestCase):
    def test_a_reused_pid_is_not_our_campaign(self):
        self.assertFalse(proc.pid_alive(os.getpid(), needle="aletheia.no-such-module"))

    def test_a_named_process_is_found(self):
        child = _sleeper("aletheia.campaign")
        self.addCleanup(_gone, child)
        self.assertTrue(proc.pid_alive(child.pid, needle="aletheia.campaign"))


class TheBrowserLock(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.profile = pathlib.Path(tmp.name) / "browser-profile"
        self.profile.mkdir()
        self.path = self.profile.parent / "browser-profile.lock"

    def hold(self, pid: int, *, old: bool = False) -> None:
        self.path.write_text(str(pid), encoding="utf-8")
        if old:
            stamp = time.time() - 10_000
            os.utime(self.path, (stamp, stamp))

    def lock(self, wait_s=1.5):
        made = browse._profile_lock(self.profile)
        made.wait_s = wait_s
        made.stale_after_s = 60.0
        return made

    def test_a_dead_holder_is_stolen_at_once(self):
        self.hold(_dead_pid())
        started = time.monotonic()
        self.assertTrue(self.lock(wait_s=30).acquire())
        self.assertLess(time.monotonic() - started, 5)

    def test_a_live_holder_is_not_robbed_for_being_old(self):
        child = _sleeper()
        self.addCleanup(_gone, child)
        self.hold(child.pid, old=True)
        self.assertFalse(self.lock().acquire(),
                         "an old lock held by a running process is a long session")

    def test_a_busy_browser_says_so_and_opens_nothing(self):
        child = _sleeper()
        self.addCleanup(_gone, child)
        self.hold(child.pid)
        with mock.patch.object(browse, "PROFILE_LOCK_WAIT_S", 1.0):
            with self.assertRaises(browse.BrowserBusy):
                with browse._Session(profile=self.profile):
                    self.fail("opened a browser someone else holds")
        self.assertEqual(self.path.read_text(encoding="utf-8"), str(child.pid))

    def test_a_launch_that_fails_gives_the_browser_back(self):
        pw = mock.MagicMock()
        pw.chromium.launch_persistent_context.side_effect = RuntimeError("no chrome")
        starter = mock.MagicMock()
        starter.return_value.start.return_value = pw
        with mock.patch("playwright.sync_api.sync_playwright", starter), \
             mock.patch.object(browse, "_browser_executable", return_value=None):
            with self.assertRaises(RuntimeError):
                with browse._Session(profile=self.profile):
                    pass
        self.assertFalse(self.path.exists(), "a failed launch kept the lock")


class OneCampaignAtATime(unittest.TestCase):
    def setUp(self):
        campaign.RUN_DIR.mkdir(parents=True, exist_ok=True)
        self.addCleanup(campaign._release)

    def lock(self, pid, *, hours_ago=0.0):
        started = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=hours_ago)
        campaign.LOCK_PATH.write_text(json.dumps(
            {"kind": "campaign", "pid": pid, "started_at": started.isoformat()}),
            encoding="utf-8")

    def test_a_dead_campaign_holds_nothing(self):
        self.lock(_dead_pid())
        self.assertIsNone(campaign.running())

    def test_a_long_healthy_batch_is_not_run_beside(self):
        child = _sleeper("aletheia.campaign")
        self.addCleanup(_gone, child)
        self.lock(child.pid, hours_ago=2.5)
        self.assertIsNotNone(campaign.running())

    def test_a_hung_batch_is_stopped_not_joined(self):
        child = _sleeper("aletheia.campaign")
        self.addCleanup(_gone, child)
        self.lock(child.pid, hours_ago=5)
        self.assertIsNone(campaign.running())
        child.wait(timeout=15)
        self.assertIsNotNone(child.returncode, "the hung batch is still running")

    def test_finishing_never_deletes_another_campaigns_lock(self):
        child = _sleeper("aletheia.campaign")
        self.addCleanup(_gone, child)
        self.lock(child.pid)
        campaign._release(owner=os.getpid())
        self.assertTrue(campaign.LOCK_PATH.exists())
        campaign._release(owner=child.pid)
        self.assertFalse(campaign.LOCK_PATH.exists())

    def test_a_batch_has_a_time_limit_well_inside_the_lock(self):
        self.assertLess(campaign.MAX_RUN * 1.5, campaign.STALE_LOCK)


class ASubmitIsSettledHonestly(apply_base.ApplyCase):
    def ready_and_confirmed(self):
        out = self.staged(extra={"#felony": "No", "#cert": True})
        apply_run.confirm(out["id"])
        return out

    def rewrite(self, run_id, **fields):
        record = apply_run.load_run(run_id)
        record.update(fields)
        for key, value in list(fields.items()):
            if value is None:
                record.pop(key)
        stateio.write_json_atomic(apply_run._record_path(run_id), record)
        return record

    def test_a_busy_browser_puts_it_back_in_line(self):
        out = self.ready_and_confirmed()
        with self.assertRaises(browse.BrowserBusy):
            apply_run.submit(out["id"], submitter=lambda r: (_ for _ in ()).throw(
                browse.BrowserBusy("busy")))
        record = apply_run.load_run(out["id"])
        self.assertEqual(record["state"], "AWAITING_YOU")
        self.assertIsNone(apply_run.was_sent(record["url"]))

    def test_it_stops_going_back_after_a_few_turns(self):
        out = self.ready_and_confirmed()
        for _ in range(apply_run.MAX_SUBMIT_TRIES):
            apply_run.accept(out["id"])
            with self.assertRaises(browse.BrowserBusy):
                apply_run.submit(out["id"], submitter=lambda r: (_ for _ in ()).throw(
                    browse.BrowserBusy("busy")))
        self.assertEqual(apply_run.load_run(out["id"])["state"], "FAILED")

    def test_pressed_and_then_broken_counts_as_sent(self):
        out = self.ready_and_confirmed()

        def pressed_then_gone(record):
            record["pressed_at"] = stateio.utcnow()
            raise RuntimeError("the page went away")
        record = apply_run.submit(out["id"], submitter=pressed_then_gone)
        self.assertEqual(record["state"], "SUBMITTED")
        self.assertEqual(record["result"]["verdict"], "submitted, unconfirmed")
        self.assertIn("Check your email", record["result"]["note"])
        self.assertIsNotNone(apply_run.was_sent(record["url"]), "it could be sent twice")

    def test_an_old_stuck_submit_with_no_trace_is_counted_as_maybe_sent(self):
        out = self.ready_and_confirmed()
        self.rewrite(out["id"], state="SUBMITTING", submit_pid=None,
                     submitted_at="2026-09-13T09:18:55Z")
        settled = apply_run.reconcile_stuck_submits()
        self.assertEqual([r["id"] for r in settled], [out["id"]])
        record = apply_run.load_run(out["id"])
        self.assertEqual(record["state"], "SUBMITTED")
        self.assertIsNotNone(apply_run.was_sent(record["url"]))

    def test_a_dead_submit_that_never_pressed_goes_back_in_line(self):
        out = self.ready_and_confirmed()
        self.rewrite(out["id"], state="SUBMITTING", submit_pid=_dead_pid(),
                     submitted_at=stateio.utcnow())
        apply_run.reconcile_stuck_submits()
        self.assertEqual(apply_run.load_run(out["id"])["state"], "AWAITING_YOU")

    def test_a_submit_still_working_is_left_alone(self):
        child = _sleeper("aletheia.apply_run")
        self.addCleanup(_gone, child)
        out = self.ready_and_confirmed()
        self.rewrite(out["id"], state="SUBMITTING", submit_pid=child.pid,
                     submitted_at=stateio.utcnow())
        self.assertEqual(apply_run.reconcile_stuck_submits(), [])
        self.assertEqual(apply_run.load_run(out["id"])["state"], "SUBMITTING")

    def test_a_submit_out_of_time_is_settled_not_left_at_submitting(self):
        out = self.ready_and_confirmed()
        self.rewrite(out["id"], state="SUBMITTING", submit_pid=_dead_pid(),
                     submitted_at=stateio.utcnow())

        def too_slow(args, **kwargs):
            raise subprocess.TimeoutExpired(args, kwargs.get("timeout"))
        with self.assertRaises(RuntimeError):
            runtime._submit_in_its_own_process(out["id"], runner=too_slow)
        self.assertEqual(apply_run.load_run(out["id"])["state"], "AWAITING_YOU")

    def test_the_submit_time_limit_outlasts_the_browser_wait(self):
        self.assertGreater(runtime.SUBMIT_TIMEOUT_S, browse.PROFILE_LOCK_WAIT_S + 600)


class ATimeLimitTakesTheWholeTree(unittest.TestCase):
    def test_the_grandchild_goes_too(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        note = pathlib.Path(tmp.name) / "grandchild.pid"
        script = (
            "import subprocess, sys, time, pathlib\n"
            "g = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'],"
            " creationflags=0x08000000 if sys.platform == 'win32' else 0)\n"
            f"pathlib.Path({str(note)!r}).write_text(str(g.pid))\n"
            "time.sleep(120)\n")
        with self.assertRaises(subprocess.TimeoutExpired):
            proc.run_tree([sys.executable, "-c", script], timeout_s=6)
        grandchild = int(note.read_text())
        for _ in range(20):
            if proc.pid_alive(grandchild) is False:
                break
            time.sleep(0.5)
        self.assertFalse(proc.pid_alive(grandchild), "its browser would still hold the profile")


if __name__ == "__main__":
    unittest.main()
