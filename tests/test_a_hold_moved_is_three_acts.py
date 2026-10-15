"""2026-10-15: "block off 2 to 3 tomorrow for focus time", "move focus
time to 4", "cancel focus time", then "what did you do today" answered:

    Today: Pencilled in Focus time (tentative, her calendar only); Moved
    Focus time to tomorrow at 4 pm, tentative, on your calendar here only;
    Took Focus time tomorrow at 4 pm off your calendar - and 3 other things.

The hold store and the command path both journal each act, the store's
line talked about her in the third person, and three acts were six."""

import unittest

from aletheia import quick, recollection


def _rows(*whats):
    return [{"what": w, "at": "10:00", "kind": "action", "who": "x"} for w in whats]


class AHoldMovedIsThreeActs(unittest.TestCase):

    def test_the_store_lines_beside_the_command_lines_are_dropped(self):
        rows = _rows(
            "Pencilled in Focus time (tentative, on your calendar here only)",
            "Pencilled in Focus time tomorrow at 2 pm, tentative, on your calendar here only.",
            "Released the hold on Focus time",
            "Pencilled in Focus time (tentative, on your calendar here only)",
            "Moved Focus time to tomorrow at 4 pm, tentative, on your calendar here only.",
            "Released the hold on Focus time",
            "Took Focus time tomorrow at 4 pm off your calendar.",
        )
        self.assertEqual([r["what"] for r in recollection._once_each(rows)], [
            "Pencilled in Focus time tomorrow at 2 pm, tentative, on your calendar here only.",
            "Moved Focus time to tomorrow at 4 pm, tentative, on your calendar here only.",
            "Took Focus time tomorrow at 4 pm off your calendar.",
        ])

    def test_a_hold_nobody_asked_for_out_loud_is_still_said(self):
        # A mission pencils things in with no command line beside it.
        rows = _rows("Pencilled in Tails on the Trail (tentative, on your calendar here only)",
                     "Added a task: call the vet")
        self.assertEqual(len(recollection._once_each(rows)), 2)

    def test_the_list_drops_the_caveat(self):
        said = quick._listed(_rows(
            "Pencilled in Focus time tomorrow at 2 pm, tentative, on your calendar here only.",
            "Took Focus time tomorrow at 4 pm off your calendar."), "today")
        self.assertEqual(said, "Today: Pencilled in Focus time tomorrow at 2 pm; "
                               "Took Focus time tomorrow at 4 pm off your calendar.")

    def test_the_store_says_your_calendar(self):
        import inspect
        from aletheia import calendar_reasoning
        self.assertNotIn("her calendar", inspect.getsource(calendar_reasoning.hold))


if __name__ == "__main__":
    unittest.main()
