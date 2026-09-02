"""A standing grant is valid only on the machine that minted it.

The attack this closes, found in the 2026-09-01 catch-up review: every
standing grant validated on a private file plus a PUBLIC approval, and
both can arrive over git — `.gitignore` stops an accidental add, never a
deliberate one. A single push could have manufactured standing
workstation trust, secret-fill authority, or autonomous-PR authority on
the operator's PC.
"""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import (code_trust, journal, machine_binding, policy, secret_trust,
                      stateio, work_trust)

MODULES = (work_trust, secret_trust, code_trust)


class BindingCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        d = Path(self.tmp.name)
        env = mock.patch.dict(os.environ,
                              {"ALETHEIA_MACHINE_KEY": str(d / "machine.key")})
        env.start(); self.addCleanup(env.stop)
        patches = [
            mock.patch.object(policy, "APPROVALS_DIR", d / "approvals"),
            mock.patch.object(policy, "HALT_PATH", d / "halt.json"),
            mock.patch.object(journal, "JOURNAL_PATH", d / "journal.jsonl"),
            mock.patch.object(work_trust, "GRANT_PATH", d / "work.json"),
            mock.patch.object(secret_trust, "GRANT_PATH", d / "secret.json"),
            mock.patch.object(code_trust, "GRANT_PATH", d / "code.json"),
        ]
        for p in patches:
            p.start(); self.addCleanup(p.stop)


class TestKey(BindingCase):
    def test_key_is_created_once_and_reused(self):
        first = machine_binding.machine_key()
        self.assertGreaterEqual(len(first), 32)
        self.assertEqual(first, machine_binding.machine_key())

    def test_degenerate_key_file_is_replaced_not_trusted(self):
        Path(os.environ["ALETHEIA_MACHINE_KEY"]).write_text("00", encoding="utf-8")
        self.assertGreaterEqual(len(machine_binding.machine_key()), 32)

    def test_key_never_lives_in_the_repo(self):
        from aletheia.fleet import REPO_ROOT
        self.assertFalse(
            str(machine_binding.KEY_PATH).startswith(str(REPO_ROOT)),
            "the machine key must live outside the repository, or git can carry it")

    def test_missing_binding_is_refused(self):
        self.assertFalse(machine_binding.verify({}, {"id": "x"}))
        self.assertFalse(machine_binding.verify({"machine_binding": ""}, {"id": "x"}))

    def test_signature_covers_the_fields(self):
        a = machine_binding.sign({"id": "g1", "expires": "2026-12-01T00:00:00Z"})
        b = machine_binding.sign({"id": "g1", "expires": "2027-12-01T00:00:00Z"})
        self.assertNotEqual(a, b)


class TestDeliveredGrantIsInert(BindingCase):
    """The core regression: a grant file + its approval arriving from
    elsewhere must not activate anything."""

    def enable_each(self):
        work_trust.enable(days=1, via="test")
        secret_trust.enable(days=1, via="test")
        code_trust.enable(days=1, via="test")

    def test_locally_minted_grants_are_active(self):
        self.enable_each()
        for mod in MODULES:
            self.assertIsNotNone(mod.active(), f"{mod.__name__} should be active")

    def test_grant_from_another_machine_is_refused(self):
        """Simulates the git-delivery attack: the attacker controls the
        grant file AND the (public, tracked) approval — but not the key."""
        self.enable_each()
        # everything the attacker could push arrives intact...
        delivered = {mod: json.loads(mod.GRANT_PATH.read_text()) for mod in MODULES}
        # ...but it was signed on a machine whose key we do not have
        Path(os.environ["ALETHEIA_MACHINE_KEY"]).unlink()
        machine_binding.machine_key()  # this machine mints a different key
        for mod, record in delivered.items():
            stateio.write_json_atomic(mod.GRANT_PATH, record)
            self.assertIsNone(
                mod.active(),
                f"{mod.__name__}: a grant minted elsewhere must be inert, even "
                "with a valid approval — this is the git-delivery escalation")

    def test_forged_grant_without_any_binding_is_refused(self):
        """The simplest attack: hand-write the JSON and push it."""
        self.enable_each()
        for mod in MODULES:
            record = json.loads(mod.GRANT_PATH.read_text())
            record.pop("machine_binding", None)
            stateio.write_json_atomic(mod.GRANT_PATH, record)
            self.assertIsNone(mod.active(), f"{mod.__name__}: unbound grant")

    def test_tampering_with_limits_invalidates_the_binding(self):
        """Raising the ceiling on a real grant must not survive."""
        self.enable_each()
        for mod, field in ((work_trust, "session_actions"),
                           (secret_trust, "max_actions"), (code_trust, "max_prs")):
            record = json.loads(mod.GRANT_PATH.read_text())
            record[field] = record[field] + 1
            stateio.write_json_atomic(mod.GRANT_PATH, record)
            self.assertIsNone(mod.active(),
                              f"{mod.__name__}: raising {field} must break the binding")

    def test_extending_expiry_invalidates_the_binding(self):
        self.enable_each()
        for mod in MODULES:
            record = json.loads(mod.GRANT_PATH.read_text())
            record["expires"] = "2099-01-01T00:00:00Z"
            stateio.write_json_atomic(mod.GRANT_PATH, record)
            self.assertIsNone(mod.active(), f"{mod.__name__}: expiry is bound")

    def test_pointing_at_a_different_approval_invalidates_the_binding(self):
        self.enable_each()
        for mod in MODULES:
            record = json.loads(mod.GRANT_PATH.read_text())
            record["approval_id"] = "some-other-approval"
            stateio.write_json_atomic(mod.GRANT_PATH, record)
            self.assertIsNone(mod.active(), f"{mod.__name__}: approval is bound")


class TestGrantStateNeverTracked(unittest.TestCase):
    def test_private_state_is_gitignored(self):
        """Belt to the binding's braces: the grant should not be *easy* to
        commit either. (gitignore is not the gate — the binding is.)"""
        import subprocess
        from aletheia.fleet import REPO_ROOT
        proc = subprocess.run(
            ["git", "check-ignore", "state/private/work-trust/grant.json"],
            cwd=str(REPO_ROOT), capture_output=True)
        self.assertEqual(proc.returncode, 0, "state/private/ must stay gitignored")


if __name__ == "__main__":
    unittest.main()
