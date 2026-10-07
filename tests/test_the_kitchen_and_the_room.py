"""Kitchen measures, volume in either word order, and her name."""
import unittest

from aletheia import quick, voice


class TheKitchen(unittest.TestCase):
    def test_volumes(self):
        self.assertEqual(quick.answer("how many ounces in a cup"), "8 ounces.")
        self.assertEqual(quick.answer("how many tablespoons in a cup"), "16 tablespoons.")
        self.assertEqual(quick.answer("how many cups in a gallon"), "16 cups.")
        self.assertEqual(quick.answer("convert 2 cups to ml"), "About 473.18 milliliters.")

    def test_an_ounce_beside_a_weight_is_a_weight(self):
        self.assertEqual(quick.answer("what is 16 oz in pounds"), "1 pound.")
        self.assertEqual(quick.answer("how many grams in a pound"), "About 453.59 grams.")

    def test_a_volume_is_not_a_length(self):
        self.assertIsNone(quick.answer("convert 2 cups to feet"))

    def test_yards(self):
        self.assertEqual(quick.answer("how many yards in a mile"), "1,760 yards.")


class TheRoom(unittest.TestCase):
    def test_turn_up_the_volume(self):
        c = (voice._interpret("turn up the volume") or {}).get("command") or {}
        self.assertEqual((c.get("kind"), c.get("action")), ("music", "volume_up"))

    def test_anything_i_need_to_know_is_the_one_list(self):
        self.assertEqual(quick.match("anything i need to know")[0],
                         quick.match("anything i should know")[0])


if __name__ == "__main__":
    unittest.main()


class TellingHerANumber(unittest.TestCase):
    def cmd(self, said):
        return (voice._interpret(said) or {}).get("command") or {}

    def test_moms_number_is_a_contact(self):
        c = self.cmd("mom's number is 605 555 0123")
        self.assertEqual((c.get("kind"), c.get("name"), c.get("phone")),
                         ("contact_add", "mom", "605 555 0123"))

    def test_an_email_address_is_a_contact(self):
        c = self.cmd("my sister's email is dana@example.com")
        self.assertEqual((c.get("kind"), c.get("name"), c.get("email")),
                         ("contact_add", "sister", "dana@example.com"))

    def test_the_confirmation_is_a_sentence(self):
        from aletheia import speech
        said = speech.spoken_receipt("contact_add", "remembered mom as 6055550123 — private contacts "
                                                    "only, never the public repo")
        self.assertEqual(said, "Got it - Mom: 605-555-0123.")

    def test_cancel_my_alarm(self):
        self.assertEqual(self.cmd("cancel my alarm"), {"kind": "reminder_off", "which": "wake up"})
        self.assertNotEqual(self.cmd("cancel my gym membership").get("kind"), "reminder_off")
