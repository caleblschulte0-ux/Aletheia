"""What she's done, on his page, as a person would write it (2026-09-24).

The live page showed: "apply: was refused by the site at jobs.ashbyhq.com
- not counted as sent: The site handed it back rather than accepting it —
it says "We   went wrong" - a subject label on a sentence, a cut inside an
open quote, a lowercase start, and the same line twice in a row.
"""
from __future__ import annotations

import unittest
from unittest import mock

from aletheia import needs_you, recollection


class ARowIsASentence(unittest.TestCase):
    def test_a_long_line_is_cut_at_a_clause_never_inside_a_quote(self):
        text = ("was refused by the site at jobs.ashbyhq.com - not counted as sent: The site handed it back "
                "rather than accepting it — it says \"We have flagged this application as possible spam and it "
                "will not be considered by the hiring team\" - so nothing went out and nothing will be pressed again")
        said = recollection._whole_words(text, 200)
        self.assertLessEqual(len(said), 202)
        self.assertEqual(said.count('"') % 2, 0, said)
        self.assertTrue(said.endswith("…"), said)
        self.assertNotIn('it says "We', said)
        self.assertEqual(recollection._whole_words("short", 200), "short")

    def test_apply_and_jobs_lines_carry_no_label_and_start_with_a_capital(self):
        row = recollection._row({"ts": "2026-09-24T20:00:00Z", "kind": "action", "actor": "aletheia-apply",
                                 "subject": "apply", "text": "was refused by the site at jobs.ashbyhq.com"})
        self.assertTrue(row["what"].startswith("Was refused by the site"), row["what"])
        row = recollection._row({"ts": "2026-09-24T20:00:00Z", "kind": "note", "actor": "aletheia-campaign",
                                 "subject": "jobs", "text": "I found 14009 openings today, 81 of them realistic"})
        self.assertTrue(row["what"].startswith("I found 14009 openings"), row["what"])


class TheSameSentenceIsPrintedOnce(unittest.TestCase):
    def test_a_verbatim_repeat_folds_to_one_row_with_a_count(self):
        same = "Was refused by the site at jobs.ashbyhq.com - not counted as sent"
        rows = [{"at": "2026-09-24T21:16:00Z", "what": same, "outcome": "failed"},
                {"at": "2026-09-24T20:33:00Z", "what": same, "outcome": "failed"},
                {"at": "2026-09-24T16:59:00Z", "what": "I found 14009 openings today", "outcome": "finished"}]
        with mock.patch.object(needs_you, "_finished_and_failed", return_value=rows), \
                mock.patch.object(needs_you, "_unattended", return_value=[]):
            out = needs_you.activity(hours=24, limit=30)
        self.assertEqual([r["what"] for r in out], [f"{same} (twice)", "I found 14009 openings today"])
        self.assertEqual(out[0]["at"], "2026-09-24T21:16:00Z", "the newest is the one kept")

    def test_different_outcomes_are_different_rows(self):
        rows = [{"at": "2026-09-24T21:16:00Z", "what": "Sent it", "outcome": "finished"},
                {"at": "2026-09-24T20:33:00Z", "what": "Sent it", "outcome": "failed"}]
        with mock.patch.object(needs_you, "_finished_and_failed", return_value=rows), \
                mock.patch.object(needs_you, "_unattended", return_value=[]):
            self.assertEqual(len(needs_you.activity(hours=24, limit=30)), 2)


if __name__ == "__main__":
    unittest.main()
