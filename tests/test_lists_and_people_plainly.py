"""Tasks with a day, the grocery list, contacts and drafts, asked plainly.

Found 2026-10-07 in the sandbox with every model off: "add pay rent to my
tasks for friday" was refused as SPENDING, and "what's on the grocery list",
"who's in my contacts" and "what drafts do I have" each waited on a model.
"""
import unittest

from aletheia import quick, voice


class Plainly(unittest.TestCase):
    def test_a_task_with_a_day_is_a_task_not_a_payment(self):
        cmd = voice._interpret("add pay rent to my tasks for friday")["command"]
        self.assertEqual((cmd["kind"], cmd["description"]), ("task_new", "pay rent"))
        self.assertIn("deadline", cmd)
        self.assertNotIn("deadline", voice._interpret("add call the bank to my tasks")["command"])

    def test_the_grocery_list_is_the_shopping_list(self):
        self.assertEqual(voice._interpret("what's on the grocery list")["command"], {"kind": "shopping_list"})
        self.assertIn("shopping list is ready", voice._interpret("start a grocery list")["say"])

    def test_contacts_and_drafts(self):
        for said in ("who's in my contacts", "show me my contacts", "who do i have saved"):
            with self.subTest(said=said):
                self.assertEqual(voice._interpret(said)["command"], {"kind": "contacts"})
        self.assertEqual(quick.match("what drafts do i have")[0], "drafts")


if __name__ == "__main__":
    unittest.main()


class SumsInWords(unittest.TestCase):
    def test_precedence_is_ordinary(self):
        self.assertEqual(quick.answer("what's 2 plus 2 times 3"), "8.")
        self.assertEqual(quick.answer("what's 15 times 12 plus 4"), "184.")
        self.assertEqual(quick.answer("what's 10 divided by 0 plus 1"), "You can't divide by zero.")
        self.assertEqual(quick.answer("what's 1000 divided by 7 times 2"), "About 285.7143.")

    def test_nothing_but_arithmetic_is_evaluated(self):
        self.assertIsNone(quick._arith("what's __import__('os') plus 1"))

    def test_the_rest(self):
        self.assertEqual(quick.answer("is 97 a prime number"), "Yes, 97 is prime.")
        self.assertEqual(quick.answer("is 91 prime"), "No - 91 is 7 times 13.")
        self.assertEqual(quick.answer("what's the average of 4 8 and 12"), "8.")
        self.assertEqual(quick.answer("round 3.14159 to 2 places"), "3.14.")
        self.assertEqual(quick.answer("how many minutes in 3 hours"), "180 minutes.")
        self.assertEqual(quick.answer("how many days in a year"), "365 days, 366 in a leap year.")
        self.assertEqual(quick.answer("what is 3/4 as a percent"), "75 percent.")


class AboutHer(unittest.TestCase):
    def test_questions_about_her_have_her_answers(self):
        self.assertIn("AI", quick.answer("are you a robot"))
        self.assertTrue(quick.answer("who made you").startswith("You did"))
        self.assertTrue(quick.answer("how old are you"))
        self.assertEqual(quick.match("what model are you")[0], "slow")

    def test_do_you_remember_me_is_not_a_lookup_of_me(self):
        from unittest import mock
        with mock.patch.object(quick, "_about_him", return_value="Your name is Caleb."):
            self.assertEqual(quick.answer("do you remember me"), "Yes. Your name is Caleb.")
        self.assertEqual(quick.match("do you remember the plumber")[0], "recall")


class TheBrowserSaidPlainly(unittest.TestCase):
    def test_youtube_search_opens_youtubes_results(self):
        from aletheia import open_it
        for said in ("search youtube for cat videos", "look up cat videos on youtube"):
            with self.subTest(said=said):
                self.assertEqual(voice._interpret(said)["command"],
                                 {"kind": "open_page", "which": "youtube search cat videos"})
        opened = []
        from unittest import mock
        with mock.patch.object(open_it.journal, "append"):
            said = open_it.open_for("youtube search cat videos", opener=lambda u: opened.append(u) or True)["said"]
            plain = open_it.open_for("youtube", opener=lambda u: True)["said"]
        self.assertEqual(opened, ["https://www.youtube.com/results?search_query=cat+videos"])
        self.assertEqual(said, "Opened YouTube results for cat videos in your browser.")
        self.assertEqual(plain, "Opened YouTube in your browser.")

    def test_no_browser_is_said_in_english(self):
        from unittest import mock
        from aletheia import browse, research
        with mock.patch.object(browse, "available", return_value=(False, "playwright is not installed (pip install playwright)")):
            with self.assertRaises(research.ResearchError) as caught:
                research.run("the weather in chicago")
        said = str(caught.exception)
        self.assertTrue(said.startswith("I can't read web pages"), said)
        self.assertNotIn("pip", said)
        self.assertNotIn("she ", said)
