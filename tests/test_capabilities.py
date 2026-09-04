import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import act, brief, journal, plans, sentinel
from aletheia.fleet import load_fleet
from aletheia.pulse import collect, enrich, find_alerts, transitions
from tests.test_pulse import FakeSource


class RecordingAPI:
    """Injectable stand-in for gh.request that scripts GET responses and
    records every write."""

    def __init__(self, open_issues=None):
        self.open_issues = open_issues or []
        self.calls = []

    def __call__(self, method, path, body=None, tok=None):
        self.calls.append((method, path, body))
        if method == "GET" and "/issues" in path:
            return self.open_issues
        if method == "POST" and path.endswith("/issues"):
            return {"number": 99}
        return {}


def _pulse(fleet, **fake_kwargs):
    return collect(fleet, FakeSource(**fake_kwargs))


class TestJournal(unittest.TestCase):
    def test_append_search_since(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "j.jsonl"
            journal.append("decision", "suggestion:x", "doing — confirmed", path=p)
            journal.append("alert", "repo:trader", "health green -> red", path=p)
            self.assertEqual(len(journal.entries(p)), 2)
            self.assertEqual(len(journal.search("trader", p)), 1)
            self.assertEqual(len(journal.since(1, p)), 2)

    def test_unknown_kind_refused(self):
        with self.assertRaises(ValueError):
            journal.append("vibes", "x", "y", path=Path("/nonexistent/j.jsonl"))


class TestTransitionsAndAlerts(unittest.TestCase):
    def setUp(self):
        self.fleet = load_fleet()

    def test_transition_detected(self):
        prev = _pulse(self.fleet)
        cur = _pulse(self.fleet, failed_workflows={"watchdog.yml"})
        t = transitions(prev, cur)
        self.assertEqual(t, [{"repo": "schwab_trader", "github": "schwab-trader",
                              "from": "green", "to": "red"}])

    def test_no_previous_pulse_means_no_transitions(self):
        self.assertEqual(transitions(None, _pulse(self.fleet)), [])

    def test_alerts_name_the_failing_workflow(self):
        cur = _pulse(self.fleet, failed_workflows={"watchdog.yml"})
        alerts = find_alerts(cur)
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0]["github"], "schwab-trader")
        self.assertEqual(alerts[0]["failing"], ["watchdog.yml"])

    def test_offline_unknown_is_not_an_alert(self):
        cur = _pulse(self.fleet)
        for r in cur["repos"].values():
            for w in r.get("workflows", {}).values():
                w.clear(); w["error"] = "unavailable offline"
            r["health"] = "unknown" if r["status"] == "active" else r["health"]
        self.assertEqual(find_alerts(cur), [])

    def test_unreachable_active_repo_is_an_alert(self):
        cur = _pulse(self.fleet, dead_repos={"schwab-trader"})
        alerts = find_alerts(cur)
        self.assertEqual([a["github"] for a in alerts], ["schwab-trader"])
        self.assertIn("error", alerts[0])


class TestSentinel(unittest.TestCase):
    def setUp(self):
        self.fleet = load_fleet()
        patcher = mock.patch.object(journal, "JOURNAL_PATH",
                                    Path(tempfile.mkdtemp()) / "j.jsonl")
        patcher.start(); self.addCleanup(patcher.stop)

    def test_opens_issue_on_new_fault(self):
        pulse = enrich(_pulse(self.fleet, failed_workflows={"watchdog.yml"}), None)
        api = RecordingAPI(open_issues=[])
        self.assertEqual(sentinel.sync(pulse, "o/r", api), "opened")
        posts = [c for c in api.calls if c[0] == "POST"]
        self.assertEqual(len(posts), 1)
        self.assertIn("schwab-trader", posts[0][2]["title"])

    def test_closes_issue_on_recovery(self):
        pulse = enrich(_pulse(self.fleet), None)
        api = RecordingAPI(open_issues=[{"number": 7, "title": "🚨 Fleet alert: schwab-trader"}])
        self.assertEqual(sentinel.sync(pulse, "o/r", api), "closed")
        self.assertIn(("PATCH", "/repos/o/r/issues/7", {"state": "closed"}), api.calls)

    def test_quiet_fleet_touches_nothing(self):
        pulse = enrich(_pulse(self.fleet), None)
        api = RecordingAPI(open_issues=[])
        self.assertEqual(sentinel.sync(pulse, "o/r", api), "quiet")
        self.assertEqual([c for c in api.calls if c[0] != "GET"], [])


