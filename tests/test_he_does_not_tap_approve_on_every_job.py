"""Two finished applications sat waiting for a tap that was never coming.

2026-09-12, his ruling: *"No one approval per application. I want this
thing just to be applying to jobs, nonstop."* The beat had been written
for the opposite shape — she fills the form, it waits as an ordinary
approval, he taps Approve on his phone — and that shape fails him at
precisely the moment the whole thing exists for: once he has gone away.

Measured that evening, twenty minutes after the hunt restarted: GitLab
and Figma were both fully answered, zero blocking questions, sitting at
AWAITING_YOU. Nothing was wrong with them. Nobody was going to tap
anything. They would have sat there until he came back and did by hand
the thing he built this to stop doing by hand.

So a standing grant over `application.submit` now authorizes a send. The
half of this worth testing is that it is a GRANT and not a hole:

- no grant and no approval sends nothing, which is the whole safety
  argument and the first thing a refactor would quietly break;
- the grant is spent per application, with the application named in the
  receipt, so "what authorized this send" has an answer per employer
  rather than one blanket yes;
- his own tap still works and still sends, because retiring the tap as
  MANDATORY is not the same as removing it.

One trap this file exists to hold, found by reading rather than by
running: `accept` and `submit` BOTH re-check
`policy.usable(record["approval"])`. An earlier version of the fix let
the record past the beat's gate and left its approval ungranted, so it
died two functions later with "it needs your confirmation" — the same
stall, moved somewhere harder to see. The grant path decides the
approval, so those two checks stay exactly as strict as they were.

And one about testing, paid for twice in CI: this file first mocked the
two modules through `sys.modules`, passed on its own, and failed all four
assertions in the full suite on both platforms. `from aletheia import
apply_run` reads an ATTRIBUTE of the package; Python only falls back to
`sys.modules` when that attribute is missing. Run alone, nothing had
imported the real module yet, so the fallback found the mock. Run in the
suite, an earlier test had imported it, the attribute was there, and the
real module answered with no runs — every send silently became zero. A
green run of one file proves less than it looks like: if the thing under
test resolves a name at call time, patch where it will actually LOOK.
"""
from __future__ import annotations

import unittest
from unittest import mock

import aletheia
# Imported for the side effect, and the noqa is load-bearing: the function
# under test does `from aletheia import apply_run, authority`, which reads an
# ATTRIBUTE of the package — so the attribute has to exist before setUp can
# patch it. See the note on test order in the docstring above.
from aletheia import apply_run as _real_apply_run  # noqa: F401
from aletheia import authority as _real_authority  # noqa: F401
from aletheia import runtime


class ARecord(dict):
    """The shape the beat reads: an id, a url, and an approval id."""


def record(run_id="apply-1", url="https://boards.greenhouse.io/x"):
    return {"id": run_id, "url": url, "approval": f"approval-{run_id}"}


class HeDoesNotTapApproveOnEveryJobCase(unittest.TestCase):
    def setUp(self):
        self.sent = []
        self.confirmed = []
        self.claimed = []

        self.runs = [record("apply-1"), record("apply-2",
                                               "https://boards.greenhouse.io/y")]
        self.approval_state = "PENDING"
        self.grant = "apply-nonstop"

        def satisfy(capability_id, action_id, **kw):
            self.claimed.append((capability_id, action_id))
            return self.grant

        def confirm(run_id, *, via="operator", because=""):
            self.confirmed.append((run_id, via, because))
            return {"id": run_id, "state": "APPROVED"}

        def submit_in_process(run_id, runner=None):
            self.sent.append(run_id)
            return {"result": {"verdict": "confirmed", "note": "sent"}}

        fake_apply_run = mock.Mock()
        fake_apply_run.all_runs.return_value = self.runs
        fake_apply_run.confirm.side_effect = confirm
        fake_apply_run.accept.side_effect = lambda run_id: {"id": run_id}
        self.apply_run = fake_apply_run

        fake_authority = mock.Mock()
        fake_authority.satisfy.side_effect = satisfy

        # The PACKAGE ATTRIBUTES, not sys.modules — see the docstring. A
        # sys.modules patch is only consulted when the attribute is absent,
        # so it worked alone and did nothing in the suite.
        for name, fake in (("apply_run", fake_apply_run),
                           ("authority", fake_authority)):
            p = mock.patch.object(aletheia, name, fake)
            p.start(); self.addCleanup(p.stop)

        patch2 = mock.patch.object(
            runtime, "policy",
            mock.Mock(load=lambda _id: {"state": self.approval_state}))
        patch2.start(); self.addCleanup(patch2.stop)

        patch3 = mock.patch.object(
            runtime, "_submit_in_its_own_process", side_effect=submit_in_process)
        patch3.start(); self.addCleanup(patch3.stop)

        patch4 = mock.patch.object(runtime, "notifications", mock.Mock())
        patch4.start(); self.addCleanup(patch4.stop)

    def test_a_standing_grant_sends_it_with_nobody_watching(self):
        sent = runtime.send_approved_applications()
        self.assertEqual([s["application"] for s in sent],
                         ["apply-1", "apply-2"],
                         "his ruling: applying to jobs, nonstop")

    def test_no_grant_and_no_approval_sends_nothing(self):
        """The safety argument. A refactor that breaks this sends his
        application to employers nothing authorized."""
        self.grant = None
        self.assertEqual(runtime.send_approved_applications(), [])
        self.assertEqual(self.sent, [])

    def test_the_grant_is_spent_per_application_and_names_it(self):
        """One blanket yes would make 'what authorized this send' a
        question with no per-employer answer, and the grant's use count
        meaningless."""
        runtime.send_approved_applications()
        self.assertEqual(self.claimed,
                         [("application.submit", "apply:apply-1"),
                          ("application.submit", "apply:apply-2")])

    def test_the_approval_is_granted_so_the_later_checks_still_pass(self):
        """`accept` and `submit` re-check `policy.usable`. Leaving the
        approval ungranted moved the stall instead of fixing it."""
        runtime.send_approved_applications()
        self.assertEqual([c[0] for c in self.confirmed], ["apply-1", "apply-2"])
        for _run, via, because in self.confirmed:
            self.assertEqual(via, "standing-grant")
            self.assertIn("apply-nonstop", because,
                          "the receipt says which grant sent it")

    def test_his_own_tap_still_sends_and_spends_no_grant(self):
        """Retiring the tap as MANDATORY is not removing it."""
        self.approval_state = "APPROVED"
        sent = runtime.send_approved_applications()
        self.assertEqual(len(sent), 2)
        self.assertEqual(self.claimed, [], "his tap needs no standing grant")
        self.assertEqual(self.confirmed, [],
                         "an approved approval is not re-granted")


if __name__ == "__main__":
    unittest.main()
