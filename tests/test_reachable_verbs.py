"""The verbs she already had, now sayable.

72 capabilities were AVAILABLE and 29 were reachable by talking to her.
Everything here fronts a capability that was already built, tested and
registered — with a real CLI caller — and simply could not be asked for
from the one channel he actually uses. `meeting.negotiate` was the worst
case: a whole multi-day negotiation engine, unreachable by voice.

Adding a kind widens the PLANNER too, because its prompt is generated from
KIND_ARGS. That is the multiplier and it is asserted below.
"""
import unittest
from unittest import mock

from aletheia import intercom, planner, voice

FLEET = {"repos": {}}

NEW_KINDS = ["meet", "recall", "brief", "handle", "travel_time",
             "shopping_add", "subscriptions", "money", "car", "projects"]


class GrammarCase(unittest.TestCase):
    def test_every_new_verb_is_in_the_grammar(self):
        for kind in NEW_KINDS:
            self.assertIn(kind, intercom.KIND_ARGS, kind)

    def test_the_private_state_verbs_run_on_the_pc(self):
        # The partition is static and disjoint: LOCAL_KINDS run on the Core,
        # everything else in Actions. Anything touching state/private/ must
        # be local — that data only exists on his machine.
        for kind in [k for k in NEW_KINDS if k != "brief"]:
            self.assertIn(kind, intercom.LOCAL_KINDS, kind)

    def test_brief_may_run_on_either_side(self):
        # brief reads the pulse and journal from the repo working copy, which
        # both sides have — and Actions is where the pulse is freshest. Voice
        # still works either way: /api/voice executes inline and never
        # consults LOCAL_KINDS.
        self.assertNotIn("brief", intercom.LOCAL_KINDS)

    def test_the_planner_gained_the_vocabulary(self):
        # the multiplier: an arbitrary sentence can now compile into these
        brief = planner.grammar_brief()
        for kind in NEW_KINDS:
            self.assertIn(kind, brief, kind)

    def test_required_arguments_are_enforced_like_any_other_kind(self):
        for kind, missing in (("meet", "person"), ("recall", "about"),
                              ("handle", "text"), ("travel_time", "place"),
                              ("shopping_add", "item")):
            problems = intercom.validate_kind_args({"kind": kind}, FLEET)
            self.assertTrue(problems, kind)
            self.assertIn(missing, problems[0], kind)

    def test_argument_free_verbs_take_no_arguments(self):
        for kind in ("brief", "subscriptions", "money", "projects"):
            self.assertEqual(
                intercom.validate_kind_args({"kind": kind}, FLEET), [], kind)
            self.assertTrue(
                intercom.validate_kind_args({"kind": kind, "extra": "x"}, FLEET), kind)


class SpokenCase(unittest.TestCase):
    def kind_of(self, phrase):
        out = voice.interpret(f"thea {phrase}")
        return out["command"]["kind"] if out["command"] else None

    def test_the_phrases_a_person_would_use(self):
        for phrase, kind in [
                ("set up a meeting with dana next week", "meet"),
                ("arrange a call with dana", "meet"),
                ("what do you know about dana", "recall"),
                ("my morning brief", "brief"),
                ("what did i miss", "brief"),
                ("handle it: chase the landlord", "handle"),
                ("how long to get to the office", "travel_time"),
                ("add milk to the shopping list", "shopping_add"),
                ("what am i paying for", "subscriptions"),
                ("whats my balance", "money"),
                ("when is the car due", "car"),
                ("what am i working on", "projects")]:
            self.assertEqual(self.kind_of(phrase), kind, phrase)

    def test_the_new_patterns_did_not_steal_the_old_ones(self):
        for phrase, kind in [
                ("read example dot com", "browse_read"),
                ("check my email", "email_check"),
                ("what is on my screen", "screen_ask"),
                ("add a task to water the plants", "task_new"),
                ("make me a sandwich", "intent")]:
            self.assertEqual(self.kind_of(phrase), kind, phrase)

    def test_status_is_still_answered_locally_without_a_command(self):
        self.assertIsNone(self.kind_of("whats going on"))

    def test_a_bare_handle_it_is_not_a_command_without_a_subject(self):
        # "handle it" alone has no referent; it must not become an empty request
        self.assertNotEqual(self.kind_of("handle it"), "handle")


class ExecutionCase(unittest.TestCase):
    """Each verb answers honestly when its store is empty."""

    def run_kind(self, **cmd):
        return intercom.execute_command(cmd, FLEET)

    def test_empty_stores_say_so_rather_than_inventing(self):
        for cmd, expect in (({"kind": "subscriptions"}, "No subscriptions"),
                            ({"kind": "projects"}, "No active projects"),
                            ({"kind": "car"}, "No vehicle")):
            self.assertIn(expect, self.run_kind(**cmd), cmd)

    def test_money_reports_zero_rather_than_silence(self):
        said = self.run_kind(kind="money")
        self.assertIn("net", said.lower())

    def test_recall_admits_when_it_knows_nothing(self):
        said = self.run_kind(kind="recall", about="a person who does not exist")
        self.assertIn("don't have anything", said)

    def test_travel_time_refuses_to_guess_an_unobserved_journey(self):
        from aletheia import places
        with mock.patch.object(places, "resolve",
                               side_effect=lambda q: {"id": q, "name": q.title()}), \
             mock.patch.object(places, "travel_time",
                               side_effect=ValueError("never observed")):
            said = self.run_kind(kind="travel_time", place="the office")
        self.assertIn("guess", said)

    def test_travel_time_needs_a_home_to_measure_from(self):
        from aletheia import places

        def resolve(query):
            if query == "home":
                raise ValueError("no such place")
            return {"id": query, "name": query.title()}

        with mock.patch.object(places, "resolve", side_effect=resolve):
            said = self.run_kind(kind="travel_time", place="the office")
        self.assertIn("no place called", said)

    def test_meet_starts_a_real_negotiation(self):
        from aletheia import scheduling
        with mock.patch.object(scheduling, "start",
                               return_value={"state": "OFFERING", "slots": [1, 2],
                                             "person": "Dana",
                                             "send_approval": "mail-x"}) as start, \
             mock.patch.object(scheduling, "spoken", return_value="drafted"):
            said = self.run_kind(kind="meet", person="dana")
        self.assertEqual(said, "drafted")
        self.assertEqual(start.call_args.args[1], "dana")

    def test_handle_persists_the_request(self):
        from aletheia import handler
        with mock.patch.object(handler, "create",
                               return_value={"intent": "chase the landlord",
                                             "state": "IN_PROGRESS"}) as create:
            said = self.run_kind(kind="handle", text="chase the landlord")
        create.assert_called_once()
        self.assertIn("chase the landlord", said)


class VehicleListingCase(unittest.TestCase):
    def test_vehicles_can_now_be_listed(self):
        # `due()` needed an id and nothing could list them, so "when is the
        # car due?" had no answer even when the data existed
        from aletheia import vehicles
        self.assertTrue(callable(vehicles.all_vehicles))
        self.assertIsInstance(vehicles.all_vehicles(), list)


if __name__ == "__main__":
    unittest.main()
