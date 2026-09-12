"""His own "start her up" command is the one that must never kill her.

2026-09-11, verbatim: *"i tired to start her up aand got this"* - and what
he got was::

    Stopping Aletheia briefly so Git state cannot move during repair ...
    Aletheia checkout is on 'live', not main. Refusing to rewrite another branch.

Three failures stacked into a dead Aletheia, and every one of them was a
safety measure:

- ``bringup_windows.ps1`` force-kills every ``-m aletheia.*`` process for
  containment, so a stale watchdog cannot resurrect old code mid-repair.
- ``recover_operator_checkout.ps1`` refuses to rewrite a branch it does not
  own - and still named ``main``, three days after the Core moved to
  ``live`` (the same pin as the workflows in
  ``test_ci_writes_where_she_reads``, one layer down).
- The recovery's ``finally`` restarted the scheduled tasks - which the
  bring-up had just DISABLED ten lines earlier, making the restart a silent
  no-op. The net was there and could not catch anything.

So: the scripts follow the deploy branch, and a repair that stops her
brings her back by a route that works even when the task is disabled.
Never by starting the voice task - the microphone is a button he presses
(his ruling, 2026-09-07).
"""
from __future__ import annotations

import re
import unittest

from aletheia.fleet import REPO_ROOT

from tests.test_ci_writes_where_she_reads import DEPLOY_BRANCH

SCRIPTS = REPO_ROOT / "scripts"
BRINGUP = SCRIPTS / "bringup_windows.ps1"
RECOVERY = SCRIPTS / "recover_operator_checkout.ps1"


def _text(path):
    return path.read_text(encoding="utf-8")


class TheBringUpNeverLeavesHerDownCase(unittest.TestCase):
    def test_the_scripts_he_runs_are_there(self):
        """A missing file passes every assertion below by reading empty."""
        for path in (BRINGUP, RECOVERY):
            with self.subTest(script=path.name):
                self.assertTrue(path.is_file(), f"{path.name} is missing")
                self.assertGreater(len(_text(path)), 500)

    def test_no_bring_up_script_rebases_onto_a_branch_the_core_does_not_read(self):
        """`fetch origin main` onto a live checkout is the 09-08 defect."""
        for path in (BRINGUP, RECOVERY):
            text = _text(path)
            with self.subTest(script=path.name):
                self.assertNotIn(
                    "origin/main", text,
                    f"{path.name} rebases onto origin/main, but the Core reads "
                    f"'{DEPLOY_BRANCH}'")
                self.assertNotIn(
                    '"fetch", "origin", "main"', text,
                    f"{path.name} fetches main rather than '{DEPLOY_BRANCH}'")

    def test_the_recovery_accepts_the_branch_the_core_actually_runs(self):
        text = _text(RECOVERY)
        self.assertIn(f'$deployBranch = "{DEPLOY_BRANCH}"', text,
                      "the recovery script no longer names the deploy branch")
        self.assertNotRegex(
            text, r'\$branch\s+-ne\s+"main"',
            "the recovery still demands main, so it refuses on the live "
            "checkout it is pointed at")

    def test_a_repair_that_stops_her_starts_her_again(self):
        """Start-ScheduledTask alone is a no-op on a disabled task."""
        for path in (BRINGUP, RECOVERY):
            text = _text(path)
            with self.subTest(script=path.name):
                self.assertRegex(
                    text, r"aletheia\.supervisor",
                    f"{path.name} stops Aletheia but has no way to start her "
                    f"that survives a disabled scheduled task")
                self.assertRegex(
                    text, r"(?s)catch|finally",
                    f"{path.name} can throw after stopping her without "
                    f"bringing her back")

    def test_bringing_her_back_never_switches_the_microphone_on(self):
        """His ruling: the microphone is a button he presses."""
        for path in (BRINGUP, RECOVERY):
            text = _text(path)
            for line in text.splitlines():
                if "Start-ScheduledTask" in line or "voice_room" in line:
                    with self.subTest(script=path.name, line=line.strip()[:70]):
                        self.assertNotIn(
                            "AletheiaVoice", line,
                            "a repair script must not start the voice task")
                        self.assertNotIn(
                            "aletheia.voice_room", line,
                            "a repair script must not start the voice room")

    def test_the_restart_proves_she_answers_rather_than_assuming_it(self):
        """INSTALLED is not WORKING: a launch is not a live Core."""
        for path in (BRINGUP, RECOVERY):
            text = _text(path)
            with self.subTest(script=path.name):
                self.assertIn("127.0.0.1:8777", text,
                              f"{path.name} restarts her without checking she "
                              f"answers")


if __name__ == "__main__":
    unittest.main()
