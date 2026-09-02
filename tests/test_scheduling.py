"""Phase 15: a meeting that arranges itself, and refuses to guess.

The negotiation is the unit under test — not any one step. What matters
is that it survives across beats, that each outward step still needs its
own approval, and that an ambiguous human reply ends with the operator
rather than with a stranger booked into the wrong hour.
"""
import datetime as dt
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import (calendar, communications, contacts, journal, mail,
                      policy, scheduling)

TZ = "America/Chicago"
def _slot(days_ahead: int, hour: int) -> dict:
    """A slot RELATIVE to today, never a frozen date.

    These were literals in September 2026, and on 2026-09-02 the suite
    started failing for no reason but the calendar: an offer whose slots
    have all passed is correctly ABANDONED, so two tests about "an offer
    nobody has answered yet" aged into asserting the opposite of what they
    meant. A fixture describing a live offer has to still describe one
    tomorrow.
    """
    day = dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=days_ahead)
    start = day.replace(hour=hour, minute=0, second=0, microsecond=0)
    return {"start": start.isoformat(),
            "end": (start + dt.timedelta(minutes=30)).isoformat()}


SLOTS = [_slot(2, 15), _slot(3, 16)]


def verdict(decision="ACCEPTED", index=0, confidence=0.95, quote="Tuesday works"):
    return {"decision": decision, "slot_index": index, "quote": quote,
            "confidence": confidence}


class SchedulingCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        env = mock.patch.dict(os.environ,
                              {"ALETHEIA_PRIVATE_STATE": str(root / "private")})
        env.start(); self.addCleanup(env.stop)
        for module, attr, value in (
                (policy, "APPROVALS_DIR", root / "approvals"),
                (policy, "HALT_PATH", root / "halt.json"),
                (journal, "JOURNAL_PATH", root / "journal.jsonl"),
                (mail, "MAIL_DIR", root / "mail"),
                (contacts, "CONTACTS_DIR", root / "contacts"),
                (communications, "THREADS_DIR", root / "threads"),
                (communications, "MESSAGES_DIR", root / "messages"),
                (communications, "EXPECT_DIR", root / "expect")):
            p = mock.patch.object(module, attr, value)
            p.start(); self.addCleanup(p.stop)
        (root / "approvals").mkdir(parents=True, exist_ok=True)
        (root / "mail").mkdir(parents=True, exist_ok=True)
        contacts.create("dana", "Dana Okafor", emails=["dana@example.com"])
        # the offer email is drafted, never actually sent, in every test
        p = mock.patch.object(mail, "resolve_address",
                              return_value=("dana@example.com", "Dana Okafor"))
        p.start(); self.addCleanup(p.stop)
        p = mock.patch.object(scheduling.meetings, "propose",
                              return_value={"status": "PROPOSED", "person": "dana",
                                            "display_name": "Dana Okafor",
                                            "slots": SLOTS})
        p.start(); self.addCleanup(p.stop)

    def start(self, nid="meet-dana"):
        first = dt.date.today() + dt.timedelta(days=1)
        return scheduling.start(nid, "dana", start_day=first.isoformat(),
                                end_day=(first + dt.timedelta(days=4)).isoformat(),
                                timezone=TZ, purpose="Project kickoff")

    def send_the_mail(self, record):
        """Stand in for mail.send_approved having really delivered it."""
        (mail.MAIL_DIR / f"{record['draft_id']}.sent.json").write_text("{}", encoding="utf-8")

    # ---- offering ----------------------------------------------------

    def test_starting_drafts_an_offer_and_sends_nothing(self):
        record = self.start()
        self.assertEqual(record["state"], scheduling.OFFERING)
        self.assertEqual(len(record["slots"]), 2)
        self.assertEqual(policy.load(record["send_approval"])["state"], "PENDING")

    def test_the_offer_says_who_it_is_and_never_impersonates_him(self):
        record = self.start()
        body = scheduling.offer_text("Dana", record["slots"], TZ)
        self.assertIn("Caleb's AI assistant", body)
        self.assertIn("Caleb asked me", body)
        self.assertNotIn("I'm Caleb", body)

    def test_no_free_slot_is_an_honest_stop_not_an_empty_offer(self):
        with mock.patch.object(scheduling.meetings, "propose",
                               return_value={"status": "NO_SLOT", "slots": []}):
            record = scheduling.start("empty", "dana", start_day="2026-09-01",
                                      end_day="2026-09-02", timezone=TZ)
        self.assertEqual(record["state"], scheduling.NEEDS_OPERATOR)
        self.assertIn("no free slot", record["history"][-1]["detail"])

    def test_a_negotiation_id_is_not_reused(self):
        self.start()
        with self.assertRaises(FileExistsError):
            self.start()

    # ---- the send gate -----------------------------------------------

    def test_an_unsent_offer_stays_offering_across_beats(self):
        record = self.start()
        scheduling.reconcile()
        self.assertEqual(scheduling.load(record["id"])["state"], scheduling.OFFERING)

    def test_approval_alone_does_not_count_as_sent(self):
        # §30: he said yes; the message has still not left
        record = self.start()
        policy.decide(record["send_approval"], "APPROVED", via="test")
        scheduling.reconcile()
        self.assertEqual(scheduling.load(record["id"])["state"], scheduling.OFFERING)

    def test_delivery_evidence_moves_it_to_sent_and_starts_waiting(self):
        record = self.start()
        self.send_the_mail(record)
        scheduling.reconcile()
        moved = scheduling.load(record["id"])
        self.assertEqual(moved["state"], scheduling.SENT)
        expectations = communications.all_expectations()
        self.assertEqual(len(expectations), 1)
        self.assertEqual(expectations[0]["status"], "WAITING")

    def test_reconcile_is_idempotent(self):
        record = self.start()
        self.send_the_mail(record)
        for _ in range(3):
            scheduling.reconcile()
        self.assertEqual(len(communications.all_expectations()), 1)

    # ---- reading the reply -------------------------------------------

    def sent(self):
        record = self.start()
        self.send_the_mail(record)
        scheduling.reconcile()
        return scheduling.load(record["id"])

    def test_a_clear_acceptance_moves_to_booking(self):
        record = self.sent()
        out = scheduling.on_reply(record["id"], "Tuesday works for me",
                                  infer=lambda *a, **k: verdict())
        self.assertEqual(out["state"], scheduling.BOOKING)
        self.assertEqual(out["accepted_slot"]["start"], SLOTS[0]["start"])

    def test_default_reply_reasoning_uses_the_bounded_routine_gateway(self):
        record = self.sent()
        routed = scheduling.reasoning_gateway.GatewayResult(
            output=verdict(), provider="ollama:qwen3:8b", policy="routine",
        )
        with mock.patch.object(scheduling.reasoning_gateway, "reason_json",
                               return_value=routed) as route:
            out = scheduling.on_reply(record["id"], "Tuesday works for me")
        self.assertEqual(out["state"], scheduling.BOOKING)
        self.assertEqual(route.call_args.kwargs["policy"], "routine")
        self.assertTrue(callable(route.call_args.kwargs["validator"]))

    def test_a_low_confidence_acceptance_goes_to_the_operator(self):
        record = self.sent()
        out = scheduling.on_reply(record["id"], "maybe tuesday?",
                                  infer=lambda *a, **k: verdict(confidence=0.4))
        self.assertEqual(out["state"], scheduling.NEEDS_OPERATOR)
        self.assertIn("not recoverable", out["history"][-1]["detail"])

    def test_a_counter_proposal_is_not_a_booking(self):
        record = self.sent()
        out = scheduling.on_reply(record["id"], "How about Friday at 10?",
                                  infer=lambda *a, **k: verdict("COUNTER", None))
        self.assertEqual(out["state"], scheduling.NEEDS_OPERATOR)

    def test_a_decline_ends_with_the_operator_not_a_retry(self):
        record = self.sent()
        out = scheduling.on_reply(record["id"], "Sorry, I can't",
                                  infer=lambda *a, **k: verdict("DECLINED", None))
        self.assertEqual(out["state"], scheduling.NEEDS_OPERATOR)

    def test_an_unreadable_reply_never_books_anything(self):
        record = self.sent()

        def boom(*a, **k):
            raise RuntimeError("provider down")

        out = scheduling.on_reply(record["id"], "yes", infer=boom)
        self.assertEqual(out["state"], scheduling.NEEDS_OPERATOR)
        self.assertIn("needs your eyes", out["history"][-1]["detail"])

    def test_a_reply_to_a_finished_negotiation_changes_nothing(self):
        record = self.sent()
        scheduling.abandon(record["id"])
        out = scheduling.on_reply(record["id"], "Tuesday!",
                                  infer=lambda *a, **k: verdict())
        self.assertEqual(out["state"], scheduling.ABANDONED)

    # ---- the model's answer is validated, not trusted -----------------

    def test_an_accept_without_a_slot_is_refused(self):
        with self.assertRaises(ValueError):
            scheduling.validate_reply(
                {"decision": "ACCEPTED", "slot_index": None,
                 "quote": "", "confidence": 0.9}, 2)

    def test_a_slot_index_out_of_range_is_refused(self):
        for index in (-1, 2, 99, True, "0"):
            with self.assertRaises(ValueError, msg=repr(index)):
                scheduling.validate_reply(
                    {"decision": "ACCEPTED", "slot_index": index,
                     "quote": "", "confidence": 0.9}, 2)

    def test_only_accept_may_carry_a_slot(self):
        with self.assertRaises(ValueError):
            scheduling.validate_reply(
                {"decision": "DECLINED", "slot_index": 1,
                 "quote": "", "confidence": 0.9}, 2)

    def test_unknown_fields_and_bad_decisions_are_refused(self):
        with self.assertRaises(ValueError):
            scheduling.validate_reply(
                {"decision": "ACCEPTED", "slot_index": 0, "confidence": 0.9,
                 "book_it": True}, 2)
        with self.assertRaises(ValueError):
            scheduling.validate_reply({"decision": "BOOK", "confidence": 1.0}, 2)

    # ---- staleness ----------------------------------------------------

    def test_an_offer_whose_slots_have_all_passed_is_abandoned(self):
        record = self.sent()
        later = dt.datetime(2026, 9, 10, tzinfo=dt.timezone.utc)
        scheduling.reconcile(now=later)
        self.assertEqual(scheduling.load(record["id"])["state"],
                         scheduling.ABANDONED)

    def test_a_live_offer_is_not_abandoned_early(self):
        record = self.sent()
        early = dt.datetime(2026, 8, 30, tzinfo=dt.timezone.utc)
        scheduling.reconcile(now=early)
        self.assertEqual(scheduling.load(record["id"])["state"], scheduling.SENT)

    # ---- booking keeps its own gate -----------------------------------

    def test_booking_requires_a_configured_provider(self):
        record = self.sent()
        scheduling.on_reply(record["id"], "Tuesday", infer=lambda *a, **k: verdict())
        with mock.patch("aletheia.calendar_live.available",
                        return_value=(False, "no provider configured")):
            out = scheduling.request_booking(record["id"])
        self.assertEqual(out["state"], scheduling.NEEDS_OPERATOR)

    def test_nothing_is_written_until_the_write_approval_is_approved(self):
        record = self.sent()
        scheduling.on_reply(record["id"], "Tuesday", infer=lambda *a, **k: verdict())
        with mock.patch("aletheia.calendar_live.available", return_value=(True, "ok")), \
             mock.patch("aletheia.calendar_live.config",
                        return_value={"provider": "google"}):
            scheduling.request_booking(record["id"])
        executed = mock.Mock()
        with mock.patch("aletheia.calendar_provider.execute_write_plan", executed):
            out = scheduling.confirm_booked(record["id"], provider=object())
        executed.assert_not_called()
        self.assertEqual(out["state"], scheduling.BOOKING)

    def test_a_write_that_returns_no_event_id_is_not_booked(self):
        record = self.sent()
        scheduling.on_reply(record["id"], "Tuesday", infer=lambda *a, **k: verdict())
        with mock.patch("aletheia.calendar_live.available", return_value=(True, "ok")), \
             mock.patch("aletheia.calendar_live.config",
                        return_value={"provider": "google"}):
            scheduling.request_booking(record["id"])
        policy.decide(scheduling.load(record["id"])["write_approval"],
                      "APPROVED", via="test")
        with mock.patch("aletheia.calendar_provider.execute_write_plan",
                        return_value={"ok": True}):
            out = scheduling.confirm_booked(record["id"], provider=object())
        self.assertEqual(out["state"], scheduling.NEEDS_OPERATOR)
        self.assertIn("unconfirmed", out["history"][-1]["detail"])

    def test_a_confirmed_write_books_it(self):
        record = self.sent()
        scheduling.on_reply(record["id"], "Tuesday", infer=lambda *a, **k: verdict())
        with mock.patch("aletheia.calendar_live.available", return_value=(True, "ok")), \
             mock.patch("aletheia.calendar_live.config",
                        return_value={"provider": "google"}):
            scheduling.request_booking(record["id"])
        policy.decide(scheduling.load(record["id"])["write_approval"],
                      "APPROVED", via="test")
        with mock.patch("aletheia.calendar_provider.execute_write_plan",
                        return_value={"external_id": "evt-123"}):
            out = scheduling.confirm_booked(record["id"], provider=object())
        self.assertEqual(out["state"], scheduling.BOOKED)
        self.assertEqual(out["external_event_id"], "evt-123")
        self.assertIn("Booked", scheduling.spoken(out))

    def test_a_corrupt_record_schedules_nothing(self):
        record = self.start()
        scheduling._path(record["id"]).write_text("{ broken", encoding="utf-8")
        self.assertEqual(scheduling.all_negotiations(), [])
        self.assertEqual(scheduling.reconcile(), [])


if __name__ == "__main__":
    unittest.main()
