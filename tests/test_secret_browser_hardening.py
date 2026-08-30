"""Credential automation fails closed around aliases, metadata and captured values."""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import secret_browser, secret_store


class HardeningCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name) / "secrets"
        patches = [
            mock.patch.object(secret_store, "ROOT", root),
            mock.patch.object(secret_store, "_protect", side_effect=lambda raw: b"ENC:" + raw[::-1]),
            mock.patch.object(secret_store, "_unprotect", side_effect=lambda enc: enc[4:][::-1]),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def test_create_refuses_existing_alias_before_claim_or_browser(self):
        secret_store.put(
            "main-key", "existing-api-key", provider="api.example.com",
            kind="api_key", allowed_hosts=["api.example.com"],
        )
        with mock.patch.object(secret_browser.secret_trust, "claim") as claim, \
             mock.patch.object(secret_browser.browse, "_Session") as session:
            with self.assertRaises(secret_browser.SecretBrowserRefused):
                secret_browser.create_capture(
                    url="https://api.example.com/keys", create_selector="#create",
                    capture_selector="#key", alias="main-key",
                )
        claim.assert_not_called()
        session.assert_not_called()
        self.assertEqual(secret_store.get("main-key"), "existing-api-key")

    def test_missing_alias_error_does_not_include_private_store_path(self):
        with self.assertRaises(secret_browser.SecretBrowserRefused) as ctx:
            secret_browser.fill_alias(
                url="https://api.example.com/settings", selector="#key", alias="missing"
            )
        message = str(ctx.exception)
        self.assertIn("unavailable or corrupt", message)
        self.assertNotIn(str(secret_store.ROOT), message)

    def test_non_api_kind_cannot_be_filled_even_when_host_bound(self):
        secret_store.put(
            "login-password", "long-enough-password", provider="api.example.com",
            kind="password", allowed_hosts=["api.example.com"],
        )
        with self.assertRaises(secret_browser.SecretBrowserRefused):
            secret_browser.fill_alias(
                url="https://api.example.com/settings", selector="#key",
                alias="login-password",
            )

    def test_capture_requires_one_ascii_opaque_value(self):
        for bad in (
            "short",
            "api key sk-abcdef0123456789",
            "line1\nline2-secret",
            "κλειδί-abcdef012345",
            "x" * (secret_browser.MAX_CAPTURE_CHARS + 1),
        ):
            with self.subTest(bad=bad[:20]):
                with self.assertRaises(secret_browser.SecretBrowserError):
                    secret_browser._api_value(bad)
        self.assertEqual(
            secret_browser._api_value("sk-abcdef0123456789"), "sk-abcdef0123456789"
        )

    def test_malformed_hosts_are_not_bindable(self):
        for bad in (
            "a..example.com", "-bad.example.com", "bad-.example.com",
            "https://example.com", "example.com:443", "example.com/path", "",
        ):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    secret_store.normalize_hosts([bad])


if __name__ == "__main__":
    unittest.main()
