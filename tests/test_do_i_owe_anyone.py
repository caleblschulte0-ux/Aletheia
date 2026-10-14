""""Do I owe anyone" went to a model and was answered about bank accounts
(2026-10-14), and once everything was paid back she answered as though he
had never mentioned money at all."""
import unittest
from unittest import mock

from aletheia import quick


class DoIOweAnyone(unittest.TestCase):
    def test_an_open_debt(self):
        with mock.patch.object(quick, "_notes", return_value=[{"text": "i owe sarah 20 dollars"}]):
            self.assertEqual(quick.answer("do i owe anyone"), "You owe Sarah $20.")
            self.assertEqual(quick.answer("do I still owe anybody anything?"), "You owe Sarah $20.")

    def test_paid_back_says_so(self):
        rows = [{"text": "i paid sarah back"}, {"text": "i owe sarah 20 dollars"}]
        with mock.patch.object(quick, "_notes", return_value=rows):
            self.assertEqual(quick.answer("do i owe anyone"),
                             "Nobody right now - everything you told me about has been paid back.")

    def test_a_lent_drill_is_not_money(self):
        with mock.patch.object(quick, "_notes", return_value=[{"text": "i lent mike my drill"}]):
            self.assertTrue(quick.answer("do i owe anyone").startswith("Nobody, as far as you've told me"))


if __name__ == "__main__":
    unittest.main()
