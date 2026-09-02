"""Regression tests for the Windows ChatGPT subscription browser mode."""
from __future__ import annotations

import os
import unittest
from unittest import mock

from aletheia import browser_reasoner


class WindowsSubscriptionModeCase(unittest.TestCase):
    def test_windows_uses_visible_chrome_for_subscription_reasoning(self):
        sentinel = object()
        with mock.patch.object(browser_reasoner.os, "name", "nt"), \
             mock.patch.object(browser_reasoner.browse, "_Session", return_value=sentinel) as session:
            result = browser_reasoner._subscription_session()
        self.assertIs(result, sentinel)
        session.assert_called_once_with(headed=True)

    def test_non_windows_keeps_hidden_subscription_browser(self):
        sentinel = object()
        with mock.patch.object(browser_reasoner.os, "name", "posix"), \
             mock.patch.object(browser_reasoner.browse, "_Session", return_value=sentinel) as session:
            result = browser_reasoner._subscription_session()
        self.assertIs(result, sentinel)
        session.assert_called_once_with(headed=False)


if __name__ == "__main__":
    unittest.main()


class UnattendedNeverInheritsTheLease(unittest.TestCase):
    """#74 said browser ChatGPT reasoning is off for unattended runtime. The
    lease is an env var, and env vars are inherited — so declining to SET it
    is not enough. The always-on side must actively drop it."""

    def test_drop_lease_clears_the_variable(self):
        from aletheia import browser_reasoner
        with mock.patch.dict(os.environ,
                             {browser_reasoner.ALLOW_ENV: "1"}):
            self.assertTrue(browser_reasoner.operator_lease_enabled())
            browser_reasoner.drop_lease()
            self.assertFalse(browser_reasoner.operator_lease_enabled())

    def test_drop_lease_scrubs_a_child_env_dict(self):
        from aletheia import browser_reasoner
        child = browser_reasoner.drop_lease(
            {browser_reasoner.ALLOW_ENV: "1", "KEEP": "yes"})
        self.assertNotIn(browser_reasoner.ALLOW_ENV, child)
        self.assertEqual(child["KEEP"], "yes")

    def test_supervisor_never_hands_the_lease_to_the_core(self):
        from aletheia import browser_reasoner, supervisor
        with mock.patch.dict(os.environ, {browser_reasoner.ALLOW_ENV: "1"}):
            env = supervisor._child_env()
        self.assertNotIn(browser_reasoner.ALLOW_ENV, env,
                         "the always-on Core must not inherit a foreground "
                         "lease to open the operator's ChatGPT browser")
        self.assertEqual(env.get("ALETHEIA_SUPERVISED"), "1")


class EveryAlwaysOnEntryPointDropsTheLease(unittest.TestCase):
    """The 2026-09-01 re-audit found the earlier fix incomplete.

    `drop_lease()` was wired into the Core and into the supervisor's CHILD
    environment — but the project loop and the voice room are registered as
    their OWN Windows scheduled tasks (aletheia.project_autostart,
    aletheia.autostart), so no parent of theirs scrubs anything and Task
    Scheduler hands them the user's environment. A persistent user-level
    lease variable would have given an unattended 30-minute code loop the
    right to open the operator's signed-in ChatGPT on his screen.

    This test reads the SCHEDULED TASK REGISTRY rather than a hand-written
    list, so a new always-on entry point cannot be registered without
    dropping the lease first.
    """

    def always_on_modules(self):
        from aletheia import autostart, project_autostart
        specs = list(autostart.TASKS.values()) + [project_autostart.SPEC]
        # "aletheia.project_loop once" -> aletheia.project_loop
        # aletheia.supervisor's whole job is starting aletheia.core, so the
        # Core belongs to this surface even though no task names it directly.
        return sorted({spec.module.split()[0] for spec in specs} | {"aletheia.core"})

    def test_the_registry_still_names_the_entry_points_we_think_it_does(self):
        self.assertEqual(
            self.always_on_modules(),
            ["aletheia.core", "aletheia.project_loop", "aletheia.supervisor",
             "aletheia.voice_room"],
            "an always-on entry point was added or renamed — check it drops the lease")

    def test_each_always_on_main_drops_the_lease_before_doing_anything(self):
        import importlib
        for name in self.always_on_modules():
            with self.subTest(module=name):
                module = importlib.import_module(name)
                dropped = []
                with mock.patch.dict(os.environ, {browser_reasoner.ALLOW_ENV: "1"}), \
                     mock.patch.object(browser_reasoner, "drop_lease",
                                       side_effect=lambda env=None: dropped.append(True)), \
                     mock.patch.object(module, "argparse") as ap:
                    ap.ArgumentParser.side_effect = RuntimeError("stop after the drop")
                    with self.assertRaises(RuntimeError):
                        module.main([])
                self.assertTrue(
                    dropped,
                    f"{name}.main() parsed arguments before dropping the ChatGPT "
                    "browser lease — an unattended process must never inherit it")
