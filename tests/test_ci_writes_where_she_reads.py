"""State CI writes to a branch the Core never reads is state she cannot see.

Found live on 2026-09-08. Five workflows hardcoded ``ref: main`` and
``git push origin main`` while the Core ran from ``live``. Nothing was
broken in a way any test could see - every workflow was internally
consistent, checking out and pushing the same branch - and the result
was that the morning brief for 2026-09-08, which said

    2 fault(s) need eyes: Shorts-pipeline, schwab-trader

sat on ``main``, while the Core, reading ``live``, still had the
previous day's

    All quiet. No faults anywhere in the fleet.

She told him everything was fine out of a file CI had stopped updating
for her. That is the exact failure this repo exists to prevent: not an
error he can see, but a confident, stale, wrong answer.

Three more consequences came from the same pin. The workflows ran
eighty-commit-old code because they checked out the stale branch;
``pages.yml`` built the wall he looks at from that same tree; and
``ci.yml`` only triggered on pushes to ``main``, so nothing pushed to
``live`` was ever tested by CI on push.

So the branch is written down HERE, once, and the workflows are held to
it. If the Core is ever moved to another branch, this constant and the
workflows have to move together - which is precisely the step that was
missed when it moved to ``live``.
"""
from __future__ import annotations

import re
import unittest

from aletheia.fleet import REPO_ROOT

WORKFLOWS = REPO_ROOT / ".github" / "workflows"

#: The branch the Core is deployed on and reads its state from.
#: Change this and the workflows in the same commit, never separately.
DEPLOY_BRANCH = "live"

_CHECKOUT_REF = re.compile(r"^\s*ref:\s*(\S+)\s*$", re.MULTILINE)
_PUSH_TARGET = re.compile(r"git push origin (\S+)", re.MULTILINE)
_PULL_TARGET = re.compile(r"git pull --rebase origin (\S+)", re.MULTILINE)


def _workflows():
    return sorted(WORKFLOWS.glob("*.yml"))


class CiWritesWhereSheReadsCase(unittest.TestCase):
    def test_there_are_workflows_to_check(self):
        """A glob that silently matches nothing passes every test below."""
        self.assertGreaterEqual(len(_workflows()), 5)

    def test_every_push_of_state_goes_to_the_branch_the_core_reads(self):
        for path in _workflows():
            text = path.read_text(encoding="utf-8")
            for branch in _PUSH_TARGET.findall(text):
                with self.subTest(workflow=path.name, branch=branch):
                    self.assertEqual(
                        branch, DEPLOY_BRANCH,
                        f"{path.name} pushes state to '{branch}', but the Core "
                        f"reads '{DEPLOY_BRANCH}'. State pushed anywhere else is "
                        f"invisible to her, and she answers from the stale copy.")

    def test_a_workflow_checks_out_what_it_pushes(self):
        """Rebasing onto one branch and pushing another is how history is lost."""
        for path in _workflows():
            text = path.read_text(encoding="utf-8")
            pushes = set(_PUSH_TARGET.findall(text))
            if not pushes:
                continue
            refs = set(_CHECKOUT_REF.findall(text))
            pulls = set(_PULL_TARGET.findall(text))
            with self.subTest(workflow=path.name):
                self.assertEqual(refs, pushes,
                                 f"{path.name} checks out {sorted(refs)} "
                                 f"and pushes {sorted(pushes)}")
                if pulls:
                    self.assertEqual(pulls, pushes,
                                     f"{path.name} rebases onto {sorted(pulls)} "
                                     f"and pushes {sorted(pushes)}")

    def test_ci_runs_on_the_branch_the_work_lands_on(self):
        """Eighty commits reached `live` without CI ever running on a push."""
        text = (WORKFLOWS / "ci.yml").read_text(encoding="utf-8")
        match = re.search(r"push:\s*\n\s*branches:\s*\[([^\]]+)\]", text)
        self.assertIsNotNone(match, "ci.yml no longer declares push branches")
        branches = {b.strip() for b in match.group(1).split(",")}
        self.assertIn(DEPLOY_BRANCH, branches,
                      f"ci.yml does not run on pushes to '{DEPLOY_BRANCH}', so "
                      f"work landing there is never tested by CI on push")

    def test_the_wall_is_built_from_the_branch_that_is_running(self):
        """A stale Pages build shows him a wall that is not his system."""
        text = (WORKFLOWS / "pages.yml").read_text(encoding="utf-8")
        refs = set(_CHECKOUT_REF.findall(text))
        self.assertEqual(
            refs, {DEPLOY_BRANCH},
            f"pages.yml builds the wall from {sorted(refs)} rather than "
            f"'{DEPLOY_BRANCH}'")


if __name__ == "__main__":
    unittest.main()
