"""Sixth sandbox batch, 2026-10-05, frontier off:

    > my address is 1 Test Road, Springfield XX   [4.0s] Here's what I'd do: Remember
                                                  that your address is ... Say approve
    > where do I live                             I don't have your address or city on
                                                  file. Tell me and I'll remember it.

"Tell me and I'll remember it" invited a sentence nothing deterministic
could take: the only path was the planner, which asked his approval to
remember his own address. `profile_set` is the kind now, with the fields he
can set by saying them, and `about_me` is the read he checks it with.

Also from the batch: "add eggs and bread to the shopping list" paid a
planner round trip and an approval for what "add milk" does in 0.0 s, when
the handler already splits "eggs and bread" into two rows; and "refused —
Nothing on your shopping list" was read back under "what did you do today".
"""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import intercom, quick, voice


class HeSaysItAndItIsOnFile(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        from aletheia import profile
        p = mock.patch.object(profile, "PROFILE_PATH", Path(self.tmp.name) / "profile.json", create=True)
        p.start(); self.addCleanup(p.stop)
        self.profile = profile

    def test_the_sentences_compile_with_his_capitals(self):
        for said, field, value in (
                ("my address is 1 Test Road, Springfield XX", "address", "1 Test Road, Springfield XX"),
                ("I live at 2 Sample Street", "address", "2 Sample Street"),
                ("my name is Pat Example", "name", "Pat Example"),
                ("call me Sam", "preferred_name", "Sam"),
                ("I live in Springfield, XX", "city", "Springfield, XX"),
                ("my email is pat@example.com", "email", "pat@example.com"),
                ("my phone number is 000 555 0100", "phone", "000 555 0100"),
                ("I work at Example Company", "current_employer", "Example Company"),
                ("my pronouns are he/him", "pronouns", "he/him")):
            cmd = voice.interpret(said)["command"]
            self.assertEqual(cmd, {"kind": "profile_set", "field": field, "value": value}, said)

    def test_the_round_trip_she_failed(self):
        with mock.patch("aletheia.journal.append"):
            said = intercom.execute_command(
                voice.interpret("my address is 1 Test Road, Springfield XX 00000")["command"], {}, quote="t")
            self.assertEqual(said, "Got it: your address is 1 Test Road, Springfield XX 00000.")
            known = self.profile.known()
        self.assertEqual(known.get("street"), "1 Test Road")
        self.assertEqual(known.get("city"), "Springfield")
        self.assertEqual(known.get("state"), "XX")
        self.assertEqual(known.get("postal_code"), "00000")

    def test_a_name_is_split_and_read_back(self):
        with mock.patch("aletheia.journal.append"):
            self.assertEqual(intercom.execute_command(voice.interpret("my name is Pat Example")["command"],
                                                      {}, quote="t"), "Got it: your name is Pat Example.")
            known = self.profile.known()
            self.assertEqual((known.get("first_name"), known.get("last_name")), ("Pat", "Example"))
            about = intercom.execute_command({"kind": "about_me"}, {}, quote="t")
        self.assertIn("Pat", about)

    def test_it_is_routine_not_an_approval(self):
        self.assertEqual(intercom.tier("profile_set"), intercom.tier("task_new"))
        self.assertIn("about_me", intercom.READ_ONLY_KINDS)

    def test_a_sensitive_field_cannot_be_set_by_the_grammar(self):
        from aletheia import profile
        for field in ("gender", "race", "veteran_status", "disability_status"):
            self.assertNotIn(field, profile.SPOKEN_FIELDS)
        self.assertTrue(intercom.validate_kind_args({"kind": "profile_set", "field": "race", "value": "x"}, {}))


class EggsAndBreadIsTwoRowsOnEveryDoor(unittest.TestCase):
    def test_the_plain_list_compiles_directly(self):
        cmd = voice.interpret("add eggs and bread to the shopping list")["command"]
        self.assertEqual(cmd, {"kind": "shopping_add", "item": "eggs and bread"})
        self.assertEqual(intercom.shopping_items_of("eggs and bread"), ["eggs", "bread"])

    def test_the_ambiguous_one_still_goes_to_the_planner(self):
        cmd = voice.interpret("add eggs milk and bread to the shopping list")["command"]
        self.assertNotEqual(cmd.get("kind"), "shopping_add")


class ARefusalIsNotSomethingSheDid(unittest.TestCase):
    def test_a_refused_command_is_journaled_as_an_event(self):
        from aletheia import act, core
        with mock.patch("aletheia.intercom.validate_kind_args", return_value=[]), \
             mock.patch("aletheia.policy.halted", return_value=False), \
             mock.patch("aletheia.intercom.execute_command", side_effect=act.Refused("Nothing on your list")), \
             mock.patch("aletheia.intercom.only_answers", return_value=False), \
             mock.patch("aletheia.journal.append") as appended:
            out = core._run_command({"kind": "shopping_off", "item": "milk"}, {})
        self.assertEqual(out["outcome"], "refused")
        self.assertEqual(appended.call_args[0][0], "event")


class TheNextMeetingHoweverHeAsks(unittest.TestCase):
    def test_phrasings(self):
        with mock.patch("aletheia.quick._next_meeting", return_value="Dentist at 2 pm."):
            for q in ("what time is my next meeting", "when am I next busy", "what's next on my calendar"):
                self.assertEqual(quick.answer(q), "Dentist at 2 pm.", q)


if __name__ == "__main__":
    unittest.main()
