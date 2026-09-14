"""He went AFK and asked for one thing: don't stop.

2026-09-12, his words: *"make sure it dont stop looking and applying end to
end until i say stop."*

Half of that was already true and half was not, which is the kind of gap
that reads as working right up until he checks:

- **Sending** never stopped. `runtime.send_approved_applications` runs on
  the Core's beat and sends anything AWAITING_YOU whose approval is
  APPROVED, and his standing grant (`apply-nonstop`, 7 days / 200 uses)
  decides those approvals without him.
- **Looking** stopped dead. `campaign.start` spawns one process that finds
  N jobs and exits. When it exits, nothing starts another. He would have
  come back to a finished pile and an idle machine.

`apply_forever` is the missing half, and it is deliberately tiny: if no
campaign is running, start one; wait; look again. Everything that makes
that safe already existed and is not re-implemented here - the campaign
lock stops two running at once, and `policy.ensure_not_halted()` is what
"stop" already means everywhere else in the system.

It runs as a Windows task beside the Core, because a loop started from a
terminal dies with the terminal - which is how the first attempt at
keeping her alive was lost the same night.
"""
from __future__ import annotations

import unittest
from unittest import mock

from aletheia import apply_forever, autostart, policy


class OneBatchAtATimeCase(unittest.TestCase):
    def test_it_does_not_start_a_second_campaign_over_a_running_one(self):
        """The lock already forbids it; the loop must not fight it."""
        started = []
        with mock.patch.object(apply_forever.campaign, "running",
                               return_value={"pid": 4242}), \
             mock.patch.object(apply_forever.policy, "ensure_not_halted"):
            out = apply_forever.once(starter=lambda **kw: started.append(kw))
        self.assertEqual(started, [], "a campaign was already under way")
        self.assertEqual(out["already"], 4242)

    def test_it_starts_one_when_nothing_is_running(self):
        calls = []

        def starter(**kw):
            calls.append(kw)
            return {"started": True, "pid": 7}

        with mock.patch.object(apply_forever.campaign, "running", return_value=None), \
             mock.patch.object(apply_forever.policy, "ensure_not_halted"), \
             mock.patch.object(apply_forever.journal, "append"):
            out = apply_forever.once(batch=8, resume="r.pdf", starter=starter)
        self.assertTrue(out["started"])
        self.assertEqual(calls, [{"count": 8, "resume": "r.pdf"}])


class WhileClaudeIsOutItWaitsCase(unittest.TestCase):
    """Live 2026-09-13 his Claude window was spent for an hour and a batch
    started every five minutes anyway, each unable to name his roles or judge
    a job, each applying to nothing."""

    def setUp(self):
        apply_forever._SAID_REST.clear()

    def test_no_batch_starts_while_nobody_can_think_and_it_is_said_once(self):
        """Since 2026-09-13 Claude resting is not enough to wait: Codex or her
        own model may carry the batch. Nobody at all is (test below for the
        other half: tests/test_apply_past_the_claude_limit.py)."""
        import datetime as dt
        until = dt.datetime(2026, 9, 13, 19, 40, tzinfo=dt.timezone.utc)
        started, said = [], []
        with mock.patch.object(apply_forever.campaign, "running", return_value=None), \
             mock.patch.object(apply_forever.policy, "ensure_not_halted"), \
             mock.patch.object(apply_forever, "_claude_rests_until", return_value=until), \
             mock.patch.object(apply_forever, "_another_mind",
                               return_value=(False, "Codex needs you to sign in again")), \
             mock.patch.object(apply_forever.journal, "append",
                               side_effect=lambda *a, **k: said.append(a)):
            for _ in range(3):
                out = apply_forever.once(starter=lambda **kw: started.append(kw))
        self.assertEqual(started, [])
        self.assertIn("resting_until", out)
        self.assertEqual(len(said), 1, "a long rest is said once, not every turn")

    def test_the_hunt_resumes_when_the_window_comes_back(self):
        calls = []
        with mock.patch.object(apply_forever.campaign, "running", return_value=None), \
             mock.patch.object(apply_forever.policy, "ensure_not_halted"), \
             mock.patch.object(apply_forever, "_claude_rests_until", return_value=None), \
             mock.patch.object(apply_forever.journal, "append"):
            out = apply_forever.once(starter=lambda **kw: calls.append(kw) or {"started": True})
        self.assertTrue(out["started"])
        self.assertEqual(len(calls), 1)


