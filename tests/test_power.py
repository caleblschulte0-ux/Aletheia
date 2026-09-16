"""Power awareness, against a fake kernel32.

The incident: the laptop slept on battery ("Sleep Reason: Battery") and she
was silent for 22 hours. These hold that she can read AC / battery, that the
PC is held awake only while work runs and released after (never the
display), that he is told once per battery episode, that it reaches the
header, and that off Windows every part is a quiet no-op.
"""
from __future__ import annotations

import datetime as dt
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from aletheia import power


class FakeKernel32:
    def __init__(self, *, ac=1, flag=1, percent=90, saver=0, seconds=0xFFFFFFFF, refuse=False):
        self.ac, self.flag, self.percent, self.saver, self.seconds = ac, flag, percent, saver, seconds
        self.refuse = refuse
        self.calls: list[tuple[int, int]] = []

    def GetSystemPowerStatus(self, pointer):
        raw = pointer._obj
        raw.ACLineStatus, raw.BatteryFlag, raw.BatteryLifePercent = self.ac, self.flag, self.percent
        raw.SystemStatusFlag, raw.BatteryLifeTime = self.saver, self.seconds
        return 1

    def SetThreadExecutionState(self, flags):
        self.calls.append((threading.get_ident(), int(flags)))
        return 0 if self.refuse else power.ES_CONTINUOUS


