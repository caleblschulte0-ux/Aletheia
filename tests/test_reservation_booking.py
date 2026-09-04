"""Booking a reservation: the second dead end, closed the same way.

`propose_booking` set BOOK_PROPOSED, named `reservation.book`, and
stopped — reachable only by hand-typing a JSON list of browser selectors
at a command line. Exactly what `subscription.cancel` was. A ledger of
intentions wearing a capability's name.
"""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import reservations


class BookingCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patch = mock.patch.object(reservations, "RES_DIR",
                                  Path(self.tmp.name) / "res")
        patch.start(); self.addCleanup(patch.stop)
        reservations.RES_DIR.mkdir(parents=True)

    def haircut(self, url=""):
        reservations.create("cut", kind="appointment",
                            description="a haircut")
        reservations.add_candidate(
            "cut", "one", provider="local", place="Ivy Barbers",
            slot="Saturday 10:00", details={"url": url} if url else {})
        reservations.select("cut", "one")


class SheNeverGuessesWhereToBOOK(BookingCase):
    def test_no_url_is_a_question_not_a_silence(self):
        self.haircut()
        reservations.propose_booking("cut")
        out = reservations.load("cut")
        self.assertEqual(out["state"], "BOOK_PROPOSED")
        self.assertIn("web address", out["blocked_on"])

    def test_starting_it_with_no_url_opens_nothing(self):
        self.haircut()
        opened = []
        out = reservations.start_booking(
            "cut", runner=lambda *a, **k: opened.append(a) or {})
        self.assertEqual(opened, [])
        self.assertIn("I will not guess one", out["blocked_on"])

    def test_the_proposal_names_something_that_can_RUN(self):
        self.haircut()
        proposal = reservations.propose_booking("cut")
        self.assertEqual(proposal["required_capability"], "web.task")
        self.assertEqual(proposal["required_approval"], "operator_always")


class ItGoesAsFarAsTheButton(BookingCase):
    def test_the_sentence_carries_the_place_and_the_slot(self):
        """A booking made at the wrong place, on the wrong day, is not a
        thing to leave to phrasing."""
        self.haircut(url="https://ivybarbers.example/book")
        asked = {}

        def runner(goal, *, start_url="", **kw):
            asked.update(goal=goal, start_url=start_url)
            return {"id": "web-1", "state": "AWAITING_YOU"}
        reservations.start_booking("cut", runner=runner)
        self.assertIn("Ivy Barbers", asked["goal"])
        self.assertIn("Saturday 10:00", asked["goal"])
        self.assertEqual(asked["start_url"], "https://ivybarbers.example/book")

    def test_it_is_waiting_on_him_not_booked(self):
        self.haircut(url="https://ivybarbers.example/book")
        out = reservations.start_booking(
            "cut", runner=lambda *a, **k: {"id": "web-1",
                                           "state": "AWAITING_YOU"})
        self.assertEqual(out["state"], "BOOK_PROPOSED")
        self.assertNotIn("blocked_on", out)


class CONFIRMED_MEANS_THE_PROVIDER_SAID_SO(BookingCase):
    """Committing him to be somewhere he is not actually booked is worse
    than not booking at all."""

    def waiting(self):
        self.haircut(url="https://ivybarbers.example/book")
        reservations.start_booking(
            "cut", runner=lambda *a, **k: {"id": "web-1",
                                           "state": "AWAITING_YOU"})

    def settle(self, record):
        return reservations.reconcile(loader=lambda _id: record)

    def test_still_waiting_on_him_changes_nothing(self):
        self.waiting()
        self.assertEqual(self.settle({"state": "AWAITING_YOU"}), [])
        self.assertEqual(reservations.load("cut")["state"], "BOOK_PROPOSED")

    def test_the_pages_own_words_are_what_confirm_it(self):
        self.waiting()
        self.settle({"state": "COMMITTED", "result": {
            "verdict": "confirmed",
            "evidence": "Your booking is confirmed for Saturday at 10."}})
        out = reservations.load("cut")
        self.assertEqual(out["state"], "CONFIRMED")
        self.assertIn("confirmed", out["confirmation"]["evidence"])

    def test_pressed_but_not_confirmed_is_NOT_booked(self):
        self.waiting()
        self.settle({"state": "COMMITTED", "result": {
            "verdict": "submitted, unconfirmed",
            "note": "The page did not say it went through."}})
        out = reservations.load("cut")
        self.assertEqual(out["state"], "BOOK_PROPOSED")
        self.assertIn("did not confirm", out["blocked_on"])

    def test_the_beat_settles_them(self):
        from aletheia import runtime
        source = Path(runtime.__file__).read_text(encoding="utf-8")
        self.assertIn("reservations.reconcile", source)


if __name__ == "__main__":
    unittest.main()
