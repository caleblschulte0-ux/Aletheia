"""Five sentences about approvals and the day, each a two-minute wait on
her own model with every frontier off (2026-09-22), each a store she holds."""
from __future__ import annotations

import unittest
from unittest import mock

from aletheia import quick, voice


class TheNoteAndTheDenialCase(unittest.TestCase):
    def test_make_a_note_is_a_note(self):
        for sentence, text in (("thea make a note that the roof leaks", "the roof leaks"),
                               ("thea take a note: call the plumber", "call the plumber"),
                               ("thea jot down that Dana called", "Dana called")):
            with self.subTest(sentence=sentence):
                out = voice.interpret(sentence)
                self.assertEqual(out["command"]["kind"], "note", sentence)
                self.assertEqual(out["command"]["text"], text)

    def test_deny_the_last_one_denies_the_newest_of_several(self):
        pending = [{"id": "a-old", "state": "PENDING", "requested_at": "2026-09-22T10:00:00Z"},
                   {"id": "a-new", "state": "PENDING", "requested_at": "2026-09-22T12:00:00Z"}]
        with mock.patch("aletheia.policy.all_approvals", return_value=pending):
            self.assertEqual(voice.interpret("thea deny the last one")["command"]["id"], "a-new")
            self.assertEqual(voice.interpret("thea cancel the first one")["command"]["id"], "a-old")
            # with no qualifier and two waiting, she still asks which
            self.assertIsNone(voice.interpret("thea deny that")["command"])


class TheDaysQuestionsCase(unittest.TestCase):
    def test_what_needs_my_yes_is_the_one_list(self):
        for sentence in ("what needs my yes", "anything that needs my approval", "what's waiting on my ok"):
            with self.subTest(sentence=sentence):
                self.assertEqual(quick.match(sentence)[0], "waiting", sentence)

    def test_did_i_miss_anything_is_todays_journal(self):
        for sentence in ("did I miss anything while I was out", "what did I miss",
                         "what happened while I was gone", "anything happen while I was asleep"):
            with self.subTest(sentence=sentence):
                self.assertEqual(quick.match(sentence)[0], "today", sentence)

    def test_what_did_you_send_today_is_the_list_by_name(self):
        hunt = {"readable": True, "sent_list": [{"company": "Stripe", "job": "Operations Analyst"},
                                                 {"company": "Figma", "job": "Ops Lead"}]}
        with mock.patch("aletheia.current_state.job_hunt", return_value=hunt):
            said = quick.answer("what did you send today")
        self.assertIn("Stripe", said)
        self.assertIn("Figma", said)
        with mock.patch("aletheia.current_state.job_hunt", return_value={"readable": True, "sent_list": []}):
            said = quick.answer("did you send anything out today")
        self.assertIn("Nothing sent today", said)
        self.assertIn("without your yes", said)


if __name__ == "__main__":
    unittest.main()
