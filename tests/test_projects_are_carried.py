"""He starts projects hot, drifts inside two weeks, and needs her to carry them.

    "I'll start a project really passionate about it for, like, a week or
    two and then just kinda get bored and forget about it ... I just need
    [her] to be able to take my projects and continue building ... and
    keeping me on track too."   — 2026-09-10

What was measured that day, and what these tests hold against:

- The local code loop had made 150 attempts and opened ZERO pull requests,
  most of them the same few failures asked about again every half hour.
- There were zero project records, so nothing said what any project was for.
- The pulse read default branches only, so Money_Machine read "empty stub"
  beside about 500 commits of Barkly on a branch.
- Every merge waited on him, which for someone who has drifted means never —
  except where he said it must: the trader and Aletheia itself.
"""
from __future__ import annotations

import copy
import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import (brief, code_worker, contracts, orchestrator, plans, policy,
                      project_loop, project_merge, pulse)
from aletheia.fleet import load_fleet

NOW = dt.datetime(2026, 9, 10, 15, 0, tzinfo=dt.timezone.utc)
BASE = "claude/barkley-mvp-mobile-qbegtj"
FULL = "me/Money_Machine"
FLEET = {"owner": "me", "repos": {
    "money_machine": {"github": "Money_Machine"},
    "schwab_trader": {"github": "schwab-trader"},
    "aletheia": {"github": "Aletheia"},
}}


