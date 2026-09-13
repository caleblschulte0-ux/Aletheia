"""The builder's rules, held to what they are FOR.

Every test here is a situation that really happened on 2026-09-13, when
the loop had run daily for three days and opened nothing.
"""
from __future__ import annotations

import unittest

from aletheia import charter_work as cw


def charter(slug, steps, *, state="open", base="claude/base-x"):
    return {"slug": slug, "title": slug, "state": state,
            "project": {"repo": "money_machine", "base_branch": base, "risk": "low"},
            "steps": steps}


def step(n, owner="thea", state="todo", needs=None, text="do the thing"):
    s = {"n": n, "text": text, "state": state, "owner": owner}
    if needs:
        s["needs"] = needs
    return s


class BranchNames(unittest.TestCase):
    def test_a_builder_branch_round_trips(self):
        ref = cw.branch_name("holdco-platform", 2, "bdd5")
        self.assertEqual(ref, "claude/thea-holdco-platform-s2-bdd5")
        self.assertEqual(cw.parse_branch(ref), ("holdco-platform", 2))

    def test_a_slug_with_hyphens_keeps_its_hyphens(self):
        """`open-range-promo` must not be truncated at the first hyphen —
        the step number is what terminates the slug, not a dash."""
        self.assertEqual(cw.parse_branch("claude/thea-open-range-promo-s1-0a1b"),
                         ("open-range-promo", 1))

    def test_someone_elses_branch_is_not_a_builder_branch(self):
        for ref in ("claude/apply-end-to-end", "chatgpt/code-worker-v1",
                    "claude/thea-x-s1", "main", ""):
            self.assertIsNone(cw.parse_branch(ref), ref)


class TheRuleThatStarvedTheLoop(unittest.TestCase):
    """A base branch someone else is committing to is NOT a collision.

    This is the whole bug. The builder works on its own branch and opens a
    pull request back into the base; a base that moves is a merge, later.
    The old prose rule skipped any charter whose base had a real commit in
    the last twelve hours, and Caleb's AI_HANDOFF loop commits to
    open-range-promo's base every hour — so it could never be picked.
    """

    def test_a_base_committed_to_one_minute_ago_is_still_eligible(self):
        plan = charter("open-range-promo", [step(1)])
        facts = {"open-range-promo": cw.RepoFacts(base_age_hours=0.016)}
        survey = cw.choose([plan], facts)
        self.assertIsNotNone(survey.decision)
        self.assertEqual(survey.decision.action, cw.BUILD)
        self.assertEqual(survey.decision.n, 1)

    def test_the_most_neglected_base_is_picked_first(self):
        a = charter("busy", [step(1)])
        b = charter("stale", [step(1)])
        facts = {"busy": cw.RepoFacts(base_age_hours=1.0),
                 "stale": cw.RepoFacts(base_age_hours=900.0)}
        self.assertEqual(cw.choose([a, b], facts).decision.slug, "stale")

    def test_a_base_that_does_not_exist_yet_is_the_most_neglected(self):
        a = charter("old", [step(1)])
        b = charter("brand-new", [step(1)])
        facts = {"old": cw.RepoFacts(base_age_hours=5000.0),
                 "brand-new": cw.RepoFacts(base_age_hours=None)}
        self.assertEqual(cw.choose([a, b], facts).decision.slug, "brand-new")


