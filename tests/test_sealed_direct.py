"""Direct ChatGPT envelopes may request encrypted observation, never plaintext."""
import unittest
from unittest import mock

from aletheia import work_direct


class SealedDirectCase(unittest.TestCase):
    def setUp(self):
        self.quote = "Look at the project page and tell me what is there"
        self.public = "A" * 200

    def envelope(self, action):
        return work_direct.encode(
            quote=self.quote,
            summary="Observe the project page privately",
            actions=[action],
        )

    def test_public_observation_plan_accepts_only_key_and_nonsecret_routing(self):
        text = self.envelope({
            "type": "observe",
            "response_id": "obs-123abc",
            "public_key": self.public,
            "target": "browser",
            "url": "https://example.com/project",
        })
        plan = work_direct.parse(text, quote=self.quote)
        self.assertEqual(plan["actions"][0]["target"], "browser")

    def test_screen_observation_rejects_url_and_browser_requires_url(self):
        with self.assertRaises(work_direct.DirectWorkRefused):
            work_direct.parse(
                self.envelope({
                    "type": "observe", "response_id": "obs-a",
                    "public_key": self.public, "target": "screen",
                    "url": "https://example.com",
                }),
                quote=self.quote,
            )
        with self.assertRaises(work_direct.DirectWorkRefused):
            work_direct.parse(
                self.envelope({
                    "type": "observe", "response_id": "obs-b",
                    "public_key": self.public, "target": "browser",
                }),
                quote=self.quote,
            )

    def test_observation_executes_through_sealed_module_and_receipt_has_no_key(self):
        text = self.envelope({
            "type": "observe",
            "response_id": "obs-123abc",
            "public_key": self.public,
            "target": "screen",
            "window": "Chrome",
        })
        with mock.patch.object(
            work_direct, "_ready_session", return_value={"id": "ws"}
        ), mock.patch(
            "aletheia.sealed_observe.run",
            return_value={
                "response_id": "obs-123abc", "state": "READY",
                "sidecar": "exchange/commands/sealed/obs-123abc.json",
                "reused": False,
            },
        ) as run:
            result = work_direct.execute(text, quote=self.quote)

        run.assert_called_once()
        self.assertEqual(result["state"], "EXECUTED")
        serialized = str(result)
        self.assertNotIn(self.public, serialized)
        self.assertIn("sealed screen observation ready", serialized)


if __name__ == "__main__":
    unittest.main()
