"""What the deterministic layer hears when it hears too much.

    "why did you add milk to the list"  -> ADDED "why did you add milk"
    "task list"                         -> created a task called "list"
    "note that Dana called"             -> noted "that dana called"

The first two are the same defect as `how long (.+)` being a journey: a
pattern loose enough to swallow a QUESTION, which then becomes a write he
never asked for. The third is quieter and worse in its way — every
pattern matches against a lowercased sentence, so anything the
deterministic layer STORED lost his capitals, and a name he said is not
a name she may re-spell.
"""
import unittest

from aletheia import voice


class AQuestionIsNeverAnInstruction(unittest.TestCase):
    def test_asking_about_the_list_does_not_write_to_it(self):
        for said in ("why did you add milk to the list",
                     "what did I add to the list",
                     "who added eggs to the shopping list"):
            kind = (voice.interpret(said).get("command") or {}).get("kind")
            self.assertNotEqual(kind, "shopping_add", said)

    def test_adding_still_adds_however_he_says_it(self):
        for said, item in (("add milk to the list", "milk"),
                           ("put bread on the shopping list", "bread"),
                           ("get eggs on the grocery list", "eggs"),
                           ("add greek yogurt to my shopping list", "greek yogurt")):
            got = voice.interpret(said)["command"]
            self.assertEqual(got, {"kind": "shopping_add", "item": item}, said)

    def test_the_task_list_is_a_list_not_a_task(self):
        for said in ("task list", "tasks", "the task list", "my tasks"):
            self.assertEqual(voice.interpret(said)["command"], {"kind": "tasks"}, said)

    def test_making_a_task_still_makes_one(self):
        got = voice.interpret("add a task to call the plumber")["command"]
        self.assertEqual(got["kind"], "task_new")
        self.assertEqual(got["description"], "call the plumber")


class HisCapitalsSurvive(unittest.TestCase):
    def test_a_name_he_said_is_not_respelled(self):
        self.assertEqual(voice.interpret("note that Dana called")["command"]["text"],
                         "Dana called")
        self.assertEqual(
            voice.interpret("add a task to call Dr Okafor")["command"]["description"],
            "call Dr Okafor")
        self.assertEqual(
            voice.interpret("remind me every Monday to email Ana")["command"]["text"],
            "email Ana")
        self.assertEqual(
            voice.interpret("add Greek yogurt to the shopping list")["command"]["item"],
            "Greek yogurt")

    def test_it_survives_the_wake_word_and_the_preamble(self):
        got = voice.interpret("thea note that the Ford is due for service")
        self.assertEqual(got["command"]["text"], "the Ford is due for service")

    def test_a_fragment_it_cannot_find_is_left_exactly_as_it_was(self):
        # Never invent: if the words were rebuilt rather than sliced out,
        # the lowercased version is what she has and what she keeps.
        self.assertEqual(voice._as_he_said("Call Dana", "something else"),
                         "something else")
        self.assertEqual(voice._as_he_said("", "x"), "x")

    def test_the_longest_alternative_wins(self):
        # Python's alternation takes the FIRST that matches, so "note"
        # beat "note that" and the note began with the word "that".
        for said, text in (("note that Dana called", "Dana called"),
                           ("write down that I paid the rent", "I paid the rent"),
                           ("note the boiler is leaking", "the boiler is leaking")):
            self.assertEqual(voice.interpret(said)["command"]["text"], text, said)


if __name__ == "__main__":
    unittest.main()
