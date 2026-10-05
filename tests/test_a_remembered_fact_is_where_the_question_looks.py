"""Found 2026-10-04 by talking to her in the sandbox, three sentences apart:

    > remember that my landlord is Dana Whitfield      Noted.
    > who is my landlord      I don't have anyone remembered as your landlord.

"remember that X is Y" compiled a journal NOTE, and "who is my X" reads the
people shelf of her memory - a writer and a reader looking at different
stores. A store with a writer and no reader makes her a liar; so does a
reader with no writer. One parser (memory.parse_fact) now serves the voice
layer and the work session's argument filling, and the reader tries the key
the writer uses.

Two more from the same run: "Not yet — Post a picture or a reel with a
caption to your Instagram account, straight off this PC - one post per
approval, never on its own needs setting up first. She posts through ..."
read a registry description aloud, in the third person, with no sentence in
it; and the brief said "Unreachable: HTTP Error 404" every day about a stub
repository that exists and is private.
"""
import unittest
import urllib.error
from unittest import mock

from aletheia import intercom, memory, quick, voice


class RememberXIsYGoesOnAShelf(unittest.TestCase):
    def test_the_sentence_compiles_to_a_memory_with_his_capitals(self):
        out = voice.interpret("remember that my landlord is Dana Whitfield")
        self.assertEqual(out["command"], {"kind": "remember", "domain": "people",
                                          "key": "landlord", "value": "Dana Whitfield",
                                          "about": "your landlord"})

    def test_a_subject_with_no_shelf_is_still_a_note_with_his_capitals(self):
        out = voice.interpret("remember that the gate code is Four Four Seven One")
        self.assertEqual(out["command"]["kind"], "note")
        self.assertEqual(out["command"]["text"], "the gate code is Four Four Seven One")
        # A password is the one note she refuses out loud (2026-10-05): the
        # journal scrubs it on the way in, so "Noted." would have kept
        # "[redacted]" and read that back.
        out = voice.interpret("remember that the wifi password is Hunter2")
        self.assertIsNone(out["command"])
        self.assertIn("I don't keep passwords", out["say"])

    def test_remember_to_is_not_a_fact(self):
        out = voice.interpret("remember to call the dentist")
        self.assertNotEqual(out["command"]["kind"], "remember")

    def test_the_round_trip_she_failed(self):
        self.addCleanup(memory.forget, "people", "landlord")
        cmd = voice.interpret("remember that my landlord is Dana Whitfield")["command"]
        said = intercom.execute_command(cmd, {}, quote="remember that my landlord is Dana Whitfield")
        # His phrase, read back ("sister s birthday" was the key, 2026-10-05).
        self.assertEqual(said, "Remembered: your landlord is Dana Whitfield.")
        self.assertNotIn("people.", said, "a receipt is read out loud, never domain.key")
        self.assertEqual(quick._person("landlord"), "Your landlord is Dana Whitfield.")

    def test_a_two_word_subject_is_found_by_the_question(self):
        self.addCleanup(memory.forget, "people", "best_friend")
        cmd = voice.interpret("remember my best friend is Marcus")["command"]
        self.assertEqual(cmd["key"], "best_friend")
        intercom.execute_command(cmd, {}, quote="t")
        self.assertEqual(quick._person("best friend"), "Your best friend is Marcus.")

    def test_one_parser_serves_both_doors(self):
        fact = memory.parse_fact("Remember my gym is Great Life.")
        self.assertEqual(fact, {"subject": "gym", "key": "gym", "value": "Great Life", "mine": True,
                                "domain": "organizations"})
        self.assertIsNone(memory.parse_fact("remember to call the dentist"))


class NotYetIsASentenceInHerVoice(unittest.TestCase):
    def test_the_capability_line_is_the_first_clause_in_first_person(self):
        found = {"matches": [{"capability": "social.publish", "status": "NEEDS_CONFIGURATION",
                              "what_it_is": "Post a picture or a reel with a caption to your Instagram "
                                            "account, straight off this PC - one post per approval, never "
                                            "on its own",
                              "to_turn_it_on": ["I post through Instagram's own page, signed in as you "
                                                "in my own browser."]}]}
        with mock.patch("aletheia.self_knowledge.for_question", return_value=found), \
             mock.patch("aletheia.demand.record"):
            said = quick._can_you("post to instagram")
        self.assertTrue(said.startswith("Not yet — I can post a picture or a reel with a caption to your "
                                        "Instagram account, straight off this PC, but it needs setting up "
                                        "first."), said)
        self.assertNotIn("never on its own needs", said)
        self.assertNotIn("She ", said)


class AMissingRepositorySaysWhatItMeans(unittest.TestCase):
    class Source:
        def recent_commits(self, gh, branch):
            raise urllib.error.HTTPError("https://api.github.com/x", 404, "Not Found", {}, None)

        def read_json(self, *a):
            return {}

        def workflow_run(self, *a):
            return {"status": "completed", "conclusion": "success"}

        def file_exists(self, *a):
            return {"exists": False}

    def test_a_404_names_the_private_repository_and_the_token(self):
        import tempfile
        from pathlib import Path
        from aletheia import fleet, pulse
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        whole = fleet.load_fleet()
        one = dict(whole); one["repos"] = {"etsy_maker": whole["repos"]["etsy_maker"]}
        with mock.patch("aletheia.stateio.private_dir", lambda name: Path(tmp.name) / name):
            out = pulse.collect(one, self.Source())
        rec = out["repos"]["etsy_maker"]
        self.assertIn("private", rec["error"])
        self.assertIn("FLEET_TOKEN", rec["error"])
        self.assertNotIn("HTTPError", rec["error"], "a type name is not a sentence")


if __name__ == "__main__":
    unittest.main()
