"""The sentences that must never reach the planner, as one list.

Every individual pattern below has its own test somewhere. This is the
net under all of them, because the failure they share is invisible: a
sentence that falls out of the deterministic layer still produces a
perfectly valid `intent` command, so `test_every_sentence_compiles_to_a_
valid_command` passes on it. Nothing was red. It just took 25-80 seconds.

That is how "stop that" came to be a kill switch that did not stop
anything: `stop` halts, `stop that` compiled an intent, and the planner
is FORBIDDEN from emitting `halt` — so the emergency stop went to a model
that was not allowed to perform it.

Measured on the operator's PC by classifying 92 ordinary sentences:
27 of them reached the planner before this list existed, 19 after. The
ones still on the slow path are there on purpose — weather and timers she
cannot do, and near-misses like "what's on tomorrow" (which is not "am I
free tomorrow") where a fast wrong answer would be worse than a slow
right one.
"""
import unittest
from unittest import mock

from aletheia import places, quick, voice

# (sentence, what must handle it). "quick" means an answer out of a store,
# "say" a turn that ends in words, anything else the command kind the
# deterministic layer must compile. A sentence marked "quick" that a
# pattern compiles instead is fine and passes: what is being asserted is
# that it does not reach the model, not which of the two fast lanes takes
# it. "are you running" is one of those — `voice` has a `running` verb.
MUST_NOT_THINK = (
    # the kill switch, with the words he would really use
    ("stop", "halt"),
    ("stop that", "halt"),
    ("stop it", "halt"),
    ("stop now", "halt"),
    ("that's enough", "halt"),
    # ordinary verbs that already existed and could not be reached
    ("read me my tasks", "tasks"),
    ("tell me my tasks", "tasks"),
    ("what's on my todo list", "tasks"),
    ("what files do I have", "file_list"),
    ("what's my car's mileage", "car"),
    ("how many miles on my car", "car"),
    # answers she holds in a store
    ("hey", "quick"),
    ("hello", "quick"),
    ("good morning", "quick"),
    ("how are you", "quick"),
    ("what's my name", "quick"),
    ("who am I", "quick"),
    ("where do I live", "quick"),
    ("are you running", "quick"),
    ("you there", "quick"),
    # a turn that ends politely and asks for nothing
    ("thanks", "say"),
    ("thank you", "say"),
)

# The other half of every pattern above: what it must NOT swallow.
STILL_THE_PLANNER_OR_ANOTHER_VERB = (
    ("stop the music", "halt"),
    ("stop the timer", "halt"),
    ("stop reminding me about the trash", "halt"),
    ("thanks for that, add milk to the shopping list", "say"),
)


class NoRoundTripForThese(unittest.TestCase):
    # What she knows about him is a PREMISE here, not a property of the
    # machine. Read off his real stores, three of these sentences answer
    # on his PC and reach the planner in CI — which is exactly the shape
    # of bug this file was written to catch, one layer up.
    HIS = {"preferred_name": "Caleb", "first_name": "Caleb",
           "last_name": "Schulte", "legal_name": "Caleb Schulte",
           "city": "Hartford", "state": "SD"}
    NOTHING_WAITING = {"halted": False, "waiting_on_you": [],
                       "notifications": []}

    def setUp(self):
        # One pattern consults the place store; stub it so this says the
        # same thing on a machine with no saved places.
        for p in (mock.patch.object(places, "resolve",
                                    side_effect=KeyError("none")),
                  mock.patch("aletheia.profile.answer", self.HIS.get),
                  mock.patch("aletheia.policy.halted", lambda: None),
                  mock.patch("aletheia.presence.snapshot",
                             lambda: dict(self.NOTHING_WAITING))):
            p.start()
            self.addCleanup(p.stop)
        quick.warm()

    def lane(self, said):
        """(kind, quick answer) — the two ways a sentence avoids the model."""
        got = voice.interpret(said) or {}
        command = got.get("command") or {}
        kind = command.get("kind")
        if kind and kind != "intent":
            return kind, None
        if got.get("say") and not kind:
            return "say", None
        return kind or "intent", quick.answer(command.get("text") or said)

    def test_none_of_them_reach_the_planner(self):
        for said, wanted in MUST_NOT_THINK:
            with self.subTest(said=said):
                kind, fast = self.lane(said)
                self.assertTrue(
                    kind != "intent" or fast,
                    f"{said!r} reaches the planner with no stored answer")
                if wanted not in ("quick", "say"):
                    self.assertEqual(kind, wanted, f"{said!r} -> {kind}")

    def test_the_patterns_do_not_swallow_their_neighbours(self):
        for said, must_not_be in STILL_THE_PLANNER_OR_ANOTHER_VERB:
            with self.subTest(said=said):
                kind, _ = self.lane(said)
                self.assertNotEqual(
                    kind, must_not_be,
                    f"{said!r} was taken by {must_not_be} and is not that")

    def test_a_real_request_is_still_a_real_request(self):
        """The net must not have caught the things that need thinking."""
        # Chosen from the same measurement: these really do end at the
        # planner today, and must keep doing so. `research`, `meet` and
        # `apply` are NOT here — the deterministic layer already compiles
        # all three, which is worth knowing before adding a pattern for
        # something it can already do.
        for said in ("what's the weather tomorrow",
                     "how many days until christmas",
                     "set a timer for 10 minutes"):
            with self.subTest(said=said):
                kind, fast = self.lane(said)
                self.assertEqual(kind, "intent", said)
                self.assertIsNone(fast, f"{said!r} was answered from a store")


if __name__ == "__main__":
    unittest.main()
