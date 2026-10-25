""""My order from Target is arriving Thursday" was refused at the money door
as an order to buy; "I'm expecting a package from Amazon" was kept and then
missing from "what packages am I expecting"; and "the package arrived" was
read back as still on its way (2026-10-24).
"""
import unittest
from unittest import mock

from aletheia import intents, quick, voice


def _notes(*newest_first):
    return mock.patch.object(quick, "_notes", return_value=[{"text": t} for t in newest_first])


class MyOrderFromTarget(unittest.TestCase):
    def test_a_delivery_is_a_note_not_a_purchase(self):
        for said in ("my order from Target is arriving thursday", "my order shipped", "my package is out for delivery",
                     "i'm expecting a package from Amazon on tuesday"):
            with self.subTest(said=said):
                self.assertEqual(voice.interpret(said).get("command"), {"kind": "note", "text": said})

    def test_buying_is_still_refused(self):
        for said in ("order me a pizza", "buy the monitor from Best Buy"):
            with self.subTest(said=said):
                self.assertNotEqual((voice.interpret(said).get("command") or {}).get("kind"), "note")
                self.assertTrue(intents._asks_to_spend(said))

    def test_expecting_is_on_the_list(self):
        with _notes("my order from Target is arriving thursday", "i'm expecting a package from Amazon on tuesday"):
            said = quick._deliveries()
        self.assertIn("Target", said)
        self.assertIn("Amazon", said)

    def test_what_came_comes_off(self):
        with _notes("the Amazon package came", "my order from Target is arriving thursday",
                    "i'm expecting a package from Amazon on tuesday"):
            said = quick._deliveries()
        self.assertIn("Target", said)
        self.assertNotIn("Amazon", said)
        with _notes("the package came", "the Amazon package came", "my order from Target is arriving thursday",
                    "i'm expecting a package from Amazon on tuesday"):
            self.assertEqual(quick._deliveries(), "Nothing's still on its way - everything you told me about has come.")


if __name__ == "__main__":
    unittest.main()
