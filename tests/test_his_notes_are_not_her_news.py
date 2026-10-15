""""Good morning. Overnight: Noted: you went to bed at 9:16 pm" and "What I did
this week: Noted: you're at the gym; ..." (2026-10-15, every model off): what
he told her is not news to him, and not her doing."""
import unittest
from unittest import mock

from aletheia import quick


class HisNotesInHisWeek(unittest.TestCase):
    def test_they_are_counted_not_read_back(self):
        rows = [{"what": "Noted: you're at the gym"}, {"what": "Added a task: call bob"}]
        with mock.patch.object(quick, "_tasks_done", return_value="Nothing ticked off this week."), \
                mock.patch.object(quick, "_on_day", side_effect=lambda back: rows if back == 0 else []):
            said = quick._week()
        self.assertNotIn("gym", said)
        self.assertIn("call bob", said)
        self.assertTrue(said.endswith("You told me 1 thing to keep."), said)

    def test_only_notes_still_says_so(self):
        rows = [{"what": "Noted: you're at the gym"}]
        with mock.patch.object(quick, "_tasks_done", return_value="Nothing ticked off this week."), \
                mock.patch.object(quick, "_on_day", side_effect=lambda back: rows if back == 0 else []):
            said = quick._week()
        self.assertEqual(said, "You haven't ticked anything off this week. You told me 1 thing to keep.")


class HisNotesOvernight(unittest.TestCase):
    def test_a_note_is_not_overnight_news(self):
        from aletheia import recollection
        import datetime as dt
        ts = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        rows = [{"ts": ts, "what": "Noted: you went to bed at 9:16 pm"}]
        with mock.patch.object(quick, "_sent_records", return_value=[]), \
                mock.patch.object(recollection, "_read_journal", return_value=(rows, None)), \
                mock.patch.object(recollection, "_something_she_did", return_value=True), \
                mock.patch.object(recollection, "_row", side_effect=lambda e: e):
            self.assertTrue(quick._overnight().startswith("A quiet night"))


if __name__ == "__main__":
    unittest.main()
