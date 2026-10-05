"""Twenty-fourth sandbox batch, 2026-10-05: files, drafts and notes.

    > read me the groceries file      a search result naming the file
    > delete the groceries file       [3.5s] the planner, and an approval for a
                                      routine, kept-first delete
    > undo (after writing a file)     "Nothing to undo: I haven't done
                                      anything on my own" - a question turn
                                      in between stopped the look-back
    > what drafts do I have           [5.1s] a model
    > search my notes for car         [3.5s] a model: "I don't have anything
                                      remembered about 'car'" - there was a note
    > how many notes do I have        [3.5s] a model
"""
import unittest
from unittest import mock

from aletheia import intercom, quick, voice, workspace

LISTING = [{"path": "groceries.txt", "bytes": 14}, {"path": "notes/plan.md", "bytes": 3}]


class AFileByItsName(unittest.TestCase):
    def test_read_and_delete_find_the_one_file(self):
        with mock.patch("aletheia.workspace.listing", return_value=LISTING):
            self.assertEqual(voice.interpret("read me the groceries file")["command"], {"kind": "file_read", "path": "groceries.txt"})
            self.assertEqual(voice.interpret("what is in the plan note")["command"], {"kind": "file_read", "path": "notes/plan.md"})
            self.assertEqual(voice.interpret("delete the groceries file")["command"],
                             {"kind": "file_delete", "path": "groceries.txt", "why": "you asked"})
            missing = voice.interpret("delete the lease file")
        self.assertIsNone(missing["command"])
        self.assertEqual(missing["say"], "I don't have a file called lease in my workspace.")


class UndoLooksPastAQuestion(unittest.TestCase):
    def test_a_question_between_does_not_stop_the_look_back(self):
        turns = [{"he_asked": "write a file called groceries with milk and eggs", "she_answered": "Wrote groceries.txt in my workspace.", "how": "stores"},
                 {"he_asked": "what's the last thing you wrote", "she_answered": "The last thing I wrote was groceries.txt: milk and eggs.", "how": "stores"},
                 {"he_asked": "delete the groceries file", "she_answered": "Here's what I'd do: Delete your groceries file. Say approve and I'll do it.", "how": "model"}]
        with mock.patch("aletheia.converse.recent", return_value=turns), \
             mock.patch.object(intercom, "_reverse_his_ask", return_value="Undone: removed groceries.txt; a copy is kept if you want it back.") as reversed_:
            said = intercom._undo_his_last_ask()
        self.assertEqual(said, "Undone: removed groceries.txt; a copy is kept if you want it back.")
        self.assertEqual(reversed_.call_args[0][0], "file_write")

    def test_a_delete_is_undone_from_her_own_receipt(self):
        turns = [{"he_asked": "delete the groceries file", "she_answered": "Deleted groceries.txt. I kept a copy, so 'undo' brings it back.", "how": "stores"}]
        with mock.patch("aletheia.converse.recent", return_value=turns), \
             mock.patch.object(intercom, "_reverse_his_ask", return_value="Undone: put groceries.txt back.") as reversed_:
            self.assertEqual(intercom._undo_his_last_ask(), "Undone: put groceries.txt back.")
        self.assertEqual(reversed_.call_args[0], ("file_delete", {"path": "groceries.txt"}))

    def test_a_deleted_file_comes_back(self):
        workspace.write("undo-me.txt", "hello", why="test")
        workspace.remove("undo-me.txt", why="test")
        said = intercom._reverse_his_ask("file_delete", {"path": "undo-me.txt"})
        self.assertEqual(said, "Undone: put undo-me.txt back.")
        self.assertEqual(workspace.read("undo-me.txt")["text"].strip(), "hello")
        workspace.remove("undo-me.txt", why="test cleanup")


class NotesAndDrafts(unittest.TestCase):
    def test_the_sentences_reach_the_stores(self):
        self.assertEqual(quick.match("what drafts do i have"), ("drafts", ""))
        self.assertEqual(quick.match("search my notes for car"), ("notes_search", "car"))
        self.assertEqual(quick.match("is there anything about the car in my notes"), ("notes_search", "car"))
        self.assertEqual(quick.match("how many notes do i have"), ("notes_count", ""))

    def test_a_note_is_found_and_counted(self):
        with mock.patch("aletheia.quick._notes", return_value=[{"text": "the car is due for service in november"}]), \
             mock.patch("aletheia.memory.everything", return_value={}):
            self.assertEqual(quick.answer("search my notes for car"), "You told me: the car is due for service in november.")
            self.assertEqual(quick.answer("how many notes do i have"), "1 note. The newest: the car is due for service in november.")
        with mock.patch("aletheia.quick._notes", return_value=[]):
            self.assertTrue(quick.answer("how many notes do i have").startswith("No notes yet."))


if __name__ == "__main__":
    unittest.main()
