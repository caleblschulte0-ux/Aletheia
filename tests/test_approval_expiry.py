"""A yes has a shelf life.

An approval never went stale. A question he was asked three weeks ago
sat PENDING, and answering it today authorised a route recorded three
weeks ago against a page that has since been redesigned — the content
binding catches a changed ROUTE, not a changed world. And a yes he gave
on Monday still pressed a button on Friday, which is not what "yes"
meant when he said it: he meant do it now.

Asking again is cheap. Doing the wrong irreversible thing is not.
"""
import datetime as dt
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import journal, policy


def ago(**kw):
    when = dt.datetime.now(dt.timezone.utc) - dt.timedelta(**kw)
    return when.strftime("%Y-%m-%dT%H:%M:%SZ")


class ExpiryCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        (root / "approvals").mkdir()
        for target, attr, value in (
                (policy, "APPROVALS_DIR", root / "approvals"),
                (policy, "HALT_PATH", root / "halt.json"),
                (journal, "JOURNAL_PATH", root / "j.jsonl")):
            patch = mock.patch.object(target, attr, value)
            patch.start(); self.addCleanup(patch.stop)

    def ask(self, aid="a1", *, reversible=False, **when):
        policy.request(aid, f"do:{aid}", reason="because", consequence="it does",
                       reversible=reversible)
        if when:
            row = policy.load(aid)
            row["requested_at"] = ago(**when)
            policy.save(row)
        return aid

    def yes(self, aid, **when):
        policy.decide(aid, "APPROVED", via="phone")
        if when:
            row = policy.load(aid)
            row["decided_at"] = ago(**when)
            policy.save(row)
        return aid


class AQuestionNobodyAnsweredGoesCold(ExpiryCase):
    def test_a_fresh_question_is_still_a_question(self):
        self.assertEqual(policy.stale_reason(policy.load(self.ask())), "")

    def test_one_nobody_answered_for_three_weeks_is_not(self):
        aid = self.ask(days=21)
        why = policy.stale_reason(policy.load(aid))
        self.assertIn("21 days", why)
        self.assertIn("ask me again", why)

    def test_the_beat_writes_that_down(self):
        aid = self.ask(days=21)
        self.assertEqual([a["id"] for a in policy.expire_stale()], [aid])
        self.assertEqual(policy.load(aid)["state"], "EXPIRED")
        self.assertIn("21 days", policy.load(aid)["expired_because"])

    def test_and_it_can_no_longer_be_approved(self):
        aid = self.ask(days=21)
        policy.expire_stale()
        with self.assertRaises(ValueError):
            policy.decide(aid, "APPROVED", via="phone")


class AYesToSomethingIRREVERSIBLE_MEANS_NOW(ExpiryCase):
    def test_a_yes_from_ten_minutes_ago_still_counts(self):
        aid = self.yes(self.ask(), minutes=10)
        ok, why = policy.usable(aid)
        self.assertTrue(ok, why)

    def test_a_yes_from_three_days_ago_does_not(self):
        aid = self.yes(self.ask(), days=3)
        ok, why = policy.usable(aid)
        self.assertFalse(ok)
        self.assertIn("cannot be undone", why)
        self.assertIn("say it again", why)

    def test_but_an_UNDOABLE_thing_can_wait(self):
        """Expiring everything would just teach him to re-approve on
        reflex, which is worse than not expiring anything."""
        aid = self.yes(self.ask("r1", reversible=True), days=30)
        ok, why = policy.usable(aid)
        self.assertTrue(ok, why)

    def test_is_approved_asks_the_same_question(self):
        aid = self.yes(self.ask(), days=3)
        self.assertFalse(policy.is_approved(aid))

    def test_a_missing_approval_is_not_a_yes(self):
        ok, why = policy.usable("never-existed")
        self.assertFalse(ok)
        self.assertIn("never-existed", why)


class EveryIrreversibleACTOR_ASKS_IT(unittest.TestCase):
    """A gate one caller checks and another does not is not a gate."""

    def test_they_go_through_policy_usable(self):
        for name in ("webtask", "apply_run", "script", "computer", "mail"):
            with self.subTest(module=name):
                source = Path("aletheia") / f"{name}.py"
                self.assertIn("policy.usable(", source.read_text(encoding="utf-8"),
                              f"{name} decides for itself whether a yes is a yes")

    def test_the_beat_expires_them(self):
        from aletheia import runtime
        self.assertIn("policy.expire_stale",
                      Path(runtime.__file__).read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
