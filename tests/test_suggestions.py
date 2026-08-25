import json
import tempfile
import unittest
from pathlib import Path

from aletheia.fleet import load_fleet
from aletheia.suggestions import validate_file


def _write(tmp: Path, name: str, payload: dict) -> Path:
    p = tmp / name
    p.write_text(json.dumps(payload), encoding="utf-8")
    return p


def _valid(sid="20260825-example"):
    return {
        "id": sid,
        "filed": "2026-08-25T12:00:00Z",
        "by": "chatgpt",
        "repo": "fleet",
        "kind": "idea",
        "title": "An example",
        "detail": "Plain prose about what could be better.",
    }


class TestValidateFile(unittest.TestCase):
    def setUp(self):
        self.fleet = load_fleet()
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_valid_suggestion_passes(self):
        p = _write(self.dir, "20260825-example.json", _valid())
        self.assertEqual(validate_file(p, self.fleet), [])

    def test_code_payload_refused(self):
        s = _valid()
        s["patch"] = "--- a/bot.py\n+++ b/bot.py"
        p = _write(self.dir, "20260825-example.json", s)
        problems = validate_file(p, self.fleet)
        self.assertTrue(any("forbidden" in x for x in problems))

    def test_id_must_match_filename(self):
        p = _write(self.dir, "wrong-name.json", _valid())
        problems = validate_file(p, self.fleet)
        self.assertTrue(any("must match filename" in x for x in problems))

    def test_unknown_repo_refused(self):
        s = _valid()
        s["repo"] = "not_a_repo"
        p = _write(self.dir, "20260825-example.json", s)
        problems = validate_file(p, self.fleet)
        self.assertTrue(any("not 'fleet'" in x for x in problems))

    def test_only_chatgpt_files_here(self):
        s = _valid()
        s["by"] = "claude"
        p = _write(self.dir, "20260825-example.json", s)
        problems = validate_file(p, self.fleet)
        self.assertTrue(any("chatgpt" in x for x in problems))


if __name__ == "__main__":
    unittest.main()
