"""API-key browser work never reveals plaintext or crosses credential boundaries."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import journal, secret_browser, secret_store


SECRET = "sk-test-super-private-1234567890"


class FakePage:
    def __init__(self, *, url="https://api.example.com/keys", create_text="Create API key",
                 capture_label="API key", capture_type="text"):
        self.url = url
        self.create_text = create_text
        self.capture_label = capture_label
        self.capture_type = capture_type
        self.clicked = []
        self.filled = []

    def goto(self, url, wait_until=None):
        return None

    def wait_for_selector(self, selector):
        return None

    def eval_on_selector(self, selector, script):
        if "value.length" in script:
            return len(self.filled[-1][1]) if self.filled else 0
        if "const v" in script:
            return SECRET
        if selector == "#create":
            return {
                "text": self.create_text, "aria": "", "title": "", "name": "",
                "id": "create", "placeholder": "", "role": "button",
                "inputType": "button", "autocomplete": "", "label": "",
                "nearby": self.create_text,
            }
        return {
            "text": "", "aria": self.capture_label, "title": "", "name": "api_key",
            "id": "key", "placeholder": self.capture_label, "role": "textbox",
            "inputType": self.capture_type, "autocomplete": "", "label": self.capture_label,
            "nearby": self.capture_label,
        }

    def click(self, selector):
        self.clicked.append(selector)

    def fill(self, selector, value):
        self.filled.append((selector, value))

    def close(self):
        pass


class FakeContext:
    def __init__(self, page):
        self.page = page

    def new_page(self):
        return self.page


class FakeSession:
    def __init__(self, page):
        self.page = page

    def __enter__(self):
        return FakeContext(self.page)

    def __exit__(self, *exc):
        return False


class SecretBrowserCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        patches = [
            mock.patch.object(secret_store, "ROOT", root / "secrets"),
            mock.patch.object(journal, "JOURNAL_PATH", root / "journal.jsonl"),
            mock.patch.object(secret_store, "_protect", side_effect=lambda raw: b"ENC:" + raw[::-1]),
            mock.patch.object(secret_store, "_unprotect", side_effect=lambda enc: enc[4:][::-1]),
            mock.patch.object(secret_browser.secret_trust, "claim", return_value={"slot": 1}),
            mock.patch.object(secret_browser.browse, "available", return_value=(True, "ready")),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def session(self, page):
        return mock.patch.object(secret_browser.browse, "_Session", return_value=FakeSession(page))

    def test_create_capture_vaults_key_and_returns_metadata_only(self):
        page = FakePage()
        with self.session(page):
            result = secret_browser.create_capture(
                url="https://api.example.com/keys",
                create_selector="#create", capture_selector="#key", alias="main-key",
            )
        self.assertEqual(page.clicked, ["#create"])
        self.assertEqual(secret_store.get("main-key"), SECRET)
        self.assertEqual(result["alias"], "main-key")
        self.assertEqual(result["allowed_hosts"], ["api.example.com"])
        self.assertNotIn(SECRET, json.dumps(result))
        journal_text = journal.JOURNAL_PATH.read_text(encoding="utf-8")
        self.assertNotIn(SECRET, journal_text)
        self.assertNotIn(SECRET, (secret_store.ROOT / "main-key.json").read_text(encoding="utf-8"))

    def test_revoke_control_is_refused_before_click_or_capture(self):
        page = FakePage(create_text="Revoke API key")
        with self.session(page):
            with self.assertRaises(secret_browser.SecretBrowserRefused):
                secret_browser.create_capture(
                    url="https://api.example.com/keys",
                    create_selector="#create", capture_selector="#key", alias="main-key",
                )
        self.assertEqual(page.clicked, [])
        self.assertFalse((secret_store.ROOT / "main-key.bin").exists())

    def test_cross_host_redirect_is_refused(self):
        page = FakePage(url="https://evil.example/steal")
        with self.session(page):
            with self.assertRaises(secret_browser.SecretBrowserRefused):
                secret_browser.create_capture(
                    url="https://api.example.com/keys",
                    create_selector="#create", capture_selector="#key", alias="main-key",
                )
        self.assertEqual(page.clicked, [])

    def test_password_like_capture_is_refused(self):
        page = FakePage(capture_label="API key", capture_type="password")
        with self.session(page):
            with self.assertRaises(secret_browser.SecretBrowserRefused):
                secret_browser.create_capture(
                    url="https://api.example.com/keys",
                    create_selector="#create", capture_selector="#key", alias="main-key",
                )
        self.assertFalse((secret_store.ROOT / "main-key.bin").exists())

    def test_fill_alias_requires_matching_host_binding(self):
        secret_store.put(
            "main-key", SECRET, provider="api.example.com", kind="api_key",
            allowed_hosts=["api.example.com"],
        )
        with mock.patch.object(secret_store, "get") as get:
            with self.assertRaises(secret_browser.SecretBrowserRefused):
                secret_browser.fill_alias(
                    url="https://evil.example/settings", selector="#key", alias="main-key"
                )
        get.assert_not_called()

    def test_fill_alias_puts_secret_only_into_live_api_key_field(self):
        secret_store.put(
            "main-key", SECRET, provider="api.example.com", kind="api_key",
            allowed_hosts=["api.example.com"],
        )
        page = FakePage()
        with self.session(page):
            result = secret_browser.fill_alias(
                url="https://api.example.com/settings", selector="#key", alias="main-key"
            )
        self.assertEqual(page.filled, [("#key", SECRET)])
        self.assertNotIn(SECRET, json.dumps(result))
        journal_text = journal.JOURNAL_PATH.read_text(encoding="utf-8")
        self.assertNotIn(SECRET, journal_text)

    def test_fill_alias_refuses_password_field(self):
        secret_store.put(
            "main-key", SECRET, provider="api.example.com", kind="api_key",
            allowed_hosts=["api.example.com"],
        )
        page = FakePage(capture_label="API key", capture_type="password")
        with self.session(page):
            with self.assertRaises(secret_browser.SecretBrowserRefused):
                secret_browser.fill_alias(
                    url="https://api.example.com/settings", selector="#key", alias="main-key"
                )
        self.assertEqual(page.filled, [])


class HostBindingCase(unittest.TestCase):
    def test_host_binding_refuses_urls_ports_and_paths(self):
        self.assertEqual(
            secret_store.normalize_hosts(["API.Example.COM."]), ["api.example.com"]
        )
        for bad in ("https://example.com", "example.com:443", "example.com/path", ""):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    secret_store.normalize_hosts([bad])


if __name__ == "__main__":
    unittest.main()
