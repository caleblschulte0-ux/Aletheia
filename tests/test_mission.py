"""One goal, a budget, and no further questions — with the budget real.

The operator, 2026-09-02: *"If I say, hey, where are my projects standing?
Look at it through all and fix all the problems — I can do that."* He could
not, and the reason was not a gate refusing him. Every capability was scoped
to one action with one approval, and the code loop did one repair in one
repository per run. A mission is the unit he actually thinks in.

The whole safety argument is that the budget is real and the refusals still
bite, so that is what these test.
"""
import datetime as dt
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import journal, machine_binding, mission, policy, stateio


class MissionCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        d = Path(self.tmp.name)
        env = mock.patch.dict(os.environ,
                              {"ALETHEIA_MACHINE_KEY": str(d / "machine.key")})
        env.start(); self.addCleanup(env.stop)
        for target, attr, value in (
                (policy, "APPROVALS_DIR", d / "approvals"),
                (policy, "HALT_PATH", d / "halt.json"),
                (journal, "JOURNAL_PATH", d / "journal.jsonl"),
                (mission, "MISSION_PATH", d / "mission.json")):
            p = mock.patch.object(target, attr, value)
            p.start(); self.addCleanup(p.stop)


class TheBudgetIsReal(MissionCase):
    def test_a_mission_runs_until_its_work_budget_is_spent(self):
        mission.start("fix_projects", hours=2, actions=2)
        self.assertIsNotNone(mission.active())
        mission.note("repo-a: PR_OPEN", spent=1)
        self.assertIsNotNone(mission.active(), "one of two spent, still running")
        mission.note("repo-b: PR_OPEN", spent=1)
        self.assertIsNone(mission.active(), "budget spent — it must end itself")
        self.assertEqual(mission.status()["state"], mission.DONE)

    def test_a_mission_ends_when_its_time_runs_out(self):
        mission.start("fix_projects", hours=1, actions=50)
        later = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=2)
        self.assertIsNone(mission.active(now=later))
        self.assertEqual(mission.status()["state"], mission.EXPIRED)

    def test_ceilings_are_bounded_at_creation(self):
        for kwargs in ({"hours": 0}, {"hours": 99}, {"actions": 0},
                       {"actions": 10_000}):
            with self.subTest(**kwargs):
                with self.assertRaises(ValueError):
                    mission.start("fix_projects", **kwargs)

    def test_progress_survives_a_restart(self):
        """The scheduled task dies and comes back. A mission that forgot its
        own history would repeat itself forever and call that working."""
        mission.start("fix_projects", hours=2, actions=5)
        mission.note("repo-a: PR_OPEN", spent=1)
        reloaded = mission.load()
        self.assertEqual(reloaded["actions_used"], 1)
        self.assertEqual(mission.status()["remaining"], 4)

    def test_a_refused_review_does_not_spend_budget(self):
        mission.start("fix_projects", hours=2, actions=2)
        mission.note("repo-a: REVIEW_REJECTED", spent=0)
        self.assertIsNotNone(mission.active(),
                             "work the reviewer refused produced nothing; "
                             "charging for it ends the mission early on exactly "
                             "the days it worked hardest")


class AMissionIsNotNewAuthority(MissionCase):
    """The point of §70: a budget answers 'how much', never 'what'."""

    def test_operator_always_can_never_be_covered(self):
        for cid in ("purchase.execute", "email.send", "finance.transact",
                    "reservation.book", "errand.run", "secret.fill",
                    "computer.control", "phone.call", "browser.interact"):
            with self.subTest(capability=cid):
                with self.assertRaises(mission.MissionRefused):
                    mission.refuse_forbidden([cid])

    def test_only_allowlisted_capabilities_are_covered(self):
        """Even a capability that is merely operator_once is refused unless
        somebody deliberately added it — an allowlist, not a risk-class rule
        that a generous classification could quietly widen."""
        with self.assertRaises(mission.MissionRefused):
            mission.refuse_forbidden(["work.direct"])
        with self.assertRaises(mission.MissionRefused):
            mission.refuse_forbidden(["secret.store"])
        mission.refuse_forbidden(["code.autonomous"])  # must not raise

    def test_an_unregistered_capability_is_refused(self):
        with self.assertRaises(mission.MissionRefused):
            mission.refuse_forbidden(["something.invented"])

    def test_every_declared_kind_is_allowlisted(self):
        """A new mission kind cannot smuggle a capability in with it."""
        for name, spec in mission.KINDS.items():
            with self.subTest(kind=name):
                mission.refuse_forbidden(spec["capabilities"])

    def test_editing_the_record_to_add_a_capability_kills_the_mission(self):
        mission.start("fix_projects", hours=2, actions=5)
        record = json.loads(mission.MISSION_PATH.read_text())
        record["capabilities"] = ["code.autonomous", "purchase.execute"]
        stateio.write_json_atomic(mission.MISSION_PATH, record)
        self.assertIsNone(mission.active(),
                          "a record edited to widen itself must not run")


