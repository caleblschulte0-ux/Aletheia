"""The registry is a document somebody reads, and she reads it TO him.

    > can you read a pdf
      Yes - Get the words out of a PDF, .docx or text file - HIS real
      documents, with no package to install.
    > can you write a document
      Yes - Create and edit real files ... inside a workspace SHE owns.

Fifteen of a hundred and thirty-seven descriptions were written in the
third person, and `quick._can_you` speaks every one of them. He is told
about a third party who happens to be him, by a narrator who happens to
be her.

The obvious fix - rewrite the pronouns at the speaking door, the way
`speech.plainly` handles every other written-for-a-log sentence - was
tried and thrown away, because its own output condemned it:

    Close my the way you close a window - I finish what I am holding,
    exits cleanly, and stays shut until you opens my again
    ... on your actual screen, where you is

"Her" as a possessive and "her" as an object are the same word, and "he
opens"/"you open" disagree in a way a substitution cannot see. That is a
parser, and a deterministic pattern that swallows too much answers a
DIFFERENT question - the failure he cannot detect.

So the source was fixed instead, and this holds the rule. It is not a
style check: every one of these strings is spoken.
"""
from __future__ import annotations

import re
import unittest

from aletheia import capabilities, quick, self_knowledge

#: Third-person pronouns. "Her"/"his" about the OPERATOR or about ALETHEIA
#: are both wrong in a sentence said to him, for opposite reasons.
_THIRD_PERSON = re.compile(
    r"\b(he|him|his|himself|she|her|hers|herself|the operator|caleb)\b", re.I)


class SaidToHimCase(unittest.TestCase):
    def test_no_description_talks_about_him_in_the_third_person(self):
        registry = capabilities.load_registry()
        offenders = []
        for entry in registry["capabilities"]:
            found = _THIRD_PERSON.search(entry.get("description", ""))
            if found:
                offenders.append(f"{entry['id']}: ...{found.group(0)}...")
        self.assertEqual(offenders, [], "\n".join(
            ["these are spoken back to him verbatim:"] + offenders))

    def test_the_word_it_is_written_in_is_the_word_he_hears(self):
        """No transform stands between the registry and the room.

        If one is ever added, this test should be the thing that argues
        with it: the last attempt produced "where you is".
        """
        entry = capabilities.get("document.read_any")
        said = quick.answer("can you read a pdf") or ""
        self.assertIn(entry["description"].rstrip("."), said)


#: A slash between two words. Out loud it is either silence or the word
#: "slash", and neither is English.
_SLASH = re.compile(r"\w/\w")


class ASlashIsNotAWordCase(unittest.TestCase):
    """Twenty of these were written for somebody reading a specification.

        > can you buy me a monitor
          Yes - Private requirements/candidates/selection workflow ending
          in an approval-bounded purchase proposal.

    `read/ack`, `one-time/interval/daily/weekly`, `mic/speaker/virtual
    cable`, `(create/update/cancel)`. Every one of them is spoken.
    """

    def test_no_description_carries_a_slash(self):
        offenders = []
        for entry in capabilities.load_registry()["capabilities"]:
            found = _SLASH.search(entry["description"])
            if found:
                offenders.append(f"{entry['id']}: ...{found.group(0)}...")
        self.assertEqual(offenders, [], "\n".join(
            ["said out loud, a slash is silence or the word 'slash':"]
            + offenders))

    def test_notes_may_keep_every_engineering_word(self):
        """The precision is not lost, it is moved somewhere nobody speaks.

        A rule that forced `notes` into plain English would cost the
        engineering record its meaning, and `notes` is never read out.
        """
        registry = capabilities.load_registry()
        self.assertTrue(
            any(_SLASH.search(str(e.get("notes") or ""))
                for e in registry["capabilities"]),
            "if this ever goes false the rule above may have been "
            "applied to notes as well, which is not the rule")


class TheOtherFieldsCase(unittest.TestCase):
    def test_notes_and_callers_may_stay_in_the_third_person(self):
        """They are never spoken, and rewriting them would lose meaning.

        `caller` names real functions; `notes` is the engineering record
        and says things like "found live 2026-09-02". Asserting the rule
        applies only where it applies is the point - a check that flags
        prose nobody reads aloud gets turned off.
        """
        registry = capabilities.load_registry()
        speakable = {"description"}
        for entry in registry["capabilities"]:
            for field in entry:
                if field in speakable:
                    continue
                self.assertNotIn(field, ("spoken", "says"),
                                 "a new spoken field needs adding above")

    def test_what_it_is_comes_from_the_description(self):
        """`self_knowledge` is the other reader, and it is spoken too."""
        found = self_knowledge.relevant("can you read my files")
        self.assertTrue(found)
        top = found[0]
        self.assertFalse(_THIRD_PERSON.search(top["what_it_is"]),
                         f"spoken: {top['what_it_is']}")

    def test_every_capability_survives_the_rule(self):
        """Every description, through the door that speaks it."""
        registry = capabilities.load_registry()
        for entry in registry["capabilities"]:
            with self.subTest(capability=entry["id"]):
                self.assertFalse(_THIRD_PERSON.search(entry["description"]))


if __name__ == "__main__":
    unittest.main()
