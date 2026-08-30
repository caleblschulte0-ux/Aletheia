"""Encrypted observations expose private UI only to the ephemeral requester key."""
import base64
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import journal, sealed_observe


def keypair():
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_der = private.public_key().public_bytes(
        Encoding.DER, PublicFormat.SubjectPublicKeyInfo
    )
    return private, base64.b64encode(public_der).decode("ascii")


def decrypt(private, envelope):
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    wrapped = base64.b64decode(envelope["wrapped_key"])
    nonce = base64.b64decode(envelope["nonce"])
    ciphertext = base64.b64decode(envelope["ciphertext"])
    aad = base64.b64decode(envelope["aad"])
    data_key = private.decrypt(
        wrapped,
        padding.OAEP(
            mgf=padding.MGF1(algorithm=hashes.SHA256()),
            algorithm=hashes.SHA256(),
            label=None,
        ),
    )
    return json.loads(AESGCM(data_key).decrypt(nonce, ciphertext, aad))


class SealedObservationCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        patches = [
            mock.patch.object(sealed_observe, "REPO_ROOT", self.root),
            mock.patch.object(
                sealed_observe,
                "SEALED_DIR",
                self.root / "exchange" / "commands" / "sealed",
            ),
            mock.patch.object(
                journal, "JOURNAL_PATH", self.root / "state" / "journal.jsonl"
            ),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        self.private, self.public = keypair()

    def test_envelope_round_trips_and_contains_no_plaintext(self):
        payload = {"kind": "screen", "private": "Project Apollo confidential"}
        envelope = sealed_observe.seal_payload(payload, self.public, "obs-abc123")
        raw = json.dumps(envelope)
        self.assertNotIn("Project Apollo", raw)
        self.assertEqual(decrypt(self.private, envelope), payload)

    def test_weak_or_invalid_key_is_refused(self):
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
        weak = rsa.generate_private_key(public_exponent=65537, key_size=1024)
        weak_der = weak.public_key().public_bytes(
            Encoding.DER, PublicFormat.SubjectPublicKeyInfo
        )
        with self.assertRaises(ValueError):
            sealed_observe.seal_payload(
                {"x": 1}, base64.b64encode(weak_der).decode("ascii"), "obs-weak"
            )
        with self.assertRaises(ValueError):
            sealed_observe.seal_payload({"x": 1}, "not-base64", "obs-bad")

    def test_no_local_work_trust_means_no_observation(self):
        with mock.patch.object(sealed_observe.work_trust, "active", return_value=None), \
             mock.patch.object(sealed_observe.perception, "observe") as observe:
            with self.assertRaises(PermissionError):
                sealed_observe.run(
                    response_id="obs-none",
                    public_key=self.public,
                    target="screen",
                )
        observe.assert_not_called()

    def test_screen_plaintext_is_only_in_encrypted_sidecar(self):
        private_text = "Private project window"
        with mock.patch.object(
            sealed_observe.work_trust, "active", return_value={"id": "grant"}
        ), mock.patch.object(
            sealed_observe.perception,
            "observe",
            return_value={"windows": [{"title": private_text}]},
        ):
            result = sealed_observe.run(
                response_id="obs-screen",
                public_key=self.public,
                target="screen",
            )
        sidecar = self.root / result["sidecar"]
        raw = sidecar.read_text(encoding="utf-8")
        self.assertNotIn(private_text, raw)
        payload = decrypt(self.private, json.loads(raw))
        self.assertEqual(payload["observation"]["windows"][0]["title"], private_text)

    def test_existing_sidecar_is_idempotent_and_rereads_nothing(self):
        path = sealed_observe.sidecar_path("obs-existing")
        path.parent.mkdir(parents=True)
        path.write_text('{"already":"sealed"}\n', encoding="utf-8")
        with mock.patch.object(sealed_observe.work_trust, "active") as trust, \
             mock.patch.object(sealed_observe.perception, "observe") as observe:
            result = sealed_observe.run(
                response_id="obs-existing",
                public_key=self.public,
                target="screen",
            )
        self.assertTrue(result["reused"])
        trust.assert_not_called()
        observe.assert_not_called()

    def test_bad_public_key_is_refused_before_private_screen_read(self):
        with mock.patch.object(
            sealed_observe.work_trust, "active", return_value={"id": "grant"}
        ), mock.patch.object(sealed_observe.perception, "observe") as observe:
            with self.assertRaises(ValueError):
                sealed_observe.run(
                    response_id="obs-bad-key",
                    public_key="A" * 200,
                    target="screen",
                )
        observe.assert_not_called()


class FakePage:
    def __init__(self):
        self.url = "https://console.example.com/keys?oauth_code=super-private-code"

    def goto(self, url, wait_until=None):
        self.url = "https://console.example.com/keys?oauth_code=super-private-code"

    def title(self):
        return "Developer Console"

    def inner_text(self, selector):
        return "API key sk-1234567890abcdefghijklmnop Project settings and billing"

    def eval_on_selector_all(self, selector, script):
        return [
            {
                "tag": "input", "type": "password", "name": "password", "id": "pw",
                "aria": "Password", "placeholder": "", "text": "", "href": "",
            },
            {
                "tag": "button", "type": "button", "role": "button", "name": "",
                "id": "refresh", "aria": "Refresh", "placeholder": "",
                "text": "Refresh",
                "href": "https://console.example.com/keys?token=private",
            },
        ]

    def close(self):
        pass


class FakeContext:
    def new_page(self):
        return FakePage()


class FakeSession:
    def __enter__(self):
        return FakeContext()

    def __exit__(self, *exc):
        return False


class BrowserObservationCase(unittest.TestCase):
    def test_browser_observation_redacts_credentials_and_url_queries(self):
        with mock.patch.object(
            sealed_observe.browse, "available", return_value=(True, "ready")
        ), mock.patch.object(
            sealed_observe.browse, "_Session", return_value=FakeSession()
        ), mock.patch.object(sealed_observe.journal, "append"):
            payload = sealed_observe.observe_browser(
                "https://console.example.com/keys"
            )

        encoded = json.dumps(payload)
        self.assertNotIn("oauth_code", encoded)
        self.assertNotIn("super-private-code", encoded)
        self.assertNotIn("sk-123456", encoded)
        self.assertNotIn("token=private", encoded)
        self.assertEqual(payload["url"], "https://console.example.com/keys")
        self.assertTrue(payload["controls"][0]["redacted"])
        self.assertIn("Refresh", encoded)


if __name__ == "__main__":
    unittest.main()
