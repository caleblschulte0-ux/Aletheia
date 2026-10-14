""""My car's tire pressure should be 35" and "my car takes 5w-30 oil" went
to the planner, and "what should my tire pressure be" / "what oil does my
car take" to a model (2026-10-14). A spec of the car is a note, read back."""
import unittest
from unittest import mock

from aletheia import quick, voice


class CarSpecs(unittest.TestCase):
    def test_said_as_a_fact_is_a_note(self):
        for said in ("my car's tire pressure should be 35", "my tire pressure is 35 psi", "my car takes 5w-30 oil"):
            out = voice._interpret(said)
            self.assertEqual((out.get("command") or {}).get("kind"), "note", said)

    def test_not_a_spec_is_not_a_note(self):
        for said in ("my car needs washing", "my doctor should be here soon", "my tire pressure is low"):
            out = voice._interpret(said) or {}
            self.assertNotEqual((out.get("command") or {}).get("kind"), "note", said)

    def test_read_back(self):
        rows = [{"text": "my car takes 5w-30 oil"}, {"text": "my car's tire pressure should be 35"}]
        with mock.patch.object(quick, "_notes", return_value=rows):
            for asked in ("what should my tire pressure be", "what tire pressure does my car need", "what's my tire pressure"):
                self.assertEqual(quick.answer(asked), "You told me: your car's tire pressure should be 35.", asked)
            for asked in ("what oil does my car take", "what kind of oil does my car need"):
                self.assertEqual(quick.answer(asked), "You told me: your car takes 5w-30 oil.", asked)

    def test_never_said_hands_on(self):
        with mock.patch.object(quick, "_notes", return_value=[{"text": "my car takes 5w-30 oil"}]):
            self.assertIsNone(quick._car_spec("what should my tire pressure be"))


if __name__ == "__main__":
    unittest.main()
