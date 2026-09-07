"""What may reach a public repository, and what may not.

`caleblschulte0-ux/Aletheia` is public. Two things were landing in it
that are nobody else's business:

- **His account balance.** Ten daily briefs carried "realized P&L
  -$40.82 · win rate 14.3% · cash $2.50" under his name, dated, because
  a vital was a vital and the pulse is committed.
- **His life, whenever he used a command line.** `use_pc_journal`
  (2026-09-03) moved the PC Core's appends to private state and was
  right, but it routes by PROCESS and only three entry points call it.
  Every `python -m aletheia.webtask`, every `apply_run`, every `profile`
  — the ones the setup doc tells him to run — wrote to the public
  journal anyway.

Both are now decided by WHAT the thing is rather than who is writing it,
and both fail closed: an unrecognised journal subject is private, and a
vital is only public if the registry says so.
"""
import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aletheia import fleet, journal, pulse


class TheJournalRoutesByWHAT_NOT_WHO(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.repo_journal = root / "state" / "journal"
        self.repo_journal.mkdir(parents=True)
        self.private = root / "private" / "journal"
        for target, attr, value in (
                (journal, "JOURNAL_PATH", self.repo_journal / "journal.jsonl"),
                (journal, "REPO_JOURNAL_DIR", self.repo_journal)):
            patch = mock.patch.object(target, attr, value)
            patch.start(); self.addCleanup(patch.stop)
        patch = mock.patch("aletheia.stateio.private_dir",
                           lambda name: root / "private" / name)
        patch.start(); self.addCleanup(patch.stop)

    def committed(self):
        path = self.repo_journal / "journal.jsonl"
        return path.read_text(encoding="utf-8") if path.exists() else ""

    def held(self):
        path = self.private / "journal-pc.jsonl"
        return path.read_text(encoding="utf-8") if path.exists() else ""

    def test_fleet_telemetry_is_the_fleets_business(self):
        journal.append("event", "repo:aletheia", "health red -> green")
        journal.append("brief", "fleet", "morning brief composed")
        self.assertIn("health red -> green", self.committed())
        self.assertEqual(self.held(), "")

    def test_his_life_is_NOT(self):
        for subject, text in (
                ("webtask", "AWAITING_YOU: apply for the job at Northwind"),
                ("apply", "staged an application at https://northwind.example"),
                ("profile", "email is on file (from resume)"),
                ("mail", "read 3 unread"),
                ("memory", "remembered something")):
            with self.subTest(subject=subject):
                journal.append("action", subject, text)
        self.assertEqual(self.committed(), "")
        for fragment in ("northwind.example", "email is on file", "read 3 unread"):
            self.assertIn(fragment, self.held())

    def test_a_subject_nobody_thought_about_is_PRIVATE(self):
        """An allowlist, so the failure direction is the safe one."""
        journal.append("action", "some_new_capability", "did a thing for him")
        self.assertEqual(self.committed(), "")
        self.assertIn("did a thing for him", self.held())

    def test_the_command_line_is_covered_and_not_just_the_Core(self):
        """`use_pc_journal` routes by process and only three entry points
        call it. This routes by entry, so a terminal is covered too."""
        self.assertNotIn("use_pc_journal", journal.append.__doc__ or "")
        journal.append("action", "webtask", "did it from a terminal")
        self.assertEqual(self.committed(), "")

    def test_reading_still_sees_ONE_stream(self):
        journal.append("event", "repo:aletheia", "health red -> green")
        journal.append("action", "webtask", "applied somewhere")
        texts = [e["text"] for e in journal.entries()]
        self.assertIn("health red -> green", texts)
        self.assertIn("applied somewhere", texts)

    def test_a_redirected_journal_is_left_exactly_where_it_points(self):
        """Every test redirects JOURNAL_PATH, and dragging his real
        private journal into that write is the cross-contamination `-t .`
        exists to prevent."""
        elsewhere = Path(self.tmp.name) / "somewhere" / "j.jsonl"
        elsewhere.parent.mkdir()
        journal.append("action", "webtask", "isolated", path=elsewhere)
        self.assertIn("isolated", elsewhere.read_text(encoding="utf-8"))
        self.assertEqual(self.held(), "")


class ARegistryDecidesWhichNumbersAreHis(unittest.TestCase):
    class Source:
        def recent_commits(self, *a):
            return [{"sha": "abc", "date": "2026-09-04T00:00:00Z", "message": "m"}]

        def read_json(self, gh, path, branch):
            return {"total_realized": -40.82, "win_rate": 14.3, "posted": [1, 2]}

        def workflow_run(self, *a):
            return {"status": "completed", "conclusion": "success"}

        def file_exists(self, *a):
            return {"exists": True}

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patch = mock.patch("aletheia.stateio.private_dir",
                           lambda name: Path(self.tmp.name) / name)
        patch.start(); self.addCleanup(patch.stop)

    def test_the_money_never_reaches_the_committed_pulse(self):
        collected = pulse.collect(fleet.load_fleet(), self.Source())
        blob = json.dumps(collected)
        self.assertNotIn("-40.82", blob)
        self.assertNotIn("14.3", blob)

    def test_but_it_is_NAMED_so_the_wall_is_not_lying(self):
        """"3 figures, on your screen only" beats pretending the repo has
        nothing to report."""
        collected = pulse.collect(fleet.load_fleet(), self.Source())
        held = collected["repos"]["schwab_trader"]["private_vitals"]
        self.assertIn("realized P&L", held)
        self.assertEqual(collected["repos"]["schwab_trader"]["vitals"], [])

    def test_and_the_numbers_are_on_his_machine(self):
        pulse.collect(fleet.load_fleet(), self.Source())
        values = {v["label"]: v.get("value")
                  for v in pulse.private_vitals()["schwab_trader"]}
        self.assertEqual(values["realized P&L"], -40.82)

    def test_a_repo_that_did_not_ask_for_privacy_still_reports(self):
        """Publishing nothing is as wrong as publishing everything: the
        Shorts post counts are the fleet's business."""
        collected = pulse.collect(fleet.load_fleet(), self.Source())
        labels = [v["label"]
                  for v in collected["repos"]["shorts_pipeline"]["vitals"]]
        self.assertTrue(labels)

    def test_the_registry_is_what_says_so(self):
        registry = fleet.load_fleet()
        private = [v["label"] for v in registry["repos"]["schwab_trader"]["vitals"]
                   if v.get("private")]
        self.assertIn("cash", private)

    def test_private_must_be_a_yes_or_a_no(self):
        registry = fleet.load_fleet()
        registry["repos"]["schwab_trader"]["vitals"][0]["private"] = "sort of"
        with self.assertRaises(fleet.FleetError):
            fleet.validate(registry)


class NOTHING_PRIVATE_IS_IN_THE_TRACKED_TREE(unittest.TestCase):
    """The durable half. The routing above stops NEW private data from
    reaching the repository; this fails the moment any lands anyway —
    a bad merge, a hand-edit, a capability that journals under a public
    subject because that read better at the time.

    It reads the working tree, so it is the same check whether it runs
    here or in CI.
    """

    def tracked(self):
        import subprocess
        out = subprocess.run(["git", "ls-files"], capture_output=True, text=True)
        for name in out.stdout.splitlines():
            path = Path(name)
            if path.is_file() and path.suffix in (".md", ".json", ".jsonl", ".txt"):
                yield path

    def private_labels(self):
        registry = fleet.load_fleet()
        return [v["label"] for repo in registry["repos"].values()
                for v in repo.get("vitals", []) if v.get("private")]

    def test_no_committed_file_carries_a_private_vital(self):
        """Ten daily briefs carried his account balance under his name."""
        labels = self.private_labels()
        self.assertTrue(labels, "the registry must actually mark some private")
        offenders = []
        for path in self.tracked():
            if path.parts[:2] == ("config", ) or path.name == "fleet.json":
                continue          # the registry DECLARES the labels
            text = path.read_text(encoding="utf-8", errors="ignore")
            for label in labels:
                # The label plus a number after it — the label alone is
                # fine (the pulse names what it is holding back).
                if re.search(re.escape(label) + r"[^\n]{0,4}[-+$\d]", text):
                    offenders.append(f"{path}: {label}")
        self.assertEqual(offenders, [], "private figures in tracked files")

    def test_the_committed_journal_holds_only_fleet_telemetry(self):
        path = Path("state/journal/journal.jsonl")
        if not path.is_file():
            self.skipTest("no in-repo journal here")
        strays = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            subject = json.loads(line).get("subject", "")
            if not journal.is_public_subject(subject):
                strays.append(subject)
        self.assertEqual(sorted(set(strays)), [],
                         "personal subjects in the public journal")

    def test_no_committed_file_quotes_a_personal_journal_entry(self):
        """The guard's first version checked the JOURNAL and missed the
        BRIEF, which renders the last 24 hours of it into a committed
        markdown file — so "webtask: Fill in the job application on this
        page with my details" was published while the journal it came
        from had already been made private."""
        line = re.compile(r"^- `\d\d:\d\d` \[\w+\] ([\w:.\-]+):", re.M)
        offenders = []
        for path in self.tracked():
            if path.suffix != ".md":
                continue
            for subject in line.findall(path.read_text(encoding="utf-8",
                                                       errors="ignore")):
                if not journal.is_public_subject(subject):
                    offenders.append(f"{path}: {subject}")
        self.assertEqual(sorted(set(offenders)), [])

    def test_the_composer_filters_rather_than_trusting_WHERE_it_runs(self):
        """`journal.since()` merges every writer including the private
        one, so a brief composed on his own machine would quote his life
        into the repository."""
        from aletheia import brief
        entries = [
            {"kind": "action", "subject": "repo:aletheia", "ts": "2026-09-04T01:00:00Z",
             "text": "health red -> green"},
            {"kind": "action", "subject": "webtask", "ts": "2026-09-04T01:01:00Z",
             "text": "applying for a job at Northwind"},
        ]
        text = brief.compose({"repos": {}, "generated_at": "2026-09-04T02:00:00Z",
                              "fleet_revision": 4, "owner": "x", "source": "t",
                              "transitions": [], "alerts": [], "plans": [],
                              "tasks": {"live": 0, "by_status": {}, "items": []}},
                             None, entries, new_suggestions=0)
        self.assertIn("health red -> green", text)
        self.assertNotIn("Northwind", text)

    def test_the_check_can_actually_see_one(self):
        """A test that cannot fail is a comment."""
        self.assertRegex("- realized P&L -$40.82 · cash $2.50",
                         re.escape("realized P&L") + r"[^\n]{0,4}[-+$\d]")
        self.assertNotRegex("- figures withheld (private vitals)",
                            re.escape("realized P&L") + r"[^\n]{0,4}[-+$\d]")


if __name__ == "__main__":
    unittest.main()
