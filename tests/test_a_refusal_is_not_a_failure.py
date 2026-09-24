"""Mail that is not set up is a refusal, not a failure.

Bottom rung, 2026-09-24: "did anyone email me today" and "what's in my
inbox" came back "That failed: mail isn't set up yet. It needs your email
address and an app password once..." - a sentence that says what to do,
prefixed as if something broke. Nothing broke. The mail kinds refuse at
the door with the same words, and a refusal is read out as one.
"""
from __future__ import annotations

import unittest
from unittest import mock

from aletheia import act, intercom, voice

WHY = ("mail isn't set up yet. It needs your email address and an app password once, on the PC, "
       "and it works from the next ask.")


class MailNotSetUpIsARefusal(unittest.TestCase):
    def test_every_mail_kind_refuses_at_the_door(self):
        with mock.patch("aletheia.mail.available", return_value=(False, WHY)), \
                mock.patch("aletheia.mail.check_unread", side_effect=AssertionError("must not be reached")):
            # A draft and a watch are deliberately not here: the draft is held
            # in her ledger, and a watch is a standing rule that starts working
            # the moment the inbox is reachable.
            for cmd in ({"kind": "email_check"}, {"kind": "email_read", "which": "Stripe"}):
                with self.subTest(kind=cmd["kind"]):
                    with self.assertRaises(act.Refused) as ctx:
                        intercom.execute_command(cmd, {}, quote="test")
                    self.assertIn("mail isn't set up yet", str(ctx.exception))

    def test_the_room_hears_a_refusal_not_a_failure(self):
        said = voice.spoken_reply("email_check", "refused", WHY)
        self.assertTrue(said.startswith("I can't do that: mail isn't set up yet"), said)
        self.assertNotIn("failed", said)

    def test_configured_mail_is_untouched(self):
        with mock.patch("aletheia.mail.available", return_value=(True, "configured for x")), \
                mock.patch("aletheia.mail.check_unread", return_value="No unread email."):
            self.assertEqual(intercom.execute_command({"kind": "email_check"}, {}, quote="test"), "No unread email.")


if __name__ == "__main__":
    unittest.main()
