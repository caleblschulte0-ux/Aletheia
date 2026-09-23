"""Seven questions put to the live Core on his PC at 10:18Z, 2026-09-23,
with his real data. Three answers were wrong in their words:

- "48 openings found today" - the campaign had seen 1,137; 48 was the
  number FILLED IN.
- "the site refused the form - the site refused it: The site handed it
  back rather than accepting it - it says ..." - one refusal, said three times.
- "17 notes: ...; (voice, unmatched) answer have shaped yeah; ..." - the
  room's unmatched transcripts listed as his notes.
"""
import datetime as dt
import unittest
from unittest import mock

from aletheia import quick

NOW = dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")


class FoundIsWhatTheHuntSaw(unittest.TestCase):
    def test_the_campaigns_own_count_wins(self):
        note = {"ts": NOW, "kind": "note", "subject": "jobs", "actor": "aletheia-campaign",
                "text": "I found 1137 openings today, 27 of them realistic for you; 1 of them looks unusually good"}
        with mock.patch("aletheia.journal.entries", return_value=[note]), \
             mock.patch("aletheia.current_state.job_hunt", return_value={"today": {"discovered": 48, "qualified": 48, "sent": 22}}):
            self.assertEqual(quick.answer("how many jobs have you found today"),
                             "1137 openings found today, 27 worth applying to, 22 sent.")

    def test_without_the_note_the_staged_count_is_called_filled_in(self):
        with mock.patch("aletheia.journal.entries", return_value=[]), \
             mock.patch("aletheia.current_state.job_hunt", return_value={"today": {"discovered": 48, "qualified": 48, "sent": 22}}):
            self.assertEqual(quick.answer("how many jobs have you found today"), "48 openings filled in today, 22 sent.")


class ARefusalSaidOnce(unittest.TestCase):
    def test_the_sites_words_are_quoted_once(self):
        rec = {"id": "apply-1", "state": "REJECTED", "company": "Tenex", "job_title": "Business Operations Analyst",
               "failure": "the site refused it: The site handed it back rather than accepting it — it says "
                          "\"We're updating your application (e.g. uploading files), please try again when they're finished.\". "
                          "Nothing was accepted; read what it wants and I will fix it and try again."}
        with mock.patch("aletheia.apply_run.find", return_value=[rec]), \
             mock.patch("aletheia.apply_run.describe", return_value="Business Operations Analyst — Tenex"):
            said = quick.answer("why didn't the Tenex one go")
        self.assertEqual(said, "Business Operations Analyst — Tenex: the site handed it back - it says "
                               "\"We're updating your application (e.g. uploading files), please try again when they're finished.\".")
        self.assertEqual(said.lower().count("refus") + said.lower().count("handed"), 1)


class TheRoomsTranscriptsAreNotNotes(unittest.TestCase):
    def test_unmatched_transcripts_are_left_out(self):
        rows = [{"ts": NOW, "kind": "note", "subject": "operator", "text": "(voice, unmatched) north korea"},
                {"ts": NOW, "kind": "note", "subject": "operator", "text": "my landlord is Mr Okafor"}]
        with mock.patch("aletheia.journal.entries", return_value=rows):
            self.assertEqual(quick.answer("what notes do you have"), "1 note: my landlord is Mr Okafor.")


if __name__ == "__main__":
    unittest.main()
