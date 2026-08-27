"""The Core's sync loop, end to end against a real local bare repo.

The scenario is Aletheia's actual life: ChatGPT relays "what does this
page say" as a browse_read command and pushes it; the Core on the PC
pulls, executes it in the (stubbed) local browser, and pushes the
receipt; the relay side pulls and reads the receipt back to the
operator. One synchronous core_tick per beat — no threads in tests.
"""
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from aletheia import core, intercom, journal, notifications, scheduler
from aletheia.fleet import load_fleet
from aletheia.sync import GitSync


def run(args, cwd):
    subprocess.run(args, cwd=str(cwd), check=True, capture_output=True, text=True)


def rmtree(path):
    """Delete a git directory on Windows too.

    Git marks objects read-only; plain rmtree then dies with WinError 5
    mid-walk. Clear the read-only bit on the offending entry and retry.
    """
    def clear_readonly(func, target, _exc):
        os.chmod(target, stat.S_IWRITE)
        func(target)
    if sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=clear_readonly)
    else:  # 3.10/3.11 spell the same hook onerror
        shutil.rmtree(path, onerror=clear_readonly)


def command_payload(cid, kind, **args):
    return {
        "id": cid, "filed": "2026-08-26T16:00:00Z", "by": "chatgpt",
        "relayed_from": "operator", "operator_quote": "what does that page say",
        "command": {"kind": kind, **args},
    }


