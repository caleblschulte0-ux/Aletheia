"""His ChatGPT subscription, on his say-so, and never quietly.

His ruling: *"Yes it can use chatgpt as a secondary worker but no api key
it has to use my subscription."*

All of it was already built and switched off behind an environment
variable he would have had to set in a shell — which is why it looked
like a missing feature rather than a closed tap.

What the variable protected is kept, and every test here is about that:
the always-on side must never QUIETLY drive his personal account.
"""
import datetime as dt
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import browser_reasoner, intercom, journal, places
from aletheia import second_opinion as so
from aletheia import voice


class LeaseCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        d = Path(self.tmp.name)
        env = mock.patch.dict(os.environ, {"ALETHEIA_PRIVATE_STATE": str(d)},
                              clear=False)
        env.start()
        self.addCleanup(env.stop)
        for p in (mock.patch.object(journal, "JOURNAL_PATH", d / "j.jsonl"),
                  mock.patch.object(so, "_boot_id", return_value="boot-1"),
                  mock.patch.dict(os.environ,
                                  {browser_reasoner.ALLOW_ENV: ""})):
            p.start()
            self.addCleanup(p.stop)


class OffUntilHeSaysOtherwiseCase(LeaseCase):
    def test_a_machine_never_asked_is_not_using_his_account(self):
        self.assertFalse(so.granted())
        self.assertFalse(browser_reasoner.operator_lease_enabled())

    def test_granting_opens_it_and_revoking_closes_it(self):
        so.grant(8, via="test")
        self.assertTrue(so.granted())
        self.assertTrue(browser_reasoner.operator_lease_enabled())
        so.revoke(via="test")
        self.assertFalse(so.granted())
        self.assertFalse(browser_reasoner.operator_lease_enabled())

    def test_it_does_not_survive_a_restart(self):
        """A durable yes is the silent always-on the design refuses, by a
        slower route."""
        so.grant(8, via="test")
        with mock.patch.object(so, "_boot_id", return_value="boot-2"):
            self.assertFalse(so.granted())

    def test_a_yes_on_tuesday_is_not_still_true_on_friday(self):
        record = so.grant(1, via="test")
        past = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=1))
        record["until"] = past.isoformat()
        from aletheia import stateio
        stateio.write_json_atomic(so.marker(), record)
        self.assertFalse(so.granted())

    def test_everything_unreadable_reads_as_no(self):
        so.marker().parent.mkdir(parents=True, exist_ok=True)
        so.marker().write_text("{not json", encoding="utf-8")
        self.assertFalse(so.granted())
        so.grant(4, via="test")
        with mock.patch.object(so, "_boot_id", return_value=""):
            self.assertFalse(so.granted(), "an unknown boot used his account")

    def test_the_environment_variable_still_wins_on_its_own(self):
        """A foreground shell that sets it is unchanged — this is an
        additional door, not a replacement."""
        with mock.patch.dict(os.environ, {browser_reasoner.ALLOW_ENV: "1"}):
            self.assertTrue(browser_reasoner.operator_lease_enabled())

    def test_a_broken_lease_module_never_opens_the_account(self):
        with mock.patch.object(so, "granted", side_effect=OSError("gone")):
            self.assertFalse(browser_reasoner.operator_lease_enabled())


class HeCanSayItCase(LeaseCase):
    def setUp(self):
        super().setUp()
        p = mock.patch.object(places, "resolve", side_effect=KeyError("none"))
        p.start()
        self.addCleanup(p.stop)

    def test_the_sentences_reach_the_right_switch(self):
        for said, kind in (("use my chatgpt", "chatgpt_on"),
                           ("use chatgpt for this", "chatgpt_on"),
                           ("stop using my chatgpt", "chatgpt_off"),
                           ("turn off chatgpt", "chatgpt_off"),
                           ("are you using my chatgpt", "chatgpt")):
            with self.subTest(said=said):
                got = (voice.interpret(said) or {}).get("command") or {}
                self.assertEqual(got.get("kind"), kind, said)

    def test_asking_is_read_only_and_stopping_never_waits(self):
        self.assertEqual(intercom.tier("chatgpt"), intercom.TIER_READ)
        self.assertEqual(intercom.tier("chatgpt_off"), intercom.TIER_ROUTINE)
        # Granting ADDS capacity, so it is the one that stops for him.
        self.assertEqual(intercom.tier("chatgpt_on"), intercom.TIER_WORLD)

    def test_it_says_how_long_it_has_and_rounds_up(self):
        """Granting eight hours and hearing "another 7" reads as though an
        hour went missing between the sentence and the answer."""
        intercom.execute_command({"kind": "chatgpt_on", "hours": 8}, {},
                                 quote="use my chatgpt")
        self.assertIn("8 hours", so.spoken())

    def test_an_expired_grant_says_why_rather_than_just_no(self):
        so.grant(1, via="test")
        with mock.patch.object(so, "_boot_id", return_value="boot-2"):
            said = so.spoken()
        self.assertIn("restarted", said)
        self.assertIn("use ChatGPT", said)


if __name__ == "__main__":
    unittest.main()
