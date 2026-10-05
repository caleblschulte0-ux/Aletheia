"""Thirty-fifth sandbox batch, 2026-10-05: a postcode, a contact's email, and a
conversation with one person by its other names.

    > my postcode is 57033                the planner, and an approval
    > Dana's email is dana@example.com    the planner, and an approval
    > what did I send Dana / when did I last talk to Dana / what's happening
      with Dana / what did Dana say / what conversations are open / who am I
      waiting on                          six models, each hedging about the
                                          thread store ("did Dana reply" was 0.0s)
    > "with dana"                         his capitals lost on the way
"""
import unittest

from aletheia import voice


class OnePerson(unittest.TestCase):
    def test_the_facts_compile(self):
        self.assertEqual(voice.interpret("my postcode is 57033")["command"], {"kind": "profile_set", "field": "postal_code", "value": "57033"})
        self.assertEqual(voice.interpret("Dana's email is dana@example.com")["command"],
                         {"kind": "contact_add", "name": "Dana", "email": "dana@example.com"})
        self.assertNotEqual(voice.interpret("my email is pat@example.com")["command"]["kind"], "contact_add")

    def test_the_conversation_by_its_other_names(self):
        for said in ("what did I send Dana", "when did I last talk to Dana", "what's happening with Dana",
                     "what did Dana say", "did Dana reply"):
            self.assertEqual(voice.interpret(said)["command"], {"kind": "thread_status", "which": "Dana"}, said)
        for said in ("what conversations are open", "who am I waiting on"):
            self.assertEqual(voice.interpret(said)["command"], {"kind": "thread_status"}, said)
        self.assertEqual(voice.interpret("what's happening with Barkly")["command"]["kind"], "intent")


if __name__ == "__main__":
    unittest.main()
