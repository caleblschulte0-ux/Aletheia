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
