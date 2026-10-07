"""Arithmetic he would otherwise wait a minute for, with every model off.

    > what's the square root of 144              -> "I can't think just now"
    > how many ounces in a pound                 -> "I can't think just now"
    > what day of the week was july 4 1990       -> "I can't think just now"
    > how many days between march 1 and april 15 -> "I can't think just now"
    > what time will it be in 3 hours            -> "I can't think just now"

Every one of these is arithmetic. `reckon` answers it, or returns None
and the question goes on - it never guesses.
"""
import datetime as dt
import unittest

from aletheia import quick, reckon


class Sums(unittest.TestCase):
    def test_roots_powers_and_fractions(self):
        self.assertEqual(quick.answer("what's the square root of 144"), "12.")
        self.assertEqual(quick.answer("square root of 2"), "About 1.41.")
        self.assertEqual(quick.answer("12 squared"), "144.")
        self.assertEqual(quick.answer("2 to the power of 10"), "1,024.")
        self.assertEqual(quick.answer("what's half of 250"), "125.")
        self.assertEqual(quick.answer("double 35"), "70.")
        self.assertIn("no real square root", reckon.arith("square root of -4"))


class TheKitchen(unittest.TestCase):
    def test_exact_answers_are_not_hedged(self):
        self.assertEqual(quick.answer("how many ounces in a pound"), "16 ounces.")
        self.assertEqual(quick.answer("how many cups in a quart"), "4 cups.")
        self.assertEqual(quick.answer("how many teaspoons in a tablespoon"), "3 teaspoons.")
        self.assertEqual(quick.answer("how many liters in a gallon"), "About 3.79 liters.")

    def test_an_ounce_beside_a_volume_is_a_fluid_ounce(self):
        self.assertEqual(reckon.kitchen("how many ounces in a cup"), "8 fluid ounces.")

    def test_volume_to_weight_is_refused_not_guessed(self):
        self.assertIn("won't guess", quick.answer("how many grams in a cup"))


class TheCalendar(unittest.TestCase):
    TODAY = dt.date(2026, 10, 7)

    def test_the_weekday_of_a_date(self):
        self.assertEqual(reckon.weekday_of("what day of the week was july 4 1990", self.TODAY),
                         "It was a Wednesday - July 4, 1990.")
        self.assertEqual(reckon.weekday_of("what day is christmas this year", self.TODAY),
                         "It's a Friday - December 25, 2026.")
        self.assertIsNone(reckon.weekday_of("what day is my dentist", self.TODAY))

    def test_days_between_two_dates(self):
        self.assertEqual(reckon.days_between("how many days between march 1 and april 15", self.TODAY),
                         "45 days.")
        self.assertEqual(reckon.days_between("how many weeks from today to christmas", self.TODAY),
                         "11 weeks and 2 days.")

    def test_the_time_later(self):
        now = dt.datetime(2026, 10, 7, 22, 30)
        self.assertEqual(reckon.time_in("what time will it be in 3 hours", now), "1:30 am tomorrow.")
        self.assertEqual(reckon.time_in("what time is it in 45 minutes", now), "11:15 pm.")


class ItNeverStealsAnotherQuestion(unittest.TestCase):
    def test_the_neighbours_keep_their_answers(self):
        self.assertEqual(quick.match("what time is it in tokyo")[0], "time_in")
        self.assertEqual(quick.match("how many days until christmas")[0], "until")
        self.assertEqual(quick.match("convert 5 miles to km")[0], "math")
        self.assertEqual(quick.match("how many applications have you sent")[0], "status_of")

    def test_an_unknown_shape_goes_on(self):
        self.assertIsNone(quick.answer("how many people work at google"))


if __name__ == "__main__":
    unittest.main()