class StopMeansHisHaltCase(unittest.TestCase):
    def test_a_halt_ends_the_loop(self):
        """"Until I say stop" is his halt switch, not a flag this invented."""
        turns = []

        def starter(**kw):
            turns.append(kw)
            return {"started": True}

        with mock.patch.object(apply_forever.policy, "ensure_not_halted",
                               side_effect=policy.Halted("he said stop")), \
             mock.patch.object(apply_forever.journal, "append"):
            code = apply_forever.forever(turns=5, starter=starter,
                                         sleeper=lambda _s: None)
        self.assertEqual(code, 0)
        self.assertEqual(turns, [], "it stopped before starting anything")

    def test_a_failed_batch_does_not_end_the_hunt(self):
        """A bad night at one employer is not a reason to stop applying."""
        attempts = []

        def angry(**kw):
            attempts.append(kw)
            raise RuntimeError("the board was unreachable")

        with mock.patch.object(apply_forever.campaign, "running", return_value=None), \
             mock.patch.object(apply_forever.policy, "ensure_not_halted"), \
             mock.patch.object(apply_forever.journal, "append"):
            apply_forever.forever(turns=3, starter=angry, sleeper=lambda _s: None)
        self.assertEqual(len(attempts), 3, "it kept trying")

    def test_it_waits_between_turns(self):
        slept = []
        with mock.patch.object(apply_forever.campaign, "running",
                               return_value={"pid": 1}), \
             mock.patch.object(apply_forever.policy, "ensure_not_halted"):
            apply_forever.forever(turns=3, wait_s=300.0, sleeper=slept.append)
        self.assertEqual(slept, [300.0, 300.0], "no sleep after the last turn")


class WaitingApplicationsAreRefilledCase(unittest.TestCase):
    """2026-09-13: refilling the applications waiting on him happened only when
    a person ran `python -m aletheia.campaign retry`, and run from an outside
    session it was killed for memory. It is a turn of her own loop now."""

    def setUp(self):
        apply_forever._LAST_REFILL.clear()
        self.addCleanup(apply_forever._LAST_REFILL.clear)
        for target, name, kw in ((apply_forever.campaign, "running", {"return_value": None}),
                                 (apply_forever.policy, "ensure_not_halted", {}),
                                 (apply_forever, "_claude_rests_until", {"return_value": None}),
                                 (apply_forever.journal, "append", {})):
            patch = mock.patch.object(target, name, **kw)
            patch.start()
            self.addCleanup(patch.stop)
        self.batches, self.refills = [], []

    def starter(self, **kw):
        self.batches.append(kw)
        return {"started": True, "pid": 1}

    def refiller(self, **kw):
        self.refills.append(kw)
        return {"started": True, "pid": 2}

    def turn(self, at, waiting):
        with mock.patch.object(apply_forever, "_waiting", return_value=waiting):
            return apply_forever.once(starter=self.starter, refiller=self.refiller,
                                      clock=lambda: at)

    def test_waiting_applications_get_a_refill_instead_of_a_batch(self):
        out = self.turn(10_000.0, waiting=3)
        self.assertTrue(out["refill"])
        self.assertEqual(self.refills, [{"limit": apply_forever.REFILL_LIMIT}])
        self.assertEqual(self.batches, [])

    def test_at_most_one_refill_an_hour_and_batches_in_between(self):
        self.turn(10_000.0, waiting=3)
        self.turn(10_000.0 + 300, waiting=3)
        self.turn(10_000.0 + 1800, waiting=3)
        self.assertEqual((len(self.refills), len(self.batches)), (1, 2))
        self.turn(10_000.0 + apply_forever.REFILL_EVERY_S, waiting=3)
        self.assertEqual(len(self.refills), 2, "an hour on, the waiting ones are read again")

    def test_nothing_waiting_is_a_batch_as_before(self):
        self.turn(10_000.0, waiting=0)
        self.assertEqual((self.refills, len(self.batches)), ([], 1))

    def test_a_refill_is_not_started_over_a_running_campaign_or_while_claude_rests(self):
        import datetime as dt
        with mock.patch.object(apply_forever.campaign, "running", return_value={"pid": 7}):
            self.turn(10_000.0, waiting=3)
        with mock.patch.object(apply_forever, "_claude_rests_until",
                               return_value=dt.datetime(2026, 9, 13, 20, tzinfo=dt.timezone.utc)), \
             mock.patch.object(apply_forever, "_another_mind", return_value=(False, "nobody")):
            self.turn(10_000.0, waiting=3)
        self.assertEqual((self.refills, self.batches), ([], []))

    def test_a_refill_that_cannot_start_does_not_take_every_turn(self):
        def broken(**kw):
            raise RuntimeError("could not spawn")
        with mock.patch.object(apply_forever, "_waiting", return_value=3):
            apply_forever.forever(turns=3, starter=self.starter, refiller=broken,
                                  sleeper=lambda _s: None)
        self.assertEqual(len(self.batches), 2)

    def test_waiting_means_needs_you(self):
        with mock.patch.object(apply_forever.campaign.apply_run, "all_runs",
                               side_effect=lambda state=None: [{}, {}] if state == "NEEDS_YOU"
                               else self.fail(f"read {state}")):
            self.assertEqual(apply_forever._waiting(), 2)