class TheOrphanBranch(unittest.TestCase):
    """Work that was pushed and never got a pull request.

    `claude/thea-holdco-platform-s2-bdd5` has sat in Money_Machine since
    2026-09-11 with one commit and no pull request, because the builder has
    no GitHub tools and its fallback needed a Core that was never switched
    on. Rebuilding the step would throw that away.
    """

    def test_a_pushed_branch_with_no_pr_is_finished_not_restarted(self):
        plan = charter("holdco-platform", [step(2)])
        facts = {"holdco-platform": cw.RepoFacts(
            thea_branches=("claude/thea-holdco-platform-s2-bdd5",))}
        d = cw.choose([plan], facts).decision
        self.assertEqual(d.action, cw.FINISH_PR)
        self.assertEqual(d.branch, "claude/thea-holdco-platform-s2-bdd5")
        self.assertEqual(d.n, 2)

    def test_finishing_a_pull_request_beats_starting_new_work(self):
        pushed = charter("holdco-platform", [step(2)])
        fresh = charter("barkly", [step(1)])
        facts = {"holdco-platform": cw.RepoFacts(
                     thea_branches=("claude/thea-holdco-platform-s2-bdd5",),
                     base_age_hours=1.0),
                 "barkly": cw.RepoFacts(base_age_hours=99999.0)}
        d = cw.choose([pushed, fresh], facts).decision
        self.assertEqual((d.action, d.slug), (cw.FINISH_PR, "holdco-platform"))

    def test_a_branch_that_already_has_its_pr_is_waiting_not_orphaned(self):
        ref = "claude/thea-holdco-platform-s2-bdd5"
        plan = charter("holdco-platform", [step(2)])
        facts = {"holdco-platform": cw.RepoFacts(thea_branches=(ref,),
                                                 open_thea_prs=(ref,))}
        survey = cw.choose([plan], facts)
        self.assertIsNone(survey.decision)
        self.assertIn("waiting for review", dict(survey.skipped)["holdco-platform"])

    def test_a_branch_naming_a_step_the_charter_lost_says_so(self):
        plan = charter("holdco-platform", [step(2)])
        facts = {"holdco-platform": cw.RepoFacts(
            thea_branches=("claude/thea-holdco-platform-s9-aaaa",))}
        survey = cw.choose([plan], facts)
        self.assertIsNone(survey.decision)
        self.assertIn("no longer has", dict(survey.skipped)["holdco-platform"])


class WhoseStepItIs(unittest.TestCase):
    def test_his_steps_are_never_picked_for_her(self):
        plan = charter("x", [step(1, owner="caleb"), step(2, owner="caleb")])
        survey = cw.choose([plan], {})
        self.assertIsNone(survey.decision)
        self.assertIn("no step of hers", dict(survey.skipped)["x"])

    def test_she_does_not_stall_behind_a_step_of_his(self):
        """His step 1 being undone must not block her step 2 — that is how
        a system meant to run without him ends up waiting for him."""
        plan = charter("x", [step(1, owner="caleb"), step(2, owner="thea")])
        self.assertEqual(cw.choose([plan], {}).decision.n, 2)

    def test_a_step_waiting_on_an_undone_need_is_not_doable(self):
        plan = charter("x", [step(1, owner="caleb"), step(2, needs=[1])])
        self.assertIsNone(cw.choose([plan], {}).decision)

    def test_a_step_whose_needs_are_done_is_doable(self):
        plan = charter("x", [step(1, owner="caleb", state="done"), step(2, needs=[1])])
        self.assertEqual(cw.choose([plan], {}).decision.n, 2)

    def test_an_unowned_step_is_hers(self):
        plan = {"slug": "x", "state": "open",
                "project": {"repo": "r", "base_branch": "b"},
                "steps": [{"n": 1, "text": "t", "state": "todo"}]}
        self.assertEqual(cw.choose([plan], {}).decision.n, 1)


class WhatIsNotACharter(unittest.TestCase):
    def test_a_plan_with_no_project_block_is_not_a_charter(self):
        plan = {"slug": "light-up-the-wall", "state": "open",
                "steps": [step(1)]}
        survey = cw.choose([plan], {})
        self.assertIsNone(survey.decision)
        self.assertIn("not a charter", dict(survey.skipped)["light-up-the-wall"])

    def test_a_proposed_charter_is_never_built(self):
        """`proposed` means he has not said yes. Nothing may be built on it."""
        plan = charter("new-idea", [step(1)], state="proposed")
        survey = cw.choose([plan], {})
        self.assertIsNone(survey.decision)
        self.assertIn("not open", dict(survey.skipped)["new-idea"])

    def test_every_skipped_charter_gives_a_reason(self):
        """Silence is what made this invisible for three days."""
        plans_ = [charter("a", [step(1, owner="caleb")]),
                  charter("b", [step(1)], state="proposed"),
                  {"slug": "c", "state": "open", "steps": []}]
        survey = cw.choose(plans_, {})
        self.assertEqual({s for s, _ in survey.skipped}, {"a", "b", "c"})
        for _, reason in survey.skipped:
            self.assertTrue(reason.strip())


