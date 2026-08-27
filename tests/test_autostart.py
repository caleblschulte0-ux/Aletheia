"""The always-on contract, held as a pure function.

These tests encode the settings that actually failed on the operator's PC
on 2026-08-27, so the shape of that outage can never be registered again
without a red test. They run anywhere: `audit()` and `register_script()`
take data and return data, and touch no Task Scheduler.
"""
import unittest
from unittest import mock

from aletheia import autostart

# exactly what `Get-ScheduledTask Aletheia` returned that morning
OUTAGE_SETTINGS = {
    "exists": True,
    "state": "Ready",
    "execute": r"C:\Python312\pythonw.exe",
    "arguments": "-m aletheia.supervisor",
    "allow_start_on_batteries": False,
    "keeps_running_on_batteries": False,
    "execution_time_limit": "PT72H",
    "restart_count": 0,
    "multiple_instances": "IgnoreNew",
    "start_when_available": False,
    "repetition_intervals": [],
    "last_run": "08/26/2026 21:43:36",
    "last_result": 2147943467,
}

HEALTHY_SETTINGS = {
    **OUTAGE_SETTINGS,
    "allow_start_on_batteries": True,
    "keeps_running_on_batteries": True,
    "execution_time_limit": "PT0S",
    "restart_count": 3,
    "start_when_available": True,
    "repetition_intervals": ["PT5M"],
}


class DurationCase(unittest.TestCase):
    def test_minutes_from_task_scheduler_durations(self):
        self.assertEqual(autostart._iso8601_minutes("PT5M"), 5)
        self.assertEqual(autostart._iso8601_minutes("PT1H30M"), 90)
        self.assertEqual(autostart._iso8601_minutes("PT72H"), 4320)
        self.assertEqual(autostart._iso8601_minutes("P1D"), 1440)
        self.assertEqual(autostart._iso8601_minutes("PT0S"), 0)

    def test_months_are_not_minutes(self):
        # P1M is one month; PT1M is one minute. Confusing them would let a
        # monthly trigger pass as a five-minute watchdog.
        self.assertGreater(autostart._iso8601_minutes("P1M"), 40000)
        self.assertEqual(autostart._iso8601_minutes("PT1M"), 1)

    def test_garbage_is_none_not_zero(self):
        self.assertIsNone(autostart._iso8601_minutes("soon"))
        self.assertIsNone(autostart._iso8601_minutes(""))
        self.assertIsNone(autostart._iso8601_minutes(None))


class AuditCase(unittest.TestCase):
    def test_the_real_outage_registration_fails_every_way_it_did(self):
        problems = " | ".join(autostart.audit(OUTAGE_SETTINGS))
        self.assertIn("DisallowStartIfOnBatteries", problems)
        self.assertIn("StopIfGoingOnBatteries", problems)
        self.assertIn("PT72H", problems)
        self.assertIn("RestartCount 0", problems)
        self.assertIn("StartWhenAvailable", problems)
        self.assertIn("no repeating trigger", problems)

    def test_the_contract_passes(self):
        self.assertEqual(autostart.audit(HEALTHY_SETTINGS), [])

    def test_unregistered_is_the_loudest_failure(self):
        self.assertEqual(len(autostart.audit({"exists": False})), 1)
        self.assertIn("nothing brings Aletheia back",
                      autostart.audit({"exists": False})[0])
        self.assertEqual(autostart.audit({}), autostart.audit({"exists": False}))

    def test_disabled_task_is_caught(self):
        self.assertIn("Disabled",
                      " ".join(autostart.audit({**HEALTHY_SETTINGS,
                                                "state": "Disabled"})))

    def test_a_too_slow_watchdog_is_not_a_watchdog(self):
        problems = autostart.audit({**HEALTHY_SETTINGS,
                                    "repetition_intervals": ["PT1H"]})
        self.assertEqual(len(problems), 1)
        self.assertIn("60m > 5m", problems[0])

    def test_multiple_instances_must_ignore_new(self):
        # Parallel would let the 5-minute watchdog start a second Aletheia
        # every five minutes forever, fighting over the port and the mic.
        for value in ("Parallel", "Queue", "StopExisting"):
            problems = " ".join(autostart.audit({**HEALTHY_SETTINGS,
                                                 "multiple_instances": value}))
            self.assertIn("MultipleInstances", problems, value)

    def test_no_execution_limit_spellings_all_pass(self):
        for value in ("PT0S", "", None):
            self.assertEqual(
                autostart.audit({**HEALTHY_SETTINGS, "execution_time_limit": value}),
                [], value)


class RegisterScriptCase(unittest.TestCase):
    def script(self, **kw):
        return autostart.register_script(
            autostart.TASKS["core"], r"C:\Py\pythonw.exe", r"C:\Users\caleb\Aletheia",
            **kw)

    def test_script_asks_for_every_clause_the_contract_needs(self):
        s = self.script()
        for clause in ("-AllowStartIfOnBatteries", "-DontStopIfGoingOnBatteries",
                       "-StartWhenAvailable", "-MultipleInstances IgnoreNew",
                       "-ExecutionTimeLimit ([TimeSpan]::Zero)",
                       "-RestartCount 3", "New-TimeSpan -Minutes 5",
                       "-Trigger $logon,$watchdog", "Register-ScheduledTask"):
            self.assertIn(clause, s)

    def test_script_carries_the_interpreter_module_and_cwd(self):
        s = self.script()
        self.assertIn(r"'C:\Py\pythonw.exe'", s)
        self.assertIn("'-m aletheia.supervisor'", s)
        self.assertIn(r"'C:\Users\caleb\Aletheia'", s)

    def test_voice_gets_its_own_registration(self):
        s = autostart.register_script(autostart.TASKS["voice"], "py.exe")
        self.assertIn("'-m aletheia.voice_room'", s)
        self.assertIn("'AletheiaVoice'", s)

    def test_quotes_in_a_path_cannot_break_out(self):
        spec = autostart.TaskSpec("x", "Odd'Name", "aletheia.core", "it's fine")
        s = autostart.register_script(spec, "py.exe", "C:\\a'b")
        self.assertIn("'Odd''Name'", s)
        self.assertIn("'C:\\a''b'", s)
        self.assertIn("'it''s fine'", s)

    def test_repeat_minutes_is_a_knob_not_a_literal(self):
        self.assertIn("New-TimeSpan -Minutes 2", self.script(repeat_minutes=2))


class OffWindowsCase(unittest.TestCase):
    def test_install_is_honest_off_windows(self):
        with mock.patch.object(autostart.os, "name", "posix"):
            ok, detail = autostart.install(autostart.TASKS["core"])
        self.assertFalse(ok)
        self.assertIn("needs Windows", detail)
        self.assertIn("aletheia.supervisor", detail)

    def test_read_task_is_honest_off_windows(self):
        with mock.patch.object(autostart.os, "name", "posix"):
            self.assertFalse(autostart.read_task("Aletheia")["exists"])

    def test_unparseable_query_never_reads_as_healthy(self):
        with mock.patch.object(autostart.os, "name", "nt"), \
                mock.patch.object(autostart, "_powershell", return_value=(0, "boom")):
            actual = autostart.read_task("Aletheia")
        self.assertFalse(actual["exists"])
        self.assertTrue(autostart.audit(actual))  # fails closed


if __name__ == "__main__":
    unittest.main()
