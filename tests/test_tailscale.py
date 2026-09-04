"""Tailscale is reported as it IS, not as PATH happens to describe it.

2026-09-02: the operator signed in to Tailscale and his checklist still
said `winget install Tailscale.Tailscale (not installed yet)`, because
the only check was `shutil.which("tailscale")` and the Windows installer
does not extend PATH. Telling him to redo a step he has just done is the
same defect class as claiming a capability that is missing (§30, §106).
"""
from __future__ import annotations

import subprocess
import types
import unittest
from pathlib import Path
from unittest import mock

from aletheia import apply as apply_mod
from aletheia import setup as setup_mod
from aletheia import tailscale

RUNNING = """{"BackendState": "Running",
  "Self": {"DNSName": "laptop-i09f9sc8.tail094da3.ts.net.", "HostName": "LAPTOP"},
  "CertDomains": ["laptop-i09f9sc8.tail094da3.ts.net"]}"""
NEEDS_LOGIN = '{"BackendState": "NeedsLogin", "Self": {}}'


def runner(stdout="", code=0, stderr=""):
    return lambda cmd, **kw: subprocess.CompletedProcess(cmd, code, stdout, stderr)


class BinaryCase(unittest.TestCase):
    def test_path_is_used_when_it_answers(self):
        with mock.patch.object(tailscale.shutil, "which", return_value="C:/x/tailscale.exe"):
            self.assertEqual(tailscale.binary(), "C:/x/tailscale.exe")

    def test_the_install_directory_is_found_when_path_does_not_have_it(self):
        real = Path.is_file
        target = tailscale.KNOWN_PATHS[0]
        with mock.patch.object(tailscale.shutil, "which", return_value=None), \
                mock.patch.object(Path, "is_file",
                                  lambda self: self == target or real(self)):
            self.assertEqual(tailscale.binary(), str(target))

    def test_absent_everywhere_is_absent(self):
        with mock.patch.object(tailscale.shutil, "which", return_value=None), \
                mock.patch.object(Path, "is_file", lambda self: False):
            self.assertIsNone(tailscale.binary())


class StateCase(unittest.TestCase):
    def state(self, stdout="", code=0, stderr="", installed=True):
        with mock.patch.object(tailscale, "binary",
                               return_value="ts.exe" if installed else None):
            return tailscale.state(runner=runner(stdout, code, stderr))

    def test_signed_in_reports_the_machine_name_without_its_trailing_dot(self):
        s = self.state(RUNNING)
        self.assertTrue(s.installed and s.running and s.ready)
        self.assertEqual(s.dns_name, "laptop-i09f9sc8.tail094da3.ts.net")
        self.assertEqual(tailscale.cert_command(s),
                         "tailscale cert laptop-i09f9sc8.tail094da3.ts.net")

    def test_installed_but_signed_out_is_not_ready_and_says_so(self):
        s = self.state(NEEDS_LOGIN)
        self.assertTrue(s.installed)
        self.assertFalse(s.running or s.ready)
        self.assertEqual(s.backend, "NeedsLogin")
        self.assertIn("NeedsLogin", s.detail)

    def test_not_installed(self):
        s = self.state(installed=False)
        self.assertFalse(s.installed or s.ready)
        self.assertIn("not installed", s.detail)

    def test_a_broken_cli_is_installed_but_not_ready_and_never_raises(self):
        for stdout, code, stderr in (("", 1, "daemon down"), ("not json", 0, ""), ("", 0, "")):
            s = self.state(stdout, code, stderr)
            self.assertTrue(s.installed)
            self.assertFalse(s.ready)
            self.assertTrue(s.detail)

    def test_an_exploding_runner_does_not_propagate(self):
        with mock.patch.object(tailscale, "binary", return_value="ts.exe"):
            def boom(cmd, **kw):
                raise OSError("access denied")
            s = tailscale.state(runner=boom)
        self.assertTrue(s.installed)
        self.assertFalse(s.ready)
        self.assertIn("OSError", s.detail)

    def test_the_command_is_honest_when_the_name_is_unknown(self):
        self.assertIn("<this-machine>", tailscale.cert_command(self.state(NEEDS_LOGIN)))


