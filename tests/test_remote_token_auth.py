"""A phone reaching the Core through `tailscale serve` needs a real token.

2026-09-03: previewing the new phone UI over Tailscale worked completely
— reads, approvals, talking to her — with NO credential at all, because
`tailscale serve` forwards to the backend as a new connection FROM THIS
MACHINE, so a phone request and a local script both show client_address
127.0.0.1. The loopback-secret fix (test_local_write_auth.py) closed the
"unauthenticated local process" hole and, by the same mechanism, silently
handed that SAME trust to every device on the tailnet. The operator's own
words once this was explained: "let's set that up" — set up the real,
scoped, revocable per-device token system `aletheia.access` was already
built for, and make the Core actually require it for a proxied request.
"""
from __future__ import annotations

import json
import os
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

from aletheia import access, core, journal

TS_HEADERS = {
    "Tailscale-User-Login": "caleblschulte0-ux@github",
    "Tailscale-Headers-Info": "https://tailscale.com/s/serve-headers",
    "X-Forwarded-For": "100.120.155.77",
}


class DetectionCase(unittest.TestCase):
    """The pure functions, no server involved."""

    def test_a_tailscale_header_is_detected_case_insensitively(self):
        self.assertTrue(access.proxied_via_tailscale({"tailscale-user-login": "x"}))
        self.assertTrue(access.proxied_via_tailscale({"TAILSCALE-Headers-Info": "x"}))

    def test_ordinary_headers_are_not_mistaken_for_it(self):
        self.assertFalse(access.proxied_via_tailscale(
            {"User-Agent": "curl", "X-Forwarded-For": "1.2.3.4"}))
        self.assertFalse(access.proxied_via_tailscale({}))

    def test_a_headerlike_object_without_keys_does_not_crash(self):
        self.assertFalse(access.proxied_via_tailscale(None))
        self.assertFalse(access.proxied_via_tailscale(object()))

    def test_forwarded_address_prefers_the_real_source(self):
        self.assertEqual(
            access.forwarded_address({"X-Forwarded-For": "100.1.2.3"}, "127.0.0.1"),
            "100.1.2.3")

    def test_forwarded_address_takes_the_first_hop_of_a_chain(self):
        self.assertEqual(
            access.forwarded_address({"X-Forwarded-For": "100.1.2.3, 10.0.0.1"}, "?"),
            "100.1.2.3")

    def test_forwarded_address_falls_back_when_absent(self):
        self.assertEqual(access.forwarded_address({}, "127.0.0.1"), "127.0.0.1")

    def test_genuinely_local_requires_both_loopback_and_no_tailscale_header(self):
        self.assertTrue(access.is_genuinely_local("127.0.0.1", {}))
        self.assertFalse(access.is_genuinely_local("127.0.0.1", TS_HEADERS))
        self.assertFalse(access.is_genuinely_local("100.1.2.3", {}))
        self.assertFalse(access.is_genuinely_local("100.1.2.3", TS_HEADERS))

    def test_a_local_process_cannot_talk_its_way_into_the_weaker_check(self):
        """Spoofing the header on a direct local request does not downgrade
        anything — it routes into the STRICTER real-token branch, which a
        forged header alone cannot satisfy."""
        self.assertFalse(access.is_genuinely_local("127.0.0.1", TS_HEADERS))


