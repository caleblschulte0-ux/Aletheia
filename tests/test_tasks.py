import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import journal, tasks


class TaskCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        for target, attr in ((tasks, "TASKS_DIR"), (journal, "JOURNAL_PATH")):
            p = mock.patch.object(target, attr, Path(self.tmp.name) / attr.lower())
            p.start(); self.addCleanup(p.stop)


class TestLifecycle(TaskCase):
    def test_create_persists_and_journals(self):
        tasks.create("call-doctor", "Call the doctor for an appointment")
        t = tasks.load("call-doctor")
        self.assertEqual(t["status"], "QUEUED")
        self.assertEqual(journal.entries()[0]["kind"], "task")

    def test_waiting_external_is_not_failure(self):
        tasks.create("call-doctor", "Call the doctor")
        tasks.set_status("call-doctor", "RUNNING")
        t = tasks.set_status("call-doctor", "WAITING_EXTERNAL", "no answer, retry tomorrow")
        self.assertEqual(t["attempts"], 1)
        self.assertEqual(t["status"], "WAITING_EXTERNAL")
        self.assertEqual(t["result"], "no answer, retry tomorrow")

    def test_attempts_count_each_run(self):
        tasks.create("t", "retries")
        for _ in range(3):
            tasks.set_status("t", "RUNNING")
            tasks.set_status("t", "RETRY_SCHEDULED")
        self.assertEqual(tasks.load("t")["attempts"], 3)

    def test_terminal_states_never_change(self):
        tasks.create("t", "done deal")
        tasks.set_status("t", "COMPLETED", "verified")
        with self.assertRaises(ValueError):
            tasks.set_status("t", "QUEUED")

    def test_invalid_state_refused(self):
        tasks.create("t", "x")
        with self.assertRaises(ValueError):
            tasks.set_status("t", "SORTA_DONE")

    def test_failed_note_lands_in_error(self):
        tasks.create("t", "x")
        tasks.set_status("t", "FAILED_RETRYABLE", "captcha appeared")
        self.assertEqual(tasks.load("t")["error"], "captcha appeared")


class TestDependencies(TaskCase):
    def test_ready_derives_from_dependencies(self):
        tasks.create("find-number", "Find the office number")
        tasks.create("call", "Call the office", dependencies=["find-number"])
        self.assertEqual([t["id"] for t in tasks.ready()], ["find-number"])
        tasks.set_status("find-number", "COMPLETED")
        self.assertEqual([t["id"] for t in tasks.ready()], ["call"])

    def test_missing_dependency_refused_at_create(self):
        with self.assertRaises(KeyError):
            tasks.create("call", "Call", dependencies=["ghost-task"])

    def test_ready_orders_by_priority(self):
        tasks.create("later", "low", priority=5)
        tasks.create("first", "high", priority=1)
        self.assertEqual([t["id"] for t in tasks.ready()], ["first", "later"])

    def test_dependency_survives_restart(self):
        """Durability is the whole point: rebuild state purely from disk."""
        tasks.create("a", "step one")
        tasks.create("b", "step two", dependencies=["a"])
        tasks.set_status("a", "COMPLETED")
        # nothing in memory: a fresh read of the store must agree
        fresh = {t["id"]: t for t in tasks.all_tasks()}
        self.assertTrue(tasks.is_ready(fresh["b"], fresh))


if __name__ == "__main__":
    unittest.main()


class TestDescription(TaskCase):
    """A description is durable truth. The 2026-09-01 catch-up found
    `operator-setup` still reading "merge, FLEET_TOKEN, Pages, ChatGPT
    Project, run the Core" with four of the five long done — every
    downstream surface faithfully rendered the stale sentence."""

    def test_correcting_a_description_is_journaled_and_keeps_history(self):
        tasks.create("setup", "merge, token, pages, run the core")
        out = tasks.describe("setup", "create the ChatGPT Project (the last step)")
        self.assertEqual(out["description"], "create the ChatGPT Project (the last step)")
        self.assertEqual(tasks.load("setup")["description"], out["description"])
        entries = journal.JOURNAL_PATH.read_text(encoding="utf-8")
        self.assertIn("description corrected", entries)
        self.assertIn("merge, token, pages, run the core", entries,
                      "the superseded sentence must survive in the journal")

    def test_a_terminal_task_is_a_record_not_a_draft(self):
        tasks.create("done-thing", "the thing that was done")
        tasks.set_status("done-thing", "COMPLETED")
        with self.assertRaises(ValueError):
            tasks.describe("done-thing", "something nicer")

    def test_empty_description_refused(self):
        tasks.create("t", "real work")
        with self.assertRaises(ValueError):
            tasks.describe("t", "   ")


class TestOpenTasksDescribeOpenWork(unittest.TestCase):
    """Reads the REAL store on purpose: this is the invariant the catch-up
    audit was asked to enforce ("no generated state describing setup work
    that already exists"), and it can only be checked against production
    truth. A non-terminal task must not name a capability the registry
    already reports AVAILABLE as though it were still to be done."""

    def test_no_open_task_asks_for_work_the_registry_says_is_done(self):
        from aletheia import capabilities
        available = {c["id"] for c in capabilities.by_status("AVAILABLE")}
        stale = []
        for task in tasks.all_tasks():
            if task["status"] in ("COMPLETED", "CANCELLED", "FAILED_TERMINAL"):
                continue
            for cap in task.get("required_capabilities", []):
                if cap in available:
                    stale.append(f"{task['id']} waits on {cap}, which is AVAILABLE")
        self.assertEqual(stale, [], "; ".join(stale))
