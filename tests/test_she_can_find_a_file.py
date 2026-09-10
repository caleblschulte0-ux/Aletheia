"""She could read a file he named anywhere, and could not find one.

    > what's in my downloads folder
      [9.1s] I don't have a way to browse your file system

    > list my files
      [0.1s] (empty)

The first is the gap. The second is worse and was already there:
`file_list` lists HER WORKSPACE, so "list MY files" answered about a
directory he has never opened. True sentence, wrong question — the same
class as "can you read my files" being answered about the web browser.

`workspace.read(anywhere=True)` opens any file on the disk. It takes a
PATH. He does not know the path. That is not a capability, it is a
precondition he cannot meet, and the proof it mattered was already in the
tree: `applications.py` had grown a private resume-finder for one caller
because the general thing did not exist.

What this holds:

- the boundary (named places, bounded depth, never the contents)
- the COUNT is not the CAP — "40 files in Downloads" about 648 was the
  first version, with "the other 35" doing arithmetic on the cap
- a filename is not a sentence
- "my files" is his, "your files" is hers, and "find my keys" is neither
"""
from __future__ import annotations

import os
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from aletheia import files, intercom, voice


class ABoundaryCase(unittest.TestCase):
    def test_the_places_are_named_not_the_whole_disk(self):
        for name in files.PLACES:
            with self.subTest(name=name):
                self.assertNotIn("..", name)
                self.assertFalse(Path(name).is_absolute())

    def test_software_directories_are_skipped(self):
        for name in ("node_modules", "__pycache__", "AppData", ".git"):
            with self.subTest(name=name):
                self.assertTrue(files._skip_dir(Path("x") / name))

    def test_a_dotfile_is_not_one_of_his_things(self):
        self.assertTrue(files._skip_file(Path(".bashrc")))
        self.assertTrue(files._skip_file(Path("~$report.docx")))
        self.assertFalse(files._skip_file(Path("lease.pdf")))

    def test_the_walk_stops(self):
        """A folder someone pointed a build tool at must not hang the room."""
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            for i in range(50):
                (root / f"f{i}.txt").write_text("x", encoding="utf-8")
            budget = [10]
            self.assertLessEqual(len(list(files._walk(root, 2, budget))), 10)

    def test_depth_is_bounded(self):
        with TemporaryDirectory() as tmp:
            deep = Path(tmp)
            for level in range(6):
                deep = deep / f"level{level}"
            deep.mkdir(parents=True)
            (deep / "buried.txt").write_text("x", encoding="utf-8")
            found = list(files._walk(Path(tmp), files.MAX_DEPTH, [10_000]))
            self.assertEqual(found, [], "walked deeper than MAX_DEPTH")

    def test_a_place_is_an_allowlist_not_a_sanitizer(self):
        """`..` cannot be cleaned up; a name she does not know is refused.

        `workspace.resolve` has to sanitize because he names arbitrary
        paths inside it. Here he names a FOLDER, from a list of the five
        places a person keeps things, so the containment is "is this one
        of them" — which cannot be walked out of by construction.
        """
        for said in ("..", "../..", r"C:\Windows", "/etc", "AppData", "~",
                     "C:\\", "Downloads/../..", r"..\..\Windows\System32",
                     "Program Files", ".ssh", "$RECYCLE.BIN"):
            with self.subTest(place=said):
                with self.assertRaises(files.FilesError):
                    files.find("x", place=said)

    def test_no_place_at_all_means_the_places_she_knows(self):
        """"List my files" is not an escape; it is the ordinary case."""
        self.assertIsNone(files._named(""))

    def test_it_never_returns_the_contents(self):
        """Reading a file is `document.read_any`, which has its own ceilings."""
        with TemporaryDirectory() as tmp:
            (Path(tmp) / "secret.txt").write_text("the password is hunter2",
                                                  encoding="utf-8")
            row = files._row(Path(tmp) / "secret.txt")
        self.assertEqual(set(row) & {"text", "contents", "body"}, set())
        self.assertNotIn("hunter2", str(row))


