"""One list of what needs him, and every row says what happens if he ignores it.

The failure this replaces is not a wrong answer, it is five right ones.
Approvals were in `policy`, work blocked on him in `work_engine`,
applications stopped on a question in the campaign records, missions at a
boundary in `browser_mission`, handoffs in `handoffs` — each with a real
reader, each answering a different sentence. "What's waiting on me"
answered from one of them, which is worse than answering from none: a
short list that is quietly incomplete teaches him it is complete.
"""
from __future__ import annotations

import unittest
from unittest import mock

from aletheia import needs_you, quick, speech


def _approval(**over) -> dict:
    row = {"id": "mail-a1e1957d0f", "state": "PENDING",
           "capability": "email.send", "requested_action": "email.send",
           "reason": "operator said: send it to Dana",
           "requested_at": "2026-09-18T10:00:00Z"}
    row.update(over)
    return row


class EveryRowHasTheSameShape(unittest.TestCase):
    def test_a_row_says_what_why_and_what_happens_if_he_does_nothing(self):
        with mock.patch("aletheia.policy.all_approvals", lambda: [_approval()]):
            rows = needs_you.items(sources={"approval": needs_you._approvals})
        self.assertEqual(len(rows), 1)
        row = rows[0]
        for field in ("what", "why", "if_ignored", "how", "since", "kind"):
            self.assertIn(field, row)
        self.assertTrue(row["what"], "a row with nothing in it is not a row")
        self.assertIn("nothing happens", row["if_ignored"].lower())

    def test_nothing_in_a_row_is_an_identifier(self):
        """He cannot act on a hex string, and it is read out loud."""
        with mock.patch("aletheia.policy.all_approvals", lambda: [_approval()]):
            rows = needs_you.items(sources={"approval": needs_you._approvals})
        for field in ("what", "why", "if_ignored", "how"):
            self.assertEqual(speech.strip_ids(rows[0][field]), rows[0][field])

    def test_a_decided_approval_is_not_waiting_on_him(self):
        decided = [_approval(state="APPROVED"), _approval(state="DENIED")]
        with mock.patch("aletheia.policy.all_approvals", lambda: decided):
            self.assertEqual(
                needs_you.items(sources={"approval": needs_you._approvals}), [])


class TheListIsOneList(unittest.TestCase):
    def test_the_same_thing_seen_from_two_stores_is_one_row(self):
        """A handoff is a work item AND an approval; an application is a
        work item AND a campaign record. Showing both turns four real
        decisions into nine."""
        rows = needs_you.items(sources={
            "a": lambda: [needs_you._row(id="1", kind="approval",
                                         what="Send the email to Dana",
                                         why="x", if_ignored="y",
                                         since="2026-09-18T10:00:00Z")],
            "b": lambda: [needs_you._row(id="2", kind="work",
                                         what="send the email to dana.",
                                         why="x", if_ignored="y",
                                         since="2026-09-18T09:00:00Z")]})
        self.assertEqual(len(rows), 1)

    def test_newest_first(self):
        rows = needs_you.items(sources={"a": lambda: [
            needs_you._row(id="old", kind="work", what="the old one", why="x",
                           if_ignored="y", since="2026-09-17T10:00:00Z"),
            needs_you._row(id="new", kind="work", what="the new one", why="x",
                           if_ignored="y", since="2026-09-18T10:00:00Z")]})
        self.assertEqual([r["id"] for r in rows], ["new", "old"])

    def test_one_dead_source_never_hides_the_others(self):
        """The failure mode of losing a row here is him not knowing he was
        asked, so a source that raises costs its own rows and no more."""
        def broken():
            raise RuntimeError("the store is gone")

        rows = needs_you.items(sources={
            "broken": broken,
            "fine": lambda: [needs_you._row(id="1", kind="work", what="a real one",
                                            why="x", if_ignored="y")]})
        self.assertEqual([r["what"] for r in rows], ["a real one"])

    def test_waiting_on_the_world_is_not_waiting_on_him(self):
        from aletheia import work_states as ws
        self.assertIn(ws.BLOCKED_USER, needs_you.HIS_STATES)
        self.assertIn(ws.BLOCKED_LOGIN, needs_you.HIS_STATES)
        self.assertNotIn(ws.BLOCKED_EXTERNAL, needs_you.HIS_STATES)
        self.assertNotIn(ws.BLOCKED_MODEL, needs_you.HIS_STATES)


