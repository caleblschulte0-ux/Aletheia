""""I parked on level 5 actually" was read back "You parked on level 5
actually", and "forget my wifi password" said "nothing remembered about my
wifi password" (2026-10-15, every model off)."""
import unittest

from aletheia import voice


class ParkedActually(unittest.TestCase):
    def test_the_correction_word_is_not_where_the_car_is(self):
        for said in ("I parked on level 5 actually", "I parked on level 5, actually",
                     "actually I parked on level 5", "I parked on level 5 instead"):
            with self.subTest(said=said):
                cmd = voice._interpret(said)["command"]
                self.assertEqual(cmd["kind"], "note")
                self.assertEqual(cmd["text"].lower(), "i parked on level 5")

    def test_a_plain_one_is_unchanged(self):
        self.assertEqual(voice._interpret("I parked on level 3 row B")["command"],
                         {"kind": "note", "text": "I parked on level 3 row B"})


if __name__ == "__main__":
    unittest.main()
