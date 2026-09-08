"""A decoration should not change what she does.

Every deterministic pattern in `voice.py` and `quick.py` is anchored at
the start of the sentence. So on 2026-09-06:

    "remind me at 4 to celebrate"      -> instant, no approval
    "🎉 remind me at 4 to celebrate 🎉"  -> five seconds through the
                                          planner, and an approval

Same words, same action, different answer — decided by an emoji. The
same was true of "uh", "so", "ok" and "hey", which is how people
actually start sentences out loud.
"""
import unittest
from unittest import mock

from aletheia import intents, quick, voice


class FillerCase(unittest.TestCase):
    def test_a_decoration_does_not_change_the_command(self):
        plain = voice.interpret("thea remind me at 4 to celebrate")["command"]
        for dressed in ("🎉 remind me at 4 to celebrate 🎉",
                        "uh remind me at 4 to celebrate",
                        "ok so hey remind me at 4 to celebrate",
                        "um, remind me at 4 to celebrate",
                        "...remind me at 4 to celebrate"):
            with self.subTest(said=dressed):
                got = voice.interpret(f"thea {dressed}")["command"]
                self.assertEqual(got["kind"], plain["kind"], dressed)
                self.assertEqual(got["at"], plain["at"], dressed)

    def test_the_fast_lane_uses_the_same_rule(self):
        """Two doors that disagree about what counts as filler is one door
        answering instantly and the other paying a planner round trip."""
        for dressed in ("so what did you do today", "uh are you halted",
                        "🎉 are you halted", "ok whats waiting on me"):
            with self.subTest(said=dressed):
                self.assertIsNotNone(quick.match(dressed), dressed)

    def test_a_sentence_that_is_ONLY_filler_is_left_alone(self):
        """"Uh" and "ok" are not commands, and stripping them to nothing
        must not turn them into one."""
        for said in ("uh", "ok", "um"):
            with self.subTest(said=said):
                self.assertIsNone(quick.match(said), said)
                got = voice.interpret(f"thea {said}")["command"]
                self.assertEqual(got["kind"], "intent", said)

    def test_hey_on_its_own_is_a_greeting_and_not_a_command(self):
        """"Hey" is filler IN FRONT of a sentence and a greeting alone.

        It was listed with "uh" and "ok" above, which was right when the
        fast lane had nothing to say to it. The rule that list protects
        is that stripping filler to nothing must not INVENT A COMMAND —
        and it still does not. What changed is that "hey" by itself is
        answered from `presence` instead of paying 25-80 seconds to be
        greeted back, and answering a greeting is not compiling one.
        """
        self.assertEqual((quick.match("hey") or (None,))[0], "greeting")
        self.assertIsNone(quick.match("uh hey"), "still filler in front")
        got = voice.interpret("thea hey")["command"]
        self.assertEqual(got["kind"], "intent", "no command was invented")

    def test_words_that_look_like_filler_but_carry_meaning_survive(self):
        for said, expect in (("like a boss", "like a boss"),
                             ("ok computer", "ok computer"),
                             ("so long and thanks", "so long and thanks")):
            with self.subTest(said=said):
                got = voice.interpret(f"thea {said}")["command"]
                self.assertEqual(got["kind"], "intent")
                self.assertEqual(got["text"], expect)

    def test_the_kill_switch_still_hears_it_through_filler(self):
        self.assertEqual(
            voice.interpret("thea um, halt")["command"]["kind"], "halt")
        self.assertEqual(
            voice.interpret("thea please resume")["command"]["kind"], "resume")


