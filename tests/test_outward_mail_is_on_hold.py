"""Outward mail is on hold, and the drafts are kept in order.

His words, 2026-09-24: "she shouldn't send anything to outside
correspondence yet. Yes, that is on hold. And she should be tracking the
drafts right now, too, and keeping all those in order."

So: with no file saying otherwise the hold is ON; every draft is held
whoever asked for it and no approval is filed; nothing is delivered by
either send loop; the hold lifts only at his keyboard; and the ledger
lists the drafts newest first with a newer one about the same thing
superseding the older.
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import conversations, journal, mail, policy


class Isolated(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        env = mock.patch.dict(os.environ, {"ALETHEIA_PRIVATE_STATE": str(root / "private")})
        env.start(); self.addCleanup(env.stop)
        for module, attr, value in ((mail, "MAIL_DIR", root / "mail"), (policy, "APPROVALS_DIR", root / "approvals"),
                                    (journal, "JOURNAL_PATH", root / "journal.jsonl")):
            p = mock.patch.object(module, attr, value)
            p.start(); self.addCleanup(p.stop)


class Sent:
    def __init__(self):
        self.sent = []

    def send(self, msg):
        self.sent.append(msg)


class TheHoldIsOnUntilHeLiftsIt(Isolated):
    def test_no_file_means_on_in_his_words(self):
        state = mail.outward_hold()
        self.assertTrue(state["on"])
        self.assertIn("on hold", state["quote"])
        self.assertIn("aletheia.mail hold off", state["command"])

    def test_a_draft_under_the_hold_is_held_and_files_no_approval(self):
        d = mail.draft("someone@example.com", "Hello", "Body", requested_via="voice")
        self.assertTrue(d["held"])
        self.assertTrue(d["held_by_ruling"])
        self.assertEqual([a for a in policy.all_approvals() if a.get("id") == d["id"]], [])
        self.assertIn(d["id"], [r["id"] for r in mail.drafts_ledger()])

    def test_nothing_goes_out_while_it_stands_even_an_old_approval(self):
        mail.lift_hold(via="test")
        d = mail.draft("someone@example.com", "Hello", "Body")
        policy.decide(d["id"], "APPROVED", via="test")
        mail.hold_outward(quote="that is on hold", via="test")
        out = Sent()
        self.assertEqual(mail.send_approved(out), [])
        self.assertEqual(out.sent, [])
        self.assertEqual(conversations.send_approved(transport=out)[0]["outcome"], "held")

    def test_lifting_it_at_the_keyboard_brings_the_approval_back(self):
        mail.lift_hold(via="test")
        self.assertFalse(mail.outward_hold()["on"])
        d = mail.draft("someone@example.com", "Hello", "Body")
        self.assertFalse(d.get("held"))
        self.assertTrue(any(a.get("id") == d["id"] for a in policy.all_approvals()))

    def test_the_command_line_says_the_state_in_words(self):
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with redirect_stdout(buf):
            mail.main(["hold", "status"])
        self.assertIn("ON HOLD", buf.getvalue())
        self.assertIn("hold off", buf.getvalue())


class TheDraftsAreKeptInOrder(Isolated):
    def test_newest_first_and_a_newer_one_about_the_same_thing_supersedes(self):
        older = mail.draft("hr@acme.example", "Re: Account Executive", "first try", held=True, about="apply-1")
        other = mail.draft("hr@zeta.example", "Interview", "hello", held=True, about="apply-2")
        newer = mail.draft("hr@acme.example", "Re: Re: Account Executive", "second try", held=True, about="apply-1")
        rows = mail.drafts_ledger()
        self.assertEqual([r["id"] for r in rows], [newer["id"], other["id"], older["id"]])
        self.assertEqual(rows[2]["superseded_by"], newer["id"])
        self.assertEqual(rows[0]["superseded_by"], "")
        self.assertEqual(rows[1]["superseded_by"], "")

    def test_three_drafts_in_one_second_still_have_one_true_order(self):
        """`created` is to the SECOND and a pursuit pass writes several drafts
        inside one. The only tie-break used to be the file's own mtime, and on
        a loaded Windows runner that came back IDENTICAL for two of them - so
        the directory listing decided which superseded which, and the answer
        changed between runs. His words were "keeping all those in order"; an
        order that is sometimes the other order is not one.
        """
        made = [mail.draft(f"hr{n}@acme.example", f"Note {n}", f"body {n}",
                           held=True, about=f"apply-{n}") for n in range(3)]
        second = made[0]["created"]
        stamps = []
        for row in made:
            path = mail.MAIL_DIR / f"{row['id']}.json"
            d = json.loads(path.read_text(encoding="utf-8"))
            # Force the exact collision the runner produced: one second for
            # all three, and one mtime for all three.
            d["created"] = second
            stamps.append(int(d["created_ns"]))
            path.write_text(json.dumps(d), encoding="utf-8")
            os.utime(path, ns=(1_700_000_000_000_000_000, 1_700_000_000_000_000_000))
        self.assertEqual(stamps, sorted(stamps), "the writer stamps them in the order it wrote them")
        self.assertEqual(len(set(stamps)), 3, "and no two share a stamp")
        expected = [r["id"] for r in reversed(made)]          # newest first
        for _ in range(4):
            self.assertEqual([r["id"] for r in mail.drafts_ledger()], expected)

    def test_a_draft_written_before_the_stamp_existed_still_has_an_order(self):
        """Nothing rewrites the store, so the old records have to keep working
        — and two of them with nothing to tell them apart must at least come
        back in the SAME order every time."""
        row = mail.draft("hr@acme.example", "Old one", "body", held=True)
        path = mail.MAIL_DIR / f"{row['id']}.json"
        d = json.loads(path.read_text(encoding="utf-8"))
        d.pop("created_ns", None)
        path.write_text(json.dumps(d), encoding="utf-8")
        first = [r["id"] for r in mail.drafts_ledger()]
        self.assertEqual(first, [row["id"]])
        self.assertEqual(first, [r["id"] for r in mail.drafts_ledger()])

    def test_the_same_thread_by_subject_when_nothing_says_what_it_is_about(self):
        a = mail.draft("hr@acme.example", "Mercury AE: what to do", "v1", held=True)
        b = mail.draft("hr@acme.example", "Re: Mercury AE: what to do", "v2", held=True)
        rows = {r["id"]: r for r in mail.drafts_ledger()}
        self.assertEqual(rows[a["id"]]["superseded_by"], b["id"])

    def test_the_words_count_only_the_current_ones_and_say_the_hold(self):
        mail.draft("hr@acme.example", "Re: Account Executive", "first", held=True, about="apply-1")
        mail.draft("hr@acme.example", "Re: Account Executive", "second", held=True, about="apply-1")
        said = mail.held_drafts_words()
        self.assertTrue(said.startswith("1 draft held"), said)
        self.assertIn("1 older draft replaced", said)
        self.assertIn("on hold", said)


if __name__ == "__main__":
    unittest.main()
