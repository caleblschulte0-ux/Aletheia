"""A reminder that actually reminds him.

"Remind me at three to call the dentist" worked end to end: the planner
produced `remind_at`, the scheduler stored it, `runtime.tick` claimed it
at three exactly, `intercom` ran `notify_operator`, and a notification
was written to disk. Nothing appeared on his screen. Nothing made a
sound. His phone, in his pocket, was not polling.

Everything upstream of delivery was right, which is exactly why nothing
caught it — every test passed and the journal said "reminder surfaced".
Surfaced WHERE.
"""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import desktop_notify, journal, notifications, stateio


class Ran:
    def __init__(self, code=0):
        self.returncode = code


class DesktopCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        d = Path(self.tmp.name)
        env = mock.patch.dict(os.environ, {"ALETHEIA_PRIVATE_STATE": str(d)})
        env.start(); self.addCleanup(env.stop)
        for target, attr, value in ((journal, "JOURNAL_PATH", d / "j.jsonl"),
                                    (notifications, "NOTICES_DIR", d / "notices"),
                                    (desktop_notify, "delivered_path",
                                     lambda: d / "delivered.json")):
            p = mock.patch.object(target, attr, value)
            p.start(); self.addCleanup(p.stop)
        # pretend we are on his PC
        self.windows = mock.patch.object(desktop_notify, "available",
                                         return_value=(True, "ready"))
        self.windows.start(); self.addCleanup(self.windows.stop)
        shell = mock.patch.object(desktop_notify, "_powershell",
                                  return_value="powershell.exe")
        shell.start(); self.addCleanup(shell.stop)

    def calls(self, code=0):
        seen = []

        def runner(argv, **kwargs):
            seen.append({"argv": argv, "input": kwargs.get("input")})
            return Ran(code)
        self.seen = seen
        return runner


class ItPutsItOnHisScreen(DesktopCase):
    def test_a_loud_notification_is_shown(self):
        notifications.publish("Reminder", "Call the dentist",
                              priority="IMPORTANT", source="reminder")
        sent = desktop_notify.deliver_pending(runner=self.calls())
        self.assertEqual(len(sent), 1)
        payload = json.loads(self.seen[0]["input"])
        self.assertEqual(payload["title"], "Reminder")
        self.assertIn("dentist", payload["body"])

    def test_the_same_reminder_is_not_shown_twice(self):
        notifications.publish("Reminder", "Call the dentist",
                              priority="IMPORTANT", source="reminder")
        desktop_notify.deliver_pending(runner=self.calls())
        again = desktop_notify.deliver_pending(runner=self.calls())
        self.assertEqual(again, [], "a toast every sixty seconds is a reason "
                                    "to turn her off")

    def test_a_quiet_notification_does_not_interrupt(self):
        """A machine that interrupts for everything is one he turns off."""
        notifications.publish("FYI", "the pulse refreshed", priority="NORMAL")
        self.assertEqual(desktop_notify.deliver_pending(runner=self.calls()), [])

    def test_a_burst_is_capped(self):
        for i in range(8):
            notifications.publish(f"Thing {i}", "body", priority="IMPORTANT")
        sent = desktop_notify.deliver_pending(runner=self.calls())
        self.assertLessEqual(len(sent), desktop_notify.MAX_PER_TICK)

    def test_an_acknowledged_notice_is_not_resurrected(self):
        notice = notifications.publish("Reminder", "old news",
                                       priority="IMPORTANT")
        notifications.set_state(notice["id"], "ACKNOWLEDGED")
        self.assertEqual(desktop_notify.deliver_pending(runner=self.calls()), [])


class ItIsNeverTheRecord(DesktopCase):
    def test_a_failed_toast_leaves_the_notification_unread(self):
        """A missed toast is a missed toast, not a lost reminder."""
        notice = notifications.publish("Reminder", "Call the dentist",
                                       priority="IMPORTANT")
        sent = desktop_notify.deliver_pending(runner=self.calls(code=1))
        self.assertEqual(sent, [])
        self.assertEqual(notifications.load(notice["id"])["state"], "UNREAD")

    def test_a_shown_toast_does_not_mark_it_read_either(self):
        """Seeing a toast go by is not the same as dealing with it."""
        notice = notifications.publish("Reminder", "Call the dentist",
                                       priority="IMPORTANT")
        desktop_notify.deliver_pending(runner=self.calls())
        self.assertEqual(notifications.load(notice["id"])["state"], "UNREAD")

    def test_a_shell_that_explodes_is_not_an_exception(self):
        notifications.publish("Reminder", "x", priority="IMPORTANT")

        def boom(*a, **k):
            raise OSError("no shell")
        self.assertEqual(desktop_notify.deliver_pending(runner=boom), [])

    def test_it_is_recorded_before_it_is_shown(self):
        """A crash between the two costs him one toast; the other order
        costs him the same toast every minute until he notices."""
        notice = notifications.publish("Reminder", "x", priority="IMPORTANT")

        def crash(*a, **k):
            raise KeyboardInterrupt
        try:
            desktop_notify.deliver_pending(runner=crash)
        except KeyboardInterrupt:
            pass
        self.assertIn(notice["id"], desktop_notify._delivered())


class ItStaysOffMachinesItCannotWorkOn(unittest.TestCase):
    def test_availability_is_honest_and_never_raises(self):
        ok, why = desktop_notify.available()
        self.assertIsInstance(ok, bool)
        self.assertTrue(why)

    def test_nothing_is_spawned_where_it_cannot_work(self):
        with mock.patch.object(desktop_notify, "available",
                               return_value=(False, "not Windows")):
            def explode(*a, **k):
                raise AssertionError("must not spawn a shell")
            self.assertEqual(desktop_notify.deliver_pending(runner=explode), [])
            self.assertFalse(desktop_notify.toast("t", "b", runner=explode))

    def test_the_prompt_never_travels_in_argv(self):
        """A reminder can contain quotes, newlines and a person's name;
        argv on Windows is a minefield and stdin is not."""
        body = (Path(__file__).parent.parent / "aletheia"
                / "desktop_notify.py").read_text(encoding="utf-8")
        self.assertIn("[Console]::In.ReadToEnd()", body)
        self.assertIn('input=payload', body)


class TheBeatDeliversIt(unittest.TestCase):
    def test_the_core_runtime_calls_it(self):
        body = (Path(__file__).parent.parent / "aletheia" / "runtime.py"
                ).read_text(encoding="utf-8")
        self.assertIn("desktop_notify.deliver_pending", body)

    def test_a_broken_delivery_cannot_stop_the_beat(self):
        body = (Path(__file__).parent.parent / "aletheia" / "runtime.py"
                ).read_text(encoding="utf-8")
        self.assertIn('guarded("desktop"', body)


if __name__ == "__main__":
    unittest.main()
