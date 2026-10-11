"""Seed names are probed like any employer's; a bad file seeds nothing."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import board_probe, stateio


class Seeds(unittest.TestCase):
    def test_the_shipped_seed_file_has_names_and_no_banned_ones(self):
        names = [r["name"].casefold() for r in board_probe.seed_rows()]
        self.assertGreater(len(names), 50)
        self.assertNotIn("enova", names)
        self.assertNotIn("linkedin", names)
        self.assertNotIn("indeed", names)

    def test_a_missing_file_seeds_nothing(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(stateio, "REPO_ROOT", Path(d)):
            self.assertEqual(board_probe.seed_rows(), [])

    def test_a_malformed_file_seeds_nothing(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(stateio, "REPO_ROOT", Path(d)):
            (Path(d) / "config").mkdir()
            (Path(d) / "config" / "employer_seeds.json").write_text("{nope", encoding="utf-8")
            self.assertEqual(board_probe.seed_rows(), [])

    def test_seeds_come_first_in_the_default_rows(self):
        seen = {}

        def pick(rows, *, learned, ledger, now, limit):
            seen["first"] = rows[0]["name"] if rows else None
            return []
        with mock.patch.object(board_probe, "pick", pick), \
                mock.patch.object(board_probe, "seed_rows", lambda: [{"name": "Seeded Co"}]):
            board_probe.probe()
        self.assertEqual(seen["first"], "Seeded Co")


if __name__ == "__main__":
    unittest.main()
