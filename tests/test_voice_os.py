"""The personal-OS voice verbs, end to end: spoken sentence -> intercom
kind -> gated execution -> durable private state -> speakable reply."""
import datetime as dt
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import (contacts, events, intercom, notifications, scheduler,
                      voice)
from aletheia.fleet import load_fleet


class VoiceOSCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        for module, attr, path in (
            (scheduler, "SCHEDULE_DIR", root / "sched" / "defs"),
            (scheduler, "RECEIPT_DIR", root / "sched" / "receipts"),
            (notifications, "NOTICES_DIR", root / "notices"),
            (events, "EVENTS_DIR", root / "events"),
            (events, "WATCHERS_DIR", root / "watchers"),
            (contacts, "CONTACTS_DIR", root / "contacts"),
        ):
            patcher = mock.patch.object(module, attr, path)
            patcher.start(); self.addCleanup(patcher.stop)
        self.fleet = load_fleet()

    def run_spoken(self, sentence):
        intent = voice.interpret(sentence)
        self.assertIsNotNone(intent["command"], intent.get("say"))
        cmd = intent["command"]
        problems = intercom.validate_kind_args(cmd, self.fleet)
        self.assertEqual(problems, [], problems)
        return intercom.execute_command(cmd, self.fleet, quote=sentence)


class TestSpokenVerbs(VoiceOSCase):
    def test_daily_reminder_by_voice_creates_a_real_schedule(self):
        detail = self.run_spoken("Thea, remind me every day at 8 am to check the pipeline")
        self.assertIn("daily reminder", detail)
        specs = scheduler.all_schedules()
        self.assertEqual(len(specs), 1)
        self.assertEqual(specs[0]["kind"], "daily")
        self.assertEqual(specs[0]["time"], "08:00")
        self.assertEqual(specs[0]["command"]["kind"], "notify_operator")

    def test_reminder_fires_as_a_notification(self):
        self.run_spoken("Thea, remind me every day at 8 am to check the pipeline")
        spec = scheduler.all_schedules()[0]
        # the runtime executes the due command through the same grammar
        cmd = spec["command"]
        self.assertEqual(intercom.validate_kind_args(cmd, self.fleet), [])
        detail = intercom.execute_command(cmd, self.fleet, quote="schedule test")
        self.assertIn("reminder surfaced", detail)
        unread = notifications.all_notifications(state="UNREAD")
        self.assertEqual(len(unread), 1)
        self.assertIn("check the pipeline", unread[0]["body"])

    def test_watch_email_by_voice_creates_a_real_watcher(self):
        contacts.create("bob", "Bob", emails=["bob@example.com"])
        detail = self.run_spoken("Thea, tell me when I get an email from bob")
        self.assertIn("watching for email from", detail)
        watchers = events.list_watchers()
        self.assertEqual(len(watchers), 1)
        self.assertEqual(watchers[0]["match"]["attributes"]["sender"], "bob@example.com")
        # the matching mail event triggers it
        result = events.emit("mail.received", "email:bob@example.com",
                            "Hello — from Bob", source="mail",
                            attributes={"sender": "bob@example.com", "fingerprint": "abc"})
        self.assertEqual(len(result["triggers"]), 1)

    def test_unknown_sender_refused_never_guessed(self):
        detail = self.run_spoken("Thea, tell me when I get an email from stranger")
        self.assertIn("don't know an address", detail)
        self.assertEqual(events.list_watchers(), [])

    def test_notifications_by_voice(self):
        notifications.publish("Reply received", "Bob replied", dedupe_key="x")
        detail = self.run_spoken("Thea, check my notifications")
        self.assertIn("Reply received", detail)
        cleared = self.run_spoken("Thea, clear my notifications")
        self.assertIn("cleared 1", cleared)
        self.assertEqual(notifications.unread_count(), 0)

    def test_contact_by_voice_is_private_never_public_memory(self):
        detail = self.run_spoken("Thea, remember person mom caleb at gmail dot com")
        self.assertIn("private contacts only", detail)
        value = contacts.resolve("mom")
        self.assertEqual(value["emails"], ["caleb@gmail.com"])

    def test_free_time_speaks_slots(self):
        with mock.patch.object(voice, "_spoken_day", return_value="2026-08-27"):
            intent = voice.interpret("Thea, when am I free tomorrow")
        cmd = intent["command"]
        self.assertEqual(cmd, {"kind": "free_time", "day": "2026-08-27"})
        detail = intercom.execute_command(cmd, self.fleet, quote="test")
        self.assertIn("free on 2026-08-27", detail)

    def test_relative_reminder_lands_in_the_future(self):
        detail = self.run_spoken("Thea, remind me in 20 minutes to take the bread out")
        self.assertIn("reminder", detail)
        spec = scheduler.all_schedules()[0]
        at = dt.datetime.fromisoformat(spec["at"])
        self.assertGreater(at, dt.datetime.now(dt.timezone.utc))


class TestSpokenTimeParsing(unittest.TestCase):
    def test_times(self):
        self.assertEqual(voice._spoken_time("8 am"), "08:00")
        self.assertEqual(voice._spoken_time("8:30 pm"), "20:30")
        self.assertEqual(voice._spoken_time("12 am"), "00:00")
        self.assertEqual(voice._spoken_time("12 pm"), "12:00")
        self.assertEqual(voice._spoken_time("14:15"), "14:15")
        self.assertIsNone(voice._spoken_time("half past nine"))
        self.assertIsNone(voice._spoken_time("25:00"))

    def test_days(self):
        import datetime as dt
        self.assertEqual(voice._spoken_day("today"), dt.date.today().isoformat())
        self.assertEqual(voice._spoken_day("tomorrow"),
                         (dt.date.today() + dt.timedelta(days=1)).isoformat())
        self.assertEqual(voice._spoken_day("2026-09-01"), "2026-09-01")
        self.assertIsNone(voice._spoken_day("someday"))


if __name__ == "__main__":
    unittest.main()