class TheCountIsNotTheCapCase(unittest.TestCase):
    """"40 files in Downloads" about 648, then "the other 35 are there too"."""

    def _place(self, tmp: str):
        return mock.patch.object(files, "places",
                                 lambda: [("Downloads", Path(tmp))])

    def test_the_total_counts_what_was_found(self):
        with TemporaryDirectory() as tmp:
            for i in range(30):
                (Path(tmp) / f"f{i}.txt").write_text("x", encoding="utf-8")
            with self._place(tmp):
                result = files.search("", place="Downloads", limit=5)
        self.assertEqual(len(result["files"]), 5)
        self.assertEqual(result["total"], 30)

    def test_the_sentence_says_the_total_not_the_cap(self):
        with TemporaryDirectory() as tmp:
            for i in range(30):
                (Path(tmp) / f"f{i}.txt").write_text("x", encoding="utf-8")
            with self._place(tmp):
                said = files.spoken(files.search("", place="Downloads", limit=5))
        self.assertIn("30 files", said)
        self.assertNotIn("5 files", said)
        # And the remainder is arithmetic on the total, not on the cap.
        self.assertIn("25 others", said)

    def test_a_count_that_hit_its_budget_says_at_least(self):
        result = {"files": [{"name": "a.txt", "path": "a", "folder": "d",
                             "bytes": 1, "modified": time.time()}],
                  "total": 1, "capped": True, "query": "", "place": ""}
        self.assertIn("at least", files.spoken(result))

    def test_a_bare_list_cannot_claim_a_total(self):
        rows = [{"name": "a.txt", "path": "a", "folder": "d", "bytes": 1,
                 "modified": time.time()}]
        self.assertIn("1 file", files.spoken(rows))


class SaidOutLoudCase(unittest.TestCase):
    def test_a_download_token_is_shortened_and_says_so(self):
        said = files.name_words("tiktok1fJfKZJSK3nexvlIlV0mIcsbcrre9YkL (2).txt")
        self.assertNotIn("fJfKZJSK3nexvlIlV0mIcsbcrre9YkL", said)
        self.assertIn("long string of letters and numbers", said)

    def test_a_long_id_is_not_read_as_a_number(self):
        """`7645813995346708496` comes out as seven quintillion."""
        said = files.name_words("developers.tiktok.com_app_7645813995346708496.png")
        self.assertNotIn("7645813995346708496", said)
        self.assertIn("a long number", said)

    def test_a_year_survives(self):
        """Shortening every digit run would eat "Taxes 2024"."""
        self.assertIn("2024", files.name_words("Taxes 2024.pdf"))

    def test_the_extension_becomes_what_it_is(self):
        self.assertIn("a PDF", files.name_words("lease.pdf"))
        self.assertIn("a Word document", files.name_words("letter.docx"))
        self.assertIn("a picture", files.name_words("cat.png"))

    def test_an_unknown_extension_keeps_its_article(self):
        """"a 8xp file" is wrong out loud, and the rule is the SOUND."""
        self.assertIn("an 8xp file", files.name_words("CYMLEASE.8xp"))
        self.assertIn("an rtf file", files.name_words("notes.rtf"))
        self.assertIn("a webm file", files.name_words("clip.webm"))

    def test_the_extension_word_survives_the_article(self):
        """Fixing the article once dropped the extension: "an file"."""
        self.assertIn("8xp", files.name_words("x.8xp"))

    def test_separators_become_spaces(self):
        self.assertIn("Caleb Schulte resume",
                      files.name_words("Caleb_Schulte_resume.pdf"))

    def test_a_folder_he_named_is_not_said_back_six_times(self):
        now = time.time()
        rows = [{"name": f"f{i}.txt", "path": f"p{i}", "folder": "d",
                 "bytes": 1, "modified": now} for i in range(3)]
        said = files.spoken({"files": rows, "total": 3, "capped": False,
                             "query": "", "place": "Downloads"})
        self.assertEqual(said.count("Downloads"), 1)

    def test_a_place_is_listed_once_each_when_nothing_is_found(self):
        """`Documents` and `OneDrive/Documents` are one word out loud."""
        with mock.patch.object(files, "places", lambda: [
                ("Documents", Path("a")), ("OneDrive/Documents", Path("b")),
                ("Desktop", Path("c"))]):
            self.assertEqual(files.place_names(), ["Documents", "Desktop"])

    def test_a_timestamp_is_never_read_out(self):
        now = time.time()
        self.assertEqual(files.when_words(now, now=now), "today")
        self.assertEqual(files.when_words(now - 86400 * 1.5, now=now), "yesterday")
        self.assertIn("months ago", files.when_words(now - 86400 * 90, now=now))

    def test_an_unknown_folder_is_refused_in_english(self):
        with self.assertRaises(files.FilesError) as caught:
            files.find("x", place="Attic")
        said = str(caught.exception)
        self.assertIn("Attic", said)
        self.assertIn("Downloads", said, "does not say what she CAN look in")


