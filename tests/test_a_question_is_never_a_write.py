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

    def test_a_persons_name_keeps_its_capital(self):
        # The one he is most likely to notice: "remember person Dana ..."
        # saved a contact whose display name was "dana".
        self.assertEqual(
            voice.interpret("remember person Dana dana at example.com")["command"]["name"],
            "Dana")
        self.assertEqual(
            voice.interpret("set up a meeting with Dana next week")["command"]["person"],
            "Dana")
        self.assertEqual(
            voice.interpret("tell me when I get an email from Dana")["command"]["who"],
            "Dana")

    def test_the_brief_is_asked_for_the_way_people_ask(self):
        for said in ("give me the brief", "brief me", "the brief",
                     "read me my briefing", "catch me up"):
            self.assertEqual(voice.interpret(said)["command"], {"kind": "brief"}, said)

    def test_the_longest_alternative_wins(self):
        # Python's alternation takes the FIRST that matches, so "note"
        # beat "note that" and the note began with the word "that".
        for said, text in (("note that Dana called", "Dana called"),
                           ("write down that I paid the rent", "I paid the rent"),
                           ("note the boiler is leaking", "the boiler is leaking")):
            self.assertEqual(voice.interpret(said)["command"]["text"], text, said)


class TheFastLaneNeverEndsTheTurn(unittest.TestCase):
    """It may remove latency. It may never remove an ANSWER.

    "am I free at 3 on friday" and "when am I free next week" both ended
    on "I couldn't parse 'next week' — say today, tomorrow, a date..." —
    a dead end produced by the very layer that exists to be helpful
    faster. Anything it cannot read goes to the planner, which resolves
    the date and compiles the same command for the price of a round trip.
    """

    def test_a_day_it_can_read_is_still_instant(self):
        for said in ("am I free friday", "am I free tomorrow afternoon",
                     "am I free"):
            got = voice.interpret(said)
            self.assertEqual(got["command"]["kind"], "free_time", said)

    def test_a_day_it_cannot_read_goes_to_the_planner(self):
        for said in ("am I free at 3 on friday", "when am I free next week",
                     "am I free the week after next"):
            got = voice.interpret(said)
            self.assertEqual((got.get("command") or {}).get("kind"), "intent", said)
            self.assertIsNone(got.get("say"), said)

    def test_a_genuinely_ambiguous_day_still_asks(self):
        # "Friday" when today IS Friday is a real question, not a parse
        # failure — that one keeps its sentence.
        got = voice.interpret("am I free on friday")
        self.assertTrue(got.get("command") or got.get("say"))


if __name__ == "__main__":
    unittest.main()
