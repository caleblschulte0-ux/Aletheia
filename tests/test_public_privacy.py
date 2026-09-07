import json
import re
import subprocess
import unittest
from pathlib import Path

from aletheia.fleet import REPO_ROOT

EMAIL_RE=re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b",re.I)


class PublicRepoPrivacyCase(unittest.TestCase):
    def test_private_runtime_roots_are_gitignored(self):
        ignore=(REPO_ROOT/".gitignore").read_text(encoding="utf-8").splitlines()
        self.assertIn("state/private/",ignore)
        self.assertIn("state/mail/",ignore)
        self.assertIn("cache/",ignore)

    def test_no_private_runtime_file_is_currently_tracked(self):
        result=subprocess.run(["git","ls-files","state/private","state/mail","cache"],cwd=REPO_ROOT,text=True,capture_output=True,check=True)
        self.assertEqual(result.stdout.strip(),"",f"private runtime path is tracked: {result.stdout}")

    def test_the_pc_journal_and_anything_derived_from_it_stay_untracked(self):
        """`state/journal/journal-pc.jsonl` is where his life lives after
        the 2026-09-04 move out of the tracked tree. The ignore pattern
        was EXACT, so a `journal-pc.jsonl.bak` written beside it by a
        migration was not ignored and reached a commit on this PUBLIC
        repo. Caught before it was pushed; this is why it cannot happen
        twice."""
        result=subprocess.run(["git","ls-files","state/journal"],cwd=REPO_ROOT,text=True,capture_output=True,check=True)
        tracked=[f for f in result.stdout.split() if f.strip()]
        for path in tracked:
            name=Path(path).name
            self.assertFalse(name.startswith("journal-pc"),f"private PC journal tracked: {path}")
            self.assertFalse(name.endswith(".bak"),f"a backup of a journal is tracked: {path}")

    def test_no_backup_file_anywhere_is_tracked(self):
        """A .bak is a copy of something, and the thing it is a copy of is
        usually the thing that was too private to keep."""
        result=subprocess.run(["git","ls-files"],cwd=REPO_ROOT,text=True,capture_output=True,check=True)
        backups=[f for f in result.stdout.split() if f.endswith((".bak",".orig",".rej"))]
        self.assertEqual(backups,[],f"backup files are tracked: {backups}")

    def test_public_people_memory_contains_no_email_address(self):
        """`memory/` is no longer a tracked directory at all — it moved to
        private runtime state, which is the stronger form of this rule: a
        file that does not exist in the repository cannot leak from it.

        The check still runs against the file when it is there, because
        "it is gone" and "it is gone FOR NOW" are different, and something
        could put it back. Absence is asserted as absence rather than
        erroring on a missing path, which is what this did after the move.
        """
        path=REPO_ROOT/"memory"/"people.json"
        if not path.is_file():
            tracked=subprocess.run(["git","ls-files","memory"],cwd=REPO_ROOT,text=True,capture_output=True,check=True)
            self.assertEqual(tracked.stdout.strip(),"","memory/ is untracked on disk but tracked in git")
            return
        text=path.read_text(encoding="utf-8")
        json.loads(text)  # must remain valid JSON
        self.assertIsNone(EMAIL_RE.search(text),"public memory/people.json contains an email-like personal address; use private contacts")

    def test_private_store_rule_is_documented_in_mail_and_stateio(self):
        mail=(REPO_ROOT/"aletheia"/"mail.py").read_text(encoding="utf-8")
        stateio=(REPO_ROOT/"aletheia"/"stateio.py").read_text(encoding="utf-8")
        self.assertIn("state/mail",mail)
        self.assertIn("private_dir",stateio)


if __name__=="__main__": unittest.main()
