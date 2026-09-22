"""Three sentences through the voice door with every frontier off
(2026-09-22): one took the wrong verb fluently, two took a two-minute
model wait for what a rule settles in a millisecond."""
from __future__ import annotations

import unittest

from aletheia import voice


class AJobSearchIsNotAFileSearchCase(unittest.TestCase):
    def test_find_me_jobs_somewhere_is_a_job_search(self):
        out = voice.interpret("Thea, find me customer success jobs in Denver")
        self.assertEqual(out["command"]["kind"], "jobs")
        self.assertEqual(out["command"]["role"], "customer success")
        self.assertEqual(out["command"]["where"], "Denver")

    def test_the_place_is_optional_and_so_is_the_politeness(self):
        for sentence, role in (("thea look for account manager jobs", "account manager"),
                               ("thea are there any remote project manager openings", "project manager"),
                               ("thea search for some sales positions please", "sales")):
            with self.subTest(sentence=sentence):
                out = voice.interpret(sentence)
                self.assertEqual(out["command"]["kind"], "jobs", sentence)
                self.assertEqual(out["command"]["role"], role)
                self.assertNotIn("where", out["command"])

    def test_a_file_is_still_a_file(self):
        out = voice.interpret("thea find my lease")
        self.assertEqual(out["command"]["kind"], "file_find")
        self.assertTrue(voice._not_a_file("me customer success jobs in denver"))
        self.assertFalse(voice._not_a_file("lease"))


class ANamedNoteIsFoundByNameCase(unittest.TestCase):
    def test_read_me_the_landlord_note_finds_it(self):
        out = voice.interpret("Thea, read me the landlord note")
        self.assertEqual(out["command"]["kind"], "file_find")
        self.assertEqual(out["command"]["query"], "landlord")

    def test_a_filename_still_reads_directly(self):
        out = voice.interpret("thea read draft-note-landlord.txt")
        self.assertEqual(out["command"]["kind"], "file_read")

    def test_read_me_my_tasks_is_not_a_file(self):
        out = voice.interpret("thea read me my tasks")
        self.assertNotEqual(out["command"].get("kind"), "file_find")


class OpenAProgramIsNotOpenAPageCase(unittest.TestCase):
    """"Open chrome" was compiled as "open chrome in the browser" - a page
    named chrome - while she could launch the program all along."""

    def test_a_program_he_names_is_launched(self):
        from aletheia import rule_planner
        kind, args, summary = rule_planner.match("open chrome")
        self.assertEqual(kind, "computer_do")
        self.assertEqual(args["steps"], [{"action": "open_app", "app": "chrome.exe", "arguments": []}])
        self.assertEqual(summary, "Open Chrome")
        kind, args, _ = rule_planner.match("launch the calculator for me")
        self.assertEqual((kind, args["steps"][0]["app"]), ("computer_do", "calc.exe"))

    def test_a_site_is_still_a_page(self):
        from aletheia import rule_planner
        kind, args, _ = rule_planner.match("open hacker news")
        self.assertEqual(kind, "web_task")
        self.assertIn("in the browser", args["goal"])

    def test_no_shell_is_ever_an_app_here(self):
        from aletheia import computer, rule_planner
        for exe in rule_planner.APPS.values():
            self.assertNotIn(exe.split(".")[0], computer.FORBIDDEN_APPS)


class SendAnEmailToSomeoneSayingSomethingCase(unittest.TestCase):
    def test_the_full_sentence_is_a_draft(self):
        out = voice.interpret("Thea, send an email to dana@example.com saying thanks for the call")
        self.assertEqual(out["command"]["kind"], "email_draft")
        self.assertEqual(out["command"]["to"], "dana@example.com")
        self.assertEqual(out["command"]["body"], "thanks for the call")

    def test_the_short_form_still_works(self):
        out = voice.interpret("thea email dana that the report is ready")
        self.assertEqual(out["command"]["kind"], "email_draft")
        self.assertEqual(out["command"]["to"], "dana")

    def test_a_text_is_still_a_text(self):
        out = voice.interpret("thea text dana saying running late")
        self.assertEqual(out["command"]["kind"], "message_send")


if __name__ == "__main__":
    unittest.main()