class LiveServerCase(unittest.TestCase):
    """The full path, over a real socket, with real minted tokens."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls._env = mock.patch.dict(os.environ,
                                   {"ALETHEIA_PRIVATE_STATE": str(Path(cls.tmp.name) / "private")})
        cls._env.start()
        cls._journal = mock.patch.object(journal, "JOURNAL_PATH",
                                         Path(cls.tmp.name) / "journal.jsonl")
        cls._journal.start()
        access.clear_failures()
        cls.server = core.make_server(port=0)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        time.sleep(0.3)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls._journal.stop()
        cls._env.stop()
        cls.tmp.cleanup()

    def setUp(self):
        access.clear_failures()

    def url(self, path):
        return f"http://127.0.0.1:{self.port}{path}"

    def get(self, path, headers=None):
        req = urllib.request.Request(self.url(path), headers=headers or {})
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status, r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read().decode("utf-8", "replace")

    def post(self, path="/api/command", headers=None, body=None):
        req = urllib.request.Request(
            self.url(path),
            data=json.dumps(body or {"kind": "note", "text": "t"}).encode(),
            headers={"Content-Type": "application/json", **(headers or {})},
            method="POST")
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status
        except urllib.error.HTTPError as exc:
            return exc.code

    # ---- the shell loads, so a new device can reach "Access" at all ----

    def test_the_ui_shell_loads_over_tailscale_with_no_token(self):
        status, body = self.get("/", headers=TS_HEADERS)
        self.assertEqual(status, 200)

    def test_the_shell_does_not_leak_the_local_only_secret_to_a_remote_device(self):
        _, body = self.get("/", headers=TS_HEADERS)
        self.assertNotIn("aletheia-local", body)

    def test_a_genuinely_local_load_still_gets_the_local_secret(self):
        _, body = self.get("/")
        self.assertIn("aletheia-local", body)

    # ---- /api/ is closed to a tailscale-proxied caller with no token ---

    def test_a_tailscale_proxied_read_with_no_token_is_refused(self):
        status, _ = self.get("/api/state", headers=TS_HEADERS)
        self.assertEqual(status, 401)

    def test_the_original_bug_a_tailscale_proxied_write_with_no_token_is_refused(self):
        """This is the exact hole: before this fix, this returned 200."""
        self.assertEqual(self.post(headers=TS_HEADERS), 401)

    def test_a_bare_local_request_is_completely_unaffected(self):
        # no Tailscale-* headers at all = the original, unchanged local path
        status, _ = self.get("/api/state")
        self.assertEqual(status, 200)
        self.assertEqual(
            self.post(headers={"X-Aletheia-Local": access.local_secret()}), 200)

    # ---- with a real token ---------------------------------------------

    def test_a_read_token_can_read_but_not_write(self):
        token, _ = access.mint("test-phone", scope="read")
        headers = {**TS_HEADERS, "Authorization": f"Bearer {token}"}
        status, _ = self.get("/api/state", headers=headers)
        self.assertEqual(status, 200)
        self.assertEqual(self.post(headers=headers), 403)

    def test_a_full_token_can_write(self):
        token, _ = access.mint("test-phone-2", scope="full")
        headers = {**TS_HEADERS, "Authorization": f"Bearer {token}"}
        self.assertEqual(self.post(headers=headers), 200)

    def test_a_revoked_token_stops_working(self):
        token, record = access.mint("test-phone-3", scope="full")
        access.revoke(record["id"])
        headers = {**TS_HEADERS, "Authorization": f"Bearer {token}"}
        status, _ = self.get("/api/state", headers=headers)
        self.assertEqual(status, 401)

    def test_a_wrong_token_over_tailscale_is_refused_not_treated_as_local(self):
        headers = {**TS_HEADERS, "Authorization": "Bearer totally-made-up"}
        status, _ = self.get("/api/state", headers=headers)
        self.assertEqual(status, 401)

    def test_the_local_secret_does_not_work_over_a_tailscale_proxied_connection(self):
        """The local secret proves "this machine"; a tailscale-proxied
        request is, by definition, not being evaluated as this machine
        talking to itself, so it must not be honoured here."""
        headers = {**TS_HEADERS, "X-Aletheia-Local": access.local_secret()}
        self.assertEqual(self.post(headers=headers), 401)

    # ---- rate limiting keys on the real device, not the shared proxy IP -

    def test_lockout_after_repeated_bad_tokens_from_one_forwarded_address(self):
        headers = {**TS_HEADERS, "Authorization": "Bearer nope"}
        for _ in range(access.MAX_FAILURES):
            self.get("/api/state", headers=headers)
        status, _ = self.get("/api/state", headers=headers)
        self.assertEqual(status, 401)  # locked out, not merely "wrong token"
        # a DIFFERENT device (different X-Forwarded-For) is not caught by it
        other = {**TS_HEADERS, "X-Forwarded-For": "100.9.9.9",
                 "Authorization": f"Bearer {access.mint('other-device')[0]}"}
        status2, _ = self.get("/api/state", headers=other)
        self.assertEqual(status2, 200)


if __name__ == "__main__":
    unittest.main()
