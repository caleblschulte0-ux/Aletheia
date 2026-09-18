"""Before a pass is spent on it: is this already true?

The live acceptance pass, 2026-09-18, spent a local pass and a frontier turn on
a charter step that was COMPLETE at the base commit - only a doc note was
stale. `aletheia.already_done` asks first, in code.

The two rules that make a skip safe are the two that are easy to lose, so they
are asserted directly here:

- it NEVER skips something that is not actually done (most of this file), and
- it never asks a model, because a model deciding "already done" is how work
  silently stops happening and is unfalsifiable afterwards.
"""
from __future__ import annotations

import datetime as dt
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import already_done as ad, work_states as ws


def item(title, **kw):
    base = {"id": "w-1", "source": "plans", "title": title, "state": ws.READY,
            "native_state": "", "payload": {}}
    base.update(kw)
    return base


class TheStoreAlreadySaysSo(unittest.TestCase):
    def test_a_charter_step_already_marked_done(self):
        plan = {"steps": [{"n": 3, "state": "done", "text": "the release notes"}]}
        with mock.patch("aletheia.plans.load", return_value=plan):
            said = ad.check(item("step three", payload={"slug": "barkly", "n": 3}))
        self.assertTrue(said["done"])
        self.assertEqual(said["by"], "state")
        self.assertIn("barkly#3", said["why"])

    def test_a_charter_step_still_to_do_is_not_skipped(self):
        plan = {"steps": [{"n": 3, "state": "todo", "text": "the release notes"}]}
        with mock.patch("aletheia.plans.load", return_value=plan):
            said = ad.check(item("step three", payload={"slug": "barkly", "n": 3}))
        self.assertFalse(said["done"])

    def test_a_plan_that_cannot_be_read_proves_nothing(self):
        with mock.patch("aletheia.plans.load", side_effect=OSError("gone")):
            said = ad.check(item("step three", payload={"slug": "barkly", "n": 3}))
        self.assertFalse(said["done"])

    def test_a_completed_task(self):
        said = ad.check(item("call the plumber", source="tasks", native_state="COMPLETED"))
        self.assertTrue(said["done"])

    def test_an_open_task_is_not_done(self):
        for state in ("OPEN", "IN_PROGRESS", "WAITING_EXTERNAL", "BLOCKED", ""):
            self.assertFalse(ad.check(item("x", source="tasks", native_state=state))["done"], state)

    def test_a_failed_item_is_not_done(self):
        # FAILED is terminal and is the opposite of done.
        self.assertFalse(ad.check(item("x", state=ws.FAILED))["done"])

    def test_a_work_item_already_done(self):
        self.assertTrue(ad.check(item("x", state=ws.DONE))["done"])


class TheFileAlreadySaysIt(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="already-done-"))

    def write(self, name, text):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return name

    def test_the_step_that_was_already_true(self):
        # plan:barkly#3, in shape.
        self.write("README.md", "# barkly\n\n## Release process\n\nTag, then publish.\n")
        said = ad.by_file("Add a README section describing the release process",
                          root=self.root, out_path="README.md")
        self.assertTrue(said["done"])
        self.assertEqual(said["by"], "file")
        self.assertEqual(said["evidence"]["phrase"], "release process")

    def test_a_file_that_does_not_exist_is_not_done(self):
        said = ad.by_file("Add a README section describing the release process",
                          root=self.root, out_path="README.md")
        self.assertFalse(said["done"])
        self.assertIn("does not exist", said["why"])

    def test_a_file_that_does_not_mention_it_is_not_done(self):
        self.write("README.md", "# barkly\n\nA dog thing.\n")
        said = ad.by_file("Add a README section describing the release process",
                          root=self.root, out_path="README.md")
        self.assertFalse(said["done"])
        self.assertIn("release", said["why"])

    def test_half_of_it_is_not_it(self):
        self.write("README.md", "# barkly\n\n## Release\n\nWe release sometimes.\n")
        said = ad.by_file("Add a README section describing the release process for the mobile app",
                          root=self.root, out_path="README.md")
        self.assertFalse(said["done"], said)

    def test_the_words_scattered_is_a_coincidence_not_the_thing(self):
        # Every word is somewhere in the file and no two of them are together.
        self.write("README.md", "Release the hounds.\n\nDue process matters.\n")
        said = ad.by_file("Add a README section describing the release process",
                          root=self.root, out_path="README.md")
        self.assertFalse(said["done"], said)
        self.assertIn("scattered", said["why"])

    def test_a_step_that_names_nothing_distinctive_proves_nothing(self):
        self.write("NOTES.md", "anything at all")
        said = ad.by_file("Write the doc", root=self.root, out_path="NOTES.md")
        self.assertFalse(said["done"])
        self.assertIn("too little", said["why"])

    def test_the_words_that_say_what_kind_of_work_it_is_do_not_count(self):
        self.assertEqual(ad.content_words("Add a README section describing the release process"),
                         ["release", "process"])

    def test_a_directory_where_a_file_should_be_is_not_done(self):
        (self.root / "docs").mkdir()
        said = ad.by_file("document the release process", root=self.root, out_path="docs")
        self.assertFalse(said["done"])


