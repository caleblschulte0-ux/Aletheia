"""127.0.0.1 proves where a packet came from, not that Caleb sent it.

2026-09-03 security review. Loopback was trusted outright — the Core's own
comment called it "the operator's own machine talking to itself" — while
POST /api/command could approve an email, resume after a halt, or drive
the desktop. Any process running under his Windows account inherited that.

Reads stay open on purpose: a local process can read `state/` off the same
disk, so gating GET costs usability and buys nothing. Writing is the
escalation, and it now needs the local session secret.
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
from unittest import mock

from aletheia import access, core


class LocalSecretCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        env = mock.patch.dict(os.environ, {"ALETHEIA_PRIVATE_STATE": self.tmp.name})
        env.start(); self.addCleanup(env.stop)

    def test_it_is_minted_once_and_reused(self):
        first = access.local_secret()
        self.assertGreaterEqual(len(first), 32)
        self.assertEqual(first, access.local_secret())
        self.assertTrue(access.local_secret_path().is_file())

    def test_it_lives_in_private_state_not_the_repository(self):
        access.local_secret()
        self.assertTrue(str(access.local_secret_path()).startswith(self.tmp.name))

    def test_comparison_accepts_only_the_real_secret(self):
        secret = access.local_secret()
        self.assertTrue(access.local_write_allowed(secret))
        for wrong in ("", None, "guess", secret + "x", secret[:-1]):
            self.assertFalse(access.local_write_allowed(wrong), wrong)


class LoopbackWriteCase(unittest.TestCase):
    """The behaviour end to end, over a real socket."""

    @classmethod
    def setUpClass(cls):
        cls.server = core.make_server(port=0)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        time.sleep(0.3)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def url(self, path):
        return f"http://127.0.0.1:{self.port}{path}"

    def post(self, headers=None, path="/api/command"):
        req = urllib.request.Request(
            self.url(path), data=json.dumps({"kind": "note", "text": "t"}).encode(),
            headers={"Content-Type": "application/json", **(headers or {})})
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status
        except urllib.error.HTTPError as exc:
            return exc.code

    def test_reads_stay_open_on_loopback(self):
        with urllib.request.urlopen(self.url("/api/state"), timeout=5) as r:
            self.assertEqual(r.status, 200)

    def test_a_local_process_cannot_write_without_the_secret(self):
        self.assertEqual(self.post(), 401)

    def test_a_wrong_secret_is_refused(self):
        self.assertEqual(self.post({"X-Aletheia-Local": "guess"}), 401)

    def test_the_real_secret_is_accepted(self):
        self.assertEqual(
            self.post({"X-Aletheia-Local": access.local_secret()}), 200)

    def test_the_secret_also_travels_as_a_bearer_token(self):
        self.assertEqual(
            self.post({"Authorization": f"Bearer {access.local_secret()}"}), 200)

    def test_the_refusal_is_journaled_in_words_he_can_read(self):
        """It is an ALERT, so the activity list on his phone keeps it — and
        it read "a local process attempted POST /api/voice/followup/ack
        without the local session secret", twice, under "what she's done".
        The diagnosis belongs in the subject; the sentence is for him."""
        from aletheia import journal
        self.assertEqual(self.post(), 401)
        line = next(e for e in reversed(journal.entries())
                    if str(e.get("subject", "")).startswith("access:"))
        self.assertNotIn("/api/", line["text"])
        self.assertNotIn("POST", line["text"])
        # the RULE, not the wording: it reads as a sentence about her
        # turning something away, and the machine half is not in it
        self.assertNotIn(":", line["text"])
        self.assertGreater(len(line["text"].split()), 8)
        # and nothing is lost: the method and the path are still on record
        self.assertIn("/api/command", line["subject"])
        self.assertEqual(line["kind"], "alert", "a refused COMMAND is an alert")

    def test_a_refused_ack_is_bookkeeping_and_names_its_client(self):
        """360 of these lines sat in his journal by 2026-09-23, six that
        night, and not one said who had asked. A refused ACK of a follow-up
        costs nothing but a stale notice: an event, never an alert - and the
        subject names the client, where it is debugged."""
        from aletheia import journal
        self.assertEqual(self.post({"User-Agent": "Wall/1.0", "Referer": "http://127.0.0.1/interface/wall.html"},
                                   path="/api/voice/followup/ack"), 401)
        line = next(e for e in reversed(journal.entries())
                    if str(e.get("subject", "")).startswith("access:POST /api/voice/followup/ack"))
        self.assertEqual(line["kind"], "event")
        self.assertIn("Wall/1.0", line["subject"])
        self.assertIn("wall.html", line["subject"])
        self.assertNotIn("Wall", line["text"], "the sentence is still his")

    def test_the_served_page_carries_the_secret_so_the_wall_still_works(self):
        with urllib.request.urlopen(self.url("/"), timeout=5) as r:
            html = r.read().decode("utf-8", "replace")
        self.assertIn('name="aletheia-local"', html)
        self.assertIn(access.local_secret(), html)


if __name__ == "__main__":
    unittest.main()
