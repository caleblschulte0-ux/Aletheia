import copy
import unittest

from aletheia.fleet import (
    DEFAULT_PATH, REPO_ROOT, FleetError, load_fleet, markdown_table, validate,
)


class TestRegistry(unittest.TestCase):
    def test_registry_loads_and_validates(self):
        fleet = load_fleet(DEFAULT_PATH)
        self.assertGreaterEqual(len(fleet["repos"]), 6)

    def test_duplicate_github_name_refused(self):
        fleet = load_fleet()
        broken = copy.deepcopy(fleet)
        first = next(iter(broken["repos"].values()))
        broken["repos"]["dupe"] = copy.deepcopy(first)
        with self.assertRaises(FleetError):
            validate(broken)

    def test_stub_with_watch_refused(self):
        fleet = load_fleet()
        broken = copy.deepcopy(fleet)
        for repo in broken["repos"].values():
            if repo["status"] == "stub":
                repo["watch"]["workflows"] = ["ghost.yml"]
                break
        else:
            self.skipTest("no stub in registry")
        with self.assertRaises(FleetError):
            validate(broken)

    def test_bad_status_refused(self):
        fleet = load_fleet()
        broken = copy.deepcopy(fleet)
        next(iter(broken["repos"].values()))["status"] = "sorta-working"
        with self.assertRaises(FleetError):
            validate(broken)


class TestNoSecondSourceOfTruth(unittest.TestCase):
    """README's fleet table is generated from the registry; drift fails here."""

    def test_readme_table_matches_registry(self):
        readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
        begin, end = "<!-- BEGIN GENERATED FLEET -->", "<!-- END GENERATED FLEET -->"
        self.assertIn(begin, readme)
        self.assertIn(end, readme)
        embedded = readme.split(begin)[1].split(end)[0].strip()
        expected = markdown_table(load_fleet()).strip()
        self.assertEqual(
            embedded, expected,
            "README fleet table drifted from config/fleet.json — regenerate "
            "with `python -m aletheia.fleet --markdown`",
        )


if __name__ == "__main__":
    unittest.main()
