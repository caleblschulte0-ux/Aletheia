""""Add a task" asks what the task is, and the next sentence is the answer."""
import unittest
from unittest import mock

from aletheia import quick, voice


def turn(said, answered=""):
    return [{"he_asked": said, "she_answered": answered}]


class ABareAsk(unittest.TestCase):
    def test_she_asks_for_the_rest(self):
        with mock.patch("aletheia.converse.recent", return_value=[]):
            self.assertEqual(voice._interpret("add a task")["say"], "What's the task?")
            self.assertIn("remind you", voice._interpret("set a reminder")["say"])

    def test_the_next_sentence_fills_it(self):
        with mock.patch("aletheia.converse.recent", return_value=turn("add a task", "What's the task?")):
            c = voice._interpret("call the plumber")["command"]
        self.assertEqual((c["kind"], c["description"]), ("task_new", "call the plumber"))

    def test_a_question_is_not_the_answer(self):
        with mock.patch("aletheia.converse.recent", return_value=turn("add a task", "What's the task?")):
            self.assertNotEqual((voice._interpret("what time is it").get("command") or {}).get("kind"), "task_new")

    def test_never_mind_is_not_a_task(self):
        with mock.patch("aletheia.converse.recent", return_value=turn("add a task", "What's the task?")), \
                mock.patch("aletheia.policy.all_approvals", return_value=[]):
            self.assertNotEqual((voice._interpret("never mind").get("command") or {}).get("kind"), "task_new")

    def test_a_reminder_in_two_turns(self):
        with mock.patch("aletheia.converse.recent", return_value=turn("set a reminder")):
            self.assertIn("When should I remind you", voice._interpret("stretch")["say"])
        with mock.patch("aletheia.converse.recent",
                        return_value=turn("stretch", "When should I remind you? Say a time.")):
            c = voice._interpret("at 6")["command"]
        self.assertEqual((c["kind"], c["text"]), ("remind_at", "stretch"))


class TheWeatherAskedSideways(unittest.TestCase):
    def test_umbrella_and_temperature_are_the_forecast(self):
        for said in ("should i bring an umbrella", "what's the temperature", "is it raining",
                     "how cold is it outside", "do i need a jacket"):
            self.assertEqual((quick.match(said) or ("",))[0], "weather", said)


if __name__ == "__main__":
    unittest.main()
