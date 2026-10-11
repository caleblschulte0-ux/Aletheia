"""While Greenhouse is paused by his ruling, name probing skips it and looks at more employers."""
import unittest
from unittest import mock

from aletheia import board_probe, rulings


class PausedProbe(unittest.TestCase):
    def setUp(self):
        self._p = mock.patch.object(rulings, "DEFAULT_PATH", rulings.REPO_RULINGS)
        self._p.start()

    def tearDown(self):
        self._p.stop()

    def test_a_paused_system_is_not_probed(self):
        providers = {c["provider"] for c in board_probe.candidates("Acme Widgets")}
        self.assertNotIn("greenhouse", providers)
        self.assertIn("lever", providers)

    def test_the_batch_is_wider_while_paused(self):
        seen = {}

        def pick(rows, *, learned, ledger, now, limit):
            seen["limit"] = limit
            return []
        with mock.patch.object(board_probe, "pick", pick):
            board_probe.probe(rows=[])
        self.assertEqual(seen["limit"], board_probe.PAUSED_EMPLOYERS_PER_BATCH)

    def test_an_explicit_limit_still_wins(self):
        seen = {}

        def pick(rows, *, learned, ledger, now, limit):
            seen["limit"] = limit
            return []
        with mock.patch.object(board_probe, "pick", pick):
            board_probe.probe(rows=[], limit=2)
        self.assertEqual(seen["limit"], 2)


if __name__ == "__main__":
    unittest.main()