class WhyItAsksCase(unittest.TestCase):
    """"Add a task to renew my registration" runs instantly. "Mark the
    registration one done" asks for approval. Same risk class, and the
    only difference is whether somebody wrote a regex for that phrasing.

    The gate is not the thing to change — `aletheia.standing` exists so he
    can say yes once for the whole routine tier, and it is deliberately
    not grantable by voice because the room microphone is unauthenticated.
    What was missing is that nothing told him the command existed at the
    moment he was being asked.
    """

    def setUp(self):
        # The throttle marker is a real file in private state, so it
        # leaks between tests in the same run. Each test starts with the
        # nudge due.
        from aletheia import stateio
        marker = stateio.private_dir("nudges") / "standing.json"
        if marker.exists():
            marker.unlink()
        self.addCleanup(lambda: marker.exists() and marker.unlink())

    ROUTINE = {"tier": "routine", "intent": "plan", "summary": "remember it",
               "approval": "intent-x",
               "steps": [{"n": 1, "status": "EXECUTABLE", "capability": None,
                          "command": {"kind": "remember"}, "detail": ""}]}

    def test_a_routine_ask_names_the_command_that_stops_it(self):
        with mock.patch.object(intents, "_due_to_mention", lambda *a: True), \
             mock.patch("aletheia.authority.active_grants", lambda: []):
            said = intents.spoken(dict(self.ROUTINE))
        self.assertIn("aletheia.standing on", said)

    def test_it_is_not_repeated_every_time(self):
        """Three replies in a row carrying it — out loud, in a room — is
        what teaches him to stop listening."""
        with mock.patch("aletheia.authority.active_grants", lambda: []):
            first = intents.spoken(dict(self.ROUTINE))
            second = intents.spoken(dict(self.ROUTINE))
        self.assertIn("aletheia.standing on", first)
        self.assertNotIn("aletheia.standing on", second)

    def test_nothing_is_said_once_the_grant_exists(self):
        with mock.patch.object(intents, "_due_to_mention", lambda *a: True), \
             mock.patch("aletheia.authority.active_grants",
                        lambda: [{"id": "standing-routine"}]):
            said = intents.spoken(dict(self.ROUTINE))
        self.assertNotIn("aletheia.standing on", said)

    def test_a_gap_step_carries_no_command_and_must_not_crash(self):
        """A GAP or MANUAL step has the key with the value None, and
        `None.get` is an AttributeError in the middle of a sentence."""
        with_gap = dict(self.ROUTINE, steps=[
            {"n": 1, "status": "EXECUTABLE", "capability": None,
             "command": {"kind": "remember"}, "detail": ""},
            {"n": 2, "status": "GAP", "capability": "room.scene",
             "command": None, "detail": "NEEDS_CONFIGURATION"}])
        with mock.patch("aletheia.authority.active_grants", lambda: []):
            said = intents.spoken(with_gap)
        self.assertTrue(said.strip())

    def test_it_is_never_offered_beside_a_deletion(self):
        """Each delete keeps a version, so the tier is right — but "2 steps
        ready — Delete all files in your workspace. Say approve. I ask
        about small local things like this until you run `standing on`"
        reads as "shall I make bulk deletion automatic?"."""
        deleting = dict(self.ROUTINE, steps=[
            {"n": 1, "status": "EXECUTABLE", "capability": None,
             "command": {"kind": "file_delete", "path": "a"}, "detail": ""}])
        with mock.patch.object(intents, "_due_to_mention", lambda *a: True), \
             mock.patch("aletheia.authority.active_grants", lambda: []):
            said = intents.spoken(deleting)
        self.assertNotIn("standing", said)

    def test_a_world_touching_ask_never_suggests_it(self):
        """Standing authority only ever covers the routine tier. Offering
        it against something that sends or spends would be a lie about
        what the command does."""
        world = dict(self.ROUTINE, tier="world")
        with mock.patch.object(intents, "_due_to_mention", lambda *a: True), \
             mock.patch("aletheia.authority.active_grants", lambda: []):
            said = intents.spoken(world)
        self.assertNotIn("standing", said)

    def test_an_already_approved_plan_does_not_ask_him_to_approve_it(self):
        """A standing grant makes the approval APPROVED on creation. "Say
        approve to run it" then sends him looking for a decision that has
        already been made."""
        covered = dict(self.ROUTINE, approval_state="APPROVED")
        said = intents.spoken(covered)
        self.assertNotIn("Say approve", said)
        self.assertIn("standing authority", said)


if __name__ == "__main__":
    unittest.main()