class ServeProxiesCase(unittest.TestCase):
    STATUS = ('{"TCP": {"443": {"HTTPS": true}}, "Web": {"laptop.tail.ts.net:443": '
              '{"Handlers": {"/": {"Proxy": "http://127.0.0.1:8777"}, '
              '"/thea-preview": {"Proxy": "http://127.0.0.1:8899"}}}}}')

    def test_every_mount_and_its_backend_are_reported(self):
        with mock.patch.object(tailscale, "binary", return_value="ts.exe"):
            out = tailscale.serve_proxies(runner=runner(self.STATUS))
        self.assertEqual(out, {"/": "http://127.0.0.1:8777",
                               "/thea-preview": "http://127.0.0.1:8899"})

    def test_no_serve_config_is_an_empty_map_not_an_error(self):
        with mock.patch.object(tailscale, "binary", return_value="ts.exe"):
            self.assertEqual(tailscale.serve_proxies(runner=runner("{}")), {})
            self.assertEqual(tailscale.serve_proxies(runner=runner("not json")), {})

    def test_not_installed_is_an_empty_map(self):
        with mock.patch.object(tailscale, "binary", return_value=None):
            self.assertEqual(tailscale.serve_proxies(), {})


class ChecklistCase(unittest.TestCase):
    def how(self, state):
        with mock.patch.object(tailscale, "state", return_value=state):
            return setup_mod._remote_how()

    def test_a_signed_in_machine_is_never_told_to_install_it(self):
        lines = self.how(tailscale.State(True, running=True, backend="Running",
                                         dns_name="laptop.tailnet.ts.net"))
        joined = " ".join(lines)
        self.assertNotIn("winget install", joined)
        self.assertIn("that part is done", joined)
        self.assertIn("tailscale cert laptop.tailnet.ts.net", joined)

    def test_a_missing_install_still_says_install(self):
        self.assertIn("winget install",
                      " ".join(self.how(tailscale.State(False, detail="x"))))

    def test_signed_out_is_told_to_sign_in_not_to_install(self):
        joined = " ".join(self.how(tailscale.State(True, backend="NeedsLogin")))
        self.assertIn("sign in", joined.lower())
        self.assertNotIn("winget install", joined)

    def test_guidance_that_explodes_does_not_break_the_audit(self):
        step = setup_mod.Step("x", "t", 1, "why",
                              lambda: (_ for _ in ()).throw(RuntimeError("nope")),
                              lambda: (setup_mod.OK, "fine"))
        self.assertIn("could not read", step.instructions()[0])

    def test_a_plain_list_is_still_a_plain_list(self):
        step = setup_mod.Step("x", "t", 1, "why", ["do the thing"],
                              lambda: (setup_mod.OK, "fine"))
        self.assertEqual(step.instructions(), ["do the thing"])


class ApplyCase(unittest.TestCase):
    def test_phone_access_prints_his_real_machine_name(self):
        record = {"id": "t1", "scope": "read", "expires": "2026-10-01T00:00:00Z"}
        access = types.SimpleNamespace(mint=lambda label, scope: ("SECRET", record))
        with mock.patch.dict("sys.modules", {"aletheia.access": access}), \
                mock.patch.object(tailscale, "state",
                                  return_value=tailscale.State(
                                      True, running=True, backend="Running",
                                      dns_name="laptop.tailnet.ts.net")):
            out = apply_mod.phone_access()
        self.assertEqual(out["tailnet_name"], "laptop.tailnet.ts.net")
        self.assertEqual(out["next"][0], "tailscale cert laptop.tailnet.ts.net")

    def test_presence_no_longer_depends_on_path_alone(self):
        with mock.patch.object(tailscale, "binary", return_value="C:/x/tailscale.exe"):
            self.assertTrue(apply_mod.tailscale_present())
        with mock.patch.object(tailscale, "binary", return_value=None):
            self.assertFalse(apply_mod.tailscale_present())


if __name__ == "__main__":
    unittest.main()