class TestBrief(unittest.TestCase):
    def setUp(self):
        self.fleet = load_fleet()

    def test_deltas_and_composition(self):
        prev = _pulse(self.fleet)
        cur = _pulse(self.fleet)
        # yesterday shorts had fewer posts
        for v in prev["repos"]["shorts_pipeline"]["vitals"]:
            if v["label"] == "trending posted":
                v["value"] = 1
        deltas = brief.vital_deltas(prev, cur)
        self.assertEqual(deltas["shorts_pipeline"]["trending posted"], 2)
        text = brief.compose(enrich(cur, prev), prev, [], new_suggestions=2)
        self.assertIn("(+2)", text)
        # And the half this test used to assert: the trader's realized
        # P&L and cash balance are PRIVATE vitals now, so they never
        # reach the brief — which is a committed file in a public repo.
        self.assertNotIn("schwab_trader", deltas)
        self.assertNotIn("P&L", text)
        self.assertIn("2 ChatGPT suggestion(s)", text)
        self.assertIn("All quiet.", text)

    def test_faults_lead_the_brief(self):
        cur = enrich(_pulse(self.fleet, failed_workflows={"daily.yml"}), None)
        text = brief.compose(cur, None, [], 0)
        self.assertIn("fault(s) need eyes", text)
        self.assertIn("Shorts-pipeline", text.split("\n")[2])


class TestPlans(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        for target, attr in ((plans, "PLANS_DIR"), (journal, "JOURNAL_PATH")):
            p = mock.patch.object(target, attr, Path(self.tmp.name) / attr.lower())
            p.start(); self.addCleanup(p.stop)
        self.addCleanup(self.tmp.cleanup)

    def test_lifecycle_is_journaled(self):
        plans.new_plan("test-plan", "A test", "prove the lifecycle")
        plans.add_step("test-plan", "first step", repo="shorts_pipeline")
        plans.set_step("test-plan", 1, "done")
        plan = plans.load("test-plan")
        self.assertEqual(plans.progress(plan), (1, 1))
        kinds = [e["kind"] for e in journal.entries()]
        self.assertEqual(kinds, ["plan", "plan", "plan"])

    def test_validate_catches_unknown_repo_and_state(self):
        plans.new_plan("bad-plan", "Bad", "goal")
        plan = plans.load("bad-plan")
        plan["steps"] = [{"n": 1, "text": "x", "state": "someday", "repo": "not_real"}]
        plans.save(plan)
        problems = plans.validate_plan(plans.load("bad-plan"), load_fleet())
        self.assertEqual(len(problems), 2)


class TestAct(unittest.TestCase):
    def setUp(self):
        self.fleet = load_fleet()
        p = mock.patch.object(journal, "JOURNAL_PATH",
                              Path(tempfile.mkdtemp()) / "j.jsonl")
        p.start(); self.addCleanup(p.stop)

    def test_unallowed_dispatch_refused(self):
        api = RecordingAPI()
        with self.assertRaises(act.Refused):
            act.dispatch(self.fleet, "shorts_pipeline", "daily.yml", request=api)
        self.assertEqual(api.calls, [])  # refused BEFORE any network call

    def test_allowed_dispatch_goes_through_front_door(self):
        api = RecordingAPI()
        act.dispatch(self.fleet, "aletheia", "pulse.yml", request=api)
        self.assertEqual(api.calls[0][0], "POST")
        self.assertIn("/actions/workflows/pulse.yml/dispatches", api.calls[0][1])
        self.assertEqual([e["kind"] for e in journal.entries()], ["action"])

    def test_issue_grant_checked(self):
        api = RecordingAPI()
        with self.assertRaises(act.Refused):
            act.file_issue(self.fleet, "money_machine", "t", "b", request=api)
        act.file_issue(self.fleet, "schwab_trader", "t", "b", request=api)
        self.assertTrue(api.calls)


if __name__ == "__main__":
    unittest.main()