def ago(days: float) -> str:
    return (NOW - dt.timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")


def charter(slug="barkly", risk="low", base=BASE, repo="money_machine", steps=None):
    return {
        "slug": slug, "title": slug.replace("-", " ").title(), "goal": "a real goal",
        "state": "open", "created": "2026-09-10T00:00:00Z",
        "project": {"repo": repo, "base_branch": base, "risk": risk},
        "steps": copy.deepcopy(steps) if steps is not None else [
            {"n": 1, "text": "fix CI", "state": "todo", "owner": "thea"},
            {"n": 2, "text": "turn on Pages", "state": "todo", "owner": "caleb"},
            {"n": 3, "text": "pick a bundle id", "state": "todo", "owner": "caleb"},
            {"n": 4, "text": "make release check pass", "state": "todo", "owner": "thea", "needs": [3]},
        ],
    }


class TempPlans(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        for target, name, value in ((plans, "PLANS_DIR", root / "plans"),
                                    (brief, "BRIEF_DIR", root / "brief")):
            patch = mock.patch.object(target, name, value)
            patch.start()
            self.addCleanup(patch.stop)


class TheCharterContractCase(unittest.TestCase):
    def test_the_charters_on_disk_are_valid_goals_and_valid_plans(self):
        fleet = load_fleet()
        found = {p["slug"]: p for p in plans.all_plans() if plans.is_charter(p)}
        for slug in ("barkly", "open-range-promo", "holdco-platform", "schwab-trader"):
            self.assertIn(slug, found)
        for slug, plan in found.items():
            with self.subTest(slug=slug):
                self.assertEqual(contracts.validate_goal(plan), [])
                self.assertEqual(plans.validate_plan(plan, fleet), [])

    def test_the_trader_waits_for_him(self):
        """His words: "The trader and Aletheia's own code still wait for you.\""""
        self.assertEqual(plans.load("schwab-trader")["project"]["risk"], "high")

    def test_an_unknown_owner_or_risk_is_refused(self):
        fleet = load_fleet()
        bad_owner = charter()
        bad_owner["steps"][0]["owner"] = "chatgpt"
        bad_risk = charter(risk="medium")
        for plan in (bad_owner, bad_risk):
            self.assertTrue(contracts.validate_goal(plan))
            self.assertTrue(plans.validate_plan(plan, fleet))

    def test_a_charter_names_a_real_repo_and_a_branch(self):
        fleet = load_fleet()
        self.assertTrue(plans.validate_plan(charter(repo="nowhere"), fleet))
        self.assertTrue(plans.validate_plan(charter(base=""), fleet))

    def test_a_need_must_name_an_earlier_step(self):
        plan = charter()
        plan["steps"][0]["needs"] = [4]
        self.assertTrue(plans.validate_plan(plan, load_fleet()))


class WhoseStepIsNextCase(unittest.TestCase):
    def test_the_builder_skips_his_steps_and_unmet_needs(self):
        plan = charter()
        self.assertEqual(plans.next_for(plan, plans.THEA)["n"], 1)
        plan["steps"][0]["state"] = "done"
        # step 4 is hers but needs step 3, which is his and not done
        self.assertIsNone(plans.next_for(plan, plans.THEA))
        self.assertEqual(plans.next_for(plan, plans.CALEB)["n"], 2)
        plan["steps"][2]["state"] = "done"
        self.assertEqual(plans.next_for(plan, plans.THEA)["n"], 4)

    def test_a_blocked_step_is_nobodys_next(self):
        plan = charter()
        plan["steps"][1]["state"] = "blocked"
        self.assertEqual(plans.next_for(plan, plans.CALEB)["n"], 3)

    def test_the_projects_next_step_is_the_first_not_done(self):
        plan = charter()
        plan["steps"][0]["state"] = "done"
        self.assertEqual(plans.next_step(plan)["n"], 2)

    def test_an_unmarked_step_is_hers(self):
        self.assertEqual(plans.owner({"n": 1, "text": "x", "state": "todo"}), plans.THEA)


class TheOrchestratorLeavesChartersAloneCase(unittest.TestCase):
    def test_a_charter_is_not_compiled_into_tasks(self):
        """Twenty placeholder tasks at the top of the brief would bury the
        one thing that needs him."""
        ordinary = {"slug": "wall", "state": "open"}
        with mock.patch.object(plans, "all_plans", return_value=[charter(), ordinary]), \
             mock.patch.object(orchestrator, "compile_goal") as compiled, \
             mock.patch.object(orchestrator, "sync_goal", return_value={}):
            orchestrator.run_all()
        compiled.assert_called_once_with("wall", worker=None)


class BranchSource:
    def __init__(self, commits=(), open_prs=(), closed_prs=(), fail=False):
        self.commits, self.open_prs, self.closed_prs = list(commits), list(open_prs), list(closed_prs)
        self.fail = fail
        self.asked = []

    def branch_commits(self, gh, branch, n=30):
        self.asked.append(("commits", gh, branch))
        if self.fail:
            raise RuntimeError("no network")
        return self.commits

    def pull_requests(self, gh, branch, state):
        self.asked.append(("prs", gh, branch, state))
        return self.open_prs if state == "open" else self.closed_prs


class ReadFromTheBranchItLivesOnCase(unittest.TestCase):
    def collect(self, source, rows=None):
        return pulse.collect_projects(FLEET, source, rows or [charter()], now=NOW)

    def test_the_charter_branch_is_what_is_read(self):
        source = BranchSource()
        self.collect(source)
        self.assertIn(("commits", "Money_Machine", BASE), source.asked)

    def test_a_render_bot_is_not_anybody_moving_the_project(self):
        source = BranchSource(commits=[
            {"date": ago(0), "bot": True, "message": "render art"},
            {"date": ago(9), "bot": False, "message": "real work"},
        ])
        item = self.collect(source)["items"][0]
        self.assertEqual(item["days_quiet"], 9)
        self.assertEqual(item["commits_7d"], 0)

    def test_nothing_but_machine_commits_is_quiet_for_at_least_that_long(self):
        source = BranchSource(commits=[
            {"date": ago(1), "bot": True, "message": "update exit decisions [skip ci]"},
            {"date": ago(12), "bot": True, "message": "update exit decisions [skip ci]"},
        ])
        item = self.collect(source)["items"][0]
        self.assertEqual((item["days_quiet"], item["quiet_at_least"]), (12, True))
        thing = brief.pick_one_thing({"projects": {"items": [
            {**item, "yours": None}]}}, now=NOW)
        self.assertEqual(thing["kind"], "drift")
        self.assertIn("at least 12 days", thing["text"])

    def test_a_state_writer_is_not_progress_but_claude_is(self):
        """The trader's sell-brain commits state every few hours with no
        linked account; it made a month-stalled executor read "moved today"."""
        sell_brain = {"author": None, "commit": {
            "author": {"name": "schwab-sell-brain"},
            "message": "sell-brain: update exit decisions [skip ci]"}}
        render = {"author": {"login": "github-actions[bot]", "type": "Bot"},
                  "commit": {"author": {"name": "github-actions[bot]"}, "message": "render art"}}
        claude = {"author": {"login": "claude", "type": "User"},
                  "commit": {"author": {"name": "Claude"}, "message": "Art: light the beach"}}
        self.assertTrue(pulse.is_machine_commit(sell_brain))
        self.assertTrue(pulse.is_machine_commit(render))
        self.assertFalse(pulse.is_machine_commit(claude))

    def test_only_a_merged_pr_naming_this_charter_is_evidence(self):
        source = BranchSource(closed_prs=[
            {"number": 5, "merged_at": ago(1), "body": "Charter-Step: barkly#1", "url": "u5"},
            {"number": 6, "merged_at": None, "body": "Charter-Step: barkly#2", "url": "u6"},
            {"number": 7, "merged_at": ago(1), "body": "Charter-Step: other#1", "url": "u7"},
        ])
        evidence = self.collect(source)["evidence"]
        self.assertEqual([(e["n"], e["pr"], e["base"]) for e in evidence], [(1, 5, BASE)])

    def test_an_unreadable_branch_says_so_instead_of_guessing_quiet(self):
        item = self.collect(BranchSource(fail=True))["items"][0]
        self.assertIn("error", item)
        self.assertNotIn("days_quiet", item)

    def test_the_summary_says_whose_step_is_next(self):
        item = self.collect(BranchSource())["items"][0]
        self.assertEqual(item["hers"]["n"], 1)
        self.assertEqual(item["yours"]["n"], 2)

    def test_the_real_collector_still_names_every_charter_without_the_methods(self):
        """A source that predates branch reads records errors, never crashes."""
        class Old:
            pass
        items = pulse.collect_projects(FLEET, Old(), [charter()], now=NOW)["items"]
        self.assertEqual(len(items), 1)
        self.assertIn("error", items[0])


class CreditOnlyFromAMergeCase(TempPlans):
    def setUp(self):
        super().setUp()
        plans.save(charter())

    def evidence(self, **over):
        row = {"slug": "barkly", "n": 1, "pr": 5, "url": "u", "merged_at": ago(1), "base": BASE}
        row.update(over)
        return [row]

    def test_a_merge_into_the_charter_branch_credits_the_step(self):
        self.assertEqual(plans.credit_merged(self.evidence()), [{"slug": "barkly", "n": 1, "pr": 5}])
        self.assertEqual(plans.load("barkly")["steps"][0]["state"], "done")

    def test_a_merge_into_another_branch_credits_nothing(self):
        self.assertEqual(plans.credit_merged(self.evidence(base="main")), [])
        self.assertEqual(plans.load("barkly")["steps"][0]["state"], "todo")

    def test_no_merge_no_credit(self):
        self.assertEqual(plans.credit_merged(self.evidence(merged_at=None)), [])

    def test_it_is_safe_to_run_every_pulse(self):
        plans.credit_merged(self.evidence())
        self.assertEqual(plans.credit_merged(self.evidence()), [])


def item(slug, **over):
    row = {"slug": slug, "title": slug.title(), "risk": "low", "done": 0, "total": 4,
           "days_quiet": 1, "open_prs": [], "yours": None, "hers": None,
           "next": {"n": 1, "text": "x", "owner": "thea", "state": "todo"}}
    row.update(over)
    return row


def pulse_of(*items):
    return {"repos": {}, "generated_at": "2026-09-10T11:00:00Z", "fleet_revision": 5,
            "projects": {"items": list(items)}}


class TheOneThingCase(TempPlans):
    def test_a_pull_request_only_he_may_merge_comes_first(self):
        trader = item("schwab-trader", risk="high", open_prs=[{
            "number": 3, "title": "watchdog names the cause", "draft": False,
            "head": "claude/thea-schwab-trader-s3-ab", "url": "https://x/3",
            "created_at": ago(2)}])
        barkly = item("barkly", yours={"n": 2, "text": "turn on Pages"}, days_quiet=30)
        thing = brief.pick_one_thing(pulse_of(barkly, trader), now=NOW)
        self.assertEqual((thing["kind"], thing["slug"], thing["pr"]), ("merge", "schwab-trader", 3))

    def test_a_low_risk_pull_request_is_hers_to_merge_not_his(self):
        barkly = item("barkly", open_prs=[{"number": 9, "head": "claude/thea-barkly-s1-x",
                                           "draft": False, "created_at": ago(1)}])
        self.assertIsNone(brief.pick_one_thing(pulse_of(barkly), now=NOW))

    def test_his_step_on_the_project_that_has_waited_longest(self):
        a = item("alpha", yours={"n": 2, "text": "a thing"}, days_quiet=2)
        b = item("bravo", yours={"n": 3, "text": "b thing"}, days_quiet=9)
        thing = brief.pick_one_thing(pulse_of(a, b), now=NOW)
        self.assertEqual((thing["kind"], thing["slug"], thing["n"]), ("step", "bravo", 3))
        self.assertIn("Reply done", thing["text"])

    def test_a_stalled_project_is_asked_about(self):
        stale = item("holdco", days_quiet=brief.DRIFT_DAYS + 1)
        thing = brief.pick_one_thing(pulse_of(stale), now=NOW)
        self.assertEqual(thing["kind"], "drift")
        self.assertIn(f"{brief.DRIFT_DAYS + 1} days", thing["text"])
        self.assertIn("keep or drop", thing["text"])

    def test_keep_quiets_the_question(self):
        stale = item("holdco", days_quiet=30)
        snoozes = {"holdco": (NOW + dt.timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%SZ")}
        self.assertIsNone(brief.pick_one_thing(pulse_of(stale), snoozes=snoozes, now=NOW))

    def test_the_brief_leads_with_it(self):
        text = brief.compose(pulse_of(item("barkly", yours={"n": 2, "text": "turn on Pages"})),
                             None, [], 0)
        self.assertIn("## 🧭 Your one thing today", text)
        self.assertIn("turn on Pages", text)
        self.assertLess(text.index("Your one thing today"), text.index("## Projects"))

    def test_the_line_his_phone_shows_is_the_one_thing(self):
        posted = []

        def request(method, path, body=None):
            if method == "GET":
                return [{"number": 12, "title": brief.BRIEF_TITLE}]
            posted.append((method, path, body))
            return {}
        brief.deliver_issue("the brief", "2026-09-10", "me/Aletheia", request=request,
                            lead="Barkly: turn on Pages. Reply done when it is.")
        comment = [b for m, p, b in posted if p.endswith("/comments")][0]["body"]
        self.assertTrue(comment.startswith("**Your one thing today:** Barkly: turn on Pages"))


class HisReplyCase(TempPlans):
    def setUp(self):
        super().setUp()
        plans.save(charter())

    def today(self, **thing):
        brief._write_state(brief.ONE_THING_FILE, thing)

    def test_done_marks_his_step_and_names_the_next(self):
        self.today(kind="step", slug="barkly", n=2, title="Barkly", step="turn on Pages")
        said = brief.reply("Done!", now=NOW)
        self.assertEqual(plans.load("barkly")["steps"][1]["state"], "done")
        self.assertIn("Marked done: turn on Pages", said)
        self.assertIn("pick a bundle id", said)

    def test_answering_twice_changes_nothing(self):
        self.today(kind="step", slug="barkly", n=2, title="Barkly", step="turn on Pages")
        brief.reply("done", now=NOW)
        self.assertIn("already answered", brief.reply("done", now=NOW))

    def test_keep_quiets_the_drift_check_for_a_week(self):
        self.today(kind="drift", slug="barkly", title="Barkly")
        brief.reply("keep", now=NOW)
        snoozes = brief._read_state(brief.SNOOZE_FILE)
        stale = item("barkly", days_quiet=30)
        tomorrow = NOW + dt.timedelta(days=1)
        self.assertIsNone(brief.pick_one_thing(pulse_of(stale), snoozes=snoozes, now=tomorrow))
        later = NOW + dt.timedelta(days=brief.SNOOZE_DAYS + 1)
        self.assertIsNotNone(brief.pick_one_thing(pulse_of(stale), snoozes=snoozes, now=later))

    def test_drop_drops_the_charter(self):
        self.today(kind="drift", slug="barkly", title="Barkly")
        brief.reply("drop it", now=NOW)
        self.assertEqual(plans.load("barkly")["state"], "dropped")

    def test_a_reply_that_answers_nothing_changes_nothing(self):
        self.today(kind="step", slug="barkly", n=2, title="Barkly", step="turn on Pages")
        said = brief.reply("thanks, looking at this later", now=NOW)
        self.assertIn("nothing changed", said)
        self.assertEqual(plans.load("barkly")["steps"][1]["state"], "todo")

    def test_keep_does_not_answer_a_step(self):
        self.today(kind="step", slug="barkly", n=2, title="Barkly", step="turn on Pages")
        self.assertIn("nothing changed", brief.reply("keep", now=NOW))

    def test_a_day_with_nothing_on_it_takes_no_answer(self):
        self.today(day="2026-09-10")
        self.assertIn("nothing changed", brief.reply("done", now=NOW))


def meta(**over):
    row = {"full_name": FULL, "private": False, "default_branch": "main"}
    row.update(over)
    return row


def a_pr(**over):
    row = {"number": 7, "state": "open", "draft": False, "mergeable": True,
           "mergeable_state": "clean", "title": "Fix the dependency audit",
           "body": "Charter-Step: barkly#1",
           "base": {"ref": BASE},
           "head": {"ref": "claude/thea-barkly-s1-ab", "sha": "abc123",
                    "repo": {"full_name": FULL}}}
    row.update(over)
    return row


def files(**over):
    row = {"filename": "barkly/app/package.json", "additions": 2, "deletions": 1,
           "patch": "@@ -1 +1 @@\n-old\n+new"}
    row.update(over)
    return [row]


def green():
    return [{"name": "Typecheck and tests", "status": "completed", "conclusion": "success"}]


class TheMergeGatesCase(unittest.TestCase):
    def test_a_clean_builder_pull_request_passes(self):
        self.assertEqual(project_merge.refusal(charter(), meta(), a_pr(), files(), green()), "")

    def test_every_gate_refuses(self):
        cases = {
            "Aletheia is his": (charter(), meta(full_name="me/Aletheia"), a_pr(), files(), green()),
            "the trader is his": (charter(), meta(full_name="me/schwab-trader"), a_pr(), files(), green()),
            "a high-risk charter": (charter(risk="high"), meta(), a_pr(), files(), green()),
            "a private repository": (charter(), meta(private=True), a_pr(), files(), green()),
            "another branch": (charter(), meta(), a_pr(base={"ref": "other"}), files(), green()),
            "the default branch": (charter(base="main"), meta(), a_pr(base={"ref": "main"}), files(), green()),
            "not a builder branch": (charter(), meta(), a_pr(head={"ref": "feature/x", "sha": "a",
                                                                 "repo": {"full_name": FULL}}), files(), green()),
            "a fork": (charter(), meta(), a_pr(head={"ref": "claude/thea-barkly-s1-ab", "sha": "a",
                                                    "repo": {"full_name": "stranger/Money_Machine"}}),
                       files(), green()),
            "a draft": (charter(), meta(), a_pr(draft=True), files(), green()),
            "names no step": (charter(), meta(), a_pr(body="just some work"), files(), green()),
            "names his step": (charter(), meta(), a_pr(body="Charter-Step: barkly#2"), files(), green()),
            "not cleanly mergeable": (charter(), meta(), a_pr(mergeable_state="blocked"), files(), green()),
            "a workflow file": (charter(), meta(), a_pr(), files(filename=".github/workflows/ci.yml"), green()),
            "a binary file": (charter(), meta(), a_pr(), [{"filename": "barkly/art.png", "additions": 0,
                                                          "deletions": 0}], green()),
            "no checks at all": (charter(), meta(), a_pr(), files(), []),
            "a failing check": (charter(), meta(), a_pr(), files(),
                                [{"name": "ci", "status": "completed", "conclusion": "failure"}]),
            "a running check": (charter(), meta(), a_pr(), files(),
                                [{"name": "ci", "status": "in_progress", "conclusion": None}]),
            "no readable files": (charter(), meta(), a_pr(), [], green()),
        }
        for name, args in cases.items():
            with self.subTest(gate=name):
                self.assertNotEqual(project_merge.refusal(*args), "", name)


class FakeGitHub:
    def __init__(self, checks=None, pr=None):
        self.calls = []
        self.checks = green() if checks is None else checks
        self.pr = pr or a_pr()

    def __call__(self, method, path, body=None):
        self.calls.append((method, path, body))
        if method == "GET" and path == "/repos/me/Money_Machine":
            return meta()
        if method == "GET" and "/pulls?state=open" in path:
            return [{"number": 7, "head": {"ref": "claude/thea-barkly-s1-ab"}}]
        if method == "GET" and path.endswith("/pulls/7"):
            return self.pr
        if method == "GET" and "/pulls/7/files" in path:
            return files()
        if method == "GET" and "/check-runs" in path:
            return {"check_runs": self.checks}
        if method == "PUT" and path.endswith("/pulls/7/merge"):
            return {"merged": True, "sha": "merged-sha"}
        raise AssertionError((method, path))

    def puts(self):
        return [c for c in self.calls if c[0] == "PUT"]


APPROVED = {"approved": True, "summary": "does what step 1 says", "findings": []}


class TheMergeSweepCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        for name in ("RULING_PATH", "MERGES_DIR", "REVIEWS_DIR", "OPENED_DIR"):
            patch = mock.patch.object(project_merge, name, root / name.lower())
            patch.start()
            self.addCleanup(patch.stop)
        for target, name, value in ((project_merge.code_trust, "active", {"id": "g"}),
                                    (project_merge.reasoner, "review_model", "opus")):
            patch = mock.patch.object(target, name, return_value=value)
            patch.start()
            self.addCleanup(patch.stop)
        project_merge.enable(project_merge.RULING_WORDS, via="test")

    def sweep(self, gh, rows=None, think=None):
        think = think or mock.Mock(return_value=dict(APPROVED))
        return project_merge.sweep(request=gh, plan_rows=rows or [charter()], fleet=FLEET,
                                   think=think, now=NOW), think

    def test_a_green_reviewed_builder_pr_is_merged_at_the_reviewed_commit(self):
        gh = FakeGitHub()
        out, think = self.sweep(gh)
        self.assertEqual(out[0]["status"], "MERGED")
        self.assertEqual(gh.puts()[0][2]["sha"], "abc123")
        self.assertEqual(think.call_args.kwargs["model"], "opus")
        self.assertEqual(len(list(project_merge.MERGES_DIR.glob("*.json"))), 1)

    def test_a_same_model_review_is_no_review(self):
        gh = FakeGitHub()
        with mock.patch.object(project_merge.reasoner, "review_model",
                               return_value=project_merge.BUILDER_MODEL):
            out, think = self.sweep(gh)
        self.assertEqual(out[0]["status"], "REVIEW_REJECTED")
        think.assert_not_called()
        self.assertEqual(gh.puts(), [])

    def test_a_rejected_change_is_reviewed_once_per_commit_not_every_cycle(self):
        think = mock.Mock(return_value={"approved": False, "summary": "wrong fix", "findings": []})
        for _ in range(3):
            out, _ = self.sweep(FakeGitHub(), think=think)
            self.assertEqual(out[0]["status"], "REVIEW_REJECTED")
        self.assertEqual(think.call_count, 1)

    def test_red_ci_is_not_reviewed_or_merged(self):
        gh = FakeGitHub(checks=[{"name": "ci", "status": "completed", "conclusion": "failure"}])
        out, think = self.sweep(gh)
        self.assertEqual(out[0]["status"], "WAITING")
        think.assert_not_called()
        self.assertEqual(gh.puts(), [])

    def test_the_repositories_he_merges_are_not_even_read(self):
        """A charter edited to say "low" on Aletheia buys nothing."""
        gh = FakeGitHub()
        rows = [charter(slug="schwab-trader", repo="schwab_trader", risk="high", base="main"),
                charter(slug="thea-herself", repo="aletheia", risk="low", base="claude/x")]
        out, _ = self.sweep(gh, rows=rows)
        self.assertEqual((out, gh.calls), ([], []))

    def test_off_means_off(self):
        project_merge.disable(via="test")
        gh = FakeGitHub()
        out, _ = self.sweep(gh)
        self.assertEqual((out, gh.calls), ([], []))

    def test_no_grant_no_merge(self):
        gh = FakeGitHub()
        with mock.patch.object(project_merge.code_trust, "active", return_value=None):
            out, _ = self.sweep(gh)
        self.assertEqual((out, gh.calls), ([], []))

    def test_a_daily_ceiling(self):
        project_merge.MERGES_DIR.mkdir(parents=True)
        for i in range(project_merge.MAX_MERGES_PER_DAY):
            (project_merge.MERGES_DIR / f"m{i}.json").write_text(
                json.dumps({"merged_at": ago(0.1)}), encoding="utf-8")
        gh = FakeGitHub()
        out, _ = self.sweep(gh)
        self.assertEqual(out[-1]["status"], "THROTTLED")
        self.assertEqual(gh.puts(), [])

    def test_halt_stops_it(self):
        with mock.patch.object(project_merge.policy, "ensure_not_halted",
                               side_effect=policy.Halted("stop")):
            with self.assertRaises(policy.Halted):
                self.sweep(FakeGitHub())


class OpeningWhatTheBuilderPushedCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patch = mock.patch.object(project_merge, "OPENED_DIR", Path(self.tmp.name) / "opened")
        patch.start()
        self.addCleanup(patch.stop)
        patch = mock.patch.object(project_merge.code_trust, "active", return_value={"id": "g"})
        patch.start()
        self.addCleanup(patch.stop)

    def github(self, existing=()):
        posts = []

        def request(method, path, body=None):
            if method == "GET" and "/branches" in path:
                return [{"name": "claude/thea-barkly-s1-ab", "commit": {"sha": "s1"}},
                        {"name": BASE, "commit": {"sha": "b"}},
                        {"name": "claude/thea-barkly-s9-zz", "commit": {"sha": "s9"}}]
            if method == "GET" and "/pulls?state=all" in path:
                return [{"head": {"ref": ref}} for ref in existing]
            if method == "POST" and path.endswith("/pulls"):
                posts.append(body)
                return {"html_url": "https://github.com/me/Money_Machine/pull/8"}
            raise AssertionError((method, path))
        return request, posts

    def test_it_opens_the_pr_naming_the_step(self):
        request, posts = self.github()
        out = project_merge.open_builder_prs(request=request, plan_rows=[charter()], fleet=FLEET)
        self.assertEqual([o["status"] for o in out], ["OPENED"])
        self.assertEqual(posts[0]["base"], BASE)
        self.assertIn("Charter-Step: barkly#1", posts[0]["body"])

    def test_it_asks_once_per_branch_head(self):
        request, posts = self.github()
        project_merge.open_builder_prs(request=request, plan_rows=[charter()], fleet=FLEET)
        project_merge.open_builder_prs(request=request, plan_rows=[charter()], fleet=FLEET)
        self.assertEqual(len(posts), 1)

    def test_a_branch_with_a_pull_request_is_left_alone(self):
        request, posts = self.github(existing=["claude/thea-barkly-s1-ab"])
        project_merge.open_builder_prs(request=request, plan_rows=[charter()], fleet=FLEET)
        self.assertEqual(posts, [])

    def test_the_trader_pr_says_who_merges_it(self):
        request, posts = self.github()
        trader = charter(slug="barkly", repo="schwab_trader", risk="high", base="main")
        project_merge.open_builder_prs(request=request, plan_rows=[trader], fleet=FLEET)
        self.assertIn("Caleb merges himself", posts[0]["body"])


class TheLoopStopsAskingTheSameQuestionCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patch = mock.patch.object(code_worker, "RUNS_DIR", Path(self.tmp.name) / "runs")
        patch.start()
        self.addCleanup(patch.stop)

    def request(self, runs, step="npm audit"):
        def request(method, path, body=None):
            if path.endswith("/actions/runs?per_page=20"):
                return {"workflow_runs": runs}
            if "/jobs" in path:
                return {"jobs": [{"name": "validate", "conclusion": "failure",
                                  "steps": [{"name": step, "conclusion": "failure"}]}]}
            raise AssertionError(path)
        return request

    def run_row(self, run_id, branch="main"):
        return {"id": run_id, "name": "CI", "status": "completed", "conclusion": "failure",
                "head_branch": branch}

    def test_a_failure_off_the_default_branch_is_not_repair_work(self):
        repo = {"full_name": "me/repo", "default_branch": "main"}
        request = self.request([self.run_row(9, branch="claude/barkley-mvp")])
        self.assertIsNone(project_loop._ci_work(repo, request=request))

    def test_a_declined_failure_is_not_asked_again_on_its_next_run(self):
        repo = {"full_name": "me/repo", "default_branch": "main"}
        first = project_loop._ci_work(repo, request=self.request([self.run_row(10)]))
        code_worker._save_run("me/repo", first["task_id"], {
            "status": "DECLINED", "updated_at": code_worker.stateio.utcnow()})
        self.assertIsNone(project_loop._ci_work(repo, request=self.request([self.run_row(11)])))
        different = project_loop._ci_work(repo, request=self.request([self.run_row(12)], step="pytest"))
        self.assertIsNotNone(different)
        self.assertNotEqual(different["task_id"], first["task_id"])

    def test_a_decline_expires_once_the_code_has_had_a_week_to_move(self):
        old = (dt.datetime.now(dt.timezone.utc)
               - dt.timedelta(days=code_worker.DECLINE_TTL_DAYS + 1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        code_worker._save_run("me/repo", "ci-abc", {"status": "DECLINED", "updated_at": old})
        self.assertFalse(code_worker.declined("me/repo", "ci-abc"))
        code_worker._save_run("me/repo", "ci-new", {"status": "DECLINED",
                                                    "updated_at": code_worker.stateio.utcnow()})
        self.assertTrue(code_worker.declined("me/repo", "ci-new"))

    def test_carrying_the_charters_never_costs_the_repair_its_turn(self):
        with mock.patch.object(project_loop.project_merge, "open_builder_prs",
                               side_effect=RuntimeError("github down")), \
             mock.patch.object(project_loop.project_merge, "sweep", return_value=[]):
            out = project_loop._carry_projects(request=mock.Mock())
        self.assertIn("opened_error", out)
        self.assertEqual(out["merges"], [])

    def test_but_halt_still_stops_everything(self):
        with mock.patch.object(project_loop.project_merge, "open_builder_prs",
                               side_effect=policy.Halted("stop")):
            with self.assertRaises(policy.Halted):
                project_loop._carry_projects(request=mock.Mock())


if __name__ == "__main__":
    unittest.main()
