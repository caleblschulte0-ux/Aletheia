import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import calendar, calendar_provider, journal, outcomes, policy


def remote(eid="e1", title="Meet", start="2026-09-01T10:00:00-05:00",
           end="2026-09-01T11:00:00-05:00", status="CONFIRMED"):
    return {"external_id": eid, "title": title, "start": start, "end": end,
            "status": status, "attendees": ["bob@example.com"]}


class CalendarProviderCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        patches = [
            mock.patch.object(calendar, "CALENDAR_DIR", root / "calendar"),
            mock.patch.object(policy, "APPROVALS_DIR", root / "approvals"),
            mock.patch.object(policy, "HALT_PATH", root / "halt.json"),
            mock.patch.object(journal, "JOURNAL_PATH", root / "journal.jsonl"),
            mock.patch.object(outcomes, "ACTIONS_DIR", root / "actions"),
        ]
        for p in patches: p.start(); self.addCleanup(p.stop)

    def test_normalization_requires_aware_time(self):
        bad = remote(); bad["start"] = "2026-09-01T10:00:00"
        with self.assertRaises(ValueError): calendar_provider.normalize_event(bad)

    def test_sync_imports_and_updates_provider_owned_event(self):
        p = calendar_provider.InMemoryCalendarProvider(events=[remote()])
        first = calendar_provider.sync_window(p, "2026-09-01T00:00:00-05:00", "2026-09-02T00:00:00-05:00")
        self.assertEqual(first["actions"][0]["action"], "CREATED")
        local = calendar.all_events()[0]; self.assertEqual(local["provider_id"], "fake.calendar")
        p.update_event("e1", {**remote(title="Changed"), "external_id":"e1"})
        second = calendar_provider.sync_window(p, "2026-09-01T00:00:00-05:00", "2026-09-02T00:00:00-05:00")
        self.assertEqual(second["actions"][0]["action"], "UPDATED"); self.assertEqual(calendar.all_events()[0]["title"], "Changed")

    def test_dirty_local_event_is_conflict_not_overwritten(self):
        p = calendar_provider.InMemoryCalendarProvider(events=[remote()])
        calendar_provider.sync_window(p, "2026-09-01T00:00:00-05:00", "2026-09-02T00:00:00-05:00")
        local = calendar.all_events()[0]; local["provider_dirty"] = True; local["title"] = "Local edit"; calendar.save(local)
        p.update_event("e1", {**remote(title="Remote edit"), "external_id":"e1"})
        out = calendar_provider.sync_window(p, "2026-09-01T00:00:00-05:00", "2026-09-02T00:00:00-05:00")
        self.assertEqual(out["conflicts"][0]["action"], "CONFLICT_LOCAL_DIRTY"); self.assertEqual(calendar.all_events()[0]["title"], "Local edit")

    def test_authoritative_window_can_tombstone_missing_remote(self):
        p = calendar_provider.InMemoryCalendarProvider(events=[remote()])
        calendar_provider.sync_window(p, "2026-09-01T00:00:00-05:00", "2026-09-02T00:00:00-05:00")
        p._events.clear()
        out = calendar_provider.sync_window(p, "2026-09-01T00:00:00-05:00", "2026-09-02T00:00:00-05:00", authoritative=True)
        self.assertEqual(out["actions"][0]["action"], "CANCELLED_MISSING_REMOTE"); self.assertEqual(calendar.all_events()[0]["status"], "CANCELLED")

    def test_write_plan_is_hash_bound_verified_and_audited(self):
        p = calendar_provider.InMemoryCalendarProvider()
        plan = calendar_provider.build_write_plan("CREATE", p.provider_id, event={"title":"Dinner", "start":"2026-09-01T18:00:00-05:00", "end":"2026-09-01T19:00:00-05:00", "attendees":[]})
        calendar_provider.request_write_approval("cal-write", plan); policy.decide("cal-write", "APPROVED", via="test")
        result = calendar_provider.execute_write_plan(plan, "cal-write", p)
        self.assertEqual(result["outcome"], "VERIFIED"); self.assertEqual(result["verification_status"],"VERIFIED")
        self.assertEqual(outcomes.load(result["action_record"])["capability"],"calendar.write")
        self.assertEqual(calendar.all_events()[0]["title"], "Dinner")

    def test_edited_plan_after_approval_is_refused(self):
        p = calendar_provider.InMemoryCalendarProvider()
        plan = calendar_provider.build_write_plan("CREATE", p.provider_id, event={"title":"Dinner", "start":"2026-09-01T18:00:00-05:00", "end":"2026-09-01T19:00:00-05:00"})
        calendar_provider.request_write_approval("cal-write", plan); policy.decide("cal-write", "APPROVED", via="test"); plan["event"]["title"] = "Tampered"
        with self.assertRaises(ValueError): calendar_provider.execute_write_plan(plan, "cal-write", p)

    def test_halt_blocks_provider_before_call(self):
        class Counting(calendar_provider.InMemoryCalendarProvider):
            def __init__(self): super().__init__(); self.calls=0
            def create_event(self, event): self.calls += 1; return super().create_event(event)
        p=Counting(); plan=calendar_provider.build_write_plan("CREATE",p.provider_id,event={"title":"X","start":"2026-09-01T18:00:00-05:00","end":"2026-09-01T19:00:00-05:00"})
        calendar_provider.request_write_approval("a",plan); policy.decide("a","APPROVED",via="test"); policy.halt("test",via="test")
        with self.assertRaises(policy.Halted): calendar_provider.execute_write_plan(plan,"a",p)
        self.assertEqual(p.calls,0)


if __name__ == "__main__": unittest.main()
