"""Remote access: fail-closed by default, and every way in is a gate.

§92 called the transport a ticket and warned in the same breath that port
8777 must never simply be exposed as a shortcut. These tests are what
stops it becoming one — most of them assert that something does NOT
happen.
"""
import datetime as dt
import json
import os
import tempfile
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

from aletheia import access, core, journal


class TokenCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        env = mock.patch.dict(os.environ,
                              {"ALETHEIA_PRIVATE_STATE": str(root / "private")})
        env.start(); self.addCleanup(env.stop)
        p = mock.patch.object(journal, "JOURNAL_PATH", root / "journal.jsonl")
        p.start(); self.addCleanup(p.stop)
        access.clear_failures()
        self.addCleanup(access.clear_failures)

    # ---- the secret ---------------------------------------------------

    def test_only_the_hash_is_ever_stored(self):
        token, record = access.mint("iPhone")
        stored = access.tokens_path().read_text(encoding="utf-8")
        self.assertNotIn(token, stored)
        self.assertIn(record["sha256"], stored)

    def test_a_minted_token_verifies_and_a_wrong_one_does_not(self):
        token, record = access.mint("iPhone")
        self.assertEqual(access.verify(token)["id"], record["id"])
        self.assertIsNone(access.verify(token + "x"))

    def test_tokens_are_not_guessable(self):
        first, _ = access.mint("a")
        second, _ = access.mint("b")
        self.assertNotEqual(first, second)
        self.assertGreaterEqual(len(first), 40)

    def test_a_revoked_token_stops_working_immediately(self):
        token, record = access.mint("lost phone")
        access.revoke(record["id"])
        self.assertIsNone(access.verify(token))
        self.assertFalse(access.enabled())

    def test_an_expired_token_stops_working(self):
        token, _ = access.mint("old", days=1)
        later = dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=2)
        self.assertIsNone(access.verify(token, now=later))
        self.assertFalse(access.enabled(now=later))

    def test_a_token_with_no_readable_expiry_is_treated_as_expired(self):
        # fail closed: an unparseable expiry is not "forever"
        self.assertTrue(access._expired({"expires": "whenever"}))
        self.assertTrue(access._expired({}))

    def test_a_token_must_be_labelled_and_must_expire(self):
        with self.assertRaises(ValueError):
            access.mint("   ")
        with self.assertRaises(ValueError):
            access.mint("x", days=0)
        with self.assertRaises(ValueError):
            access.mint("x", days=100000)

    def test_an_unknown_scope_is_refused(self):
        with self.assertRaises(ValueError):
            access.mint("x", scope="admin")

    def test_a_corrupt_token_store_authenticates_nobody(self):
        token, _ = access.mint("iPhone")
        access.tokens_path().write_text("{ not json", encoding="utf-8")
        self.assertIsNone(access.verify(token))
        self.assertFalse(access.enabled())

    # ---- brute force --------------------------------------------------

    def test_repeated_wrong_guesses_lock_the_address_out(self):
        token, _ = access.mint("iPhone")
        for _ in range(access.MAX_FAILURES):
            access.verify("wrong", address="10.0.0.9")
        self.assertTrue(access.locked_out("10.0.0.9"))
        # even the RIGHT token is refused while locked out
        self.assertIsNone(access.verify(token, address="10.0.0.9"))
        # and a different address is unaffected
        self.assertIsNotNone(access.verify(token, address="10.0.0.10"))

    # ---- scope --------------------------------------------------------

    def test_a_read_token_may_not_change_anything(self):
        self.assertTrue(access.scope_allows("read", "GET"))
        self.assertTrue(access.scope_allows("read", "HEAD"))
        self.assertFalse(access.scope_allows("read", "POST"))
        self.assertTrue(access.scope_allows("full", "POST"))

    def test_read_is_the_default_scope(self):
        _, record = access.mint("iPhone")
        self.assertEqual(record["scope"], "read")

    # ---- header parsing -------------------------------------------------

    def test_bearer_is_read_case_insensitively_and_never_guesses(self):
        self.assertEqual(access.bearer({"Authorization": "Bearer abc"}), "abc")
        self.assertEqual(access.bearer({"Authorization": "bearer abc"}), "abc")
        self.assertEqual(access.bearer({"Authorization": "Basic abc"}), "")
        self.assertEqual(access.bearer({}), "")

    # ---- the bind decision ---------------------------------------------

    def test_loopback_never_needs_anything(self):
        self.assertIsNone(access.bind_refusal("127.0.0.1", None, None))

    def test_off_loopback_without_a_token_is_refused(self):
        refusal = access.bind_refusal("0.0.0.0", "c.pem", "k.pem")
        self.assertIn("no access token", refusal)

    def test_off_loopback_without_tls_is_refused_even_with_a_token(self):
        access.mint("iPhone")
        refusal = access.bind_refusal("0.0.0.0", None, None)
        self.assertIn("TLS", refusal)
        self.assertIn("tailscale cert", refusal)

    def test_off_loopback_with_missing_cert_files_is_refused(self):
        access.mint("iPhone")
        refusal = access.bind_refusal("0.0.0.0", "nope.pem", "nope.key")
        self.assertIn("not found", refusal)

    def test_off_loopback_is_allowed_only_when_both_conditions_hold(self):
        access.mint("iPhone")
        cert = Path(self.tmp.name) / "c.pem"; cert.write_text("x")
        key = Path(self.tmp.name) / "k.pem"; key.write_text("x")
        self.assertIsNone(access.bind_refusal("0.0.0.0", str(cert), str(key)))

    def test_the_core_refuses_to_bind_off_loopback_by_default(self):
        with self.assertRaises(ValueError) as caught:
            core.make_server("0.0.0.0", 0)
        self.assertIn("refusing to serve", str(caught.exception))


