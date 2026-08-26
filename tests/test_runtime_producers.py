import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import events, mail, notifications, proactive, runtime


class RuntimeProducerCase(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        root=Path(self.tmp.name)
        patches=[
            mock.patch.object(events,"EVENTS_DIR",root/"events"),
            mock.patch.object(events,"WATCHERS_DIR",root/"watchers"),
            mock.patch.object(runtime,"EVENT_CURSOR",root/"event-cursor.json"),
            mock.patch.object(runtime,"PULSE_CURSOR",root/"pulse-cursor.json"),
            mock.patch.object(mail,"MAIL_DIR",root/"mail"),
            mock.patch.object(notifications,"NOTIFICATIONS_DIR",root/"notifications"),
            mock.patch.object(proactive,"RULES_DIR",root/"rules"),
            mock.patch.object(proactive,"RECEIPTS_DIR",root/"rule-receipts"),
        ]
        for p in patches: p.start(); self.addCleanup(p.stop)
        self.root=root

    def write_pulse(self, generated="2026-08-26T20:07:00Z"):
        path=self.root/"pulse.json"
        path.write_text(json.dumps({
            "generated_at":generated,
            "transitions":[{"repo":"shorts_pipeline","github":"Shorts-pipeline","from":"green","to":"red"}],
        }),encoding="utf-8")
        return path

    def test_pulse_transition_emits_once(self):
        p=self.write_pulse()
        first=runtime.mirror_pulse_events(pulse_path=p,cursor_path=self.root/"pc.json")
        second=runtime.mirror_pulse_events(pulse_path=p,cursor_path=self.root/"pc.json")
        self.assertEqual(first[0]["action"],"emitted")
        self.assertEqual(second,[])
        ev=events.list_events(events_dir=events.EVENTS_DIR)[0]
        self.assertEqual(ev["kind"],"fleet.health_changed")
        self.assertTrue(ev["id"].startswith("evt-20260826T200700"))

    def test_pulse_event_cannot_block_later_normal_bus_event(self):
        p=self.write_pulse("2026-08-26T20:07:00Z")
        runtime.mirror_pulse_events(pulse_path=p,cursor_path=self.root/"pc.json")
        runtime.process_new_events(now=dt.datetime(2026,8,26,20,8,tzinfo=dt.timezone.utc),
                                   cursor_path=self.root/"event-cursor.json",
                                   events_dir=events.EVENTS_DIR,watchers_dir=events.WATCHERS_DIR)
        later=events.emit("test.later","subject","later",source="test",
                          occurred_at="2026-08-26T20:09:00Z",
                          event_id="evt-20260826T200900000000Z-aaaaaaaaaa")
        actions=runtime.process_new_events(now=dt.datetime(2026,8,26,20,10,tzinfo=dt.timezone.utc),
                                          cursor_path=self.root/"event-cursor.json",
                                          events_dir=events.EVENTS_DIR,watchers_dir=events.WATCHERS_DIR)
        cursor=json.loads((self.root/"event-cursor.json").read_text())
        self.assertEqual(cursor["last_event_id"],later["event"]["id"])
        self.assertIsInstance(actions,list)

    def test_first_mail_poll_baselines_and_next_header_emits(self):
        old={"from":"A <a@example.com>","subject":"Old","date":"Wed, 26 Aug 2026 18:00:00 -0500","message_id":"<old>"}
        new={"from":"A <a@example.com>","subject":"New","date":"Wed, 26 Aug 2026 19:00:00 -0500","message_id":"<new>"}
        class T:
            unread=[old]
            def fetch_unread(self,limit): return self.unread[:limit]
        t=T()
        self.assertEqual(mail.poll_events(transport=t),[{"action":"baseline","count":1}])
        self.assertEqual(events.list_events(events_dir=events.EVENTS_DIR),[])
        t.unread=[new,old]
        out=mail.poll_events(transport=t)
        self.assertEqual([x["action"] for x in out],["received"])
        self.assertEqual(events.list_events(events_dir=events.EVENTS_DIR)[0]["summary"].split(" — ")[0],"New")


if __name__=="__main__": unittest.main()
