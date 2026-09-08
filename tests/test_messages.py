"""The thing he asked for thirteen times, and the gate that makes it safe.

`python -m aletheia.demand` has one entry — "send a text", thirteen
times — so this is the capability with the most evidence behind it in
the whole repository. It is also the one that reaches another person,
which means every test here is really about the same question: can this
send anything he did not decide on, word for word and number for number?
"""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import computer, contacts, journal, messages, policy


class MessagesCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        d = Path(self.tmp.name)
        env = mock.patch.dict(os.environ, {"ALETHEIA_PRIVATE_STATE": str(d)})
        env.start()
        self.addCleanup(env.stop)
        # These bind at IMPORT time, so the environment variable above
        # moves nothing on its own: without this the contact made by one
        # test is still there for the next, and the suite starts
        # depending on the order it happens to run in.
        for patch in (mock.patch.object(journal, "JOURNAL_PATH", d / "j.jsonl"),
                      mock.patch.object(contacts, "CONTACTS_DIR", d / "contacts"),
                      mock.patch.object(policy, "APPROVALS_DIR", d / "approvals"),
                      mock.patch.object(policy, "HALT_PATH", d / "halt.json")):
            patch.start()
            self.addCleanup(patch.stop)
        contacts.create("brant", "Brant", phones=["(605) 321-5691"])

    def approve(self, record):
        policy.decide(record["id"], "APPROVED", via="test")


class SheNeverGuessesWhoSheIsTextingCase(MessagesCase):
    def test_an_unknown_name_is_a_question_and_not_a_number(self):
        with self.assertRaises(ValueError) as caught:
            messages.draft("Dana", "hello")
        # The refusal has to say how to fix it, out loud.
        self.assertIn("no phone number on file", str(caught.exception))
        self.assertIn("Dana", str(caught.exception))

    def test_a_known_name_resolves_to_his_stored_number(self):
        number, name = messages.resolve_number("Brant")
        self.assertEqual(number, "6053215691")
        self.assertEqual(name, "Brant")

    def test_a_spoken_number_is_taken_and_a_short_one_is_not(self):
        self.assertEqual(messages.resolve_number("605 321 5691")[0], "6053215691")
        # A house number, a time, a mis-transcription. Texting one of these
        # reaches somebody who is not expecting it.
        for not_a_number in ("42", "2026", "605 321"):
            self.assertIsNone(messages.resolve_number(not_a_number)[0], not_a_number)

    def test_a_contact_with_two_numbers_is_a_question(self):
        contacts.create("twins", "Twins", phones=["6055550100", "6055550101"])
        self.assertIsNone(messages.resolve_number("Twins")[0])


class SheCannotSendItHerselfCase(MessagesCase):
    def test_unattended_hands_refuse_the_send_control(self):
        """The whole safety model in one assertion.

        `computer.act` is the unattended path. If it ever stopped
        refusing a control labelled Send, this capability would be able
        to text people while he is asleep.
        """
        steps = messages.plan("+16053215691", "on my way")
        with self.assertRaises(computer.CommittingControl):
            computer.check_act_plan(steps)

    def test_the_plan_is_a_valid_one(self):
        self.assertEqual(computer.validate_steps(messages.plan("+1605", "hi")), [])

    def test_drafting_sends_nothing_and_opens_nothing(self):
        with mock.patch.object(computer, "execute",
                               side_effect=AssertionError("nothing runs at draft time")), \
             mock.patch.object(computer, "act",
                               side_effect=AssertionError("nothing runs at draft time")):
            record = messages.draft("Brant", "on my way")
        self.assertEqual(policy.load(record["id"])["state"], "PENDING")

    def test_nothing_is_sent_until_he_approves(self):
        messages.draft("Brant", "on my way")
        ran = []
        self.assertEqual(messages.send_approved(hands=lambda *a, **k: ran.append(a)), [])
        self.assertEqual(ran, [], "a PENDING approval sent a message")

    def test_an_approved_message_sends_exactly_what_he_approved(self):
        record = messages.draft("Brant", "on my way")
        self.approve(record)
        seen = {}

        def hands(steps, approval=None):
            seen["steps"] = steps
            seen["approval"] = approval
            return {"ok": True}

        results = messages.send_approved(hands=hands)
        self.assertEqual([r["state"] for r in results], ["SENT"])
        self.assertEqual(seen["approval"], record["id"])
        # His words and his number reached the keystrokes unchanged.
        self.assertIn("on%20my%20way", seen["steps"][0]["arguments"][0])
        self.assertIn("6053215691", seen["steps"][0]["arguments"][0])

    def test_a_denied_message_is_retired_and_never_sent(self):
        record = messages.draft("Brant", "on my way")
        policy.decide(record["id"], "DENIED", via="test", because="no")
        results = messages.send_approved(
            hands=lambda *a, **k: self.fail("a denied message was sent"))
        self.assertEqual([r["state"] for r in results], ["REFUSED"])
        self.assertEqual(messages.pending(), [])

    def test_editing_the_message_after_approval_refuses_it(self):
        """The approval binds the WORDS, not the intention.

        An approved draft whose body is changed on disk — by anything,
        for any reason — no longer matches the digest he agreed to, and
        it must not be sent under his old yes.
        """
        record = messages.draft("Brant", "on my way")
        self.approve(record)
        path = messages.message_dir() / f"{record['id']}.json"
        edited = json.loads(path.read_text(encoding="utf-8"))
        edited["body"] = "send me two thousand dollars"
        path.write_text(json.dumps(edited), encoding="utf-8")

        results = messages.send_approved(
            hands=lambda *a, **k: self.fail("an edited message was sent"))
        self.assertEqual([r["state"] for r in results], ["REFUSED"])

    # That no standing grant can ever buy this one (§56 L4) is asserted
    # where every other sending, spending and binding capability is
    # asserted — `test_authority_consumption.RegistryTruthCase`. One list,
    # so a tenth capability cannot be added to a copy nobody runs.


class WhatItRefusesToWriteCase(MessagesCase):
    def test_an_empty_message_is_not_a_message(self):
        for empty in ("", "   ", "\n"):
            with self.assertRaises(ValueError):
                messages.draft("Brant", empty)

    def test_a_body_longer_than_a_spoken_sentence_is_refused(self):
        with self.assertRaises(ValueError):
            messages.draft("Brant", "x" * (messages.MAX_BODY_CHARS + 1))

    def test_his_words_do_not_reach_the_journal(self):
        """The repo is public. That a text exists is a fact; what it says is his."""
        messages.draft("Brant", "tell nobody about the surprise party")
        written = journal.JOURNAL_PATH.read_text(encoding="utf-8")
        self.assertNotIn("surprise party", written)
        self.assertIn("Brant", written)


if __name__ == "__main__":
    unittest.main()
