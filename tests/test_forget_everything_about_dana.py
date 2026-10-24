""""Dana's kids are Max and Lily" went to the planner and, with nobody to
think, was lost; "who are Dana's kids" went to a model. "Forget everything
about Dana" forgot ONE note, said "Forgotten: Dana moved to Denver", and
"what do you know about Dana" still read out her birthday (2026-10-24).
"""
import unittest
from unittest import mock

from aletheia import contacts, intercom, journal, quick, voice

NOTES = [{"text": "Dana moved to Denver"}, {"text": "Jo likes tea"},
         {"text": "Dana likes orchids"}, {"text": "Dana's birthday is March 3"}]


class DanasKids(unittest.TestCase):
    def _cmd(self, sentence):
        return voice.interpret(sentence).get("command") or {}

    def test_a_plural_relation_is_a_note(self):
        for sentence in ("Dana's kids are Max and Lily", "my sister's children are Max, Leo and Lily",
                         "our dogs are Bo and Rex"):
            with self.subTest(sentence=sentence):
                self.assertEqual(self._cmd(sentence), {"kind": "note", "text": sentence})

    def test_but_not_how_they_are(self):
        self.assertNotEqual(self._cmd("my kids are sick and tired").get("kind"), "note")

    def test_who_are_they_reads_the_note(self):
        rows = [{"text": "my sister's children are Max, Leo and Lily"}, {"text": "Dana's kids are Max and Lily"}]
        with mock.patch.object(quick, "_notes", return_value=rows):
            for asked, says in (("who are Dana's kids", "Dana's kids"), ("what are Dana's kids' names", "Dana's kids"),
                                ("who are my sister's kids", "children are Max, Leo"),
                                ("what are my sister's children's names", "children are Max, Leo")):
                with self.subTest(asked=asked):
                    self.assertIn(says, quick.answer(asked) or "")


class ForgetEverythingAboutDana(unittest.TestCase):
    def test_every_note_naming_her_goes(self):
        tomb = []
        with mock.patch.object(quick, "_notes", return_value=NOTES), \
                mock.patch.object(journal, "append", side_effect=lambda *a, **k: tomb.append(a[2])), \
                mock.patch.object(intercom, "_remembered_matching", return_value=[]), \
                mock.patch.object(contacts, "all_contacts", return_value=[]), \
                mock.patch.object(contacts, "resolve", return_value={"name": "Dana", "phone": "6055550101"}):
            said = intercom.execute_command({"kind": "forget", "about": "everything about Dana"}, {},
                                            quote="forget everything about Dana")
        self.assertEqual(sorted(tomb), ["Dana likes orchids", "Dana moved to Denver", "Dana's birthday is March 3"])
        self.assertIn("Forgotten 3 things about Dana", said)
        self.assertIn("still in your contacts", said)

    def test_a_plain_forget_is_still_one(self):
        tomb = []
        with mock.patch.object(quick, "_notes", return_value=NOTES), \
                mock.patch.object(journal, "append", side_effect=lambda *a, **k: tomb.append(a[2])), \
                mock.patch.object(intercom, "_remembered_matching", return_value=[]):
            intercom.execute_command({"kind": "forget", "about": "Dana moved to Denver"}, {}, quote="forget")
        self.assertEqual(tomb, ["Dana moved to Denver"])


if __name__ == "__main__":
    unittest.main()
