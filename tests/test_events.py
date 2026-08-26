import json
import tempfile
import unittest
from pathlib import Path

from aletheia import events


class EventFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.events_dir = root / "events"
        self.watchers_dir = root / "watchers"

    def tearDown(self):
        self.tmp.cleanup()

    def emit(self, **kw):
        base = dict(
            kind="mail.reply",
            subject="person:alice",
            summary="Alice replied",
            source="mail",
            attributes={"conversation_id": "c1"},
        )
        base.update(kw)
        return events.emit(
            events_dir=self.events_dir,
            watchers_dir=self.watchers_dir,
            **base,
        )


class TestEvents(EventFixture):
    def test_emit_persists_one_immutable_event(self):
        result = self.emit(
            event_id="evt-one",
            occurred_at="2026-08-26T14:00:00.000000Z",
        )
        path = self.events_dir / "evt-one.json"
        self.assertTrue(path.is_file())
        self.assertEqual(json.loads(path.read_text())["summary"], "Alice replied")
        self.assertEqual(result["watcher_errors"], [])
        with self.assertRaises(FileExistsError):
            self.emit(
                event_id="evt-one",
                occurred_at="2026-08-26T14:00:00.000000Z",
            )

    def test_matching_once_watcher_triggers_only_once(self):
        events.create_watcher(
            {"kind": "mail.reply", "subject_prefix": "person:"},
            note="tell me when they reply",
            created_by="operator",
            watcher_id="watch-one",
            watchers_dir=self.watchers_dir,
        )
        first = self.emit(event_id="evt-a")
        second = self.emit(event_id="evt-b")
        self.assertEqual(
            [t["watcher_id"] for t in first["triggers"]],
            ["watch-one"],
        )
        self.assertEqual(second["triggers"], [])
        self.assertEqual(
            events.list_watchers(watchers_dir=self.watchers_dir)[0]["state"],
            "TRIGGERED",
        )

    def test_persistent_watcher_triggers_for_each_matching_event(self):
        events.create_watcher(
            {"kind": "fleet.health_changed", "attributes": {"to": "red"}},
            note="track outages",
            created_by="operator",
            once=False,
            watcher_id="watch-many",
            watchers_dir=self.watchers_dir,
        )
        one = self.emit(
            kind="fleet.health_changed",
            source="pulse",
            subject="repo:a",
            summary="green -> red",
            attributes={"to": "red"},
            event_id="evt-1",
        )
        two = self.emit(
            kind="fleet.health_changed",
            source="pulse",
            subject="repo:b",
            summary="unknown -> red",
            attributes={"to": "red"},
            event_id="evt-2",
        )
        self.assertEqual(len(one["triggers"]), 1)
        self.assertEqual(len(two["triggers"]), 1)
        watcher = events.list_watchers(watchers_dir=self.watchers_dir)[0]
        self.assertEqual(watcher["state"], "ACTIVE")
        self.assertEqual(watcher["trigger_count"], 2)

    def test_non_matching_event_does_not_trigger(self):
        events.create_watcher(
            {"kind": "mail.reply"},
            note="reply",
            created_by="operator",
            watcher_id="watch-mail",
            watchers_dir=self.watchers_dir,
        )
        result = self.emit(
            kind="calendar.changed",
            source="calendar",
            event_id="evt-cal",
        )
        self.assertEqual(result["triggers"], [])

    def test_cancel_is_append_only_marker(self):
        events.create_watcher(
            {"kind": "mail.reply"},
            note="reply",
            created_by="operator",
            watcher_id="watch-cancel",
            watchers_dir=self.watchers_dir,
        )
        receipt = events.cancel_watcher(
            "watch-cancel",
            cancelled_by="operator",
            reason="not needed",
            watchers_dir=self.watchers_dir,
        )
        again = events.cancel_watcher(
            "watch-cancel",
            cancelled_by="someone",
            reason="different",
            watchers_dir=self.watchers_dir,
        )
        self.assertEqual(receipt, again)
        self.assertEqual(
            events.list_watchers(watchers_dir=self.watchers_dir)[0]["state"],
            "CANCELLED",
        )
        self.assertEqual(self.emit(event_id="evt-after")["triggers"], [])

    def test_corrupt_watcher_is_isolated(self):
        events.create_watcher(
            {"kind": "mail.reply"},
            note="good",
            created_by="operator",
            watcher_id="watch-good",
            watchers_dir=self.watchers_dir,
        )
        defs = self.watchers_dir / "definitions"
        (defs / "watch-bad.json").write_text("{broken")
        result = self.emit(event_id="evt-good")
        self.assertEqual(len(result["triggers"]), 1)
        self.assertEqual(len(result["watcher_errors"]), 1)
        self.assertEqual(result["watcher_errors"][0]["definition"], "watch-bad.json")

    def test_sensitive_attribute_keys_refused(self):
        with self.assertRaisesRegex(ValueError, "sensitive"):
            self.emit(attributes={"access_token": "nope"})

    def test_watcher_requires_narrowing_match(self):
        with self.assertRaises(ValueError):
            events.create_watcher(
                {},
                note="everything",
                created_by="operator",
                watchers_dir=self.watchers_dir,
            )

    def test_duplicate_evaluation_is_idempotent(self):
        events.create_watcher(
            {"kind": "mail.reply"},
            note="reply",
            created_by="operator",
            once=False,
            watcher_id="watch-idem",
            watchers_dir=self.watchers_dir,
        )
        result = self.emit(event_id="evt-idem")
        event = result["event"]
        first, _ = events.evaluate_watchers(event, watchers_dir=self.watchers_dir)
        second, _ = events.evaluate_watchers(event, watchers_dir=self.watchers_dir)
        self.assertEqual(first, second)
        self.assertEqual(len(first), 1)
        self.assertEqual(
            len(list((self.watchers_dir / "triggers" / "watch-idem").glob("*.json"))),
            1,
        )

    def test_events_list_newest_first_by_id(self):
        self.emit(event_id="evt-20260826-a")
        self.emit(event_id="evt-20260826-b")
        got = events.list_events(events_dir=self.events_dir, limit=2)
        self.assertEqual(
            [event["id"] for event in got],
            ["evt-20260826-b", "evt-20260826-a"],
        )


if __name__ == "__main__":
    unittest.main()
