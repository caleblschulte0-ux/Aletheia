"""His words, 2026-09-23: "she should be allowed to draft emails to the
[openrangeinteractive] inbox. Sending them yet? Not yet, because I don't
know what she's drafting, but she should definitely be allowed to draft them
just to make sure the workflow is always working." The night before, six
such drafts had been turned into notifications; a draft is a draft."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import journal, mail, policy, pursuit, quick


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


class AHeldDraft(Isolated):
    def test_asks_for_nothing_and_is_never_sent_by_the_loop(self):
        d = mail.draft("openrangeinteractive@gmail.com", "Mercury AE: what to do", "Location is the key variable.",
                       requested_via="pursuit", held=True)
        self.assertTrue(d["held"])
        with self.assertRaises(Exception):
            policy.load(d["id"])
        sent = []

        class Transport:
            def send(self, msg):
                sent.append(msg)
        self.assertEqual(mail.send_approved(transport=Transport()), [])
        self.assertEqual(sent, [])
        self.assertEqual([x["id"] for x in mail.held_drafts()], [d["id"]])
        self.assertIn("held, not sent", journal.JOURNAL_PATH.read_text(encoding="utf-8"))

    def test_an_ordinary_draft_still_asks(self):
        d = mail.draft("someone@example.com", "Hello", "Body", requested_via="voice")
        self.assertEqual(policy.load(d["id"])["state"], "PENDING")
        self.assertEqual(mail.held_drafts(), [])

    def test_he_can_ask_what_she_has_drafted(self):
        self.assertEqual(quick.match("what have you drafted")[0], "drafts")
        self.assertEqual(quick.match("any drafts waiting?")[0], "drafts")
        self.assertEqual(quick.match("what's in my drafts")[0], "drafts")
        self.assertIn("No drafts waiting", quick.answer("what have you drafted"))
        mail.draft("openrangeinteractive@gmail.com", "Mercury AE: what to do", "Body", held=True)
        said = quick.answer("what have you drafted")
        self.assertIn("1 draft held, not sent: 'Mercury AE: what to do' to openrangeinteractive", said)


class ThePursuitsNoteToHimself(Isolated):
    def test_becomes_a_held_draft_and_one_notice(self):
        record = {"id": "opp-1", "subject": {"name": "Mercury"}}
        move = {"id": "m1", "why": "location is the variable",
                "detail": {"to": "openrangeinteractive@gmail.com", "subject": "Mercury AE: what to do",
                           "text": "Say Sioux Falls up front.", "grounded_on": ["e1"]}}
        notices = []
        with mock.patch.object(pursuit, "_his_own", return_value=True), \
             mock.patch.object(mail, "available", return_value=(True, "configured")), \
             mock.patch("aletheia.notifications.publish", side_effect=lambda *a, **k: notices.append((a, k))):
            out = pursuit._do_note(record, move, None)
        self.assertEqual(out["state"], "handed to him")
        self.assertIn("held", out["effect"])
        drafts = mail.held_drafts()
        self.assertEqual(len(drafts), 1)
        self.assertEqual(drafts[0]["subject"], "Mercury AE: what to do")
        self.assertEqual(out["handle"], drafts[0]["id"])
        self.assertEqual(len(notices), 1)
        self.assertIn("held; it goes only when you say send", notices[0][0][1])


if __name__ == "__main__":
    unittest.main()