class CoreSyncFixture(unittest.TestCase):
    """Bare repo + two clones; subclasses add their tests."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        self.origin = base / "origin.git"
        run(["git", "init", "--bare", "-b", "main", str(self.origin)], base)
        self.relay = base / "relay"
        self.pc = base / "pc"
        for clone in (self.relay, self.pc):
            run(["git", "clone", str(self.origin), str(clone)], base)
            run(["git", "config", "user.email", "t@t"], clone)
            run(["git", "config", "user.name", "t"], clone)
        (self.relay / "exchange" / "commands").mkdir(parents=True)
        (self.relay / "exchange" / "commands" / ".gitkeep").write_text("")
        run(["git", "add", "."], self.relay)
        run(["git", "commit", "-m", "seed"], self.relay)
        run(["git", "push", "origin", "main"], self.relay)
        run(["git", "pull", "origin", "main"], self.pc)
        # the Core under test lives in the PC clone
        self.fleet = load_fleet()
        self.syncer = GitSync(repo_root=self.pc, branch="main")
        self.status = {"enabled": True, "last_tick": None, "pull": None,
                       "push": None, "commands_executed": 0}
        for target, attr, value in (
                (intercom, "COMMANDS_DIR", self.pc / "exchange" / "commands"),
                (journal, "JOURNAL_PATH", self.pc / "state" / "journal" / "journal.jsonl")):
            p = mock.patch.object(target, attr, value)
            p.start(); self.addCleanup(p.stop)
        # the runtime's outside-world observers must never leave the test:
        # mail polling reached the operator's REAL Gmail from this suite
        # (and a throttled login hung it); receipts/pulse likewise read
        # real stores. Each producer has its own dedicated tests.
        from aletheia import runtime, verification
        for target, attr in ((runtime, "poll_mail_events"),
                             (runtime, "mirror_pulse_events")):
            p = mock.patch.object(target, attr, return_value=[])
            p.start(); self.addCleanup(p.stop)
        p = mock.patch.object(verification, "reconcile_durable_receipts", return_value=[])
        p.start(); self.addCleanup(p.stop)

    def relay_files_command(self, cid, kind, **args):
        path = self.relay / "exchange" / "commands" / f"{cid}.json"
        path.write_text(json.dumps(command_payload(cid, kind, **args)), encoding="utf-8")
        run(["git", "add", "."], self.relay)
        run(["git", "commit", "-m", f"chatgpt: {cid}"], self.relay)
        run(["git", "push", "origin", "main"], self.relay)


class CoreSyncCase(CoreSyncFixture):
    def test_voice_command_round_trip(self):
        self.relay_files_command("20260826-read", "browse_read", url="https://example.com")
        page = {"url": "https://example.com/", "title": "Example Domain",
                "text": "Illustrative examples live here.", "links": []}
        with mock.patch("aletheia.browse.read_page", return_value=page):
            status = core.core_tick(self.syncer, self.fleet, self.status)
        self.assertTrue(status["pull"]["ok"], status["pull"])
        self.assertEqual(status["commands_executed"], 1)
        self.assertTrue(status["push"]["ok"], status["push"])
        # the relay side sees the receipt and can speak it back
        run(["git", "pull", "origin", "main"], self.relay)
        receipt = json.loads(
            (self.relay / "exchange" / "commands" / "20260826-read.result.json")
            .read_text(encoding="utf-8"))
        self.assertEqual(receipt["outcome"], "done")
        self.assertIn("Example Domain", receipt["detail"])
        # and the journal entry rode along in the same push
        self.assertTrue(
            (self.relay / "state" / "journal" / "journal.jsonl").exists())

    def test_receipt_makes_second_tick_a_noop(self):
        self.relay_files_command("20260826-read", "browse_read", url="https://example.com")
        page = {"url": "https://example.com/", "title": "T", "text": "x", "links": []}
        with mock.patch("aletheia.browse.read_page", return_value=page) as rp:
            core.core_tick(self.syncer, self.fleet, self.status)
            core.core_tick(self.syncer, self.fleet, self.status)
        self.assertEqual(rp.call_count, 1)
        self.assertEqual(self.status["commands_executed"], 1)

    def test_cloud_kinds_are_left_for_actions(self):
        self.relay_files_command("20260826-note", "note", text="hello")
        core.core_tick(self.syncer, self.fleet, self.status)
        self.assertEqual(self.status["commands_executed"], 0)
        self.assertFalse(
            (self.pc / "exchange" / "commands" / "20260826-note.result.json").exists())

    def test_runtime_rides_the_sync_beat(self):
        # a due private schedule executes through the SAME intercom gates
        # inside the ordinary core_tick — no second execution path
        base = Path(self.tmp.name)
        patches = [
            mock.patch.object(scheduler, "SCHEDULE_DIR", base / "sched" / "defs"),
            mock.patch.object(scheduler, "RECEIPT_DIR", base / "sched" / "receipts"),
            mock.patch.object(notifications, "NOTICES_DIR", base / "notices"),
        ]
        for p in patches:
            p.start(); self.addCleanup(p.stop)
        scheduler.create("beat-note", {"kind": "note", "text": "from a schedule"},
                         kind="once", at="2026-08-26T00:00:00+00:00")
        status = core.core_tick(self.syncer, self.fleet, self.status)
        self.assertEqual(status["runtime"].get("schedules"), 1, status.get("runtime"))
        texts = [e["text"] for e in journal.entries()]
        self.assertTrue(any("from a schedule" in t for t in texts), texts[-5:])
        # second tick: the occurrence receipt makes it exactly-once
        status = core.core_tick(self.syncer, self.fleet, self.status)
        self.assertEqual(status["runtime"].get("schedules"), 0, status.get("runtime"))

    def test_tick_survives_a_dead_remote(self):
        # remote vanishes mid-life; the tick reports and returns, never raises
        rmtree(self.origin)
        status = core.core_tick(self.syncer, self.fleet, self.status)
        self.assertFalse(status["pull"]["ok"])

    def test_start_sync_loop_disabled_outside_a_repo(self):
        with mock.patch("aletheia.core.GitSync") as gs:
            gs.return_value.available.return_value = (False, "no remote")
            stop = core.start_sync_loop(self.fleet, interval_s=0.01)
        stop.set()
        self.assertFalse(core.SYNC_STATUS["enabled"])


if __name__ == "__main__":
    unittest.main()


class SelfUpdateCase(CoreSyncFixture):
    """A pulled commit touching code triggers restart; state-only commits don't."""

    def relay_pushes_file(self, rel, content, msg):
        path = self.relay / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        run(["git", "add", "."], self.relay)
        run(["git", "commit", "-m", msg], self.relay)
        run(["git", "push", "origin", "main"], self.relay)

    def test_code_commit_fires_on_code_update_and_skips_processing(self):
        self.relay_pushes_file("aletheia/newmod.py", "x = 1\n", "feat: new code")
        self.relay_files_command("20260826-read", "browse_read", url="https://example.com")
        fired = []
        with mock.patch("aletheia.browse.read_page") as rp:
            core.core_tick(self.syncer, self.fleet, self.status,
                           on_code_update=fired.append)
        self.assertEqual(len(fired), 1)
        self.assertIn("aletheia/newmod.py", fired[0])
        rp.assert_not_called()  # restarting takes precedence; next run processes

    def test_state_only_commit_does_not_restart(self):
        self.relay_pushes_file("state/pulse/latest.json", "{}\n", "pulse")
        fired = []
        core.core_tick(self.syncer, self.fleet, self.status,
                       on_code_update=fired.append)
        self.assertEqual(fired, [])

    def test_no_callback_means_no_crash_on_code_update(self):
        self.relay_pushes_file("aletheia/newmod.py", "x = 1\n", "feat")
        status = core.core_tick(self.syncer, self.fleet, self.status)
        self.assertTrue(status["pull"]["ok"])


