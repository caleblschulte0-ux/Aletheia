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


class ThatAfterAQuestion(unittest.TestCase):
    """"Remind me at 6", "what are my reminders for today", "actually make
    that 7" - the question in between is not what "that" points at."""

    def _thread(self, *asks):
        from aletheia import converse
        return mock.patch.object(converse, "recent", return_value=[{"he_asked": a, "she_answered": ""} for a in asks])

    def test_the_reminder_before_the_question_moves(self):
        from aletheia import voice
        with self._thread("remind me to water the plants at 6 pm", "what are my reminders for today"):
            got = voice._interpret("actually make that 7 pm")["command"]
        self.assertEqual((got["kind"], got["replaces"]), ("remind_at", "water the plants"))
        self.assertIn("T19:00", got["at"])

    def test_a_newer_writer_is_what_that_means(self):
        from aletheia import voice
        with self._thread("remind me to water the plants at 6 pm", "add milk to my shopping list"):
            self.assertEqual(voice._recent_reminder_ask(), {})


class WhatHeJustAsked(unittest.TestCase):
    def test_his_words_back(self):
        from aletheia import converse
        thread = [{"you": "thea what are my reminders for today", "her": "None."},
                  {"you": "what did i just ask you", "her": "..."}]
        with mock.patch.object(converse, "_thread", return_value=thread):
            self.assertEqual(quick.answer("what did i just ask you"),
                             "You asked: “what are my reminders for today.”")


class DueOnADay(unittest.TestCase):
    def test_what_is_due_friday(self):
        self.assertEqual(quick.match("what's due friday"), ("due", "friday"))
        self.assertEqual(quick.match("anything due on monday"), ("due", "monday"))


class AMovedDeadlineIsASentence(unittest.TestCase):
    def test_the_journal_names_the_task_and_the_day(self):
        from aletheia import journal, tasks
        lines = []
        with mock.patch.object(tasks, "load", return_value={"id": "t1", "description": "call the plumber",
                                                             "status": "PENDING"}), \
                mock.patch.object(tasks, "save"), \
                mock.patch.object(journal, "append", side_effect=lambda *a, **k: lines.append(a)):
            tasks.set_deadline("t1", "2026-10-09")
        self.assertEqual(lines[0][2], "Moved call the plumber to Friday 9 October")
