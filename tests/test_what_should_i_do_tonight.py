""""What should I do tonight" went to a model with Dune on his watch list
(2026-10-21, every model off)."""
import unittest
from unittest import mock

from aletheia import quick


class Tonight(unittest.TestCase):
    def lists(self, rows):
        return (mock.patch("aletheia.lists.all_lists", return_value=[{"name": "watch"}] if rows else []),
                mock.patch("aletheia.lists.kind_of", return_value="watch"),
                mock.patch("aletheia.lists.items", return_value=rows))

    def ask(self, said, plans, rows):
        real = quick.answer
        plan = lambda q: plans if q.startswith("what am i doing") else real(q)
        a, b, c = self.lists(rows)
        with a, b, c, mock.patch.object(quick, "answer", side_effect=plan):
            return quick._pick_for_me(quick._tidy(said))

    def test_nothing_planned_picks_off_his_list(self):
        self.assertEqual(self.ask("what should I do tonight", "Nothing on your calendar tonight.", ["Dune"]),
                         "Nothing's planned tonight. From your watch list: Dune.")

    def test_his_plans_come_first(self):
        self.assertEqual(self.ask("anything fun to do this weekend", "Saturday: the walk at 9 am.", ["Dune"]),
                         "Saturday: the walk at 9 am.")

    def test_nothing_to_pick_from_is_a_models(self):
        self.assertIsNone(self.ask("what should we do tonight", "Nothing on your calendar tonight.", []))


if __name__ == "__main__":
    unittest.main()
