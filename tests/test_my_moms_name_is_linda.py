"""A person's name typed in lower case is kept with its capital.

2026-10-28, typed the way he types on his phone:

    > my mom's name is linda
    > what's my mom's name
      You told me: your mom's name is linda.

A pet's name already got its capital ("my dog's name is Max").
"""
import unittest

from aletheia import voice


class PeoplesNames(unittest.TestCase):
    def test_typed_lower_case(self):
        for said, kept in (("my mom's name is linda", "my mom's name is Linda"),
                           ("my sister is named sarah", "my sister's name is Sarah"),
                           ("my landlord's name is john smith", "my landlord's name is John Smith")):
            self.assertEqual(voice.interpret(said)["command"], {"kind": "note", "text": kept}, said)

    def test_his_own_capitals_are_kept(self):
        self.assertEqual(voice.interpret("My boss's name is Mary Jo")["command"]["text"], "my boss's name is Mary Jo")
        self.assertEqual(voice.interpret("my friend's name is DeShawn")["command"]["text"], "my friend's name is DeShawn")

    def test_a_pet_is_unchanged(self):
        self.assertEqual(voice.interpret("my dog's name is max")["command"]["text"], "my dog's name is Max")


if __name__ == "__main__":
    unittest.main()
