import datetime as dt
import tempfile
import unittest
from pathlib import Path

from aletheia import calendar, communications, contacts, context, gaps, outcomes, projects, scheduler, stateio, tasks


class Rooted(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        contacts.CONTACTS_DIR = self.root / "state" / "contacts"
        calendar.CALENDAR_DIR = self.root / "state" / "calendar" / "events"
        scheduler.SCHEDULE_DIR = self.root / "state" / "schedules" / "definitions"
        scheduler.RECEIPT_DIR = self.root / "state" / "schedules" / "receipts"
        communications.THREADS_DIR = self.root / "state" / "communications" / "threads"
        communications.MESSAGES_DIR = self.root / "state" / "communications" / "messages"
        communications.EXPECT_DIR = self.root / "state" / "communications" / "expectations"
        outcomes.ACTIONS_DIR = self.root / "state" / "actions"
        projects.PROJECTS_DIR = self.root / "state" / "projects"
        context.REFS_DIR = self.root / "state" / "context" / "refs"
    def tearDown(self):
        self.tmp.cleanup()


class TestStateIO(Rooted):
    def test_safe_id_rejects_paths(self):
        with self.assertRaises(ValueError):
            stateio.safe_id("../oops")

    def test_atomic_roundtrip(self):
        p = self.root / "a" / "x.json"
        stateio.write_json_atomic(p, {"b": 2, "a": 1})
        self.assertEqual(stateio.read_json(p), {"a": 1, "b": 2})

    def test_exclusive_refuses_overwrite(self):
        p = self.root / "x.json"
        stateio.create_json_exclusive(p, {"x": 1})
        with self.assertRaises(FileExistsError):
            stateio.create_json_exclusive(p, {"x": 2})


class TestContacts(Rooted):
    def test_create_and_resolve_alias(self):
        contacts.create("bob-smith", "Bob Smith", emails=["bob@example.com"], aliases=["Robert"])
        self.assertEqual(contacts.resolve("robert")["id"], "bob-smith")

    def test_ambiguous_name_refused(self):
        data = [{"id": "a", "display_name": "Sam", "aliases": [], "emails": []},
                {"id": "b", "display_name": "Sam", "aliases": [], "emails": []}]
        with self.assertRaises(LookupError):
            contacts.resolve("Sam", data)

    def test_unknown_refused(self):
        with self.assertRaises(KeyError):
            contacts.resolve("nobody", [])

    def test_primary_email_requires_exactly_one(self):
        with self.assertRaises(LookupError):
            contacts.primary_email({"id": "x", "emails": ["a@b.com", "c@d.com"]})

    def test_bad_email_refused(self):
        with self.assertRaises(ValueError):
            contacts.create("x", "X", emails=["not-mail"])


class TestCalendar(Rooted):
    def test_timezone_required(self):
        with self.assertRaises(ValueError):
            calendar.parse_time("2026-08-26T10:00:00")

    def test_overlap_half_open(self):
        a = dt.datetime.fromisoformat("2026-08-26T10:00:00+00:00")
        b = a + dt.timedelta(hours=1)
        self.assertFalse(calendar.overlaps(a, b, b, b + dt.timedelta(hours=1)))

    def test_conflict_with_buffer(self):
        events = [{"start": "2026-08-26T10:00:00+00:00", "end": "2026-08-26T11:00:00+00:00"}]
        self.assertEqual(calendar.conflicts("2026-08-26T09:45:00+00:00", "2026-08-26T10:00:00+00:00", events=events), [])
        self.assertEqual(len(calendar.conflicts("2026-08-26T09:45:00+00:00", "2026-08-26T10:00:00+00:00", events=events, buffer_before=15)), 1)

    def test_free_slots_exclude_event(self):
        events = [{"start": "2026-08-26T10:00:00-05:00", "end": "2026-08-26T11:00:00-05:00"}]
        slots = calendar.free_slots(dt.date(2026, 8, 26), duration_minutes=60, timezone="America/Chicago",
                                    work_start=dt.time(9), work_end=dt.time(12), events=events, step_minutes=60)
        self.assertEqual(len(slots), 2)
        self.assertTrue(slots[0][0].endswith("-05:00"))

    def test_create_duplicate_refused(self):
        calendar.create("meet", "Meet", "2026-08-26T10:00:00-05:00", "2026-08-26T11:00:00-05:00")
        with self.assertRaises(FileExistsError):
            calendar.create("meet", "Again", "2026-08-26T12:00:00-05:00", "2026-08-26T13:00:00-05:00")


class TestScheduler(Rooted):
    def test_once_not_due_early(self):
        spec = scheduler.create("one", {"kind": "noop"}, kind="once", at="2026-08-26T12:00:00+00:00")
        now = dt.datetime.fromisoformat("2026-08-26T11:00:00+00:00")
        self.assertIsNone(scheduler.occurrence_at_or_before(spec, now))

    def test_interval_occurrence(self):
        spec = scheduler.create("int", {"kind": "noop"}, kind="interval", every_minutes=30,
                                anchor="2026-08-26T10:00:00+00:00")
        now = dt.datetime.fromisoformat("2026-08-26T11:14:00+00:00")
        self.assertEqual(scheduler.occurrence_at_or_before(spec, now),
                         dt.datetime.fromisoformat("2026-08-26T11:00:00+00:00"))

    def test_claim_is_idempotent(self):
        spec = scheduler.create("one", {"kind": "noop"}, kind="once", at="2026-08-26T10:00:00+00:00")
        now = dt.datetime.fromisoformat("2026-08-26T11:00:00+00:00")
        self.assertIsNotNone(scheduler.claim_due(spec, now=now))
        self.assertIsNone(scheduler.claim_due(spec, now=now))

    def test_weekly_respects_weekday(self):
        spec = scheduler.create("wk", {"kind": "noop"}, kind="weekly", timezone="America/Chicago",
                                time="09:00", weekdays=[0])
        now = dt.datetime.fromisoformat("2026-08-26T20:00:00+00:00")
        occurrence = scheduler.occurrence_at_or_before(spec, now)
        self.assertEqual(occurrence.astimezone(dt.timezone.utc).weekday(), 0)

    def test_schedule_command_requires_kind(self):
        with self.assertRaises(ValueError):
            scheduler.create("bad", {}, kind="once", at="2026-08-26T10:00:00+00:00")


class TestCommunications(Rooted):
    def test_reply_expectation_resolves(self):
        communications.create_thread("t1", participants=["me", "bob"])
        communications.record_message("m1", thread_id="t1", direction="OUTBOUND", channel="email", participant="bob", summary="question")
        exp = communications.expect_reply("e1", thread_id="t1", after_message_id="m1", from_participant="bob")
        communications.record_message("m2", thread_id="t1", direction="INBOUND", channel="email", participant="bob", summary="answer")
        self.assertEqual(communications.evaluate_expectation(exp)["status"], "REPLIED")

    def test_unrelated_inbound_does_not_resolve(self):
        communications.create_thread("t1", participants=["me", "bob", "sam"])
        communications.record_message("m1", thread_id="t1", direction="OUTBOUND", channel="email", participant="bob", summary="question")
        exp = communications.expect_reply("e1", thread_id="t1", after_message_id="m1", from_participant="bob")
        communications.record_message("m2", thread_id="t1", direction="INBOUND", channel="email", participant="sam", summary="other")
        self.assertEqual(communications.evaluate_expectation(exp)["status"], "WAITING")

    def test_message_requires_existing_thread(self):
        with self.assertRaises(ValueError):
            communications.record_message("m1", thread_id="missing", direction="OUTBOUND", channel="email", participant="x", summary="x")

    def test_duplicate_message_refused(self):
        communications.create_thread("t1", participants=["me", "bob"])
        communications.record_message("m1", thread_id="t1", direction="OUTBOUND", channel="email", participant="bob", summary="x")
        with self.assertRaises(FileExistsError):
            communications.record_message("m1", thread_id="t1", direction="OUTBOUND", channel="email", participant="bob", summary="x")


class TestOutcomes(Rooted):
    def test_plan_hash_stable(self):
        a = outcomes.start("a", capability="x", intent="do x", plan={"b": 2, "a": 1})
        self.assertEqual(len(a["plan_sha256"]), 64)

    def test_success_requires_evidence_before_verify(self):
        outcomes.start("a", capability="x", intent="x", plan={})
        outcomes.add_attempt("a", outcome="SUCCEEDED")
        with self.assertRaises(ValueError):
            outcomes.verify("a")

    def test_verify_pass(self):
        outcomes.start("a", capability="x", intent="x", plan={})
        outcomes.add_attempt("a", outcome="SUCCEEDED")
        outcomes.add_evidence("a", "ev", kind="equals", observed=3, expected=3)
        self.assertEqual(outcomes.verify("a")["status"], "VERIFIED")

    def test_verify_fail_becomes_retryable(self):
        outcomes.start("a", capability="x", intent="x", plan={})
        outcomes.add_attempt("a", outcome="SUCCEEDED")
        outcomes.add_evidence("a", "ev", kind="truthy", observed=False)
        self.assertEqual(outcomes.verify("a")["status"], "FAILED_RETRYABLE")

    def test_terminal_attempt_blocks_more(self):
        outcomes.start("a", capability="x", intent="x", plan={})
        outcomes.add_attempt("a", outcome="FAILED_TERMINAL")
        with self.assertRaises(ValueError):
            outcomes.add_attempt("a", outcome="SUCCEEDED")


class TestGaps(Rooted):
    REG = {"capabilities": [{"id": "good", "status": "AVAILABLE"},
                            {"id": "pc", "status": "NEEDS_CONFIGURATION"},
                            {"id": "phone.call", "status": "NOT_BUILT"}]}

    def test_assess(self):
        report = gaps.assess(["good", "pc", "missing"], registry=self.REG)
        self.assertEqual(report["available"], ["good"])
        self.assertEqual(report["unknown"], ["missing"])
        self.assertFalse(report["satisfied"])

    def test_specs_for_blocked_and_unknown(self):
        specs = gaps.development_specs(["phone.call", "missing"], registry=self.REG)
        self.assertEqual(len(specs), 2)
        self.assertTrue(all(s["assigned_worker"] == "claude" for s in specs))

    def test_materialize_idempotent(self):
        original_all = gaps.tasks.all_tasks
        original_create = gaps.tasks.create
        items = []
        try:
            gaps.tasks.all_tasks = lambda: list(items)
            def fake_create(tid, description, **kwargs):
                item = {"id": tid, "description": description, **kwargs}
                items.append(item)
                return item
            gaps.tasks.create = fake_create
            first = gaps.materialize(["phone.call"], registry=self.REG)
            second = gaps.materialize(["phone.call"], registry=self.REG)
            self.assertEqual(first[0]["id"], second[0]["id"])
            self.assertEqual(len(items), 1)
        finally:
            gaps.tasks.all_tasks = original_all
            gaps.tasks.create = original_create


class TestProjects(Rooted):
    def test_project_updates(self):
        projects.create("alpha", "Alpha", goal="ship it")
        value = projects.update("alpha", add_task="t1", add_person="bob", blocker="waiting", decision="use v1")
        self.assertEqual(value["task_ids"], ["t1"])
        self.assertEqual(len(value["decisions"]), 1)

    def test_terminal_project_immutable(self):
        projects.create("alpha", "Alpha", goal="ship")
        projects.update("alpha", status="COMPLETED")
        with self.assertRaises(ValueError):
            projects.update("alpha", add_task="t")


class TestContext(Rooted):
    def test_unique_resolution(self):
        context.remember("r1", kind="person", value="contact:bob", label="Bob")
        self.assertEqual(context.resolve(kind="person")["value"], "contact:bob")

    def test_same_value_not_ambiguous(self):
        context.remember("r1", kind="person", value="contact:bob", label="Bob")
        context.remember("r2", kind="person", value="contact:bob", label="him")
        self.assertEqual(context.resolve(kind="person")["value"], "contact:bob")

    def test_different_values_ambiguous(self):
        context.remember("r1", kind="person", value="contact:bob", label="Bob")
        context.remember("r2", kind="person", value="contact:sam", label="Sam")
        with self.assertRaises(LookupError):
            context.resolve(kind="person")


if __name__ == "__main__":
    unittest.main()
