"""Who is thinking is a fact she holds, never a thing a model says about
itself. With every frontier off (2026-09-22) she said "Thinking with the
big models", answered "which model are you using" with "Sonnet 5", and
"when will Claude be back" with "I'm running on Claude right now -
nothing's down". Three lies and a developer's word, in the one place his
"see it's working" ask needs the truth."""
from __future__ import annotations

import unittest
from unittest import mock

from aletheia import current_state, quick, speech


class TheBrainsLineHonoursTheSwitchCase(unittest.TestCase):
    def minds(self, **over):
        base = {"claude": {"resting_until": None, "installed": True},
                "codex": {"resting_until": None, "installed": True},
                "local": {"allowed": True, "why": "", "busy": None, "recent": {}},
                "switched_off": False}
        base.update(over)
        return base

    def test_switched_off_never_claims_the_big_models_are_thinking(self):
        said = current_state.brains_words(self.minds(switched_off=True))
        self.assertNotIn("Thinking with the big models", said)
        self.assertIn("switched off", said)
        self.assertIn("my own model", said)

    def test_switched_off_with_no_own_model_says_nobody_can_think(self):
        said = current_state.brains_words(self.minds(switched_off=True,
                                                     local={"allowed": False, "why": "my own model is not running",
                                                            "busy": None, "recent": {}}))
        self.assertIn("Nobody can think", said)

    def test_with_the_switch_off_thinking_reads_it(self):
        with mock.patch("aletheia.reasoning_gateway.frontier_off", return_value=True), \
             mock.patch("aletheia.reasoner.local_allowed", return_value=(False, "off")):
            minds = current_state.thinking()
        self.assertTrue(minds["switched_off"])
        self.assertFalse(minds["anyone"])

    def test_the_questions_about_the_models_are_the_brains_line(self):
        for sentence in ("which model are you using", "are you on claude", "are the big models out",
                         "when will claude be back", "is your own model running",
                         "how long until you can think properly again", "is chatgpt down"):
            with self.subTest(sentence=sentence):
                self.assertEqual(quick.match(sentence)[0], "slow", sentence)


class AModelNamingItselfIsScrubbedCase(unittest.TestCase):
    def test_tier_names_become_her_words(self):
        self.assertEqual(speech.plain_models("I'm running on Sonnet 5 right now."),
                         "I'm running on the big model right now.")
        self.assertEqual(speech.plain_models("This came from qwen3:8b via Ollama."),
                         "This came from my own model via my own model.")
        self.assertEqual(speech.plain_models("GPT-5 and Claude Opus 5 are both out."),
                         "the big model and the big model are both out.")

    def test_ordinary_words_are_left_alone(self):
        for text in ("a sonnet by Shakespeare is fourteen lines",):
            # "sonnet" alone is a poem; only the tier shapes are model names
            self.assertIn("sonnet", speech.plain_models(text).casefold())

    def test_it_is_part_of_the_one_door_for_prose(self):
        self.assertIn("the big model", speech.spoken_prose("Sonnet 5 answered this."))


if __name__ == "__main__":
    unittest.main()
