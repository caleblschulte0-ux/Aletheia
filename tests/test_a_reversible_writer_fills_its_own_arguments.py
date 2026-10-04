"""A reversible writer's required arguments are derived from the task's words.

Found 2026-09-18 in the C4b demonstration (task compose-fills-reversible-args):
the compose route RUNS a reversible-local step without asking, but fill_args
filled only topic- and person-shaped strings. So `task_new` needed an id,
`compose` a path and `remember` a domain, a key and a value, and every one of
those work items was handed to Caleb with "which the work does not say". The
broker was never the bottleneck; the argument filling was.

The rule under every case here is quick.py's: a derivation may only ever
remove a handoff, never invent a value. Each one names a fact somebody can
look at (the words of the ask, his task store), and words that do not settle
an argument leave it missing.
"""
import unittest
from unittest import mock

from aletheia import program_compose, tools


class _Catalog(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = tools.catalog()

    def tool(self, name):
        return self.catalog[name]


class ATaskGetsAnIdFromItsOwnWords(_Catalog):
    def test_the_id_is_the_description_in_kebab(self):
        task = {"title": "add a task to call the plumber about the boiler",
                "detail": "add a task to call the plumber about the boiler"}
        with mock.patch("aletheia.tasks.all_tasks", return_value=[]):
            args, missing = program_compose.fill_args(self.tool("task_new"), task)
        self.assertEqual(missing, [])
        self.assertEqual(args["id"], "add-a-task-to-call-the-plumber-about-the-boiler")
        self.assertIn("plumber", args["description"])

    def test_an_id_already_taken_is_made_unique_against_his_store(self):
        task = {"title": "call the plumber", "detail": "call the plumber"}
        rows = [{"id": "call-the-plumber"}, {"id": "call-the-plumber-2"}]
        with mock.patch("aletheia.tasks.all_tasks", return_value=rows):
            args, missing = program_compose.fill_args(self.tool("task_new"), task)
        self.assertEqual(missing, [])
        self.assertEqual(args["id"], "call-the-plumber-3")

    def test_a_given_description_wins_over_the_task_words(self):
        task = {"title": "something else entirely", "detail": "something else entirely"}
        with mock.patch("aletheia.tasks.all_tasks", return_value=[]):
            args, missing = program_compose.fill_args(self.tool("task_new"), task,
                                                      {"description": "Renew the passport"})
        self.assertEqual(missing, [])
        self.assertEqual(args["id"], "renew-the-passport")
        self.assertEqual(args["description"], "Renew the passport")

    def test_the_id_is_what_tasks_create_accepts(self):
        import re
        long = "write " + " ".join(["word"] * 40)
        with mock.patch("aletheia.tasks.all_tasks", return_value=[]):
            args, _ = program_compose.fill_args(self.tool("task_new"), {"title": long, "detail": long})
        self.assertTrue(re.fullmatch(r"[a-z0-9][a-z0-9-]*", args["id"]), args["id"])
        self.assertLessEqual(len(args["id"]), program_compose._KEBAB_LIMIT)
        self.assertFalse(args["id"].endswith("-"))


class ADocumentGetsAPathInHerWorkspace(_Catalog):
    def test_the_path_is_the_ask_as_a_markdown_file(self):
        task = {"title": "write a note about the landlord meeting",
                "detail": "write a note about the landlord meeting"}
        args, missing = program_compose.fill_args(self.tool("compose"), task)
        self.assertEqual(missing, [])
        self.assertEqual(args["path"], "write-a-note-about-the-landlord-meeting.md")
        self.assertIn("landlord", args["what"])

    def test_a_given_path_is_kept(self):
        task = {"title": "write a note", "detail": "write a note"}
        args, missing = program_compose.fill_args(self.tool("compose"), task, {"path": "notes/today.md"})
        self.assertEqual(missing, [])
        self.assertEqual(args["path"], "notes/today.md")


class AFactIsReadOffTheSentenceNeverGuessed(_Catalog):
    def test_remember_x_is_y_fills_key_value_and_a_people_domain(self):
        task = {"title": "remember that my landlord is Dana Whitfield",
                "detail": "remember that my landlord is Dana Whitfield"}
        args, missing = program_compose.fill_args(self.tool("remember"), task)
        self.assertEqual(missing, [])
        self.assertEqual(args["key"], "landlord")
        self.assertEqual(args["value"], "Dana Whitfield", "his capitals stay")
        self.assertEqual(args["domain"], "people")

    def test_an_organization_and_a_preference_find_their_shelves(self):
        for text, domain in (("remember my gym is Great Life", "organizations"),
                             ("remember that my favorite coffee is a flat white", "preferences")):
            args, missing = program_compose.fill_args(self.tool("remember"),
                                                      {"title": text, "detail": text})
            self.assertEqual(missing, [], text)
            self.assertEqual(args["domain"], domain, text)
        # "my ..." alone is not a shelf: a fact about his week is a note, not his identity.
        text = "remember my lease is up in March"
        args, missing = program_compose.fill_args(self.tool("remember"), {"title": text, "detail": text})
        self.assertEqual(missing, ["domain"])

    def test_a_fact_with_no_shelf_in_its_words_leaves_the_domain_missing(self):
        text = "remember the wifi password is hunter2"
        args, missing = program_compose.fill_args(self.tool("remember"), {"title": text, "detail": text})
        self.assertEqual(args["key"], "wifi_password")
        self.assertEqual(args["value"], "hunter2")
        self.assertEqual(missing, ["domain"], "a wrong shelf is worse than a question")

    def test_words_that_are_not_x_is_y_fill_nothing(self):
        text = "remember to call the dentist"
        args, missing = program_compose.fill_args(self.tool("remember"), {"title": text, "detail": text})
        self.assertEqual(sorted(missing), ["domain", "key", "value"])
        self.assertNotIn("value", args)


class ANoteWasAlreadyFillable(_Catalog):
    def test_note_text_comes_from_the_words(self):
        text = "note that the boiler guy comes Tuesday"
        args, missing = program_compose.fill_args(self.tool("note"), {"title": text, "detail": text})
        self.assertEqual(missing, [])
        self.assertEqual(args["text"], text)


if __name__ == "__main__":
    unittest.main()
