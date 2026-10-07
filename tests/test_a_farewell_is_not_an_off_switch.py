""""See you later" shut her down; a nod went to the planner."""
import unittest
from unittest import mock

from aletheia import voice


def out(said):
    return voice._interpret(said) or {}


class AFarewellIsNotAnOffSwitch(unittest.TestCase):
    def test_see_you_later_does_not_close_her(self):
        self.assertNotEqual((out("see you later").get("command") or {}).get("kind"), "close")

    def test_turn_yourself_off_still_closes_her(self):
        self.assertEqual(out("turn yourself off")["command"]["kind"], "close")


class ANod(unittest.TestCase):
    def test_ok_with_nothing_waiting(self):
        with mock.patch("aletheia.policy.all_approvals", return_value=[]):
            for said in ("ok", "cool", "got it", "sounds good"):
                self.assertEqual(out(said), {"command": None, "say": "Okay."}, said)

    def test_ok_with_something_waiting_is_not_swallowed(self):
        with mock.patch("aletheia.policy.all_approvals", return_value=[{"id": "a", "state": "PENDING"}]):
            self.assertNotEqual(out("ok").get("say"), "Okay.")


if __name__ == "__main__":
    unittest.main()
