import unittest
from unittest import mock

from aletheia import hunt_funnel, jobs


class BoardsBySystem(unittest.TestCase):
    def test_counts_only_never_names(self):
        rows = [{"provider": "lever", "token": "acme", "company": "Acme"},
                {"provider": "lever", "token": "b", "company": "B"},
                {"provider": "ashby", "token": "c", "company": "C"}]
        with mock.patch.object(jobs, "_learned_boards", return_value=rows):
            got = hunt_funnel.boards_by_system()
        self.assertEqual(got, {"ashby": 1, "lever": 2})
        self.assertNotIn("Acme", repr(got))

    def test_unreadable_is_empty_not_an_error(self):
        with mock.patch.object(jobs, "_learned_boards", side_effect=OSError):
            self.assertEqual(hunt_funnel.boards_by_system(), {})


if __name__ == "__main__":
    unittest.main()