class ItCanBeStopped(MissionCase):
    def test_halt_ends_a_running_mission(self):
        mission.start("fix_projects", hours=2, actions=5)
        policy.halt("stop everything", via="test")
        with self.assertRaises(policy.Halted):
            mission.start("fix_projects")

    def test_stop_is_one_word_and_immediate(self):
        mission.start("fix_projects", hours=2, actions=5)
        self.assertTrue(mission.stop())
        self.assertIsNone(mission.active())
        self.assertEqual(mission.status()["state"], mission.STOPPED)
        self.assertFalse(mission.stop(), "stopping a stopped mission is not an error")

    def test_two_missions_cannot_compete_for_one_budget(self):
        mission.start("fix_projects", hours=2, actions=5)
        with self.assertRaises(mission.MissionError):
            mission.start("fix_projects")


class ItCannotBeGrantedRemotely(MissionCase):
    def test_a_mission_delivered_over_git_is_inert(self):
        """Same attack as the standing grants: the file and its approval can
        both travel, the machine key cannot."""
        mission.start("fix_projects", hours=2, actions=5)
        delivered = json.loads(mission.MISSION_PATH.read_text())
        Path(os.environ["ALETHEIA_MACHINE_KEY"]).unlink()
        machine_binding.machine_key()          # a different machine's key
        stateio.write_json_atomic(mission.MISSION_PATH, delivered)
        self.assertIsNone(mission.active())

    def test_raising_the_ceiling_on_disk_breaks_the_binding(self):
        mission.start("fix_projects", hours=2, actions=2)
        record = json.loads(mission.MISSION_PATH.read_text())
        record["max_actions"] = 500
        stateio.write_json_atomic(mission.MISSION_PATH, record)
        self.assertIsNone(mission.active())

    def test_extending_the_deadline_on_disk_breaks_the_binding(self):
        mission.start("fix_projects", hours=1, actions=5)
        record = json.loads(mission.MISSION_PATH.read_text())
        record["expires"] = "2099-01-01T00:00:00Z"
        stateio.write_json_atomic(mission.MISSION_PATH, record)
        self.assertIsNone(mission.active())


class HeCanSeeWhatItIsDoing(MissionCase):
    def test_status_distinguishes_never_ran_from_finished(self):
        self.assertFalse(mission.status()["running"])
        self.assertIn("no mission", mission.status()["detail"])
        mission.start("fix_projects", hours=2, actions=5)
        mission.note("repo-a: PR_OPEN", spent=1)
        mission.stop()
        after = mission.status()
        self.assertFalse(after["running"])
        self.assertEqual(after["used"], 1)
        self.assertTrue(after["ended_because"],
                        "'nothing running' and 'it ended having done one thing' "
                        "are different answers")

    def test_it_answers_out_loud(self):
        self.assertIn("don't have a mission", mission.spoken_status())
        mission.start("fix_projects", hours=2, actions=4)
        mission.note("repo-a: PR_OPEN", spent=1)
        said = mission.spoken_status()
        self.assertIn("1 of 4", said)
        self.assertIn("3 to go", said)


