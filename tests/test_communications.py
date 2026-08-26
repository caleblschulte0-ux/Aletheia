import datetime as dt
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import communications

UTC = dt.timezone.utc


class CommunicationCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        for attr, path in (("THREADS_DIR", root / "threads"), ("MESSAGES_DIR", root / "messages"),
                           ("EXPECT_DIR", root / "expectations")):
            patcher = mock.patch.object(communications, attr, path)
            patcher.start(); self.addCleanup(patcher.stop)


class TestCommunications(CommunicationCase):
    def test_unknown_participant_refused(self):
        communications.create_thread("t", participants=["bob"])
        with self.assertRaises(ValueError):
            communications.record_message("m1", thread_id="t", direction="OUTBOUND", channel="email",
                                          participant="alice", summary="hi")

    def test_expectation_requires_outbound_anchor(self):
        communications.create_thread("t", participants=["bob"])
        communications.record_message("m1", thread_id="t", direction="INBOUND", channel="email",
                                      participant="bob", summary="hello")
        with self.assertRaises(ValueError):
            communications.expect_reply("e1", thread_id="t", after_message_id="m1", from_participant="bob")

    def test_reply_after_anchor_resolves(self):
        communications.create_thread("t", participants=["bob"])
        communications.record_message("m1", thread_id="t", direction="OUTBOUND", channel="email",
                                      participant="bob", summary="question", occurred_at="2026-08-26T10:00:00-05:00")
        exp = communications.expect_reply("e1", thread_id="t", after_message_id="m1", from_participant="bob")
        communications.record_message("m2", thread_id="t", direction="INBOUND", channel="email",
                                      participant="bob", summary="answer", occurred_at="2026-08-26T16:01:00+00:00")
        resolved = communications.evaluate_expectation(exp, now=dt.datetime(2026, 8, 26, 17, tzinfo=UTC))
        self.assertEqual(resolved["status"], "REPLIED")
        self.assertEqual(resolved["reply_message_id"], "m2")

    def test_old_inbound_message_does_not_count_as_reply(self):
        communications.create_thread("t", participants=["bob"])
        communications.record_message("old", thread_id="t", direction="INBOUND", channel="email",
                                      participant="bob", summary="old", occurred_at="2026-08-26T09:00:00-05:00")
        communications.record_message("m1", thread_id="t", direction="OUTBOUND", channel="email",
                                      participant="bob", summary="question", occurred_at="2026-08-26T10:00:00-05:00")
        exp = communications.expect_reply("e1", thread_id="t", after_message_id="m1", from_participant="bob")
        self.assertEqual(communications.evaluate_expectation(exp, now=dt.datetime(2026, 8, 26, 17, tzinfo=UTC))["status"], "WAITING")

    def test_deadline_becomes_overdue(self):
        communications.create_thread("t", participants=["bob"])
        communications.record_message("m1", thread_id="t", direction="OUTBOUND", channel="email",
                                      participant="bob", summary="question", occurred_at="2026-08-26T10:00:00+00:00")
        exp = communications.expect_reply("e1", thread_id="t", after_message_id="m1", from_participant="bob",
                                          deadline="2026-08-26T12:00:00+00:00")
        result = communications.evaluate_expectation(exp, now=dt.datetime(2026, 8, 26, 13, tzinfo=UTC))
        self.assertEqual(result["status"], "OVERDUE")

    def test_closed_thread_refuses_new_message(self):
        communications.create_thread("t", participants=["bob"])
        communications.close_thread("t")
        with self.assertRaises(ValueError):
            communications.record_message("m1", thread_id="t", direction="OUTBOUND", channel="email",
                                          participant="bob", summary="hi")


if __name__ == "__main__":
    unittest.main()