class TheRefillShareTheCampaignLockCase(unittest.TestCase):
    def setUp(self):
        import tempfile
        from pathlib import Path
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        for target, name, value in ((apply_forever.campaign, "LOCK_PATH", root / "running.json"),
                                    (apply_forever.campaign, "RUN_DIR", root)):
            patch = mock.patch.object(target, name, value)
            patch.start()
            self.addCleanup(patch.stop)
        patch = mock.patch.object(apply_forever.campaign.journal, "append")
        patch.start()
        self.addCleanup(patch.stop)

    def test_start_retry_launches_retry_with_notify_under_the_lock(self):
        import json
        campaign = apply_forever.campaign
        spawned = []
        out = campaign.start_retry(limit=25, spawner=lambda args: spawned.append(args) or 4242)
        self.assertTrue(out["started"])
        self.assertEqual(spawned[0][1:], ["-m", "aletheia.campaign", "retry", "--limit", "25",
                                          "--notify"])
        lock = json.loads(campaign.LOCK_PATH.read_text(encoding="utf-8"))
        self.assertEqual((lock["kind"], lock["pid"]), ("retry", 4242))

    def test_it_never_overlaps_a_batch_and_a_batch_never_overlaps_it(self):
        campaign = apply_forever.campaign
        with mock.patch.object(campaign.proc, "pid_alive", return_value=True), \
             mock.patch.object(campaign.applications, "find_resume", return_value="r.pdf"):
            campaign.start("", count=3, spawner=lambda args: 1)
            again = campaign.start_retry(spawner=lambda args: self.fail("ran over a batch"))
            self.assertFalse(again["started"])
            campaign._release()
            campaign.start_retry(spawner=lambda args: 2)
            batch = campaign.start("", count=3, spawner=lambda args: self.fail("ran over a refill"))
            self.assertFalse(batch["started"])

    def test_retry_notify_releases_its_lock_when_done(self):
        import datetime as dt
        import json
        import os
        campaign = apply_forever.campaign
        campaign.LOCK_PATH.write_text(json.dumps(
            {"kind": "retry", "pid": os.getpid(),
             "started_at": dt.datetime.now(dt.timezone.utc).isoformat()}), encoding="utf-8")
        done = {"ready": [], "blocked": [], "failed": [], "closed": [], "left": [],
                "questions": [], "submitted": 0}
        with mock.patch.object(campaign, "retry_waiting", return_value=done) as retry, \
             mock.patch.object(campaign, "_notify") as told:
            self.assertEqual(campaign.main(["retry", "--limit", "5", "--notify"]), 0)
        retry.assert_called_once_with(limit=5)
        self.assertFalse(campaign.LOCK_PATH.exists())
        told.assert_not_called()   # nothing became ready: no hourly "still waiting"

    def test_retry_that_fails_still_releases_the_lock(self):
        import datetime as dt
        import json
        import os
        campaign = apply_forever.campaign
        campaign.LOCK_PATH.write_text(json.dumps(
            {"kind": "retry", "pid": os.getpid(),
             "started_at": dt.datetime.now(dt.timezone.utc).isoformat()}), encoding="utf-8")
        with mock.patch.object(campaign, "retry_waiting", side_effect=RuntimeError("boom")):
            self.assertEqual(campaign.main(["retry", "--notify"]), 1)
        self.assertFalse(campaign.LOCK_PATH.exists())


class ItSurvivesTheSessionThatStartedItCase(unittest.TestCase):
    def test_it_is_registered_as_an_always_on_task(self):
        spec = autostart.TASKS["apply"]
        self.assertEqual(spec.module, "aletheia.apply_forever")
        self.assertEqual(spec.name, "AletheiaApply")

    def test_the_task_has_the_never_dies_contract(self):
        """Same settings as the Core: repeating, unbounded, restarting, and
        IgnoreNew so the repetition can only ever replace a dead run."""
        script = autostart.register_script(autostart.TASKS["apply"], "pythonw.exe")
        self.assertIn("-m aletheia.apply_forever", script)
        self.assertIn("MultipleInstances IgnoreNew", script)
        self.assertIn("ExecutionTimeLimit ([TimeSpan]::Zero)", script)
        self.assertIn("AllowStartIfOnBatteries", script)
        self.assertIn("RepetitionInterval", script)

    def test_it_drops_the_chatgpt_lease_like_every_other_always_on_entry(self):
        """An always-on process may never open his signed-in ChatGPT - the
        defect that put windows over his work earlier the same day."""
        import inspect
        source = inspect.getsource(apply_forever.main)
        self.assertIn("drop_lease", source)


if __name__ == "__main__":
    unittest.main()