class SaidOutLoud(unittest.TestCase):
    def test_the_thing_comes_first_and_the_count_only_if_it_is_real(self):
        """"1 waiting on you — the first is Cancel the task to call the
        plumber" is a row index read aloud: he cannot act on "the first",
        there is no second, and the one fact arrives last."""
        one = [needs_you._row(id="1", kind="approval",
                              what="cancel the task to call the plumber",
                              why="I need your yes first",
                              if_ignored="nothing happens",
                              how="say approve")]
        said = needs_you.spoken(one)
        self.assertNotIn("the first is", said)
        self.assertNotIn("1 waiting", said)
        self.assertIn("call the plumber", said)
        self.assertIn("Say approve", said)
        self.assertIn("nothing happens", said.lower())

    def test_more_than_one_is_counted_because_then_the_count_is_news(self):
        rows = [needs_you._row(id=str(n), kind="approval", what=f"thing {n}",
                               why="x", if_ignored="y", how="say approve")
                for n in range(3)]
        said = needs_you.spoken(rows)
        self.assertIn("3 things need you", said)

    def test_nothing_is_a_sentence_not_an_empty_answer(self):
        self.assertEqual(needs_you.spoken([]), "Nothing needs you right now.")


class TheVoiceReadsTheSameList(unittest.TestCase):
    def test_both_questions_give_the_same_answer(self):
        """"What needs my attention" and "what's waiting on me" had two
        implementations over two sets of stores, and they disagreed."""
        from aletheia import voice
        rows = [needs_you._row(id="1", kind="approval", what="send the email",
                               why="I need your yes first",
                               if_ignored="nothing happens until you say so",
                               how="say approve")]
        snap = {"halted": False, "waiting_on_you": [], "notifications": []}
        with mock.patch.object(needs_you, "items", lambda *a, **k: rows), \
             mock.patch("aletheia.presence.snapshot", lambda: snap):
            self.assertEqual(voice._attention_say(), quick._waiting())

    def test_an_empty_list_is_still_a_store_she_read(self):
        snap = {"halted": False, "waiting_on_you": [], "notifications": []}
        with mock.patch.object(needs_you, "items", lambda *a, **k: []), \
             mock.patch("aletheia.presence.snapshot", lambda: snap):
            self.assertEqual(quick._waiting(), "Nothing needs you right now.")


class TheActivityView(unittest.TestCase):
    def test_a_recovery_is_not_a_failure(self):
        """"repo health red -> green" filed under "failed" tells him
        something broke at the moment it stopped being broken."""
        self.assertEqual(needs_you._outcome_of("recovery"), "recovered")
        self.assertEqual(needs_you._outcome_of("alert"), "failed")
        self.assertEqual(needs_you._outcome_of("error"), "failed")
        self.assertEqual(needs_you._outcome_of("action"), "finished")

    def test_finished_failed_and_unattended_arrive_in_one_list(self):
        day = [{"at": "Fri 09:00", "kind": "action", "what": "sent the email"},
               {"at": "Fri 08:00", "kind": "alert", "what": "the sync broke"}]
        ledger = [{"at": "Fri 10:00", "said": "made a branch", "tool": "repo.branch"}]
        with mock.patch("aletheia.recollection.day", lambda **k: day), \
             mock.patch("aletheia.autonomy.recent", lambda **k: ledger), \
             mock.patch("aletheia.autonomy.is_outward", lambda row: False):
            rows = needs_you.activity()
        self.assertEqual([r["outcome"] for r in rows],
                         ["unattended", "finished", "failed"])

    def test_one_dead_receipt_store_does_not_blank_the_history(self):
        def broken(**k):
            raise RuntimeError("no journal")

        with mock.patch("aletheia.recollection.day", broken), \
             mock.patch("aletheia.autonomy.recent",
                        lambda **k: [{"at": "Fri 10:00", "said": "made a branch"}]), \
             mock.patch("aletheia.autonomy.is_outward", lambda row: False):
            self.assertEqual(len(needs_you.activity()), 1)


if __name__ == "__main__":
    unittest.main()
