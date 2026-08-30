"""Regression tests for normal-Chrome authentication on Windows."""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import browse


class NativeChromeLoginCase(unittest.TestCase):
    def test_explicit_chrome_path_is_authoritative(self):
        with mock.patch.dict(os.environ, {"ALETHEIA_CHROME_PATH": r"C:\\Chrome\\chrome.exe"}):
            self.assertEqual(browse._system_chrome_path(), r"C:\\Chrome\\chrome.exe")

    def test_automation_prefers_the_same_chrome_used_for_login(self):
        with mock.patch.object(browse, "_system_chrome_path", return_value="chrome.exe"), \
             mock.patch.object(browse, "_chromium_path", return_value="chromium.exe"):
            self.assertEqual(browse._browser_executable(), "chrome.exe")

    def test_native_login_uses_dedicated_profile_without_playwright_auth(self):
        with tempfile.TemporaryDirectory() as td:
            profile = Path(td) / "profile"
            fake_chrome = Path(td) / "chrome.exe"
            fake_chrome.write_bytes(b"")
            completed = mock.Mock(returncode=0)
            with mock.patch.object(browse, "_system_chrome_path", return_value=str(fake_chrome)), \
                 mock.patch.object(browse.subprocess, "run", return_value=completed) as run:
                rc = browse.native_login("https://chatgpt.com/", profile=profile)

            self.assertEqual(rc, 0)
            argv = run.call_args.args[0]
            self.assertEqual(argv[0], str(fake_chrome))
            self.assertIn(f"--user-data-dir={profile}", argv)
            self.assertIn("https://chatgpt.com/", argv)
            self.assertFalse(any("remote-debugging" in arg for arg in argv))
            self.assertFalse(any("automation" in arg.lower() for arg in argv))
            self.assertTrue(profile.is_dir())

    def test_user_closing_browser_is_benign_cleanup(self):
        class TargetClosedError(Exception):
            pass

        self.assertTrue(browse._closed_browser_error(TargetClosedError("closed")))
        self.assertTrue(browse._closed_browser_error(
            RuntimeError("Target page, context or browser has been closed")
        ))
        self.assertFalse(browse._closed_browser_error(RuntimeError("disk failure")))


if __name__ == "__main__":
    unittest.main()
