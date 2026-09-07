"""Model prose reaches a ROOM, and it is written for a screen.

Found by talking to her. "how much time do I spend on my computer" came
back with an asterisk pair around a word ("What I *can* do"), a
parenthesised identifier ("computer.observe/control"), and a Windows menu
path. Every character of it was true. Read out loud, the emphasis is
silence, the identifier is gibberish, and neither is something he can act
on — §145 exactly.

The other half is `recollection.on_date`: "what did I ask you to do
yesterday" answered "Want me to check the journal directly for entries
from 2026-09-05?" — offering to read a file she can read. The journal did
not travel with the question because `_PAST` matches "did you" and he
said "did I ask you".
"""
import datetime as dt
import unittest
from unittest import mock

from aletheia import quick, recollection, speech


class NothingSpokenIsMarkdown(unittest.TestCase):
    def test_emphasis_is_silence_out_loud(self):
        self.assertEqual(speech.unmarkdown("What I *can* do"), "What I can do")
        self.assertEqual(speech.unmarkdown("**Yes** — it works"), "Yes — it works")
        self.assertEqual(speech.unmarkdown("run `pytest -q` now"), "run pytest -q now")

    def test_a_name_with_underscores_is_a_name_not_emphasis(self):
        # `_this_` is emphasis and `file_path` is a thing he asked about.
        # Getting it wrong renames the thing.
        self.assertEqual(speech.unmarkdown("open file_path and read_me"),
                         "open file_path and read_me")

    def test_a_link_keeps_its_words_and_loses_its_url(self):
        self.assertEqual(speech.unmarkdown("see [the docs](https://x.co/y)"),
                         "see the docs")

    def test_a_heading_and_a_bullet_are_layout(self):
        self.assertEqual(speech.unmarkdown("## Today\n- one\n- two"),
                         "Today\none\ntwo")


class NoIdentifierSurvivesTheDoor(unittest.TestCase):
    def test_a_capability_id_becomes_what_it_is(self):
        said = speech.say_capabilities("I can (computer.observe) for you")
        self.assertNotIn("computer.observe", said)
        self.assertIn("desktop", said.lower())

    def test_the_models_slash_shorthand_is_expanded_not_mangled(self):
        said = speech.say_capabilities("look live (computer.observe/control)")
        self.assertNotIn("/", said)
        self.assertIn(" or ", said)

    def test_something_the_registry_does_not_know_is_left_alone(self):
        # example.com and converse.py are the same shape as a capability
        # id. Replacing what she cannot look up is inventing.
        said = speech.say_capabilities("see example.com or converse.py")
        self.assertEqual(said, "see example.com or converse.py")

    def test_a_description_is_one_clause_even_when_the_colon_is_tight(self):
        # "Operate the Windows PC: observe, open apps, click, type" — the
        # split wanted whitespace before the colon, so the whole list came
        # out inside a parenthesis, out loud.
        said = speech._capability_english("computer.control")
        self.assertNotIn(":", said)
        self.assertLess(len(said.split()), 8, said)

    def test_spoken_prose_is_all_of_it_in_one_place(self):
        said = speech.spoken_prose(
            "What I *can* do is (computer.observe) — approval intent-7aed1b5dcd")
        self.assertNotIn("*", said)
        self.assertNotIn("computer.observe", said)
        self.assertNotIn("intent-7aed1b5dcd", said)


class CountPhraseSaysThePlural(unittest.TestCase):
    def test_it_stopped_writing_matchs(self):
        # Half of one journal line was written through count_phrase and
        # half was "match(es)", and she read the whole thing out.
        self.assertEqual(speech.count_phrase(3, "match"), "3 matches")
        self.assertEqual(speech.count_phrase(1, "match"), "1 match")
        self.assertEqual(speech.count_phrase(2, "box"), "2 boxes")
        self.assertEqual(speech.count_phrase(3, "company"), "3 companies")

    def test_it_did_not_break_the_ordinary_ones(self):
        self.assertEqual(speech.count_phrase(2, "board"), "2 boards")
        self.assertEqual(speech.count_phrase(2, "day"), "2 days")
        self.assertEqual(speech.count_phrase(2, "gap task"), "2 gap tasks")
        self.assertEqual(speech.count_phrase(0, "step"), "0 steps")

    def test_an_explicit_plural_still_wins(self):
        self.assertEqual(speech.count_phrase(2, "person", "people"), "2 people")


class SheReadsTheJournalInsteadOfOfferingTo(unittest.TestCase):
    def test_what_he_asked_carries_the_journal(self):
        # "did I ask you" is not "did you", and matching nothing meant no
        # journal travelled with the question at all.
        self.assertTrue(recollection._PAST.search("what did I ask you to do yesterday"))

    def test_yesterday_is_that_day_not_a_wider_window(self):
        got = recollection.for_question("what did you do yesterday")
        tz_now = dt.datetime.now()
        self.assertIn("her day on", got["asked_about"])
        self.assertIn("date", got)
        self.assertNotEqual(got["date"], tz_now.strftime("%Y-%m-%d"))

    def test_the_note_forbids_offering_to_go_and_look(self):
        got = recollection.for_question("what did you do yesterday")
        self.assertIn("this IS the look", got["note"])

    def test_a_nonsense_date_is_not_a_crash_and_not_a_guess(self):
        self.assertEqual(recollection.on_date("not a date"), [])
        self.assertEqual(recollection.on_date(""), [])
        # Older than the lookback: refused rather than reading a year of
        # journal files to answer a spoken question.
        self.assertEqual(recollection.on_date("2019-01-01"), [])

    def test_today_and_yesterday_cannot_report_the_same_evening(self):
        asked = []

        def on_date(date, **k):
            asked.append(date)
            return []

        with mock.patch.object(recollection, "on_date", on_date):
            quick.answer("what did you do today")
            quick.answer("what did you do yesterday")
        self.assertEqual(len(asked), 2)
        self.assertNotEqual(asked[0], asked[1])


if __name__ == "__main__":
    unittest.main()
