"""A radio list of countries whose heading was not read still gets his country.

Live 2026-10-13 a Recruitee form held twice on a radio group the funnel
could only call "united states": the options were read, the question was
not, so the group took its first option as its label and matched nothing.
"""
import unittest

from aletheia import formfill


def _radios(options, question=""):
    return [{"selector": f"#c{i}", "label": o, "option": o, "group": "where",
             "question": question, "type": "radio", "required": True,
             "name": "where", "id": f"c{i}", "tag": "input", "value": ""}
            for i, o in enumerate(options)]


class ACountryListWithNoHeading(unittest.TestCase):
    def _pick(self, fields, known):
        _rest, groups = formfill._group_choices(fields)
        return formfill._from_profile(groups[0], known)

    def test_his_country_is_chosen(self):
        got = self._pick(_radios(["United States", "Canada", "Mexico"]),
                         {"country": "USA"})
        self.assertEqual(got["label"], "United States")

    def test_a_list_without_his_country_is_left_to_him(self):
        self.assertIsNone(self._pick(_radios(["Germany", "France", "Spain"]),
                                     {"country": "United States"}))

    def test_a_yes_no_pair_is_not_read_as_countries(self):
        self.assertIsNone(self._pick(_radios(["Yes", "No"]),
                                     {"country": "United States"}))

    def test_a_question_that_was_read_is_matched_as_before(self):
        got = self._pick(_radios(["Yes", "No"], question="Do you need a visa?"),
                         {"country": "United States"})
        self.assertIsNone(got)


if __name__ == "__main__":
    unittest.main()
