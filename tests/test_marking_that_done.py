""""Mark that done" when "that" is nothing, or one of several.

With nothing open (2026-10-12, every model off) "mark it done" was queued
for a model "on my list" until one was back, and "done with all of them"
became an approval to mark a task called "all of them" done. With two
open, "mark that done" became an approval for a task called "that". None
of it needs a model: the list is on disk, and it is either empty or a
short question.
"""
import unittest
from unittest import mock

from aletheia import voice


def task(tid, description, status="QUEUED"):
    return {"id": tid, "description": description, "status": status}


def turn(said, answered=""):
    return [{"he_asked": said, "she_answered": answered}]


TWO = [task("t1", "buy stamps"), task("t2", "wash the car")]


def said_with(rows, sentence, turns=()):
    with mock.patch("aletheia.tasks.all_tasks", lambda: rows), \
            mock.patch("aletheia.converse.recent", return_value=list(turns)):
        return voice.interpret(f"thea {sentence}")


class NothingOpen(unittest.TestCase):
    def test_a_pronoun_on_an_empty_list_says_so(self):
        for sentence in ("mark it done", "mark that done", "mark that as complete",
                         "done with all of them", "mark them all done", "they're all done",
                         "mark everything done"):
            with self.subTest(sentence=sentence):
                got = said_with([], sentence)
                self.assertIsNone(got["command"], sentence)
                self.assertEqual(got["say"], "There's nothing open on your list to mark done.")

    def test_a_list_that_cannot_be_read_is_not_called_empty(self):
        def broken():
            raise OSError("unreadable")
        with mock.patch("aletheia.tasks.all_tasks", broken), \
                mock.patch("aletheia.converse.recent", return_value=[]):
            got = voice.interpret("thea mark it done")
        self.assertNotIn("nothing open", str(got.get("say") or ""))


class SeveralOpen(unittest.TestCase):
    def test_mark_that_done_asks_which(self):
        got = said_with(TWO, "mark that done")
        self.assertIsNone(got["command"])
        self.assertEqual(got["say"], "Which one — buy stamps or wash the car?")

    def test_the_answer_names_one(self):
        got = said_with(TWO, "wash the car", turn("mark that done", "Which one — buy stamps or wash the car?"))
        self.assertEqual(got["command"], {"kind": "task_done", "which": "wash the car"})

    def test_the_answer_counts_in_the_list_she_read(self):
        got = said_with(TWO, "the first one", turn("mark it done", "Which one — buy stamps or wash the car?"))
        self.assertEqual(got["command"], {"kind": "task_done", "which": "buy stamps"})

    def test_all_of_them_is_still_not_one_sentences_to_undo(self):
        got = said_with(TWO, "done with all of them")
        self.assertIsNone(got["command"])
        self.assertIn("whole task list", got["say"])

    def test_one_open_still_just_does_it(self):
        got = said_with(TWO[:1], "mark that done")
        self.assertEqual(got["command"], {"kind": "task_done", "which": "buy stamps"})


if __name__ == "__main__":
    unittest.main()
