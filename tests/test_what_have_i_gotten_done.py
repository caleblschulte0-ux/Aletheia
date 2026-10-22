""""What have I gotten done this week" went to a model (2026-10-22)."""
import unittest
from unittest import mock

from aletheia import quick


class GottenDone(unittest.TestCase):
    def test_the_phrasings_read_the_done_list(self):
        for said in ("what have I gotten done this week", "what did I cross off today", "what all did I get done yesterday"):
            with self.subTest(said=said), mock.patch.object(quick, "_tasks_done", return_value="DONE LIST") as done:
                self.assertEqual(quick.answer(said), "DONE LIST")
                done.assert_called_once()


if __name__ == "__main__":
    unittest.main()