class RemoteRequestCase(unittest.TestCase):
    """The handler's gate, exercised over a real socket."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        env = mock.patch.dict(os.environ,
                              {"ALETHEIA_PRIVATE_STATE": str(root / "private")})
        env.start(); self.addCleanup(env.stop)
        p = mock.patch.object(journal, "JOURNAL_PATH", root / "journal.jsonl")
        p.start(); self.addCleanup(p.stop)
        access.clear_failures()
        self.addCleanup(access.clear_failures)
        self.server = core.make_server(port=0)
        self.port = self.server.server_address[1]
        import threading
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.shutdown)

    def get(self, token=None, remote="10.0.0.5", path="/api/status"):
        """A request that the handler will treat as remote."""
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        request = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}",
                                         headers=headers)
        # the socket really is loopback; pretend the peer is elsewhere
        with mock.patch.object(core.access, "is_loopback",
                               side_effect=lambda a: False):
            try:
                with urllib.request.urlopen(request, timeout=5) as response:
                    return response.status, json.loads(response.read().decode())
            except urllib.error.HTTPError as exc:
                return exc.code, json.loads(exc.read().decode())

    def post(self, token=None):
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/command",
            data=json.dumps({"kind": "note", "text": "hi"}).encode(),
            headers=headers, method="POST")
        with mock.patch.object(core.access, "is_loopback",
                               side_effect=lambda a: False):
            try:
                with urllib.request.urlopen(request, timeout=5) as response:
                    return response.status, json.loads(response.read().decode())
            except urllib.error.HTTPError as exc:
                return exc.code, json.loads(exc.read().decode())

    def test_loopback_still_answers_with_no_credential(self):
        request = urllib.request.Request(f"http://127.0.0.1:{self.port}/api/status")
        with urllib.request.urlopen(request, timeout=5) as response:
            self.assertEqual(response.status, 200)

    def test_a_remote_request_with_no_token_is_401(self):
        status, body = self.get()
        self.assertEqual(status, 401)
        self.assertEqual(body, {"error": "unauthorized"})

    def test_a_remote_request_with_a_bad_token_is_401(self):
        access.mint("iPhone")
        self.assertEqual(self.get("not-the-token")[0], 401)

    def test_the_401_does_not_say_why(self):
        # an error that distinguishes "no such token" from "wrong scope"
        # is an oracle; both read the same from outside
        access.mint("iPhone")
        _, body = self.get("wrong")
        self.assertEqual(set(body), {"error"})

    def test_a_live_read_token_can_read(self):
        token, _ = access.mint("iPhone", scope="read")
        status, body = self.get(token)
        self.assertEqual(status, 200)
        self.assertIn("tasks", body)

    def test_a_read_token_cannot_command(self):
        token, _ = access.mint("iPhone", scope="read")
        status, body = self.post(token)
        self.assertEqual(status, 403)
        self.assertIn("read-only", body["error"])

    def test_a_full_token_can_command(self):
        token, _ = access.mint("laptop", scope="full")
        status, body = self.post(token)
        self.assertEqual(status, 200)
        self.assertEqual(body["outcome"], "done")

    def test_a_revoked_token_stops_working_without_a_restart(self):
        token, record = access.mint("stolen", scope="full")
        self.assertEqual(self.get(token)[0], 200)
        access.revoke(record["id"])
        self.assertEqual(self.get(token)[0], 401)

    def test_remote_use_is_journaled_with_the_token_id(self):
        token, record = access.mint("iPhone")
        self.get(token)
        texts = [e["text"] for e in journal.entries(journal.JOURNAL_PATH)]
        self.assertTrue(any(record["id"] in t and "/api/status" in t for t in texts))

    def test_a_refused_credential_is_journaled(self):
        access.mint("iPhone")
        self.get("wrong")
        texts = [e["text"] for e in journal.entries(journal.JOURNAL_PATH)]
        self.assertTrue(any("rejected remote credential" in t for t in texts))


if __name__ == "__main__":
    unittest.main()
