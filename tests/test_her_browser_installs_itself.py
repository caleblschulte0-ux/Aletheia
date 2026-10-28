"""His PC, 2026-10-28: the Core's Python had no Playwright, so every page refused."""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import browse


class HerBrowserInstallsItself(unittest.TestCase):
    def setUp(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        self.state = Path(td.name) / "install.json"
        for patch in (mock.patch.object(browse, "_install_state_path", return_value=self.state),
                      mock.patch.object(browse.journal, "append"),
                      mock.patch.dict(os.environ, {"ALETHEIA_NO_SELF_INSTALL": "", "ALETHEIA_REHEARSAL": ""})):
            patch.start()
            self.addCleanup(patch.stop)

    def test_a_missing_browser_is_installed_in_the_background_once(self):
        spawner = mock.Mock(return_value=4321)
        with mock.patch.object(browse, "_browser_on_disk", return_value=False):
            first = browse.ensure_installed(now=1000.0, spawner=spawner, importable=False)
            again = browse.ensure_installed(now=1060.0, spawner=spawner, importable=False)
        self.assertTrue(first["started"])
        self.assertNotIn("started", again)
        spawner.assert_called_once()
        self.assertEqual(spawner.call_args.args[0][-2:], ["aletheia.browse", "install"])

    def test_it_tries_again_after_a_while(self):
        spawner = mock.Mock(return_value=1)
        with mock.patch.object(browse, "_browser_on_disk", return_value=False):
            browse.ensure_installed(now=0.0, spawner=spawner, importable=False)
            browse.ensure_installed(now=browse.INSTALL_EVERY_S + 1, spawner=spawner, importable=False)
        self.assertEqual(spawner.call_count, 2)

    def test_a_browser_that_is_there_installs_nothing(self):
        spawner = mock.Mock()
        with mock.patch.object(browse, "_browser_on_disk", return_value=True):
            self.assertTrue(browse.ensure_installed(spawner=spawner, importable=True)["ok"])
        spawner.assert_not_called()

    def test_a_test_run_or_a_rehearsal_never_installs(self):
        spawner = mock.Mock()
        for env in ({"ALETHEIA_NO_SELF_INSTALL": "1"}, {"ALETHEIA_REHEARSAL": "1"}):
            with mock.patch.dict(os.environ, env), \
                 mock.patch.object(browse, "_browser_on_disk", return_value=False):
                browse.ensure_installed(spawner=spawner, importable=False)
        spawner.assert_not_called()

    def test_the_beat_asks(self):
        from aletheia import runtime
        with mock.patch.object(browse, "ensure_installed", return_value={"ok": True}) as ensure:
            runtime._heal_browser()
        ensure.assert_called_once()


if __name__ == "__main__":
    unittest.main()
