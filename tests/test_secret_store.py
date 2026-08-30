"""Local secret storage never writes plaintext metadata or exposes a print/get CLI."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import secret_store


class SecretStoreCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name) / "secrets"
        patch = mock.patch.object(secret_store, "ROOT", root)
        patch.start(); self.addCleanup(patch.stop)
        protect = mock.patch.object(
            secret_store, "_protect", side_effect=lambda raw: b"ENC1:" + raw[::-1]
        )
        unprotect = mock.patch.object(
            secret_store, "_unprotect",
            side_effect=lambda enc: enc[len(b"ENC1:"):][::-1],
        )
        protect.start(); unprotect.start()
        self.addCleanup(protect.stop); self.addCleanup(unprotect.stop)

    def test_put_get_round_trip_and_metadata_has_no_plaintext(self):
        secret = "sk-test-super-private-123456789"
        row = secret_store.put("openai-main", secret, provider="OpenAI", kind="api_key")
        self.assertEqual(row["name"], "openai-main")
        self.assertEqual(secret_store.get("openai-main"), secret)

        cipher = (secret_store.ROOT / "openai-main.bin").read_bytes()
        metadata = (secret_store.ROOT / "openai-main.json").read_text(encoding="utf-8")
        self.assertNotIn(secret.encode("utf-8"), cipher)
        self.assertNotIn(secret, metadata)
        self.assertNotIn("sk-test", metadata)

    def test_list_returns_metadata_only(self):
        secret_store.put("one", "first-secret", provider="A")
        secret_store.put("two", "second-secret", provider="B")
        rows = secret_store.list_metadata()
        self.assertEqual([r["name"] for r in rows], ["one", "two"])
        serialized = json.dumps(rows)
        self.assertNotIn("first-secret", serialized)
        self.assertNotIn("second-secret", serialized)

    def test_overwrite_preserves_created_time_but_updates_value(self):
        first = secret_store.put("service", "old-value", provider="X")
        second = secret_store.put("service", "new-value", provider="X")
        self.assertEqual(second["created_at"], first["created_at"])
        self.assertEqual(secret_store.get("service"), "new-value")

    def test_missing_ciphertext_is_key_error_and_missing_metadata_fails_closed(self):
        with self.assertRaises(KeyError):
            secret_store.get("missing")
        # stateio deliberately normalizes missing/corrupt JSON state to ValueError.
        # Metadata is state, so keep that fail-closed contract rather than
        # special-casing a missing file into a different exception family.
        with self.assertRaises(ValueError):
            secret_store.metadata("missing")

    def test_empty_and_oversize_values_refused(self):
        with self.assertRaises(ValueError):
            secret_store.put("x", "")
        with self.assertRaises(ValueError):
            secret_store.put("x", "a" * (secret_store.MAX_SECRET_BYTES + 1))

    def test_delete_removes_ciphertext_and_metadata(self):
        secret_store.put("service", "value")
        self.assertTrue(secret_store.delete("service"))
        self.assertFalse((secret_store.ROOT / "service.bin").exists())
        self.assertFalse((secret_store.ROOT / "service.json").exists())
        self.assertFalse(secret_store.delete("service"))

    def test_unsafe_alias_is_refused(self):
        with self.assertRaises(ValueError):
            secret_store.put("../outside", "value")


class AvailabilityCase(unittest.TestCase):
    def test_non_windows_reports_unavailable_without_importing_dpapi(self):
        with mock.patch.object(secret_store.os, "name", "posix"):
            ok, why = secret_store.available()
        self.assertFalse(ok)
        self.assertIn("Windows", why)

    def test_no_cli_command_exists_to_print_plaintext(self):
        source = Path(secret_store.__file__).read_text(encoding="utf-8")
        self.assertNotIn('sub.add_parser("get")', source)
        self.assertNotIn('sub.add_parser("show")', source)


if __name__ == "__main__":
    unittest.main()
