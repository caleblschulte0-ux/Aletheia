"""A thing she lacks is said as a thing she does not have (2026-09-24).

Handed the Instagram project, she answered: "I can't a local secret vault
sealed by Windows DPAPI to this user on this machine and social.publish
yet." A registry description is a noun phrase, which does not follow "I
can't"; and an id the registry has never heard of was read out raw.
"""
from __future__ import annotations

import unittest
from unittest import mock

from aletheia import intents


class ANounPhraseIsNotAVerb(unittest.TestCase):
    def test_a_registry_thing_is_something_she_does_not_have(self):
        gaps = [{"capability": "secret.store"}, {"capability": "social.publish"}]
        with mock.patch.object(intents, "_setup_step", return_value=None), \
                mock.patch("aletheia.speech._capability_english",
                           side_effect=lambda n: "a local secret vault sealed by Windows DPAPI to this user" if n == "secret.store" else ""):
            said = intents._cannot_yet(gaps, {"gap_tasks": ["t1"]})
        self.assertEqual(said, "I don't have a local secret vault sealed by Windows DPAPI to this user or "
                               "a way to publish social yet. I've put it on the build list.")

    def test_a_verb_phrase_still_reads_as_cannot(self):
        with mock.patch.object(intents, "_setup_step", return_value=None), \
                mock.patch("aletheia.speech._capability_english", return_value="look at the desktop"):
            said = intents._cannot_yet([{"capability": "computer.observe"}], {})
        self.assertEqual(said, "I can't look at the desktop yet.")

    def test_an_unknown_id_is_never_read_out_raw(self):
        # An id the registry has never heard of (social.publish is in it now).
        self.assertEqual(intents._in_english("moon.landing"), "a way to landing moon")
        self.assertNotIn("moon.landing", intents._in_english("moon.landing"))


if __name__ == "__main__":
    unittest.main()
