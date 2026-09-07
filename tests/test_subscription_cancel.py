"""Cancelling a subscription: the dead end, and closing it.

`request_cancel` set CANCEL_REQUESTED, named the capability
`subscription.cancel`, and stopped — and the only way to reach that
capability was to hand-type a JSON list of browser selectors at a command
line. So "cancel my gym membership" produced a record that said
CANCEL_REQUESTED forever, with nothing able to carry it out and nothing
saying so. A capability nothing can call is not a capability.
"""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import subscriptions


class CancelCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patch = mock.patch.object(subscriptions, "SUBS_DIR",
                                  Path(self.tmp.name) / "subs")
        patch.start(); self.addCleanup(patch.stop)
        subscriptions.SUBS_DIR.mkdir(parents=True)

    def gym(self, **kw):
        return subscriptions.create("gym", merchant="Iron Works Gym",
                                    amount=29.0, **kw)


class SheNeverGuessesWhereToGo(CancelCase):
    def test_no_url_is_a_QUESTION_not_a_silence(self):
        """It sat in CANCEL_REQUESTED saying nothing at all about what
        was stopping it."""
        self.gym()
        out = subscriptions.request_cancel("gym")
        self.assertEqual(out["status"], "CANCEL_REQUESTED")
        self.assertIn("web address", out["blocked_on"])
        self.assertIn("Iron Works Gym", out["blocked_on"])

    def test_starting_it_with_no_url_asks_rather_than_searching(self):
        """Guessing a cancellation URL is how you end up on a page
        wearing his bank's colours that somebody else owns."""
        self.gym()
        opened = []
        out = subscriptions.start_cancellation(
            "gym", runner=lambda *a, **k: opened.append(a) or {})
        self.assertEqual(opened, [])
        self.assertIn("I will not guess one", out["blocked_on"])

    def test_a_url_must_be_a_web_address(self):
        with self.assertRaises(ValueError):
            self.gym(url="iron-works.example")
        self.gym()
        with self.assertRaises(ValueError):
            subscriptions.set_url("gym", "javascript:alert(1)")


class ItGoesAsFarAsTheButtonAndStops(CancelCase):
    def test_the_sentence_is_written_here_not_by_a_model(self):
        """A cancellation aimed at the wrong merchant is not a thing to
        leave to phrasing."""
        self.gym(url="https://ironworks.example/account")
        asked = {}

        def runner(goal, *, start_url="", **kw):
            asked.update(goal=goal, start_url=start_url)
            return {"id": "web-1", "state": "AWAITING_YOU"}
        subscriptions.start_cancellation("gym", runner=runner)
        self.assertEqual(asked["goal"],
                         "Cancel my Iron Works Gym subscription on this page.")
        self.assertEqual(asked["start_url"], "https://ironworks.example/account")

    def test_it_is_waiting_on_him_not_cancelled(self):
        self.gym(url="https://ironworks.example/account")
        out = subscriptions.start_cancellation(
            "gym", runner=lambda *a, **k: {"id": "web-1",
                                           "state": "AWAITING_YOU"})
        self.assertEqual(out["status"], "CANCEL_REQUESTED")
        self.assertEqual(out["web_task"], "web-1")
        self.assertNotIn("blocked_on", out)


class CANCELLED_MEANS_THE_MERCHANT_SAID_SO(CancelCase):
    """A press is an action; whether the merchant accepted it is a
    different question, and this is exactly where answering the second
    with the first costs him a charge a month for as long as he believes
    it (§30, §68)."""

    def waiting(self):
        self.gym(url="https://ironworks.example/account")
        subscriptions.start_cancellation(
            "gym", runner=lambda *a, **k: {"id": "web-1",
                                           "state": "AWAITING_YOU"})

    def settle(self, record):
        return subscriptions.reconcile(loader=lambda _id: record)

    def test_still_waiting_on_him_changes_nothing(self):
        self.waiting()
        self.assertEqual(self.settle({"state": "AWAITING_YOU"}), [])
        self.assertEqual(subscriptions.load("gym")["status"], "CANCEL_REQUESTED")

    def test_the_merchants_own_words_are_what_cancel_it(self):
        self.waiting()
        self.settle({"state": "COMMITTED", "result": {
            "verdict": "confirmed",
            "evidence": "Your membership has been cancelled."}})
        out = subscriptions.load("gym")
        self.assertEqual(out["status"], "CANCELLED")
        self.assertIn("has been cancelled", out["evidence"])
        self.assertTrue(out["cancelled_at"])

    def test_pressed_but_NOT_confirmed_is_not_cancelled(self):
        self.waiting()
        self.settle({"state": "COMMITTED", "result": {
            "verdict": "submitted, unconfirmed",
            "note": "The page did not say it went through."}})
        out = subscriptions.load("gym")
        self.assertEqual(out["status"], "CANCEL_REQUESTED")
        self.assertIn("did not confirm", out["blocked_on"])

    def test_a_refusal_is_not_cancelled_either(self):
        self.waiting()
        self.settle({"state": "REJECTED", "result": {
            "verdict": "rejected", "note": "The site handed it back."}})
        out = subscriptions.load("gym")
        self.assertEqual(out["status"], "CANCEL_REQUESTED")
        self.assertIn("did not confirm", out["blocked_on"])

    def test_a_missing_run_record_does_not_crash_the_beat(self):
        self.waiting()

        def gone(_id):
            raise FileNotFoundError(_id)
        self.assertEqual(subscriptions.reconcile(loader=gone), [])


class HeCanJustSayIt(unittest.TestCase):
    def test_the_kind_exists_and_the_planner_can_see_it(self):
        from aletheia import intercom, planner
        self.assertIn("subscription_cancel", intercom.KIND_ARGS)
        self.assertIn("subscription_cancel", planner.grammar_brief())

    def test_the_beat_settles_them(self):
        from aletheia import runtime
        source = Path(runtime.__file__).read_text(encoding="utf-8")
        self.assertIn("subscriptions.reconcile", source)

    def test_the_capability_it_names_is_one_that_can_actually_run(self):
        """It named `subscription.cancel`, whose only entry point was a
        hand-typed JSON list of browser selectors."""
        import tempfile as tf
        with tf.TemporaryDirectory() as root:
            with mock.patch.object(subscriptions, "SUBS_DIR",
                                   Path(root) / "subs"):
                subscriptions.SUBS_DIR.mkdir(parents=True)
                subscriptions.create("x", merchant="A Shop")
                out = subscriptions.request_cancel("x")
        self.assertEqual(out["cancel_proposal"]["required_capability"],
                         "web.task")
        self.assertEqual(out["cancel_proposal"]["required_approval"],
                         "operator_always")


if __name__ == "__main__":
    unittest.main()
