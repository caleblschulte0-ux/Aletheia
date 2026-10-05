"""Thirtieth sandbox batch, 2026-10-05: the kill switch in a rehearsal, standing
permission, a duplicate task, and sums a model was doing.

    > halt (rehearsal)                        "it would reach past this machine"
    > add a task to call the bank, twice      two tasks
    > give yourself standing permission ...   "I couldn't make sense of part of that"
    > what standing permissions do you have   [6.0s] a model
    > how many ounces in a pound / 15 percent off 80 / a third of 90 / double 45
                                              four models, 3.5 to 8 seconds
"""
import os
import unittest
from unittest import mock

from aletheia import act, intercom, quick, tasks


class TheSwitchesInARehearsal(unittest.TestCase):
    def test_the_refusal_does_not_claim_the_world(self):
        with mock.patch.dict(os.environ, {intercom.REHEARSAL: "1"}):
            with self.assertRaises(act.Refused) as caught:
                intercom.execute_command({"kind": "halt"}, {"repos": {}})
        said = str(caught.exception)
        self.assertIn("I didn't halt", said)
        self.assertNotIn("reach past this machine", said)


class ADuplicateTask(unittest.TestCase):
    def test_the_same_words_are_the_same_task(self):
        import uuid
        tag = uuid.uuid4().hex[:6]
        first = intercom.execute_command({"kind": "task_new", "id": f"walk-the-dog-{tag}", "description": f"walk the dog {tag}"}, {"repos": {}})
        again = intercom.execute_command({"kind": "task_new", "id": f"walk-the-dog-{tag}-2", "description": f"walk the dog {tag}"}, {"repos": {}})
        self.assertIn("queued", first)
        self.assertIn("already on your list", again)
        self.assertEqual(len([x for x in tasks.all_tasks() if x.get("description") == f"walk the dog {tag}"]), 1)


class StandingPermission(unittest.TestCase):
    def test_it_is_read_live_and_granted_at_the_keyboard(self):
        said = quick.answer("what standing permissions do you have")
        self.assertRegex(said, r"^I answer \d+ kinds of question without asking;")
        self.assertIn("aletheia.standing on", said)
        self.assertIn("aletheia.interviews on", said)
        asked = quick.answer("give yourself standing permission for calendar holds")
        self.assertTrue(asked.startswith("I can't grant myself anything, including calendar holds."), asked)
        self.assertIn("never by voice", asked)


class Sums(unittest.TestCase):
    def test_the_arithmetic_a_person_asks(self):
        self.assertEqual(quick.answer("what's 15 percent off 80"), "68 - that's 12 off.")
        self.assertEqual(quick.answer("what's 20 percent off 50 dollars"), "$40 - that's $10 off.")
        self.assertEqual(quick.answer("what's a third of 90"), "30.")
        self.assertEqual(quick.answer("what's three quarters of 80"), "60.")
        self.assertEqual(quick.answer("double 45"), "90.")
        self.assertEqual(quick.answer("what's half of 90 dollars"), "$45.")
        self.assertEqual(quick.answer("how many ounces in a pound"), "16 ounces in a pound.")
        self.assertEqual(quick.answer("how many feet in a mile"), "5,280 feet in a mile.")
        self.assertEqual(quick.answer("how many teaspoons in a tablespoon"), "3 teaspoons in a tablespoon.")
        self.assertIsNone(quick.answer("how many ounces in a week"))


if __name__ == "__main__":
    unittest.main()
