import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import stateio


class TestStateIO(unittest.TestCase):
    def test_safe_id_refuses_paths(self):
        for value in ("../secret", "a/b", "", "UPPER"):
            with self.assertRaises(ValueError):
                stateio.safe_id(value)

    def test_private_root_can_be_moved_outside_repo(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"ALETHEIA_PRIVATE_STATE": tmp}):
            self.assertEqual(stateio.private_dir("calendar"), Path(tmp) / "calendar")

    def test_atomic_write_round_trips(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "x.json"
            stateio.write_json_atomic(path, {"hello": "world"})
            self.assertEqual(stateio.read_json(path), {"hello": "world"})

    def test_exclusive_create_is_idempotency_primitive(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "receipt.json"
            stateio.create_json_exclusive(path, {"id": 1})
            with self.assertRaises(FileExistsError):
                stateio.create_json_exclusive(path, {"id": 2})
            self.assertEqual(json.loads(path.read_text())["id"], 1)

    def test_oversized_state_refused(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(stateio, "MAX_JSON_BYTES", 32):
            with self.assertRaises(ValueError):
                stateio.write_json_atomic(Path(tmp) / "big.json", {"x": "a" * 100})


if __name__ == "__main__":
    unittest.main()