class ItNeverAsksAModel(unittest.TestCase):
    def test_no_reasoning_of_any_kind(self):
        root = Path(tempfile.mkdtemp(prefix="already-done-"))
        (root / "README.md").write_text("## Release process\nTag it.\n", encoding="utf-8")
        from aletheia import local_model_pool, reasoning_gateway

        def never(*a, **k):
            raise AssertionError("the already-done check asked a model")

        with mock.patch.object(reasoning_gateway, "reason_json", side_effect=never), \
                mock.patch.object(reasoning_gateway, "local_json", side_effect=never), \
                mock.patch.object(local_model_pool, "run_json", side_effect=never), \
                mock.patch.object(local_model_pool, "auto_json", side_effect=never):
            said = ad.check(item("add a README section describing the release process"),
                            root=root, out_path="README.md",
                            text="add a README section describing the release process")
        self.assertTrue(said["done"])

    def test_a_check_may_never_be_why_work_stops(self):
        with mock.patch.object(ad, "by_state", side_effect=RuntimeError("boom")):
            said = ad.check(item("x"))
        self.assertFalse(said["done"])
        self.assertIn("could not run", said["why"])


class ASkipIsRecordedHonestly(unittest.TestCase):
    def test_it_says_it_was_already_true_rather_than_claiming_she_did_it(self):
        verdict = {"done": True, "by": "file", "why": "README.md already says it",
                   "evidence": {"file": "README.md"}, "checked": ["state", "file"]}
        out = ad.skipped(item("add a README section describing the release process"), verdict,
                         route="doc")
        self.assertEqual(out["state"], ws.DONE)
        self.assertEqual(out["kind"], "already")
        self.assertIn("already", out["reason"])
        self.assertIn("no model was asked", out["did"])
        self.assertEqual(out["evidence"]["already_done"]["by"], "file")
        self.assertEqual(out["evidence"]["already_done"]["checked"], ["state", "file"])

    def test_the_outcome_is_a_valid_work_item_view(self):
        verdict = {"done": True, "by": "state", "why": "already done", "evidence": {}, "checked": []}
        out = ad.skipped(item("x"), verdict)
        self.assertEqual(ws.problems({"state": out["state"], "requires": []}), [])


class TheWorkSessionAsksFirst(unittest.TestCase):
    def test_a_route_that_would_have_spent_a_pass_returns_the_skip(self):
        from aletheia import work_runners
        it = item("step three", source="plans", payload={"slug": "barkly", "n": 3})
        plan = {"steps": [{"n": 3, "state": "done"}]}
        with mock.patch("aletheia.plans.load", return_value=plan), \
                mock.patch.object(work_runners, "_journal"), \
                mock.patch.object(work_runners, "_frontier_ok", return_value=False), \
                mock.patch.object(work_runners, "_doc", side_effect=AssertionError("it ran the route anyway")), \
                mock.patch.object(work_runners, "_compose", side_effect=AssertionError("it ran the route anyway")):
            out = work_runners.run(it, dt.datetime(2026, 9, 18, tzinfo=dt.timezone.utc))
        self.assertEqual(out["state"], ws.DONE)
        self.assertEqual(out["kind"], "already")
        self.assertTrue(out["evidence"]["already_done"]["why"])

    def test_an_item_that_is_not_done_still_runs_its_route(self):
        from aletheia import work_runners
        it = item("step three", source="plans", payload={"slug": "barkly", "n": 3})
        plan = {"steps": [{"n": 3, "state": "todo"}]}
        ran = {}
        with mock.patch("aletheia.plans.load", return_value=plan), \
                mock.patch.object(work_runners, "_journal"), \
                mock.patch.object(work_runners, "_frontier_ok", return_value=False), \
                mock.patch.object(work_runners, "current_session", return_value={"id": "s"}), \
                mock.patch.object(work_runners, "_compose", side_effect=lambda *a, **k: (
                    ran.update(ran=True),
                    {"state": ws.DONE, "reason": "", "next": "", "did": "", "kind": "done"})[1]):
            work_runners.run(it, dt.datetime(2026, 9, 18, tzinfo=dt.timezone.utc))
        self.assertTrue(ran.get("ran"), "a step still to do was skipped")


if __name__ == "__main__":
    unittest.main()
