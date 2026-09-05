from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from staging.jarvis_gap.browser_transfers import propose_download, propose_upload
from staging.jarvis_gap.computer_extensions import propose
from staging.jarvis_gap.multimodal_router import ReasoningRequest, require_available, route


class ComputerExtensionTests(unittest.TestCase):
    def test_semantic_scroll(self):
        proposal = propose([
            {"action": "scroll", "window": {"title": "Settings"},
             "direction": "down", "units": 3}
        ])
        self.assertFalse(proposal.as_dict()["execution_authority"])
        self.assertEqual(proposal.highest_risk, "low")

    def test_coordinates_refused(self):
        with self.assertRaisesRegex(ValueError, "coordinates"):
            propose([
                {"action": "drag_drop", "window": {"title": "x"},
                 "source": {"x": "1"}, "destination": {"best_match": "b"}}
            ])

    def test_high_risk_propagates(self):
        proposal = propose([
            {"action": "hotkey", "window": {"title": "x"}, "keys": ["CTRL", "L"]},
            {"action": "drag_drop", "window": {"title": "x"},
             "source": {"best_match": "a"}, "destination": {"best_match": "b"}},
        ])
        self.assertEqual(proposal.highest_risk, "high")

    def test_unknown_hotkey_refused(self):
        with self.assertRaises(ValueError):
            propose([{"action": "hotkey", "window": {"title": "x"}, "keys": ["F13"]}])

    def test_clipboard_metadata_does_not_echo_text(self):
        metadata = propose([{"action": "clipboard_write", "text": "secret"}]).as_dict()
        safe = {key: value for key, value in metadata.items() if key != "steps"}
        self.assertNotIn("secret", repr(safe))


class BrowserTransferTests(unittest.TestCase):
    def test_upload_binds_hash(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "a.txt"
            path.write_text("hello", encoding="utf-8")
            proposal = propose_upload(path, allowed_roots=[directory])
            self.assertEqual(proposal.size_bytes, 5)
            self.assertEqual(len(proposal.sha256), 64)
            self.assertFalse(proposal.as_dict()["execution_authority"])

    def test_upload_outside_root_refused(self):
        with tempfile.TemporaryDirectory() as source, tempfile.TemporaryDirectory() as allowed:
            path = Path(source) / "x"
            path.write_text("x", encoding="utf-8")
            with self.assertRaises(PermissionError):
                propose_upload(path, allowed_roots=[allowed])

    def test_download_overwrite_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / "x.txt").write_text("exists", encoding="utf-8")
            with self.assertRaises(FileExistsError):
                propose_download(
                    directory, "x.txt", allowed_roots=[directory], max_bytes=10,
                    expected_origin="https://example.com",
                )

    def test_download_traversal_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                propose_download(
                    directory, "../x.txt", allowed_roots=[directory], max_bytes=10,
                    expected_origin="https://example.com",
                )


class MultimodalRouteTests(unittest.TestCase):
    def test_image_never_silently_downgrades_to_text(self):
        decision = route(ReasoningRequest("what is this", has_image=True))
        self.assertEqual(decision.primary_role, "vision")
        with self.assertRaises(RuntimeError):
            require_available(decision, {"fast", "deep"})

    def test_deep_text(self):
        self.assertEqual(
            route(ReasoningRequest("reason", depth="deep")).primary_role,
            "deep",
        )

    def test_safety_critical_answer_is_not_authoritative(self):
        decision = route(ReasoningRequest("inspect", safety_critical=True))
        self.assertFalse(decision.returned_answer_may_be_authoritative)


if __name__ == "__main__":
    unittest.main()
