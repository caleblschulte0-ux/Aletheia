""""Log a 3 mile run", "I went on a 3 mile run", "I did a 5k run"
(2026-10-14: a note nothing added up, a model, and a task ticked off) are
the run "I went for a 3 mile run" already kept, in the words the weekly
total adds up.
"""
import unittest
from unittest import mock

from aletheia import policy, voice


def said(sentence):
    with mock.patch.object(policy, "all_approvals", return_value=[]):
        return voice.interpret(f"thea {sentence}")["command"]


class ARunSaidAnyWay(unittest.TestCase):
    def test_each_is_kept_as_the_run(self):
        self.assertEqual(said("log a 3 mile run"), {"kind": "note", "text": "I ran 3 miles"})
        self.assertEqual(said("i went on a 3 mile run"), {"kind": "note", "text": "I ran 3 miles"})
        self.assertEqual(said("i did a 5k run"), {"kind": "note", "text": "I ran 5 k"})
        self.assertEqual(said("log a 30 minute walk"), {"kind": "note", "text": "I walked for 30 minutes"})

    def test_a_task_is_still_a_task(self):
        self.assertEqual(said("i did the dishes")["kind"], "task_done")


class WhichFridayForATask(unittest.TestCase):
    def test_due_next_friday_asks_which_friday(self):
        with mock.patch.object(policy, "all_approvals", return_value=[]), \
                mock.patch.object(voice, "_names_one_open_task", return_value=True):
            got = voice.interpret("thea make the passport one due next friday")
        from aletheia import localtime
        if localtime.today().weekday() != 4:
            self.assertTrue(got["say"].startswith("Which Friday"), got)

    def test_the_answer_to_which_friday_sets_that_day(self):
        import datetime as dt
        from aletheia import localtime
        today = localtime.today()
        ahead = (4 - today.weekday()) % 7
        soon = today + dt.timedelta(days=ahead)
        later = soon + dt.timedelta(days=7)
        question = (f"Which Friday — the {voice._ordinal(soon.day)}, "
                    f"or the week after on the {voice._ordinal(later.day)}?")
        with mock.patch.object(voice, "_previous_turn", return_value=("make the passport one due next friday", question)), \
                mock.patch.object(voice, "_previous_ask", return_value="make the passport one due next friday"), \
                mock.patch.object(voice, "_names_one_open_task", return_value=True):
            got = said(f"the {voice._ordinal(later.day)}")
        self.assertEqual((got["kind"], got["which"], got["deadline"]), ("task_change", "passport", later.isoformat()))


if __name__ == "__main__":
    unittest.main()
