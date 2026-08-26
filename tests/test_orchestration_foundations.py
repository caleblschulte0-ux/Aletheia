import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import context, gaps, projects


class FoundationCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        for module, attr, path in (
            (projects, "PROJECTS_DIR", root / "projects"),
            (context, "REFS_DIR", root / "refs"),
        ):
            patcher = mock.patch.object(module, attr, path)
            patcher.start(); self.addCleanup(patcher.stop)


class TestGaps(FoundationCase):
    REGISTRY = {"capabilities": [
        {"id": "good", "status": "AVAILABLE"},
        {"id": "pc", "status": "NEEDS_CONFIGURATION", "caller": "local"},
        {"id": "phone.call", "status": "NOT_BUILT", "caller": "ticket"},
    ]}

    def test_assess_separates_available_blocked_unknown(self):
        report = gaps.assess(["good", "pc", "missing"], registry=self.REGISTRY)
        self.assertEqual(report["available"], ["good"])
        self.assertEqual(report["unknown"], ["missing"])
        self.assertEqual(report["blocked"][0]["id"], "pc")
        self.assertFalse(report["satisfied"])

    def test_development_specs_are_reviewable_worker_tasks(self):
        specs = gaps.development_specs(["phone.call", "missing"], registry=self.REGISTRY)
        self.assertEqual(len(specs), 2)
        self.assertTrue(all(spec["assigned_worker"] == "claude" for spec in specs))
        self.assertTrue(all(spec["required_capabilities"] == [] for spec in specs))

    def test_materialize_deduplicates_existing_task(self):
        items = []
        with mock.patch.object(gaps.tasks, "all_tasks", side_effect=lambda: list(items)), \
             mock.patch.object(gaps.tasks, "create") as create:
            def fake_create(tid, description, **kwargs):
                item = {"id": tid, "description": description, **kwargs}
                items.append(item)
                return item
            create.side_effect = fake_create
            first = gaps.materialize(["phone.call"], registry=self.REGISTRY)
            second = gaps.materialize(["phone.call"], registry=self.REGISTRY)
        self.assertEqual(first[0]["id"], second[0]["id"])
        self.assertEqual(create.call_count, 1)


class TestProjects(FoundationCase):
    def test_project_records_tasks_people_blockers_decisions(self):
        projects.create("alpha", "Alpha", goal="ship it")
        value = projects.update("alpha", add_task="t1", add_person="bob", blocker="waiting", decision="use v1")
        self.assertEqual(value["task_ids"], ["t1"])
        self.assertEqual(value["people"], ["bob"])
        self.assertEqual(value["blockers"][0]["text"], "waiting")
        self.assertEqual(value["decisions"][0]["text"], "use v1")

    def test_terminal_project_immutable(self):
        projects.create("alpha", "Alpha", goal="ship")
        projects.update("alpha", status="COMPLETED")
        with self.assertRaises(ValueError):
            projects.update("alpha", add_task="t")

    def test_invalid_project_data_fails_closed(self):
        with self.assertRaises(ValueError):
            projects.create("alpha", "", goal="ship")


class TestContext(FoundationCase):
    def test_unique_resolution(self):
        context.remember("r1", kind="person", value="contact:bob", label="Bob")
        self.assertEqual(context.resolve(kind="person")["value"], "contact:bob")

    def test_same_value_is_not_ambiguous(self):
        context.remember("r1", kind="person", value="contact:bob", label="Bob")
        context.remember("r2", kind="person", value="contact:bob", label="him")
        self.assertEqual(context.resolve(kind="person")["value"], "contact:bob")

    def test_multiple_values_require_disambiguation(self):
        context.remember("r1", kind="person", value="contact:bob", label="Bob")
        context.remember("r2", kind="person", value="contact:sam", label="Sam")
        with self.assertRaises(LookupError):
            context.resolve(kind="person")


if __name__ == "__main__":
    unittest.main()
