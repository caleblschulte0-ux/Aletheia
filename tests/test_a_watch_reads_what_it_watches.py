"""A recurring watch reads what the finished work it is about found (his PC, 2026-10-11).

"Watch shortlisted cities for roles and cost changes" ran after the comparison that chose the
shortlist was DONE, and said no shortlist had been chosen: an occurrence has no needs, so the
comparison's findings never reached it.
"""

import unittest

from aletheia import program_run, programs, work_states as ws


def _t(key, title, does, *, state=ws.DONE, said="", activity=None, workstream="w1", at="2026-10-11T17:07:00Z"):
    return {"key": key, "title": title, "does": does, "state": state, "from_activity": activity,
            "workstream": workstream, "needs": [], "updated_at": at,
            "results": [{"outcome": "ok", "said": said, "at": at}] if said else []}


class AWatchReadsWhatItWatches(unittest.TestCase):
    def setUp(self):
        self.compare = _t("t10", "Compare a shortlist of warm red-state cities",
                          ["compare warm red-state cities on cost of living, taxes, housing and jobs"],
                          said="Shortlist: Tampa, Austin, Nashville, Charleston.")
        self.unrelated = _t("t4", "Save Caleb's answers as preferences", ["write his answers down"],
                            said="Wrote preferences.json")
        self.other_stream = _t("t9", "Compare shortlisted gyms", ["compare gyms"], said="Gyms: A, B",
                               workstream="w2")
        self.watch = _t("a3-1", "Watch shortlisted cities for roles and cost changes",
                        ["look for new matching postings in shortlisted cities"], state=ws.READY,
                        activity="a3")
        self.record = {"tasks": [self.compare, self.unrelated, self.other_stream, self.watch]}

    def test_the_shortlist_reaches_the_watch(self):
        found = program_run._found(self.record, self.watch, answers=False)
        self.assertIn("Shortlist: Tampa, Austin, Nashville, Charleston.", found)
        self.assertNotIn("Wrote preferences.json", found)
        self.assertNotIn("Gyms: A, B", found)

    def test_unfinished_work_is_not_read_as_found(self):
        self.compare["state"] = ws.RUNNING if hasattr(ws, "RUNNING") else ws.READY
        self.assertEqual(programs.what_it_watches(self.record, self.watch), [])

    def test_a_task_that_is_not_recurring_reads_only_its_needs(self):
        task = _t("t11", "Find events in the shortlisted cities", ["search events"], state=ws.READY)
        self.record["tasks"].append(task)
        self.assertNotIn("Shortlist: Tampa, Austin, Nashville, Charleston.",
                         program_run._found(self.record, task, answers=False))


if __name__ == "__main__":
    unittest.main()
