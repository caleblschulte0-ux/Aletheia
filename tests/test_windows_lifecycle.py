"""The lifecycle around the always-on machine, not the features on it.

Everything here comes from the operator's 2026-09-01 catch-up brief:
destructive git behaviour, preservation of his local state, tests writing
into production state, an installer lifting HALT, an updater racing
active work, watchdog duplication. These are the checks that can be made
from here; what remains unverifiable off the Windows machine is listed in
the review record rather than asserted as if it had been proved.
"""
from __future__ import annotations

import os
import re
import tempfile
import unittest
from pathlib import Path

from aletheia import autostart, policy, project_autostart, stateio
from aletheia.fleet import REPO_ROOT

ACTIVATION_SCRIPTS = ("scripts/activate_operator.ps1", "scripts/activate_operator_v2.ps1")


def script(name: str) -> str:
    return (REPO_ROOT / name).read_text(encoding="utf-8")


class TheSuiteNeverWritesProductionState(unittest.TestCase):
    """`python -m unittest discover -s tests -t .` — the `-t .` is what makes
    tests/__init__.py load before anything imports aletheia, which points every
    store at a throwaway directory. Without it, modules bind their real paths at
    import time and any test that forgets a patch writes into the operator's
    private state. That happened three times in one day. Silence is the failure
    mode, so this asserts the isolation is actually in force."""

    def test_private_state_is_a_throwaway_directory(self):
        root = str(stateio.private_dir("probe"))
        self.assertNotIn(str(REPO_ROOT / "state" / "private"), root,
                         "run the suite with -t . — private state is NOT isolated")
        self.assertTrue(os.environ.get("ALETHEIA_PRIVATE_STATE"),
                        "ALETHEIA_PRIVATE_STATE is unset; tests/__init__.py did not run")

    def test_the_kill_switch_under_test_is_not_the_operators(self):
        self.assertNotEqual(Path(policy.HALT_PATH), REPO_ROOT / "state" / "halt.json",
                            "a test could halt or resume the real system")


class InstallersDoNotRaceTheRunningCore(unittest.TestCase):
    """`git checkout -f -B main origin/main` discards every uncommitted change
    and every local commit not on origin/main. On a machine where Aletheia
    actually runs, that is the Core's un-checkpointed state and any checkpoint
    commit that could not be pushed."""

    def test_every_hard_reset_stops_the_always_on_tasks_first(self):
        seen = 0
        for name in ACTIVATION_SCRIPTS:
            body = script(name)
            for line_no, line in enumerate(body.splitlines()):
                # a real invocation, not the comment above it explaining one
                if not re.match(r"\s*git .*checkout -f", line):
                    continue
                before = "\n".join(body.splitlines()[:line_no])
                self.assertIn("Stop-AletheiaTasks", before,
                              f"{name}: resets the tree under a running Core")
                self.assertIn("Assert-NothingUnpushed", before,
                              f"{name}: would silently delete unpushed commits")
                seen += 1
        self.assertTrue(seen, "no hard reset found — did the scripts move?")

    def test_the_scripts_stop_the_tasks_that_actually_exist(self):
        """A renamed scheduled task would turn the stop into a no-op, and
        nothing would look wrong."""
        registered = {spec.name for spec in autostart.TASKS.values()}
        registered.add(project_autostart.TASK_NAME)
        for name in ACTIVATION_SCRIPTS:
            body = script(name)
            stop = re.search(r"function Stop-AletheiaTasks \{(.+?)\n\}", body, re.S)
            self.assertIsNotNone(stop, name)
            for task in registered:
                self.assertIn(f'"{task}"', stop.group(1),
                              f"{name}: does not stop the {task} task")

    def test_an_escape_hatch_exists_and_is_explicit(self):
        for name in ACTIVATION_SCRIPTS:
            self.assertIn("ALETHEIA_DISCARD_LOCAL_COMMITS", script(name),
                          f"{name}: a refusal with no way through is a trap")


class NoInstallerLiftsTheKillSwitch(unittest.TestCase):
    def test_no_script_resumes_from_halt(self):
        for path in sorted((REPO_ROOT / "scripts").glob("*.ps1")):
            body = path.read_text(encoding="utf-8")
            self.assertNotIn("aletheia.policy resume", body, path.name)
            self.assertNotRegex(body, r'"resume"', f"{path.name} resumes the system")

    def test_minting_standing_authority_is_refused_while_halted(self):
        """The activation scripts call `work_trust on` / `code_trust on` as an
        ordinary step, so a re-run while halted would hand back the authority
        the operator had just stopped. The refusal lives in the modules, not in
        the scripts, so it holds however they are invoked."""
        from aletheia import code_trust, secret_trust, work_trust
        for module in (work_trust, code_trust, secret_trust):
            source = (REPO_ROOT / "aletheia" / f"{module.__name__.split('.')[-1]}.py"
                      ).read_text(encoding="utf-8")
            enable = source.split("def enable(", 1)[1].split("\ndef ", 1)[0]
            self.assertIn("policy.ensure_not_halted()", enable,
                          f"{module.__name__}.enable() mints authority while halted")


class OnlyOneWatchdogPerJob(unittest.TestCase):
    """Two things restarting the same process fight each other, and the loser
    is whatever it was writing at the time."""

    def test_scheduled_task_names_are_unique(self):
        names = [spec.name for spec in autostart.TASKS.values()]
        names.append(project_autostart.TASK_NAME)
        self.assertEqual(len(names), len(set(names)), f"duplicate task names: {names}")

    def test_only_the_supervisor_starts_the_core(self):
        """The Core must not be registered as its own task as well: the
        supervisor already restarts it, and a second starter would race the
        self-update restart."""
        modules = [spec.module.split()[0] for spec in autostart.TASKS.values()]
        self.assertNotIn("aletheia.core", modules,
                         "the Core is started by aletheia.supervisor, not by a task of its own")

    def test_multiple_instances_of_the_project_loop_are_refused(self):
        registration = project_autostart.register_script("python.exe", tempfile.gettempdir())
        self.assertIn("-MultipleInstances IgnoreNew", registration,
                      "a slow cycle would otherwise be joined by the next one")


if __name__ == "__main__":
    unittest.main()
