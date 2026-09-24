"""Fifteen orders and facts with every model rung off (2026-09-24).

- "Add buy stamps to my task list" was refused at the door as an
  instruction to spend money. Its verb is ADD; what it adds is a line to
  his own list. Recording is not spending.
- "Stop opening ChatGPT windows" - his words, twice, on 2026-09-12 -
  reached the planner with every model off. It is his switch and has a
  phrasing now, and so does lifting it.
"""
from __future__ import annotations

import unittest

from aletheia import intents, voice


class RecordingIsNotSpending(unittest.TestCase):
    def test_a_task_a_reminder_or_a_note_that_mentions_buying_is_not_refused(self):
        for s in ("add buy stamps to my task list", "remind me at 3 to buy milk", "note that I need to order a new charger",
                  "add a task to pay the electric bill", "remember that the car payment is on the 5th"):
            self.assertFalse(intents._asks_to_spend(s), s)

    def test_an_instruction_to_spend_is_still_refused_at_the_door(self):
        for s in ("buy me stamps", "order a pizza", "book me a flight to Tokyo", "pay the electric bill",
                  "buy stamps and add it to the list"):
            self.assertTrue(intents._asks_to_spend(s), s)

    def test_a_question_about_money_never_was(self):
        self.assertFalse(intents._asks_to_spend("how much would stamps cost"))


class HisChatGptSwitchHasHisWords(unittest.TestCase):
    def test_stop_opening_chatgpt_windows_is_the_off_switch(self):
        for s in ("stop opening chatgpt windows", "stop opening up ChatGPT windows", "I said stop opening chatgpt windows",
                  "no more chatgpt windows", "don't keep opening chat gpt"):
            out = voice.interpret(f"thea {s}")
            self.assertEqual((out.get("command") or {}).get("kind"), "chatgpt_off", s)

    def test_you_can_open_chatgpt_again_is_the_on_switch(self):
        for s in ("you can open chatgpt again", "chatgpt windows are fine again", "it's ok to open chatgpt again"):
            out = voice.interpret(f"thea {s}")
            self.assertEqual((out.get("command") or {}).get("kind"), "chatgpt_on", s)


class ANoteIsForgettableToo(unittest.TestCase):
    """"Remember that my sister's name is Dana" is kept as a note and read
    back by "what's my sister's name"; "forget my sister's name" then said
    she had nothing (2026-09-24). The journal is append-only, so a
    forgotten note gets a tombstone the readers honour."""

    def setUp(self):
        import os, tempfile
        from pathlib import Path
        from unittest import mock
        from aletheia import journal
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        env = mock.patch.dict(os.environ, {"ALETHEIA_PRIVATE_STATE": str(root / "private")})
        env.start(); self.addCleanup(env.stop)
        p = mock.patch.object(journal, "JOURNAL_PATH", root / "journal.jsonl")
        p.start(); self.addCleanup(p.stop)

    def test_forgetting_a_note_takes_it_out_of_every_reader(self):
        from aletheia import intercom, journal, quick
        journal.append("note", "operator", "my sister's name is Dana", actor="operator")
        self.assertIn("Dana", quick.answer("what's my sister's name") or "")
        said = intercom.execute_command({"kind": "forget", "about": "my sister's name"}, {}, quote="forget my sister's name")
        self.assertTrue(said.startswith("Forgotten: my sister's name is Dana"), said)
        self.assertNotIn("Dana", quick.answer("what's my sister's name") or "")
        self.assertEqual([n for n in quick._notes() if "Dana" in str(n.get("text"))], [])

    def test_nothing_to_forget_is_still_said_plainly(self):
        from aletheia import intercom
        said = intercom.execute_command({"kind": "forget", "about": "my landlord"}, {}, quote="forget my landlord")
        self.assertTrue(said.startswith("I have nothing remembered about my landlord"), said)


if __name__ == "__main__":
    unittest.main()