class Isolated(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        env = mock.patch.dict(os.environ, {"ALETHEIA_PRIVATE_STATE": str(Path(self.tmp.name))})
        env.start()
        self.addCleanup(env.stop)
        self.told: list[dict] = []

    def publish(self, title, body, **kw):
        self.told.append({"title": title, "body": body, **kw})


class ReadingThePowerState(Isolated):
    def test_plugged_in(self):
        state = power.status(kernel32=FakeKernel32(ac=1, flag=8, percent=80))
        self.assertEqual((state["known"], state["on_ac"], state["charging"], state["low"]), (True, True, True, False))
        self.assertEqual(state["said"], "plugged in, battery 80% and charging")

    def test_on_battery_and_low(self):
        state = power.status(kernel32=FakeKernel32(ac=0, flag=2, percent=18, seconds=1800))
        self.assertEqual((state["on_ac"], state["low"], state["critical"]), (False, True, False))
        self.assertEqual(state["said"], "on battery at 18%, low, about 30 minutes left")

    def test_low_by_percent_even_when_windows_says_high(self):
        self.assertTrue(power.status(kernel32=FakeKernel32(ac=0, flag=1, percent=20))["low"])

    def test_a_desktop_with_no_battery_is_never_low(self):
        state = power.status(kernel32=FakeKernel32(ac=1, flag=128, percent=255))
        self.assertEqual((state["has_battery"], state["low"], state["battery_percent"]), (False, False, None))

    def test_off_windows_it_is_honestly_unknown(self):
        with mock.patch.object(power.sys, "platform", "linux"):
            state = power.status()
        self.assertFalse(state["known"])
        self.assertIsNone(state["on_ac"])


class HoldingThePCAwake(Isolated):
    def test_held_only_while_the_body_runs_and_never_the_display(self):
        k = FakeKernel32()
        with power.keep_awake("a batch", kernel32=k, watch_power=False) as hold:
            self.assertTrue(hold["held"])
            self.assertEqual(len(k.calls), 1)
            self.assertEqual([h["reason"] for h in power.holds()], ["a batch"])
        flags = [f for _t, f in k.calls]
        self.assertEqual(flags, [power.ES_CONTINUOUS | power.ES_SYSTEM_REQUIRED, power.ES_CONTINUOUS])
        self.assertTrue(all(not f & power.ES_DISPLAY_REQUIRED for f in flags))
        self.assertEqual(power.holds(), [], "released, and its marker is gone")

    def test_released_on_the_same_thread_even_when_the_work_raises(self):
        k = FakeKernel32()
        with self.assertRaises(RuntimeError):
            with power.keep_awake("a batch", kernel32=k, watch_power=False):
                raise RuntimeError("the form broke")
        self.assertEqual(len(k.calls), 2)
        self.assertEqual(k.calls[0][0], k.calls[1][0])
        self.assertEqual(k.calls[1][1], power.ES_CONTINUOUS)

    def test_nested_holds_release_once_at_the_outermost(self):
        k = FakeKernel32()
        with power.keep_awake("outer", kernel32=k, watch_power=False):
            with power.keep_awake("inner", kernel32=k, watch_power=False):
                pass
            self.assertEqual(len(k.calls), 1, "the inner exit must not release the outer hold")
        self.assertEqual(len(k.calls), 2)

    def test_a_refused_hold_still_runs_the_work(self):
        ran = []
        with power.keep_awake("x", kernel32=FakeKernel32(refuse=True), watch_power=False) as hold:
            ran.append(1)
        self.assertEqual((ran, hold["held"]), ([1], False))

    def test_off_windows_it_is_a_no_op(self):
        ran = []
        with mock.patch.object(power.sys, "platform", "linux"):
            with power.keep_awake("x", watch_power=False) as hold:
                ran.append(1)
        self.assertEqual((ran, hold["held"]), ([1], False))

    def test_a_dead_processes_marker_is_ignored_not_deleted(self):
        from aletheia import stateio
        marker = power._holds_dir() / "hold-999999-1.json"
        stateio.write_json_atomic(marker, {"pid": 999999, "reason": "ghost", "held": True})
        with mock.patch("aletheia.proc.pid_alive", return_value=False):
            self.assertEqual(power.holds(), [])
        self.assertTrue(marker.exists())


class TellingHimOnce(Isolated):
    NOW = dt.datetime(2026, 9, 16, 12, 0, tzinfo=dt.timezone.utc)

    def test_on_battery_while_working_is_said_once_per_episode(self):
        k = FakeKernel32(ac=0, flag=1, percent=70)
        for minute in range(5):
            power.watch(working=True, kernel32=k, publish=self.publish,
                        now=self.NOW + dt.timedelta(minutes=minute))
        keys = {t["dedupe_key"] for t in self.told}
        self.assertEqual(keys, {"power-battery:2026-09-16T12:00:00Z"})
        # Plugged in, then unplugged again: a new episode, a new notice.
        power.watch(working=True, kernel32=FakeKernel32(ac=1), publish=self.publish, now=self.NOW)
        power.watch(working=True, kernel32=k, publish=self.publish, now=self.NOW + dt.timedelta(hours=1))
        self.assertEqual(len({t["dedupe_key"] for t in self.told}), 2)

    def test_on_battery_with_nothing_running_is_not_news(self):
        power.watch(working=False, kernel32=FakeKernel32(ac=0, flag=1, percent=70), publish=self.publish,
                    now=self.NOW)
        self.assertEqual(self.told, [])

    def test_low_battery_is_said_even_when_idle(self):
        seen = power.watch(working=False, kernel32=FakeKernel32(ac=0, flag=2, percent=15),
                           publish=self.publish, now=self.NOW)
        self.assertEqual(seen["told"], ["low"])
        self.assertEqual(self.told[0]["priority"], "IMPORTANT")

    def test_plugged_in_says_nothing(self):
        power.watch(working=True, kernel32=FakeKernel32(ac=1, percent=10), publish=self.publish, now=self.NOW)
        self.assertEqual(self.told, [])

    def test_a_real_notification_is_deduped_by_the_store(self):
        from aletheia import notifications
        with mock.patch.object(notifications, "NOTICES_DIR", Path(self.tmp.name) / "notices"):
            k = FakeKernel32(ac=0, flag=1, percent=70)
            power.watch(working=True, kernel32=k, now=self.NOW)
            power.watch(working=True, kernel32=k, now=self.NOW + dt.timedelta(minutes=1))
            self.assertEqual(len(list((Path(self.tmp.name) / "notices").glob("*.json"))), 1)


class InTheHeader(Isolated):
    def test_on_battery_while_working_raises_a_banner(self):
        with mock.patch.object(power, "_KERNEL32", FakeKernel32(ac=0, flag=1, percent=55)):
            block = power.section()
        signal = power.signal(block, working=True)
        self.assertFalse(signal["ok"])
        self.assertIn("on battery at 55%", signal["banner"])

    def test_plugged_in_is_quietly_ok_and_unknown_is_no_row(self):
        with mock.patch.object(power, "_KERNEL32", FakeKernel32(ac=1, percent=100)):
            self.assertTrue(power.signal(power.section(), working=True)["ok"])
        self.assertIsNone(power.signal({"known": False}, working=True))

    def test_mission_control_carries_the_power_signal(self):
        from aletheia import current_state, mission_control as mc
        current_state.forget_cache()
        mc.forget_cache()
        self.addCleanup(current_state.forget_cache)
        self.addCleanup(mc.forget_cache)
        with mock.patch.object(power, "_KERNEL32", FakeKernel32(ac=0, flag=2, percent=12)):
            out = mc.gather(fresh=True, providers={})
        rows = [s for s in out["header"]["signals"] if s["what"] == "power"]
        self.assertEqual(len(rows), 1)
        self.assertFalse(rows[0]["ok"])


class WhereWorkRuns(Isolated):
    def test_a_campaign_batch_holds_the_pc_awake_and_a_read_does_not(self):
        from aletheia import campaign
        entered = []

        class Hold:
            def __init__(self, reason):
                entered.append(reason)

            def __enter__(self):
                return {}

            def __exit__(self, *exc):
                return False
        with mock.patch.object(power, "keep_awake", Hold), \
                mock.patch.object(campaign, "retry_waiting", return_value={"ready": [], "failed": []}), \
                mock.patch.object(campaign, "spoken", return_value=""), \
                mock.patch.object(campaign, "open_questions", return_value=[]):
            campaign.main(["retry"])
            campaign.main(["questions"])
        self.assertEqual(entered, ["campaign retry"])

    def test_the_general_browser_loop_holds_it_while_it_drives(self):
        import inspect
        from aletheia import browser_loop
        self.assertIn("power.keep_awake", inspect.getsource(browser_loop.pursue))


if __name__ == "__main__":
    unittest.main()