class JournalConflictRegressionCase(CoreSyncFixture):
    """The 2026-08-26 bootstrap abort: the PC and the cloud both appended
    to journal.jsonl, so every pull collided. Per-writer files + the
    checkpoint-before-pull make that collision structurally impossible."""

    def setUp(self):
        super().setUp()
        # the Core on the PC writes its OWN file, as core.main() arranges
        p = mock.patch.object(journal, "JOURNAL_PATH",
                              self.pc / "state" / "journal" / "journal-pc.jsonl")
        p.start(); self.addCleanup(p.stop)

    def cloud_appends_journal(self):
        d = self.relay / "state" / "journal"
        d.mkdir(parents=True, exist_ok=True)
        with (d / "journal.jsonl").open("a", encoding="utf-8") as f:
            f.write('{"ts": "2026-08-26T12:00:00Z", "kind": "note", "actor": '
                    '"aletheia", "subject": "cloud", "text": "cloud entry"}\n')
        run(["git", "add", "."], self.relay)
        run(["git", "commit", "-m", "cloud journal append"], self.relay)
        run(["git", "push", "origin", "main"], self.relay)

    def test_dirty_pc_journal_plus_cloud_append_pulls_clean(self):
        journal.append("note", "pc", "local entry before pull")  # dirty tree
        self.cloud_appends_journal()
        status = core.core_tick(self.syncer, self.fleet, self.status)
        self.assertTrue(status["pull"]["ok"], status["pull"])
        # both entries survive, one merged stream
        texts = [e["text"] for e in journal.entries()]
        self.assertIn("local entry before pull", texts)
        self.assertIn("cloud entry", texts)

    def test_checkpoint_commits_reach_the_remote_without_receipts(self):
        journal.append("note", "pc", "quiet tick entry")
        status = core.core_tick(self.syncer, self.fleet, self.status)
        self.assertTrue(status["push"]["ok"], status["push"])
        run(["git", "pull", "origin", "main"], self.relay)
        pc_file = self.relay / "state" / "journal" / "journal-pc.jsonl"
        self.assertIn("quiet tick entry", pc_file.read_text(encoding="utf-8"))


class HeartbeatBatchingCase(CoreSyncFixture):
    """Journal-only pushes batch to one per 10 minutes; receipts never wait."""

    def test_quiet_journal_change_within_window_commits_but_does_not_push(self):
        core.core_tick(self.syncer, self.fleet, self.status)  # sets last_push_s
        before = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(self.origin),
                                capture_output=True, text=True).stdout
        journal.append("note", "pc", "heartbeat entry")
        core.core_tick(self.syncer, self.fleet, self.status)
        after = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(self.origin),
                               capture_output=True, text=True).stdout
        self.assertEqual(before, after)  # nothing pushed inside the window

    def test_receipts_push_immediately_even_inside_the_window(self):
        core.core_tick(self.syncer, self.fleet, self.status)
        self.relay_files_command("20260827-read", "browse_read", url="https://example.com")
        page = {"url": "https://example.com/", "title": "T", "text": "x", "links": []}
        with mock.patch("aletheia.browse.read_page", return_value=page):
            status = core.core_tick(self.syncer, self.fleet, self.status)
        self.assertTrue(status["push"]["ok"], status.get("push"))
        run(["git", "pull", "origin", "main"], self.relay)
        self.assertTrue((self.relay / "exchange" / "commands" /
                         "20260827-read.result.json").exists())

    def test_batched_heartbeats_ride_out_with_the_next_push(self):
        core.core_tick(self.syncer, self.fleet, self.status)
        journal.append("note", "pc", "batched entry")
        core.core_tick(self.syncer, self.fleet, self.status)   # committed, unpushed
        self.status["last_push_s"] = 0.0                       # window expires
        status = core.core_tick(self.syncer, self.fleet, self.status)
        self.assertTrue(status["push"]["ok"], status.get("push"))
        run(["git", "pull", "origin", "main"], self.relay)
        pc_journal = self.relay / "state" / "journal" / "journal.jsonl"
        self.assertIn("batched entry", pc_journal.read_text(encoding="utf-8"))

class StaleCodeCase(unittest.TestCase):
    """Local commits move HEAD before the Core ever looks, so `after ==
    before` and the pull-based restart never fires. Found live: a new
    command kind sat on disk, unknown to the running Core, for half an
    hour. The files are the authority, not just git."""

    def test_nothing_newer_than_the_process_is_not_stale(self):
        self.assertEqual(core.stale_code_files(started_at=time.time() + 60), [])

    def test_code_written_after_the_process_started_is_stale(self):
        stale = core.stale_code_files(started_at=0)
        self.assertTrue(stale)
        self.assertTrue(any(name.endswith(".py") for name in stale))

    def test_the_report_is_bounded(self):
        self.assertLessEqual(len(core.stale_code_files(started_at=0, limit=3)), 3)

    def test_pycache_is_not_code(self):
        self.assertFalse([n for n in core.stale_code_files(started_at=0, limit=200)
                          if "__pycache__" in n])
