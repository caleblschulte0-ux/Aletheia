"""Self-diagnosis and patch proposals: evidence first, models inside it, and
the live checkout out of reach.

Scripted models only. The trial test builds a scratch git repository and
proves the one thing that matters most: a proposal is tried in a separate
worktree, the named tests run there, and the checkout it came from is
byte-for-byte unchanged.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import agent_session, apply_run, memory_tools, repo_tools, self_diagnosis as sd
from aletheia import stateio, tools


def write_application(ident: str, **fields) -> None:
    folder = apply_run.staged_dir()
    folder.mkdir(parents=True, exist_ok=True)
    stateio.write_json_atomic(folder / f"{ident}.json", {"id": ident, **fields})


def fake_recall(snippets=None):
    calls = []

    def recall(query, sources=None, k=5, include_ledger=True, **kw):
        calls.append({"query": query, "sources": sources})
        if sources == ["code"]:
            return {"snippets": [], "basis": "GUESS"}
        return {"snippets": list(snippets or []), "basis": "FOUND IN HISTORY", "answered_by": "lexical"}
    recall.calls = calls
    return recall


def fake_code_tools(hits=None):
    def search(args):
        if "would not take a click" in args["query"]:
            return {"matched": 1, "hits": hits or [{"path": "aletheia/apply_run.py", "line": 120,
                                                    "text": "raise ApplyError('the Submit button would not take a click')"}]}
        return {"matched": 0, "hits": []}

    def symbol(args):
        return {"definitions": [{"path": "aletheia/apply_run.py", "line": 40, "kind": "class"}]} \
            if args["name"] == "ApplyError" else {"definitions": []}

    def read(args):
        return {"path": args["path"], "start": args["start"], "end": args["start"] + 5,
                "text": f"{args['start']}: raise ApplyError('the Submit button would not take a click')"}
    return {"search": search, "symbol": symbol, "read": read}


CAPTCHA_FAILURE = ("ApplyError: the Submit button would not take a click - a CAPTCHA challenge was "
                   "in front of it, and she does not solve those - nothing was sent")


class Classifying(unittest.TestCase):
    def test_a_named_wall_is_a_boundary(self):
        verdict = sd.classify({"state": "FAILED", "text": CAPTCHA_FAILURE, "record": {}})
        self.assertEqual(verdict["kind"], sd.BOUNDARY)
        self.assertIn("CAPTCHA", verdict["boundary"])

    def test_a_crash_is_a_defect(self):
        verdict = sd.classify({"state": "FAILED", "text": "KeyError: 'questions' in formfill.plan",
                               "record": {}}, {"locations": [{"path": "aletheia/formfill.py"}]})
        self.assertEqual(verdict["kind"], sd.DEFECT)

    def test_both_at_once_is_unclear_not_a_confident_boundary(self):
        verdict = sd.classify({"state": "FAILED", "text": "TypeError while reading the hCaptcha frame"})
        self.assertEqual(verdict["kind"], sd.UNCLEAR)
        self.assertLess(verdict["confidence"], 0.5)

    def test_the_vocabulary_names_walls_not_sites(self):
        for name, _pattern in sd.BOUNDARY_SIGNS:
            for site in ("palantir", "lever", "greenhouse", "workday", "linkedin"):
                self.assertNotIn(site, name.casefold())


class Diagnosing(unittest.TestCase):
    def setUp(self):
        write_application("apply-diag0001", state="FAILED", company="Examplecorp",
                          job_title="Operations Analyst", failure=CAPTCHA_FAILURE,
                          filled=[{"label": "Salary", "value": "SECRET-ANSWER-77"}])

    def test_a_record_is_resolved_gathered_and_classified_without_a_model(self):
        recall = fake_recall([{"source": "fixes", "where": "commit abc123", "text": "hCaptcha: stop and say so",
                               "basis": "FOUND IN HISTORY", "ts": "2026-09-13"}])
        d = sd.diagnose("apply-diag0001", recall=recall, code_tools=fake_code_tools())
        self.assertEqual(d["failure"]["kind"], "application")
        self.assertEqual(d["kind"], sd.BOUNDARY)
        self.assertEqual(d["basis"], "KNOWN")
        self.assertEqual(d["provenance"]["classified_by"], "rules")
        self.assertEqual(d["likely_location"][0]["path"], "aletheia/apply_run.py")
        sources = [e["source"] for e in d["evidence"]]
        self.assertEqual(sources[0], "application")
        self.assertIn("fixes", sources)
        self.assertIn("code", sources)
        self.assertNotIn("SECRET-ANSWER-77", json.dumps(d))
        # similar failures were searched in history, code separately
        self.assertIn("journal", recall.calls[0]["sources"])

    def test_free_words_find_the_record_through_the_general_ledger(self):
        d = sd.diagnose("why can't you handle the Examplecorp application", recall=fake_recall(),
                        code_tools=fake_code_tools())
        self.assertEqual(d["failure"]["ref"], "apply-diag0001")
        self.assertEqual(d["failure"]["resolved_by"], "ledger")

    def test_nothing_found_is_said_and_confidence_stays_low(self):
        d = sd.diagnose("the thing that broke on tuesday", recall=fake_recall(), code_tools=fake_code_tools())
        self.assertIsNone(d["failure"]["resolved_by"])
        self.assertLessEqual(d["confidence"], 0.35)
        self.assertIn("no record", d["note"])

    def test_a_model_may_refine_only_inside_the_evidence(self):
        def think(system, text):
            self.assertIn("CODE:", text)
            self.assertIn("aletheia/apply_run.py", text)
            return ({"kind": "defect", "summary": "The click check gives up too early.",
                     "likely_location": [{"path": "aletheia/apply_run.py", "line": 120, "why": "raises"},
                                         {"path": "aletheia/invented.py", "line": 1, "why": "made up"}],
                     "evidence_ids": ["e1", "e99"], "confidence": 0.9, "next_step": "check the frame"},
                    "fake:local")
        d = sd.diagnose("apply-diag0001", think=think, recall=fake_recall(), code_tools=fake_code_tools())
        self.assertEqual(d["kind"], sd.DEFECT)
        self.assertEqual([l["path"] for l in d["likely_location"]], ["aletheia/apply_run.py"])
        self.assertEqual(d["cited_evidence"], ["e1"])
        self.assertLessEqual(d["confidence"], 0.4)          # it cited a file nobody showed it
        self.assertEqual(d["provenance"]["classified_by"], "fake:local")
        self.assertEqual(d["provenance"]["dropped_uncited_locations"], ["aletheia/invented.py"])

    def test_a_model_that_fails_leaves_the_rules_diagnosis_standing(self):
        def think(system, text):
            raise TimeoutError("cpu")
        d = sd.diagnose("apply-diag0001", think=think, recall=fake_recall(), code_tools=fake_code_tools())
        self.assertEqual(d["kind"], sd.BOUNDARY)
        self.assertIn("TimeoutError", d["provenance"]["model_failed"])

    def test_a_stronger_reviewer_is_stored_beside_never_over(self):
        def reviewer(system, text):
            return {"agrees": False, "kind": "defect", "comment": "I think it is a bug."}, "subscription.auto"
        d = sd.diagnose("apply-diag0001", review=True, reviewer=reviewer, recall=fake_recall(),
                        code_tools=fake_code_tools())
        self.assertEqual(d["kind"], sd.BOUNDARY)
        rev = d["provenance"]["reviewer"]
        self.assertEqual((rev["provider"], rev["policy"], rev["agrees"], rev["kind"]),
                         ("subscription.auto", "critical", False, "defect"))
        self.assertIn("not the author", rev["role"])

    def test_a_failing_test_resolves_and_reads_as_a_defect(self):
        d = sd.diagnose("test:tests.test_formfill.Plan.test_x", detail="AssertionError: 2 != 3",
                        recall=fake_recall(), code_tools=fake_code_tools())
        self.assertEqual(d["failure"]["kind"], "failing test")
        self.assertEqual(d["kind"], sd.DEFECT)


class Proposing(unittest.TestCase):
    def setUp(self):
        write_application("apply-diag0002", state="FAILED", company="Otherco", failure="KeyError: 'label'")
        self.diagnosis = sd.diagnose("apply-diag0002", recall=fake_recall(), code_tools=fake_code_tools())

    def test_a_proposal_is_a_record_and_nothing_else(self):
        diff = "--- a/aletheia/formfill.py\n+++ b/aletheia/formfill.py\n@@ -1 +1 @@\n-x\n+y\n"
        with mock.patch.object(repo_tools, "_tracked_file", lambda n: n):
            record = sd.propose_patch("apply-diag0002", diff=diff, diagnosis=self.diagnosis,
                                      tests=["tests.test_formfill"], check=lambda d: (True, "applies"))
        saved = json.loads(Path(record["path"]).read_text(encoding="utf-8"))
        self.assertTrue(Path(record["path"]).is_relative_to(stateio.private_root()))
        self.assertEqual(saved["status"], "PROPOSED")
        self.assertIn("Nothing was applied", saved["authority"])
        self.assertEqual(saved["files"], ["aletheia/formfill.py"])
        self.assertEqual(saved["suggested_tests"], ["tests.test_formfill"])
        self.assertEqual(saved["touches_authority"], [])
        self.assertEqual(saved["provenance"]["diff_by"], "the asking session's model")

    def test_a_patch_to_a_gate_says_so_in_capitals(self):
        diff = "--- a/config/capabilities.json\n+++ b/config/capabilities.json\n@@ -1 +1 @@\n-a\n+b\n"
        with mock.patch.object(repo_tools, "_tracked_file", lambda n: n):
            record = sd.propose_patch("apply-diag0002", diff=diff, diagnosis=self.diagnosis,
                                      check=lambda d: (True, ""), write=False)
        self.assertEqual(record["touches_authority"], ["config/capabilities.json"])
        self.assertIn("NEVER PERMISSION", record["warning"].upper())

    def test_a_boundary_gets_no_diff_and_says_why(self):
        write_application("apply-diag0003", state="NEEDS_YOU", company="Wallco", failure=CAPTCHA_FAILURE)
        d = sd.diagnose("apply-diag0003", recall=fake_recall(), code_tools=fake_code_tools())
        drafted = []
        record = sd.propose_patch("apply-diag0003", diagnosis=d, write=False,
                                  think=lambda s, t: drafted.append(1) or ({"diff": "x"}, "m"))
        self.assertEqual(drafted, [])
        self.assertIn("boundary", record["why_no_diff"])

    def test_the_local_model_can_draft_the_diff_and_is_named(self):
        diff = "--- a/aletheia/formfill.py\n+++ b/aletheia/formfill.py\n@@ -1 +1 @@\n-x\n+y\n"
        with mock.patch.object(repo_tools, "_tracked_file", lambda n: n):
            record = sd.propose_patch("apply-diag0002", diagnosis=self.diagnosis, write=False,
                                      think=lambda s, t: ({"diff": diff, "summary": "guard the key"},
                                                          "ollama:qwen3:8b"),
                                      check=lambda d: (False, "patch does not apply"))
        self.assertEqual(record["provenance"]["diff_by"], "ollama:qwen3:8b")
        self.assertFalse(record["diff_check"]["ok"])

    def test_an_untracked_path_in_a_diff_is_refused_by_the_check(self):
        checked = sd.check_diff("--- a/state/private/secrets/x.json\n+++ b/state/private/secrets/x.json\n",
                                git=lambda d: self.fail("git must not be asked"))
        self.assertFalse(checked["ok"])


class TheLiveCheckoutIsOutOfReach(unittest.TestCase):
    def test_the_guard_refuses_the_checkout_inside_it_and_above_it(self):
        live = repo_tools.root()
        for path in (live, live / "aletheia", live / "state" / "private" / "x", live.parent):
            with self.subTest(path=str(path)):
                with self.assertRaises(sd.LiveCheckoutRefused):
                    sd.assert_not_live(path)
        outside = Path(tempfile.gettempdir()) / "aletheia-patch-worktrees" / "p"
        self.assertEqual(sd.assert_not_live(outside), outside.resolve())

    def test_a_worktree_root_inside_the_repo_is_refused_before_git_runs(self):
        calls = []
        with mock.patch.object(sd, "load_proposal", lambda i: {"id": i, "diff": "--- a/x\n+++ b/x\n",
                                                               "suggested_tests": ["tests.test_x"]}), \
                mock.patch.object(sd, "worktrees_root", lambda: repo_tools.root() / "tmp-worktrees"):
            with self.assertRaises(sd.LiveCheckoutRefused):
                sd.try_patch("patch-x", git=lambda *a, **k: calls.append(a) or (0, ""))
        self.assertEqual(calls, [])

    def test_git_verbs_that_touch_a_remote_or_the_checkout_are_never_run(self):
        for verb in ("push", "merge", "pull", "checkout", "reset", "stash"):
            with self.assertRaises(sd.LiveCheckoutRefused):
                sd._run_git([verb], Path(tempfile.gettempdir()))

    def test_no_test_name_means_no_trial(self):
        with mock.patch.object(sd, "load_proposal", lambda i: {"id": i, "diff": "d", "suggested_tests": []}):
            with self.assertRaises(ValueError):
                sd.try_patch("patch-x", git=lambda *a, **k: self.fail("git ran"))


def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


@unittest.skipIf(shutil.which("git") is None, "git is not installed")
class ATrialInAScratchRepository(unittest.TestCase):
    def setUp(self):
        self.repo = Path(tempfile.mkdtemp(prefix="sd-live-"))
        self.trees = Path(tempfile.mkdtemp(prefix="sd-trees-"))
        _git(self.repo, "init", "-q")
        _git(self.repo, "config", "user.email", "t@t")
        _git(self.repo, "config", "user.name", "t")
        (self.repo / "calc.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
        (self.repo / "tests").mkdir()
        (self.repo / "tests" / "__init__.py").write_text("", encoding="utf-8")
        (self.repo / "tests" / "test_calc.py").write_text(
            "import unittest\nfrom calc import add\n\nclass T(unittest.TestCase):\n"
            "    def test_add(self):\n        self.assertEqual(add(2, 3), 5)\n", encoding="utf-8")
        _git(self.repo, "add", "-A")
        _git(self.repo, "commit", "-q", "-m", "init")
        self.before = (self.repo / "calc.py").read_bytes()
        self.patches = [mock.patch.object(repo_tools, "root", lambda: self.repo),
                        mock.patch.dict(os.environ, {"ALETHEIA_PATCH_WORKTREES": str(self.trees)})]
        for p in self.patches:
            p.start()
        repo_tools._LS.update({"at": 0.0, "root": None, "files": None})

    def tearDown(self):
        for p in self.patches:
            p.stop()
        repo_tools._LS.update({"at": 0.0, "root": None, "files": None})
        subprocess.run(["git", "worktree", "prune"], cwd=self.repo, capture_output=True)
        shutil.rmtree(self.repo, ignore_errors=True)
        shutil.rmtree(self.trees, ignore_errors=True)

    def test_the_fix_is_tried_elsewhere_and_the_checkout_does_not_move(self):
        diff = ("--- a/calc.py\n+++ b/calc.py\n@@ -1,2 +1,2 @@\n def add(a, b):\n"
                "-    return a - b\n+    return a + b\n")
        record = sd.propose_patch("test:tests.test_calc", diff=diff, tests=["tests.test_calc"],
                                  diagnosis={"kind": "defect", "summary": "subtracts", "evidence": [],
                                             "provenance": {"classified_by": "rules"}})
        self.assertTrue(record["diff_check"]["ok"], record["diff_check"])
        live_calls = []
        real = sd._run_git

        def watched(args, cwd, **kw):
            if Path(cwd).resolve() == self.repo.resolve():
                live_calls.append(args[0])
            return real(args, cwd, **kw)
        tried = sd.try_patch(record["id"], git=watched)
        trial = tried["trials"][-1]
        self.assertTrue(trial["applied"], trial)
        self.assertTrue(trial["passed"], trial.get("output_tail"))
        self.assertTrue(Path(trial["worktree"]).resolve().is_relative_to(self.trees.resolve()))
        # the live checkout: same bytes, clean status, still on its own branch
        self.assertEqual((self.repo / "calc.py").read_bytes(), self.before)
        status = subprocess.run(["git", "status", "--porcelain"], cwd=self.repo, capture_output=True, text=True)
        self.assertEqual(status.stdout.strip(), "")
        self.assertEqual(set(live_calls), {"worktree"})
        branches = subprocess.run(["git", "branch", "--list", "thea/*"], cwd=self.repo,
                                  capture_output=True, text=True).stdout
        self.assertIn(f"thea/proposal-{record['id']}", branches)
        self.assertFalse(Path(trial["worktree"]).exists())


class InsideASession(unittest.TestCase):
    def test_recall_basis_reaches_the_session_and_a_proposal_runs_but_a_trial_is_handed_off(self):
        catalog = {name: tool for name, tool in tools.catalog().items()
                   if name in ("memory.recall", "repo.propose_patch", "repo.try_patch")}
        ran = []
        catalog["memory.recall"] = tools.with_handler(
            catalog["memory.recall"], lambda a: ran.append("recall") or
            {"basis": "FOUND IN HISTORY", "history": [{"source": "journal", "text": "captcha"}]})
        catalog["repo.propose_patch"] = tools.with_handler(
            catalog["repo.propose_patch"], lambda a: ran.append("propose") or {"proposal": "patch-1"})
        catalog["repo.try_patch"] = tools.with_handler(
            catalog["repo.try_patch"], lambda a: ran.append("TRIAL RAN") or {})
        replies = [{"tool": "memory.recall", "args": {"query": "captcha"}},
                   {"tool": "repo.propose_patch", "args": {"failure": "apply-x"}},
                   {"tool": "repo.try_patch", "args": {"proposal": "patch-1"}},
                   {"answer": "From my history it looks like a CAPTCHA; I wrote a proposal."}]
        think = lambda system, text: (replies.pop(0), "fake:model")
        broker = agent_session.Broker(catalog, halted=lambda: False, registry={"capabilities": []})
        result = agent_session.AgentSession("why did it fail", think=think, catalog=catalog, broker=broker,
                                            now_line=lambda: "NOW", record=False).run()
        self.assertEqual(ran, ["recall", "propose"])
        self.assertEqual(result.knowing, "FOUND IN HISTORY")
        self.assertEqual(result.handoffs[0]["tool"], "repo.try_patch")
        self.assertEqual(result.outcome, agent_session.HANDED_OFF)

    def test_the_tool_observation_fits_a_small_prompt(self):
        with mock.patch("aletheia.semantic_index.recall", lambda q, sources=None, k=4: {
                "basis": "KNOWN", "note": "n",
                "facts": [{"store": "applications", "id": f"a{i}", "fact": {"x": "y" * 2000}} for i in range(5)],
                "snippets": [{"source": "journal", "where": "w", "ts": "2026-09-16T00:00:00Z",
                              "text": "z" * 2000, "basis": "FOUND IN HISTORY"}] * 4}):
            shown = memory_tools.recall({"query": "q"})
        text, _hidden = agent_session.sanitise(shown, tools.TRUSTED_LOCAL_STATE)
        self.assertNotIn("more characters cut", text)
        self.assertEqual(shown["more_facts"], 3)


if __name__ == "__main__":
    unittest.main()
