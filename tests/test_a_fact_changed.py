"""2026-10-15, every model off: "the gate code is 4321", then "change the
gate code to 9876" went to the planner, and "change my wifi password to xyz"
did too."""
import unittest
from unittest import mock

from aletheia import intercom, quick, voice


class AFactChanged(unittest.TestCase):
    def test_the_new_fact_replaces_the_old(self):
        with mock.patch.object(quick, "_notes", return_value=[{"text": "the gate code is 4321"}]):
            got = voice._interpret("change the gate code to 9876")
        self.assertEqual(got["command"], {"kind": "note", "text": "the gate code is 9876",
                                          "replaces": "the gate code is 4321"})
        self.assertEqual(got["say"], "Updated: the gate code is 9876.")

    def test_nothing_told_is_not_a_change(self):
        with mock.patch.object(quick, "_notes", return_value=[]):
            got = voice._interpret("change the gate code to 9876")
        self.assertNotEqual((got.get("command") or {}).get("replaces"), "the gate code is 4321")

    def test_a_password_is_still_not_kept(self):
        got = voice._interpret("change my wifi password to xyz")
        self.assertIsNone(got["command"])
        self.assertIn("I don't keep passwords", got["say"])

    def test_the_old_one_is_tombstoned(self):
        from aletheia import journal
        with mock.patch.object(journal, "append") as wrote:
            intercom.execute_command({"kind": "note", "text": "the gate code is 9876",
                                      "replaces": "the gate code is 4321"}, {}, quote="t")
        rows = [c.args for c in wrote.call_args_list]
        self.assertIn(("note", "operator", "the gate code is 9876"), rows)
        self.assertIn(("note", intercom.FORGOTTEN_SUBJECT, "the gate code is 4321"), rows)


if __name__ == "__main__":
    unittest.main()
