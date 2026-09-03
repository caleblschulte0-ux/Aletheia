"""The last mile, and where it is supposed to stop.

An errand is the one primitive behind buying, booking and cancelling
(§152). These tests hold the three properties that let it exist at all:
authorization binds to the exact errand, money has a ceiling checked
against what the page really says, and §143's boundaries stop it and hand
the rest back to the operator.

No browser opens here: `reader`/`interact` are injected.
"""
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import errands, journal, policy

STEPS = [{"action": "click", "selector": "#checkout"},
         {"action": "click", "selector": "#place-order"}]


class ErrandCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        env = mock.patch.dict(os.environ,
                              {"ALETHEIA_PRIVATE_STATE": str(root / "private")})
        env.start(); self.addCleanup(env.stop)
        for module, attr, value in ((policy, "APPROVALS_DIR", root / "approvals"),
                                    (journal, "JOURNAL_PATH", root / "journal.jsonl")):
            p = mock.patch.object(module, attr, value)
            p.start(); self.addCleanup(p.stop)
        (root / "approvals").mkdir(parents=True, exist_ok=True)
        halt = mock.patch.object(policy, "halted", return_value=None)
        halt.start(); self.addCleanup(halt.stop)

    def propose(self, **kw):
        """A CANCELLATION by default. A spending errand no longer runs at
        all (the 2026-09-03 checkout finding), so the tests about ordinary
        errand behaviour use a kind that still executes; the money tests
        below pass kind="purchase" explicitly."""
        base = dict(site="https://shop.example/cart", kind="cancellation",
                    steps=STEPS, why="he asked for it")
        base.update(kw)
        return errands.propose(kw.pop("errand_id", "e1"), **base)

    def propose_purchase(self, **kw):
        return self.propose(kind="purchase", ceiling="60.00", **kw)

    def approve(self, record):
        policy.decide(record["approval"], "APPROVED", via="test")

    def execute(self, page_text="Order total $42.00", after="Thanks, order #A1"):
        return errands.run(
            "e1",
            reader=lambda url: {"url": url, "title": "t", "text": page_text},
            interact=lambda url, steps, aid: {"url": url, "title": "t",
                                              "text": after,
                                              "steps_done": ["click", "click"]})

    # ---- authorization ---------------------------------------------

    def test_proposing_asks_and_runs_nothing(self):
        record = self.propose()
        self.assertEqual(record["state"], errands.PROPOSED)
        self.assertEqual(policy.load(record["approval"])["state"], "PENDING")
        # The approval is BOUND to the exact page and step list (the
        # confused-deputy fix); the human sentence lives in `reason`.
        from aletheia import browse
        self.assertEqual(policy.load(record["approval"])["requested_action"],
                         browse.approval_action(record["site"], record["steps"]))
        self.assertIn("cancellation", policy.load(record["approval"])["reason"])

    def test_an_unapproved_errand_is_refused(self):
        self.propose()
        done = self.execute()
        self.assertEqual(done["state"], errands.REFUSED)
        self.assertIn("not APPROVED", done["detail"])

    def test_an_approved_errand_runs_and_records_evidence(self):
        self.approve(self.propose())
        done = self.execute()
        self.assertEqual(done["state"], errands.COMPLETED)
        self.assertEqual(done["evidence"]["steps_done"], ["click", "click"])

    def test_steps_changed_after_approval_are_refused_not_adapted(self):
        record = self.propose()
        self.approve(record)
        record["steps"] = [{"action": "click", "selector": "#buy-the-expensive-one"}]
        from aletheia import stateio
        stateio.write_json_atomic(errands._path("e1"), record)
        done = self.execute()
        self.assertEqual(done["state"], errands.REFUSED)
        self.assertIn("changed after it was approved", done["detail"])

    def test_the_ceiling_cannot_be_raised_after_approval(self):
        record = self.propose_purchase()
        self.approve(record)
        record["ceiling"] = "9999.00"
        from aletheia import stateio
        stateio.write_json_atomic(errands._path("e1"), record)
        self.assertEqual(self.execute()["state"], errands.REFUSED)

    def test_an_errand_runs_once(self):
        self.approve(self.propose())
        self.assertEqual(self.execute()["state"], errands.COMPLETED)
        self.assertEqual(self.execute()["state"], errands.REFUSED)

    def test_halt_stops_an_authorized_errand(self):
        self.approve(self.propose())
        with mock.patch.object(policy, "halted", return_value={"reason": "stop"}):
            self.assertEqual(self.execute()["state"], errands.REFUSED)

    # ---- money ------------------------------------------------------

    def test_a_spending_errand_does_not_run_at_all_yet(self):
        """2026-09-03: the ceiling was compared with the page BEFORE the
        steps ran, and then the whole sequence — the irreversible click
        included — ran with no re-read. A $40 cart that becomes $75 at
        checkout passed. Spending is refused until the final total is
        verified immediately before the commit."""
        self.approve(self.propose_purchase())
        clicked = []
        done = errands.run(
            "e1", reader=lambda url: {"text": "Order total $42.00"},
            interact=lambda *a: clicked.append(a) or {"text": "ok"})
        self.assertEqual(done["state"], errands.AT_BOUNDARY)
        self.assertEqual(clicked, [], "a spending errand must click nothing")
        self.assertIn("final total", done["detail"])

    def test_a_page_over_the_ceiling_is_abandoned_before_clicking(self):
        """The pre-flight check still stands for when spending returns."""
        self.approve(self.propose_purchase())
        clicked = []
        with mock.patch.object(errands, "SPENDING_KINDS", set()):
            done = errands.run(
                "e1", reader=lambda url: {"text": "Subtotal $58.00  Total $84.99"},
                interact=lambda *a: clicked.append(a) or {"text": "ok"})
        self.assertEqual(done["state"], errands.REFUSED)
        self.assertEqual(clicked, [], "it clicked buy on an over-ceiling page")
        self.assertIn("84.99", done["detail"])

    def test_the_total_is_the_largest_figure_not_the_first(self):
        # "$4.99 shipping ... $312.00 total" must not read as $4.99
        self.assertEqual(errands.observed_total("Shipping $4.99  Total $312.00"),
                         errands._money("312.00"))
        self.assertIsNone(errands.observed_total("no prices here"))
        self.assertEqual(errands.observed_total("Total: USD 1,299.00"),
                         errands._money("1299.00"))

    def test_a_spending_errand_must_declare_a_ceiling(self):
        with self.assertRaises(ValueError) as caught:
            self.propose(kind="purchase", ceiling=None)
        self.assertIn("must declare a ceiling", str(caught.exception))

    def test_a_non_spending_errand_takes_no_ceiling(self):
        with self.assertRaises(ValueError):
            self.propose(kind="cancellation", ceiling="10.00")

    def test_a_page_with_no_price_does_not_silently_pass_as_free(self):
        # no figure found is "unknown", and unknown is not "under the cap":
        # the errand proceeds only because the ceiling still binds the
        # approval, and the absence is recorded rather than assumed
        self.approve(self.propose_purchase())
        with mock.patch.object(errands, "SPENDING_KINDS", set()):
            done = self.execute(page_text="Confirm your order")
        self.assertIsNone(done["observed_total"])

    # ---- §143 boundaries --------------------------------------------

    def test_a_bank_step_up_stops_the_errand_before_it_acts(self):
        self.approve(self.propose())
        clicked = []
        done = errands.run(
            "e1",
            reader=lambda url: {"text": "Total $42.00. Verified by Visa: enter your code"},
            interact=lambda *a: clicked.append(a) or {"text": "ok"})
        self.assertEqual(done["state"], errands.AT_BOUNDARY)
        self.assertEqual(clicked, [])
        self.assertIn("bank", done["detail"])
        self.assertTrue(done["remaining"])

    def test_a_boundary_reached_mid_errand_is_handed_back(self):
        self.approve(self.propose())
        done = self.execute(after="Enter the one-time code we sent to your phone")
        self.assertEqual(done["state"], errands.AT_BOUNDARY)
        self.assertIn("one-time code", done["detail"])
        self.assertIn("handed the last step back", done["remaining"])

    def test_every_boundary_class_in_143_is_recognised(self):
        for text, expect in [
                ("Please complete reCAPTCHA", "blocking automation"),
                ("Signature required here", "signature"),
                ("Upload your driving licence", "identity"),
                ("Use Face ID to continue", "biometrics"),
                ("I agree to the terms", "consent"),
                ("3-D Secure authentication", "bank")]:
            hit = errands.boundary_in(text)
            self.assertIsNotNone(hit, text)
            self.assertIn(expect, hit[1], text)

    def test_an_ordinary_page_is_not_a_boundary(self):
        self.assertIsNone(errands.boundary_in(
            "Your cart: 1 x kettle, $42.00. Proceed to checkout."))

    def test_spoken_tells_him_what_is_left_to_do(self):
        self.approve(self.propose())
        said = errands.spoken(self.execute(after="Please enter your verification code"))
        self.assertIn("as far as I can", said)

    # ---- validation --------------------------------------------------

    def test_a_non_http_site_is_refused(self):
        with self.assertRaises(ValueError):
            self.propose(site="file:///c:/windows/system32")

    def test_an_unknown_kind_is_refused(self):
        with self.assertRaises(ValueError):
            self.propose(kind="wire_transfer")

    def test_steps_are_bounded(self):
        with self.assertRaises(ValueError):
            self.propose(steps=STEPS * 20)

    def test_malformed_steps_are_refused_by_the_browser_validator(self):
        with self.assertRaises(ValueError) as caught:
            self.propose(steps=[{"action": "click"}])  # no selector
        self.assertIn("selector", str(caught.exception))

    def test_a_read_failure_fails_the_errand_rather_than_guessing(self):
        self.approve(self.propose())

        def boom(url):
            raise OSError("dns")

        done = errands.run("e1", reader=boom, interact=lambda *a: {"text": "ok"})
        self.assertEqual(done["state"], errands.FAILED)


if __name__ == "__main__":
    unittest.main()
