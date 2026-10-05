"""Forty-seventh sandbox batch, 2026-10-05: drafts, and the mail verbs that
are not built.

    > draft a text to Dana       [6.6s] a model wrote a message in its reply and drafted nothing
    > what did I draft           [4.6s] a model, describing that reply as a draft
    > scrap the draft            [12.0s] a model: "there's nothing to scrap"
    > reply to Dana              [6.0s] a model
    > unsubscribe me from that newsletter / mark it as read   [5.0s] a model each, asking which
"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import intercom, mail, quick, voice


class ScrapTheDraft(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        p = mock.patch.object(mail, "MAIL_DIR", Path(self.tmp.name))
        p.start(); self.addCleanup(p.stop)

    def _draft(self, name, subject):
        with mock.patch.object(mail, "outward_hold", return_value={"on": True}):
            return mail.draft(f"{name.lower()}@example.com", subject, "hello", held=True)

    def test_the_verb_and_the_store(self):
        self.assertEqual(voice.interpret("thea scrap the draft")["command"], {"kind": "draft_discard", "which": ""})
        self.assertEqual(voice.interpret("thea delete the draft to Dana")["command"]["which"], "Dana")
        with self.assertRaises(LookupError):
            mail.discard_draft("")
        from aletheia import act
        with self.assertRaises(act.Refused) as refused:
            intercom.execute_command({"kind": "draft_discard"}, "scrap the draft")
        self.assertIn("No drafts waiting", str(refused.exception))
        a = self._draft("Dana", "running late")
        b = self._draft("Sam", "the invoice")
        self.assertEqual(len(mail.held_drafts()), 2)
        with self.assertRaises(LookupError):
            mail.discard_draft("nobody")
        said = intercom.execute_command({"kind": "draft_discard", "which": "Dana"}, "scrap the draft to Dana")
        self.assertEqual(said.casefold(), "Scrapped the draft to Dana: 'running late'. Nothing was sent.".casefold())
        self.assertEqual([d["id"] for d in mail.held_drafts()], [b["id"]])
        with self.assertRaises(act.Refused):
            intercom.execute_command({"kind": "draft_discard", "which": "Dana"}, "q")
        # the newest when he names none
        intercom.execute_command({"kind": "draft_discard"}, "scrap the draft")
        self.assertEqual(mail.held_drafts(), [])
        self.assertIn("No drafts waiting", mail.held_drafts_words())
        self.assertTrue((Path(self.tmp.name) / f"{a['id']}.refused.json").exists())


class NothingToSayIsAQuestion(unittest.TestCase):
    def test_a_draft_with_no_body_asks_without_a_model(self):
        d = voice.interpret("thea draft a text to Dana")
        self.assertIsNone(d["command"])
        self.assertTrue(d["say"].startswith("What should the text to Dana say?"), d["say"])
        self.assertTrue(voice.interpret("thea email Dana")["say"].startswith("What should the email to Dana say?"))
        self.assertEqual(voice.interpret("thea text Dana saying hi")["command"]["kind"], "message_send")
        self.assertEqual(voice.interpret("thea email Dana the notes file")["command"]["kind"], "intent")

    def test_reply_to_dana(self):
        with mock.patch.object(mail, "available", return_value=(False, "mail isn't set up yet.")):
            self.assertIn("I can't read what Dana sent", voice.interpret("thea reply to Dana")["say"])
        with mock.patch.object(mail, "available", return_value=(True, "configured")):
            self.assertTrue(voice.interpret("thea reply to Dana")["say"].startswith("What should the reply to Dana say?"))

    def test_what_is_not_built_is_said_and_counted(self):
        from aletheia import demand
        with mock.patch.object(demand, "record") as rec:
            self.assertIn("isn't built", voice.interpret("thea mark it as read")["say"])
            self.assertIn("isn't built", voice.interpret("thea unsubscribe me from that newsletter")["say"])
        self.assertEqual(rec.call_count, 2)
        self.assertIn("unsubscribe me from that newsletter", rec.call_args[0][1])

    def test_what_did_i_draft_reads_the_store(self):
        for said in ("what did I draft", "did I draft anything", "what have I drafted", "anything drafted"):
            self.assertEqual(quick.match(said)[0], "drafts", said)


if __name__ == "__main__":
    unittest.main()