class TheHandoff(unittest.TestCase):
    def test_the_body_carries_the_line_that_credits_the_step(self):
        """`plans.credit_merged` will not credit a step without this exact
        line, so it is written here rather than by whoever remembers it."""
        body = cw.pr_body("barkly", 3, "Add the sound effects")
        self.assertEqual(body.splitlines()[0], "Charter-Step: barkly#3")
        self.assertIn("Add the sound effects", body)

    def test_the_credit_line_is_what_plans_actually_looks_for(self):
        from aletheia import plans as P
        body = cw.pr_body("barkly", 3, "x")
        import re
        m = re.search(r"^Charter-Step:\s*(?P<slug>[^\s#]+)#(?P<n>\d+)\s*$",
                      body, re.M)
        self.assertIsNotNone(m)
        self.assertEqual((m.group("slug"), int(m.group("n"))), ("barkly", 3))
        self.assertTrue(hasattr(P, "credit_merged"))


class NothingToDo(unittest.TestCase):
    def test_no_charters_is_a_survey_not_a_crash(self):
        survey = cw.choose([], {})
        self.assertIsNone(survey.decision)
        self.assertEqual(survey.skipped, [])
        self.assertEqual(survey.as_dict()["action"], "none")

    def test_the_survey_serialises_for_a_machine(self):
        plan = charter("x", [step(1, text="build it")])
        d = cw.choose([plan], {}).as_dict()
        self.assertEqual((d["action"], d["slug"], d["n"]), ("build", "x", 1))
        self.assertEqual(d["text"], "build it")


if __name__ == "__main__":
    unittest.main()


class ObservingGitHub(unittest.TestCase):
    """The read that feeds the rules. Stubbed at the wire — a suite that
    reaches the network answers differently on a train."""

    FLEET = {"owner": "caleblschulte0-ux",
             "repos": {"money_machine": {"github": "Money_Machine"}}}
    PLAN = charter("holdco-platform", [step(2)],
                   base="claude/ai-holdco-master-playbook-i5q80w")
    BRANCH = "claude/thea-holdco-platform-s2-bdd5"

    def _request(self, routes):
        def request(method, path, *a, **k):
            for key, value in routes.items():
                if key in path:
                    return value
            return []
        return request

    def test_a_pushed_branch_with_no_pr_is_seen(self):
        req = self._request({"/branches": [{"name": self.BRANCH}, {"name": "main"}],
                             "/pulls": [],
                             "/commits": [{"commit": {"committer":
                                          {"date": "2026-08-06T02:51:23Z"}}}]})
        facts = cw.observe(self.PLAN, self.FLEET, request=req)
        self.assertEqual(facts.thea_branches, (self.BRANCH,))
        self.assertEqual(facts.open_thea_prs, ())
        self.assertGreater(facts.base_age_hours, 0)

    def test_branches_that_are_not_builder_branches_are_ignored(self):
        req = self._request({"/branches": [{"name": "main"},
                                           {"name": "claude/apply-end-to-end"}],
                             "/pulls": [{"head": {"ref": "claude/apply-end-to-end"}}]})
        facts = cw.observe(self.PLAN, self.FLEET, request=req)
        self.assertEqual((facts.thea_branches, facts.open_thea_prs), ((), ()))

    def test_a_repo_the_token_cannot_see_is_empty_facts_not_a_crash(self):
        def boom(method, path, *a, **k):
            raise OSError("403")
        facts = cw.observe(self.PLAN, self.FLEET, request=boom)
        self.assertEqual(facts, cw.RepoFacts())

    def test_a_charter_whose_repo_is_not_in_the_fleet_is_empty_facts(self):
        plan = dict(self.PLAN, project={"repo": "nope", "base_branch": "b"})
        def explode(*a, **k):
            raise AssertionError("must not call GitHub for an unknown repo")
        self.assertEqual(cw.observe(plan, self.FLEET, request=explode), cw.RepoFacts())

    def test_survey_decides_from_what_it_saw(self):
        req = self._request({"/branches": [{"name": self.BRANCH}],
                             "/pulls": [], "/commits": []})
        d = cw.survey([self.PLAN], self.FLEET, request=req).decision
        self.assertEqual((d.action, d.branch), (cw.FINISH_PR, self.BRANCH))

    def test_it_never_writes(self):
        """This module reads. Opening a pull request is
        project_merge.open_builder_prs, and there must not be a second one."""
        seen = []
        def request(method, path, *a, **k):
            seen.append(method)
            return []
        cw.survey([self.PLAN], self.FLEET, request=request)
        self.assertEqual(set(seen), {"GET"})
        src = open("aletheia/charter_work.py", encoding="utf-8").read()
        self.assertNotIn('"POST"', src)
