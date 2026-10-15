""""How much is my car insurance a year" with "my car insurance is 120 a
month" kept read back the monthly figure; and the bills list said "your phone
bill ... and car insurance ..." (2026-10-15, every model off)."""
import unittest
from unittest import mock

from aletheia import quick


def ask(question, notes):
    with mock.patch.object(quick, "_notes", return_value=[{"text": n} for n in notes]):
        return quick.answer(question)


class ABillAYear(unittest.TestCase):
    def test_monthly_asked_by_the_year(self):
        self.assertEqual(ask("how much is my car insurance a year", ["my car insurance is 120 a month"]),
                         "About $1,440 a year - you told me your car insurance is 120 a month.")

    def test_yearly_asked_by_the_month(self):
        self.assertEqual(ask("how much does my gym membership cost per month", ["my gym membership is 300 a year"]),
                         "About $25 a month - you told me your gym membership is 300 a year.")

    def test_the_same_period_is_read_back(self):
        self.assertEqual(ask("how much is my phone bill", ["my phone bill is 85 a month"]),
                         "You told me: your phone bill is 85 a month.")
        self.assertEqual(ask("how much is my electric bill usually", ["my electric bill was 120 dollars"]),
                         "You told me: your electric bill was 120 dollars.")

    def test_every_bill_is_his(self):
        said = ask("how much do i spend on bills a month", ["my phone bill is 85 a month", "my car insurance is 120 a month"])
        self.assertIn("your car insurance is 120 a month", said)
        self.assertIn("your phone bill is 85 a month", said)


if __name__ == "__main__":
    unittest.main()
