""""Define serendipity" went to the planner (2026-10-07). A dictionary
answers from a dictionary, and a word it lacks is said to be unknown."""
import unittest
from unittest import mock

from aletheia import dictionary, quick

ENTRY = [{"word": "serendipity", "meanings": [
    {"partOfSpeech": "noun", "definitions": [
        {"definition": "An unsought, unintended, and/or unexpected discovery made by happy accident."},
        {"definition": "The faculty of making such discoveries."}]},
]}]


class WhatAWordMeans(unittest.TestCase):
    def test_the_sentences_reach_the_dictionary(self):
        self.assertEqual(quick.match("define serendipity"), ("define", "serendipity"))
        self.assertEqual(quick.match("what does ubiquitous mean"), ("define", "ubiquitous"))
        self.assertEqual(quick.match("what's the definition of hubris"), ("define", "hubris"))

    def test_what_she_just_said_is_not_a_word_to_look_up(self):
        for said in ("what does that mean", "what does it mean", "what's the meaning of life"):
            self.assertNotEqual((quick.match(said) or ("",))[0], "define", said)

    def test_the_dictionarys_own_words(self):
        said = dictionary.spoken("serendipity", fetch=lambda w: ENTRY)
        self.assertTrue(said.startswith("Serendipity: as a noun, an unsought"), said)
        self.assertIn("; or, as a noun, the faculty", said)

    def test_an_unknown_word_is_said_to_be_unknown(self):
        self.assertIn("doesn't have \"blorft\"", dictionary.spoken("blorft", fetch=lambda w: []))

    def test_no_internet_says_so(self):
        def down(word):
            raise OSError("offline")
        self.assertIn("internet may be down", dictionary.spoken("word", fetch=down))

    def test_through_quick(self):
        with mock.patch.object(dictionary, "_fetch", return_value=ENTRY):
            self.assertIn("happy accident", quick.answer("define serendipity"))
