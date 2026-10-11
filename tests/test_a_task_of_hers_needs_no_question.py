"""state/tasks/compose-fills-reversible-args (2026-09-18): a mission step that makes a task of hers
needed an id and a description, and both went to him as "which the work does not say". A task of
hers is hers to rename or drop; its name and purpose are the mission task's own words."""
import unittest

from aletheia import program_compose as pc, tools


class ATaskOfHersNeedsNoQuestion(unittest.TestCase):
    def setUp(self):
        self.tool = tools.catalog()["task_new"]
        self.task = {"title": "Track replies from the shortlisted employers", "detail": "one row each"}

    def test_its_name_and_purpose_are_the_tasks_own_words(self):
        got = pc.default_args(self.tool, self.task, ["id", "description"])
        self.assertEqual(got["id"], pc.new_id(self.task["title"]))
        self.assertEqual(got["description"], "Track replies from the shortlisted employers - one row each")

    def test_the_same_task_names_the_same_record_on_a_retry(self):
        self.assertEqual(pc.default_args(self.tool, self.task, ["id"]),
                         pc.default_args(self.tool, dict(self.task), ["id"]))

    def test_what_she_would_have_to_invent_stays_missing(self):
        self.assertNotIn("deadline", pc.default_args(self.tool, self.task, ["deadline"]))
        note = tools.catalog()["note"]
        self.assertEqual(pc.default_args(note, self.task, ["text"]), {})