class TheSweepCoversEveryRepository(MissionCase):
    """The structural fix. `cycle()` returns after ONE repair in ONE
    repository; six repos at one item per half hour is not an answer to
    "fix all the problems"."""

    def repos(self):
        return {"repos": [{"full_name": f"me/r{i}", "private": False,
                           "observation_complete": True} for i in range(4)]}

    def test_a_sweep_works_several_repositories_in_one_slice(self):
        from aletheia import code_worker, project_loop
        mission.start("fix_projects", hours=2, actions=10)
        with mock.patch.object(project_loop.code_trust, "active",
                               return_value={"id": "ct"}), \
             mock.patch.object(project_loop, "reconcile_prior", return_value=[]), \
             mock.patch.object(project_loop.portfolio, "scan_all",
                               return_value=self.repos()), \
             mock.patch.object(project_loop, "choose_work",
                               side_effect=lambda repo, request=None: {
                                   "task_id": "t", "kind": "issue",
                                   "objective": "o", "evidence": ""}), \
             mock.patch.object(code_worker, "prepare_pr",
                               return_value={"status": "PR_OPEN",
                                             "pr_url": "u"}) as prepare:
            result = project_loop.run_mission_slice(request=mock.Mock(), slice_max=3)
        self.assertEqual(result["status"], "SWEPT")
        self.assertEqual(len(result["worked"]), 3, "swept more than one repo")
        self.assertEqual(prepare.call_count, 3)
        self.assertEqual(mission.status()["used"], 3)

    def test_a_sweep_stops_the_moment_the_budget_is_gone(self):
        from aletheia import code_worker, project_loop
        mission.start("fix_projects", hours=2, actions=1)
        with mock.patch.object(project_loop.code_trust, "active",
                               return_value={"id": "ct"}), \
             mock.patch.object(project_loop, "reconcile_prior", return_value=[]), \
             mock.patch.object(project_loop.portfolio, "scan_all",
                               return_value=self.repos()), \
             mock.patch.object(project_loop, "choose_work",
                               side_effect=lambda repo, request=None: {
                                   "task_id": "t", "kind": "issue",
                                   "objective": "o", "evidence": ""}), \
             mock.patch.object(code_worker, "prepare_pr",
                               return_value={"status": "PR_OPEN",
                                             "pr_url": "u"}) as prepare:
            project_loop.run_mission_slice(request=mock.Mock(), slice_max=9)
        self.assertEqual(prepare.call_count, 1, "the ceiling is the ceiling")

    def test_no_mission_means_no_sweep(self):
        from aletheia import code_worker, project_loop
        with mock.patch.object(code_worker, "prepare_pr") as prepare:
            result = project_loop.run_mission_slice(request=mock.Mock())
        self.assertEqual(result["status"], "NO_MISSION")
        prepare.assert_not_called()

    def test_halting_mid_sweep_stops_it(self):
        from aletheia import code_worker, project_loop
        mission.start("fix_projects", hours=2, actions=10)

        def halt_after_first(*a, **k):
            policy.halt("enough", via="test")
            return {"status": "PR_OPEN", "pr_url": "u"}

        with mock.patch.object(project_loop.code_trust, "active",
                               return_value={"id": "ct"}), \
             mock.patch.object(project_loop, "reconcile_prior", return_value=[]), \
             mock.patch.object(project_loop.portfolio, "scan_all",
                               return_value=self.repos()), \
             mock.patch.object(project_loop, "choose_work",
                               side_effect=lambda repo, request=None: {
                                   "task_id": "t", "kind": "issue",
                                   "objective": "o", "evidence": ""}), \
             mock.patch.object(code_worker, "prepare_pr",
                               side_effect=halt_after_first) as prepare:
            with self.assertRaises(policy.Halted):
                project_loop.run_mission_slice(request=mock.Mock(), slice_max=9)
        self.assertEqual(prepare.call_count, 1,
                         "a kill switch checked only at the top of a "
                         "twenty-minute run is a suggestion")

    def test_one_repository_failing_does_not_end_the_sweep(self):
        from aletheia import code_worker, project_loop
        mission.start("fix_projects", hours=2, actions=10)
        calls = []

        def flaky(full_name, *a, **k):
            calls.append(full_name)
            if len(calls) == 1:
                raise RuntimeError("that repo is a mess")
            return {"status": "PR_OPEN", "pr_url": "u"}

        with mock.patch.object(project_loop.code_trust, "active",
                               return_value={"id": "ct"}), \
             mock.patch.object(project_loop, "reconcile_prior", return_value=[]), \
             mock.patch.object(project_loop.portfolio, "scan_all",
                               return_value=self.repos()), \
             mock.patch.object(project_loop, "choose_work",
                               side_effect=lambda repo, request=None: {
                                   "task_id": "t", "kind": "issue",
                                   "objective": "o", "evidence": ""}), \
             mock.patch.object(code_worker, "prepare_pr", side_effect=flaky):
            result = project_loop.run_mission_slice(request=mock.Mock(), slice_max=3)
        self.assertEqual(len(result["errors"]), 1)
        self.assertTrue(result["worked"], "it moved on to the next repository")


if __name__ == "__main__":
    unittest.main()
