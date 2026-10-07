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
