import unittest

from aletheia import formfill


class TheYearADegreeWasReceived(unittest.TestCase):
    def test_year_phrasings_ask_for_the_year(self):
        for label in ("Year degree was received (or the year the degree would be received)",
                      "Year your degree was or will be awarded",
                      "Degree year",
                      "Year of completion"):
            self.assertEqual(formfill.match_field({"label": label}), "graduation_year", label)

    def test_the_degree_itself_is_still_the_degree(self):
        self.assertEqual(formfill.match_field({"label": "Highest degree obtained"}), "degree")
        self.assertEqual(formfill.match_field({"label": "Graduation year"}), "graduation_year")


if __name__ == "__main__":
    unittest.main()
