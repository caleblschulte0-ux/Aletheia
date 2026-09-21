"""What he reads on the Thea page and hears from her, held to plain words.

Found 2026-09-21 by rendering the page and asking her five ordinary things
with every model down (the seamless brief's UX pass). Each of these was on
his screen or in her reply:

    "I could not reach a model to answer that: subscription reasoning and
     local deep reasoning are unavailable (subscription: neither ..."
    "...until you run python -m aletheia.standing on, once."
    "Here's what I'd do: text your sister ... Say yes and I'll do it.
     I can't send a text message yet."
    "session: Answered with on, from boards.example.com"
    "Work inventory - Everything unfinished across her queues, read as one
     - the next executable item"          (above the card for the one task)
    "Waiting on you: 41 approvals.  Next: 41 approvals waiting for your yes"
    two health boxes, one yellow and one red, about the same fact
"""
import datetime as dt
import unittest
from unittest import mock

from aletheia import converse, intents, mission_control, mission_work, speech


class NobodyCanThinkCase(unittest.TestCase):
    def test_it_is_one_sentence_a_person_would_say(self):
        said = converse.nobody_can_think_words(
            "subscription reasoning and local deep reasoning are unavailable "
            "(subscription: neither Claude nor the ChatGPT browser could answer)")
        self.assertTrue(said.startswith("I can't think just now"), said)
        self.assertNotIn("(", said)
        self.assertNotIn("unavailable", said)
        self.assertIn("still works", said)

    def test_the_one_fix_he_can_do_is_named_when_there_is_one(self):
        self.assertIn("Signing in to Claude on the PC",
                      converse.nobody_can_think_words("Claude CLI is not on PATH"))
        self.assertNotIn("Signing in", converse.nobody_can_think_words("model not pulled"))


class AGapLeadsCase(unittest.TestCase):
    def test_what_she_cannot_do_is_said_before_what_she_offers(self):
        record = {"intent": "plan", "tier": "routine",
                  "summary": "Text your sister that you're running late",
                  "steps": [{"n": 1, "status": "EXECUTABLE", "capability": None,
                             "command": {"kind": "task_new", "id": "t", "description": "x"},
                             "detail": ""},
                            {"n": 2, "status": "GAP", "capability": "message.send",
                             "command": {}, "detail": "not built"}],
                  "gap_tasks": ["verify-message-send"]}
        with mock.patch.object(intents, "_due_to_mention", lambda *a: False), \
             mock.patch.object(intents, "_cannot_yet",
                               return_value="I can't send a text message yet."), \
             mock.patch.object(intents, "_own_model_line", return_value=""):
            said = intents.spoken(record)
        self.assertTrue(said.startswith("I can't send a text message yet."), said)
        self.assertIn("What I can do: here's what I'd do", said)
        self.assertLess(said.index("can't"), said.index("Say approve"))


class ForReadingCase(unittest.TestCase):
    def test_a_provider_takes_its_preposition_with_it(self):
        self.assertEqual(
            speech.for_reading("Answered with ollama:qwen3:8b on subscription.auto, "
                               "from https://boards.example.com/jobs/7?token=abc123"),
            "Answered, from boards.example.com")
        self.assertEqual(speech.for_reading("Planned with local.qwen3 and saved it"),
                         "Planned and saved it")
        self.assertEqual(speech.for_reading("Answered via anthropic/claude-sonnet on gateway.plan."),
                         "Answered.")


class TheHeaderCase(unittest.TestCase):
    def test_next_does_not_repeat_doing(self):
        now = dt.datetime(2026, 9, 21, 15, 0, tzinfo=dt.timezone.utc)
        h = mission_control.header({"state": "IDLE"}, now=now,
                                   core={"heartbeat_age_s": 5, "alive": True}, approvals=41)
        self.assertTrue(h["doing"].startswith("Waiting on you: 41 approvals"), h["doing"])
        self.assertNotIn("41", h["next"])
        self.assertIn("Nothing happens until you do", h["next"])


class TheWorkCardCase(unittest.TestCase):
    def test_a_queue_that_can_run_is_its_own_cards_not_an_inventory_card(self):
        summary = {"readable": True, "as_of": "t", "halted": False, "counts": {"READY": 1},
                   "executable_total": 1, "blocked_total": 0,
                   "executable_now": [{"id": "task:call", "title": "call the plumber"}],
                   "blocked": [], "said": "1 thing can run now"}
        part = mission_work.build({"summary": summary}, {})
        self.assertEqual(part.get("missions", []), [])
        self.assertEqual(part["signals"][0]["ok"], True)
        self.assertIn(mission_work.CARD_ID, part["details"])   # still one tap away

    def test_a_blocked_queue_still_gets_a_card_in_plain_words(self):
        summary = {"readable": True, "as_of": "t", "halted": False, "counts": {},
                   "executable_total": 0, "blocked_total": 2, "executable_now": [],
                   "blocked": [{"id": "x", "title": "build it", "state": "BLOCKED_MODEL",
                                "reason": "Claude is resting", "next": "when Claude's limit resets"}],
                   "said": ""}
        card = mission_work.build({"summary": summary}, {})["missions"][0]
        self.assertEqual(card["title"], "Waiting work")
        self.assertEqual(card["goal"], "2 things can't move yet")
        for machine in ("inventory", "executable", "queues"):
            self.assertNotIn(machine, (card["goal"] + card["next"] + card["title"]).lower())


if __name__ == "__main__":
    unittest.main()
