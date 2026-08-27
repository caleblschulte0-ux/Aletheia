import base64
import hashlib
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from aletheia import calendar_auth


class RecordingTransport:
    def __init__(self, payload=None):
        self.payload = payload or {"refresh_token": "refresh-secret", "access_token": "access-secret"}
        self.calls = []

    def request(self, method, url, *, headers=None, json_body=None, form=None,
                expected=None, operation="request"):
        self.calls.append({"method": method, "url": url, "headers": dict(headers or {}),
                           "json": json_body, "form": dict(form or {}), "operation": operation})
        return 200, {}, dict(self.payload)


class OAuthBootstrapCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def _browser_sender(self, expected_state: str, *, bad_first: bool = False,
                        bodies: list[str] | None = None):
        threads = []

        def open_browser(auth_url: str) -> bool:
            query = urllib.parse.parse_qs(urllib.parse.urlparse(auth_url).query)
            redirect_uri = query["redirect_uri"][0]
            state = query["state"][0]
            self.assertEqual(state, expected_state)

            def send():
                if bad_first:
                    bad = redirect_uri + "?" + urllib.parse.urlencode({"state": "x" * 43, "code": "bad-code"})
                    with self.assertRaises(urllib.error.HTTPError) as caught:
                        urllib.request.urlopen(bad, timeout=3).read()
                    self.assertEqual(caught.exception.code, 400)
                good = redirect_uri + "?" + urllib.parse.urlencode({"state": state, "code": "one-time-code"})
                with urllib.request.urlopen(good, timeout=3) as response:
                    body = response.read().decode("utf-8")
                if bodies is not None:
                    bodies.append(body)

            thread = threading.Thread(target=send, daemon=True)
            threads.append(thread)
            thread.start()
            return True

        return open_browser, threads

    def test_pkce_is_s256_and_state_is_high_entropy(self):
        verifier, challenge = calendar_auth.new_pkce()
        expected = base64.urlsafe_b64encode(
            hashlib.sha256(verifier.encode("ascii")).digest()).decode("ascii").rstrip("=")
        self.assertEqual(challenge, expected)
        self.assertGreaterEqual(len(verifier), 43)
        self.assertLessEqual(len(verifier), 128)
        self.assertGreaterEqual(len(calendar_auth.new_state()), 32)

    def test_authorization_urls_are_exactly_scoped(self):
        url, scope = calendar_auth.build_authorization_url(
            "google", client_id="client", redirect_uri="http://127.0.0.1:1234/",
            state="s" * 43, challenge="c" * 43)
        query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        self.assertEqual(scope, calendar_auth.GOOGLE_READ_SCOPE)
        self.assertEqual(query["scope"], [calendar_auth.GOOGLE_READ_SCOPE])
        self.assertEqual(query["code_challenge_method"], ["S256"])
        self.assertEqual(query["access_type"], ["offline"])

        url, scope = calendar_auth.build_authorization_url(
            "microsoft", client_id="client", redirect_uri="http://localhost:4321/",
            state="s" * 43, challenge="c" * 43, enable_writes=True)
        query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        self.assertEqual(scope, "offline_access Calendars.ReadWrite")
        self.assertEqual(query["scope"], [scope])
        self.assertEqual(query["response_mode"], ["query"])

    def test_loopback_rejects_wrong_state_then_accepts_once(self):
        expected_state = "s" * 43
        bodies = []
        browser, threads = self._browser_sender(expected_state, bad_first=True, bodies=bodies)

        def builder(redirect_uri: str) -> str:
            self.assertTrue(redirect_uri.startswith("http://127.0.0.1:"))
            self.assertTrue(redirect_uri.endswith("/"))
            url, _ = calendar_auth.build_authorization_url(
                "google", client_id="client", redirect_uri=redirect_uri,
                state=expected_state, challenge="c" * 43)
            return url

        redirect_uri, code = calendar_auth.listen_once(
            expected_state, provider="google", timeout=5,
            open_browser=browser, authorization_url_builder=builder)
        for thread in threads:
            thread.join(timeout=3)
        self.assertEqual(code, "one-time-code")
        self.assertTrue(redirect_uri.endswith("/"))
        self.assertNotIn("oauth/callback", redirect_uri)
        self.assertEqual(len(bodies), 1)
        self.assertNotIn("one-time-code", bodies[0])
        self.assertNotIn(expected_state, bodies[0])

    def test_microsoft_redirect_uses_standard_localhost_root(self):
        expected_state = "m" * 43
        threads = []

        def open_browser(auth_url: str) -> bool:
            query = urllib.parse.parse_qs(urllib.parse.urlparse(auth_url).query)
            redirect_uri = query["redirect_uri"][0]
            parsed = urllib.parse.urlparse(redirect_uri)
            self.assertEqual(parsed.hostname, "localhost")
            self.assertEqual(parsed.path, "/")
            # The listener is intentionally IPv4 loopback-only. Use its numeric
            # address for the hermetic callback so CI never depends on localhost
            # resolver preference between ::1 and 127.0.0.1.
            callback = f"http://127.0.0.1:{parsed.port}/?" + urllib.parse.urlencode(
                {"state": expected_state, "code": "one-time-code"})
            thread = threading.Thread(
                target=lambda: urllib.request.urlopen(callback, timeout=3).read(), daemon=True)
            threads.append(thread); thread.start(); return True

        def builder(redirect_uri: str) -> str:
            return calendar_auth.build_authorization_url(
                "microsoft", client_id="client", redirect_uri=redirect_uri,
                state=expected_state, challenge="c" * 43)[0]

        redirect_uri, code = calendar_auth.listen_once(
            expected_state, provider="microsoft", timeout=5,
            open_browser=open_browser, authorization_url_builder=builder)
        for thread in threads:
            thread.join(timeout=3)
        self.assertEqual(code, "one-time-code")
        self.assertTrue(redirect_uri.startswith("http://localhost:"))
        self.assertTrue(redirect_uri.endswith("/"))

    def test_exchange_uses_code_verifier_and_returns_only_refresh_token(self):
        fake = RecordingTransport()
        refresh = calendar_auth.exchange_code(
            "microsoft", client_id="client", code="one-time-code",
            verifier="v" * 64, redirect_uri="http://localhost:1234/",
            scope="offline_access Calendars.Read", transport=fake)
        self.assertEqual(refresh, "refresh-secret")
        call = fake.calls[0]
        self.assertEqual(call["method"], "POST")
        self.assertEqual(call["form"]["code_verifier"], "v" * 64)
        self.assertEqual(call["form"]["grant_type"], "authorization_code")
        self.assertNotIn("client_secret", call["form"])

    def test_config_write_is_secret_free_to_caller_and_never_overwrites_silently(self):
        path = self.root / "calendar-live.json"
        summary = calendar_auth.write_config(
            "google", client_id="client", refresh_token="refresh-secret",
            client_secret="client-secret", timezone="America/Chicago", path=path)
        self.assertEqual(summary["provider"], "google")
        self.assertNotIn("refresh_token", summary)
        self.assertNotIn("client_secret", summary)
        raw = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(raw["oauth"]["refresh_token"], "refresh-secret")
        with self.assertRaises(FileExistsError):
            calendar_auth.write_config(
                "google", client_id="other", refresh_token="other-secret",
                timezone="America/Chicago", path=path)
        unchanged = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(unchanged["oauth"]["refresh_token"], "refresh-secret")

    def test_authorize_end_to_end_is_hermetic_and_persists_no_access_token(self):
        target = self.root / "calendar-live.json"
        fake = RecordingTransport()
        threads = []

        def open_browser(auth_url: str) -> bool:
            query = urllib.parse.parse_qs(urllib.parse.urlparse(auth_url).query)
            redirect_uri = query["redirect_uri"][0]
            state = query["state"][0]
            callback = redirect_uri + "?" + urllib.parse.urlencode(
                {"state": state, "code": "one-time-code"})
            thread = threading.Thread(
                target=lambda: urllib.request.urlopen(callback, timeout=3).read(), daemon=True)
            threads.append(thread); thread.start(); return True

        result = calendar_auth.authorize(
            "google", client_id="client", timezone="America/Chicago",
            path=target, transport=fake, open_browser=open_browser)
        for thread in threads:
            thread.join(timeout=3)
        self.assertEqual(result["provider"], "google")
        stored = json.loads(target.read_text(encoding="utf-8"))
        self.assertEqual(stored["oauth"]["refresh_token"], "refresh-secret")
        self.assertNotIn("access_token", stored["oauth"])
        self.assertNotIn("one-time-code", target.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
