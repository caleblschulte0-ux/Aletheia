"""Live 2026-09-23, frontier off: her own model addressed a note to
"[Hiring manager or recruiter contact from DevRev email]" and the pursuit
published "A note worth sending to [Hiring manager or recruiter contact from
DevRev email]" to him. A role or a placeholder is a description of a person to
find, not a person; the move is dropped, never handed to him to address."""
import unittest

from aletheia import pursuit


class NobodyByName(unittest.TestCase):
    def test_placeholders_and_roles_are_nobody(self):
        for to in ("[Hiring manager or recruiter contact from DevRev email]",
                   "<recruiter>", "the hiring manager", "Ro's talent team",
                   "someone at Notion", "whoever runs partnerships", "HR team at Vanta"):
            self.assertTrue(pursuit.nobody_by_name(to), to)

    def test_a_name_or_an_address_is_somebody(self):
        for to in ("Dana Whitfield", "Dana", "dana@devrev.ai", "Hiring Manager <dana@devrev.ai>",
                   "Priya Raman, VP Partnerships"):
            self.assertFalse(pursuit.nobody_by_name(to), to)


class TheValidatorDropsIt(unittest.TestCase):
    def test_a_note_to_a_placeholder_is_dropped_with_the_reason(self):
        record = {"id": "opp-1", "state": pursuit.OPEN, "subject": {"name": "DevRev"},
                  "evidence": [{"id": "e1", "text": "the posting stresses partners"}],
                  "never_repeat": [], "moves": []}
        clean, dropped = pursuit.validate(
            {"moves": [{"kind": "note_to_person", "why": "the posting stresses partners and he manages them",
                        "cites": ["e1"],
                        "detail": {"to": "[Hiring manager or recruiter contact from DevRev email]",
                                   "text": "Hello", "grounded_on": ["e1"]}}]}, record)
        self.assertEqual(clean["moves"], [])
        self.assertIn("not a person", dropped[0]["why"])


if __name__ == "__main__":
    unittest.main()
