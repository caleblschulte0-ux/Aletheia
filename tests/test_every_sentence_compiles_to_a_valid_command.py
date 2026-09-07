"""What the deterministic layer emits has to be a command the Core accepts.

`voice.interpret` builds command dicts by hand in about forty places. A
typo in one of them — a missing arg, a renamed key, a kind that no longer
exists — is invisible until he says that particular sentence, and then it
fails at the grammar gate with an approval already offered.

So: a corpus of sentences a person really says, every one of them run
through the real interpreter, and every command it produces validated
against `intercom.KIND_ARGS` — the same check the Core does. It is not a
test of the ANSWERS (that is what talking to her is for); it is a test
that nothing she compiles is malformed.
"""
import unittest
from unittest import mock

from aletheia import fleet as fleet_mod, intercom, places, voice

SENTENCES = [
    # the switch
    "stop", "stop everything", "halt", "resume",
    # tasks
    "add a task to call the plumber", "new task: pay rent by friday",
    "what are my tasks", "task list", "tasks", "what do I have to do",
    "mark the passport one done", "finished the passport one",
    # reminders
    "remind me at 3 to call the dentist", "remind me at noon to eat",
    "remind me every day at 8 am to stretch",
    "remind me every monday to take out the trash",
    "remind me every tuesday and thursday at 6pm to go to the gym",
    "remind me in 20 minutes to check the oven",
    "what reminders do I have", "stop reminding me about the trash",
    "cancel the reminder about the gym",
    # notifications
    "snooze that for an hour", "snooze that", "what's waiting on me",
    # the shopping list
    "add milk to the shopping list", "put bread on the shopping list",
    "what's on my shopping list", "take milk off my shopping list",
    # memory and contacts
    "remember person Dana dana at example.com",
    "what do you know about my car", "list my contacts",
    "what's my mom's number", "what are you watching for",
    "tell me when I get an email from dana",
    # the world she reads
    "check email", "what's in my inbox", "read example.com",
    "research whether the boiler is under warranty",
    "what files do I have", "give me the brief", "am I free tomorrow afternoon",
    "how much money do I have", "what am I paying for",
    "what have I applied to", "what's my car's mileage",
    # meetings and journeys
    "set up a meeting with dana next week",
    "how long to get to the airport",
    # her own state
    "are you halted", "what time is it", "what day is it",
    "what did you do today", "what did you do yesterday",
    "what do you still need from me",
]


class EverySentenceCompilesCleanly(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fleet = fleet_mod.load_fleet()

    def test_no_sentence_produces_a_malformed_command(self):
        # The place store is consulted by one pattern; stub it so this
        # test says the same thing on a machine with no saved places.
        with mock.patch.object(places, "resolve", side_effect=KeyError("none")):
            for said in SENTENCES:
                with self.subTest(said=said):
                    got = voice.interpret(said)
                    command = got.get("command")
                    if command is None:
                        self.assertTrue(got.get("say"), "neither a command nor words")
                        continue
                    problems = intercom.validate_kind_args(command, self.fleet)
                    self.assertEqual(problems, [], f"{said!r} -> {command}")

    def test_every_sentence_produces_something(self):
        with mock.patch.object(places, "resolve", side_effect=KeyError("none")):
            for said in SENTENCES:
                got = voice.interpret(said)
                self.assertTrue(got.get("command") or got.get("say"), said)

    def test_the_corpus_covers_the_verbs_it_claims_to(self):
        # A corpus that quietly stops reaching a verb is a test that
        # passes because it checks nothing.
        with mock.patch.object(places, "resolve", side_effect=KeyError("none")):
            kinds = {(voice.interpret(s).get("command") or {}).get("kind")
                     for s in SENTENCES}
        for expected in ("task_new", "tasks", "task_done", "remind_at",
                         "remind_daily", "remind_weekly", "reminders",
                         "reminder_off", "notify_snooze", "shopping_add",
                         "shopping_list", "shopping_off", "contacts",
                         "watches", "applications", "halt", "resume"):
            self.assertIn(expected, kinds, f"nothing in the corpus reaches {expected}")


if __name__ == "__main__":
    unittest.main()