class MatchingCase(unittest.TestCase):
    def test_every_word_he_said_has_to_appear(self):
        """"lease pdf" must not return every PDF he owns."""
        self.assertTrue(files.matches("Lease 2024.pdf", ["lease", "2024"]))
        self.assertFalse(files.matches("Invoice 2024.pdf", ["lease", "2024"]))

    def test_a_partial_word_matches(self):
        """He is speaking, not writing a regex."""
        self.assertTrue(files.matches("Invoice-March.pdf", ["invoic"]))

    def test_no_words_means_everything(self):
        self.assertTrue(files.matches("anything.txt", []))

    def test_the_middle_of_a_word_is_mostly_a_coincidence(self):
        """Asked for "lease" she filled three of five slots with "Release"."""
        self.assertEqual(files.rank("Lease 2024.pdf", ["lease"]), 0)
        self.assertEqual(files.rank("Greek Release Appeal.pdf", ["lease"]), 1)
        self.assertIsNone(files.rank("Invoice.pdf", ["lease"]))

    def test_a_coincidence_is_ranked_below_not_thrown_away(self):
        with TemporaryDirectory() as tmp:
            real = Path(tmp) / "Lease 2019.pdf"
            near = Path(tmp) / "Greek Release Appeal.pdf"
            real.write_text("x", encoding="utf-8")
            near.write_text("x", encoding="utf-8")
            # The coincidence is NEWER, so only the rank can save the answer.
            os.utime(real, (1, 1))
            with mock.patch.object(files, "places",
                                   lambda: [("Downloads", Path(tmp))]):
                found = files.find("lease", place="Downloads")
        self.assertEqual([r["name"] for r in found],
                         ["Lease 2019.pdf", "Greek Release Appeal.pdf"])


class WhoseFilesCase(unittest.TestCase):
    """"my files" is his; "your files" is hers; "my keys" is neither."""

    def _kind(self, said):
        return (voice._interpret(said) or {}).get("command", {}).get("kind")

    def test_his_files_are_his(self):
        for said in ("list my files", "what files do i have", "show me my files"):
            with self.subTest(said=said):
                self.assertEqual(self._kind(said), "file_find")

    def test_her_workspace_is_still_reachable(self):
        for said in ("what files do you have", "what's in your workspace",
                     "list your files"):
            with self.subTest(said=said):
                self.assertEqual(self._kind(said), "file_list")

    def test_a_folder_he_names_is_carried(self):
        command = voice._interpret("what's in my downloads folder")["command"]
        self.assertEqual(command["kind"], "file_find")
        self.assertEqual(command["place"], "Downloads")

    def test_a_store_is_not_a_folder(self):
        """"what's in my calendar" is not a file question."""
        for said in ("what's in my calendar", "what's in my inbox"):
            with self.subTest(said=said):
                self.assertNotEqual(self._kind(said), "file_find")

    def test_finding_a_thing_that_is_not_a_file(self):
        """A pattern that swallows too much answers a different question."""
        for said in ("find my keys", "do i have any reminders",
                     "find my phone", "do i have any emails"):
            with self.subTest(said=said):
                self.assertNotEqual(self._kind(said), "file_find")

    def test_his_capitals_survive(self):
        command = voice._interpret("find my Schulte Lease")["command"]
        self.assertEqual(command["query"], "Schulte Lease")


class WiredCase(unittest.TestCase):
    def test_the_kind_is_in_the_grammar(self):
        self.assertIn("file_find", intercom.KIND_ARGS)

    def test_looking_at_his_own_files_commits_him_to_nothing(self):
        self.assertEqual(intercom.tier("file_find"), intercom.tier("file_list"))

    def test_the_registry_knows_it(self):
        from aletheia import capabilities
        entry = capabilities.get("file.find")
        self.assertEqual(entry["status"], "AVAILABLE")
        self.assertEqual(entry["module"], "aletheia.files")
        self.assertIn("file_find", entry["caller"])

    def test_an_empty_workspace_still_proves_the_workspace(self):
        """"(empty)" out loud reads as "you have no files"."""
        from aletheia import workspace
        with mock.patch.object(workspace, "listing", lambda *a, **k: []):
            text = intercom.execute_command({"kind": "file_list"}, {},
                                            quote="test")
        self.assertNotIn("(empty)", text)
        self.assertIn("workspace", text)


class OneImplementationCase(unittest.TestCase):
    def test_the_resume_finder_uses_the_general_one(self):
        """A private finder in a module about job applications is how the
        gap stayed invisible for as long as it did."""
        import inspect

        from aletheia import applications
        body = inspect.getsource(applications.find_resume)
        self.assertIn("_files.find(", body)
        self.assertNotIn("iterdir()", body)


if __name__ == "__main__":
    unittest.main()
